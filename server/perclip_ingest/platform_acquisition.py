from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit

from .web_extraction import (
    ExtractionResult,
    SafeWebFetcher,
    SENSITIVE_QUERY_KEYS,
    WebFetchError,
    WebFetchResult,
    canonicalize_url,
)


class PlatformAcquisitionError(WebFetchError):
    """A finite, safe platform-acquisition failure."""


@dataclass(frozen=True)
class AcquiredWebDocument:
    fetched: WebFetchResult
    extraction: ExtractionResult | None = None
    raw_role: str = "raw_html"
    raw_filename: str = "raw.html"
    acquisition_engine: str = "safe-web-fetcher"
    acquisition_engine_version: str = "v1"
    fallback_used: bool = False
    primary_safe_error_code: str = ""
    fallback_redirect_count: int = 0


class PlatformAcquisitionAdapter(Protocol):
    def supports(self, url: str) -> bool: ...

    def accepts_primary_error(self, error: WebFetchError) -> bool: ...

    def acquire(
        self,
        url: str,
        fetcher: SafeWebFetcher,
        *,
        primary_error: WebFetchError,
    ) -> AcquiredWebDocument: ...


def _normalized_text(value: object, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit].strip()


class BilibiliAcquisitionAdapter:
    """One public-metadata fallback for an exact Bilibili video identity."""

    engine = "perclip-bilibili-acquisition"
    engine_version = "v1"
    supported_hosts = frozenset({"bilibili.com", "www.bilibili.com", "m.bilibili.com"})
    fallback_host = "api.bilibili.com"
    _video_path = re.compile(r"^/video/(BV[A-Za-z0-9]{10})/?$")
    _accepted_primary_errors = frozenset(
        {
            "web_fetch_failed",
            "upstream_http_error",
            "unsupported_content_type",
            "response_too_large",
        }
    )

    def _identity(self, url: str) -> tuple[str, str] | None:
        try:
            raw = urlsplit(url.strip())
            if raw.username is not None or raw.password is not None:
                return None
            if any(
                key.casefold() in SENSITIVE_QUERY_KEYS
                for key, _value in parse_qsl(raw.query, keep_blank_values=True)
            ):
                return None
            canonical = canonicalize_url(url)
        except (ValueError, WebFetchError):
            return None
        parsed = urlsplit(canonical)
        host = (parsed.hostname or "").casefold().rstrip(".")
        match = self._video_path.fullmatch(parsed.path)
        if host not in self.supported_hosts or match is None:
            return None
        return canonical, match.group(1)

    def supports(self, url: str) -> bool:
        return self._identity(url) is not None

    def accepts_primary_error(self, error: WebFetchError) -> bool:
        return str(error).strip().casefold() in self._accepted_primary_errors

    def _fallback_url(self, bvid: str) -> str:
        return f"https://{self.fallback_host}/x/web-interface/view?{urlencode({'bvid': bvid})}"

    def acquire(
        self,
        url: str,
        fetcher: SafeWebFetcher,
        *,
        primary_error: WebFetchError,
    ) -> AcquiredWebDocument:
        identity = self._identity(url)
        if identity is None:
            raise PlatformAcquisitionError("bilibili_identity_unsupported")
        canonical, bvid = identity
        try:
            fallback = fetcher.fetch(self._fallback_url(bvid), allow_json=True)
        except WebFetchError as error:
            raise PlatformAcquisitionError("bilibili_acquisition_fetch_failed") from error
        fallback_host = (urlsplit(fallback.resolved_url).hostname or "").casefold().rstrip(".")
        if fallback_host != self.fallback_host:
            raise PlatformAcquisitionError("bilibili_metadata_source_mismatch")
        if fallback.content_type != "application/json":
            raise PlatformAcquisitionError("bilibili_metadata_content_type_invalid")
        extraction = self._extract_metadata(
            fallback.body,
            expected_bvid=bvid,
            canonical_url=canonical,
        )
        fetched = WebFetchResult(
            safe_original_url=canonical,
            resolved_url=canonical,
            canonical_url=canonical,
            content_type=fallback.content_type,
            body=fallback.body,
            redirect_chain=(),
        )
        return AcquiredWebDocument(
            fetched=fetched,
            extraction=extraction,
            raw_role="raw_platform_metadata",
            raw_filename="raw-bilibili-metadata.json",
            acquisition_engine=self.engine,
            acquisition_engine_version=self.engine_version,
            fallback_used=True,
            primary_safe_error_code=str(primary_error).strip().casefold(),
            fallback_redirect_count=len(fallback.redirect_chain),
        )

    def _extract_metadata(
        self,
        body: bytes,
        *,
        expected_bvid: str,
        canonical_url: str,
    ) -> ExtractionResult:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PlatformAcquisitionError("bilibili_metadata_invalid") from error
        if not isinstance(payload, dict) or type(payload.get("code")) is not int:
            raise PlatformAcquisitionError("bilibili_metadata_invalid")
        if payload["code"] != 0:
            raise PlatformAcquisitionError("bilibili_metadata_unavailable")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise PlatformAcquisitionError("bilibili_metadata_invalid")
        if data.get("bvid") != expected_bvid:
            raise PlatformAcquisitionError("bilibili_identity_mismatch")
        title = _normalized_text(data.get("title"), limit=500)
        description = _normalized_text(data.get("desc"), limit=4000)
        owner = data.get("owner")
        author = _normalized_text(owner.get("name"), limit=300) if isinstance(owner, dict) else ""
        if not title or not description:
            raise PlatformAcquisitionError("bilibili_metadata_insufficient")
        published_at = ""
        pubdate = data.get("pubdate")
        if isinstance(pubdate, int) and not isinstance(pubdate, bool) and pubdate > 0:
            try:
                published_at = datetime.fromtimestamp(pubdate, timezone.utc).date().isoformat()
            except (OverflowError, OSError, ValueError):
                published_at = ""
        host = (urlsplit(canonical_url).hostname or "").casefold().rstrip(".")
        return ExtractionResult(
            engine=self.engine,
            engine_version=self.engine_version,
            title=title,
            text=description,
            quality_score=round(min(1.0, len(description) / 1200), 3),
            status="partial",
            quality_reason="video_description_without_transcript",
            title_source="bilibili.public_metadata.title",
            canonical_url=canonical_url,
            canonical_url_source="bilibili.video_identity",
            canonical_validation_result="accepted",
            canonical_source_host=host,
            canonical_host=host,
            canonical_cross_origin=False,
            author=author,
            author_source="bilibili.public_metadata.owner.name" if author else "",
            published_at=published_at,
            published_at_source="bilibili.public_metadata.pubdate" if published_at else "",
            language="zh-CN",
            language_source="bilibili.platform_default",
        )


DEFAULT_PLATFORM_ACQUISITION_ADAPTERS: tuple[PlatformAcquisitionAdapter, ...] = (
    BilibiliAcquisitionAdapter(),
)


def acquire_web_document(
    url: str,
    fetcher: SafeWebFetcher,
    *,
    adapters: Sequence[PlatformAcquisitionAdapter] = (),
) -> AcquiredWebDocument:
    """Fetch normally, then allow one matching platform fallback on finite errors."""

    try:
        fetched = fetcher.fetch(url)
    except WebFetchError as error:
        for adapter in adapters:
            if adapter.supports(url) and adapter.accepts_primary_error(error):
                return adapter.acquire(url, fetcher, primary_error=error)
        raise
    filename = "raw.txt" if fetched.content_type == "text/plain" else "raw.html"
    return AcquiredWebDocument(fetched=fetched, raw_filename=filename)
