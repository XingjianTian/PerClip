from __future__ import annotations

import json
from pathlib import Path

import pytest

from perclip_ingest.platform_acquisition import (
    BilibiliAcquisitionAdapter,
    DEFAULT_PLATFORM_ACQUISITION_ADAPTERS,
    PlatformAcquisitionError,
    acquire_web_document,
)
from perclip_ingest.web_extraction import WebFetchError, WebFetchResult


FIXTURES = Path(__file__).parents[2] / "tests/fixtures/stage24/bilibili_acquisition"
VIDEO_URL = "https://www.bilibili.com/video/BV1AB411C7D9"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_frozen_manifest_executes_supported_page_and_failure_shapes():
    manifest = json.loads(fixture("case_manifest.json"))
    assert manifest["schema_version"] == "perclip.stage24.bilibili-acquisition-fixture.v1"
    assert {case["expected"] for case in manifest["cases"]} == {
        "partial",
        "declined",
        "bilibili_metadata_unavailable",
        "bilibili_metadata_insufficient",
        "bilibili_metadata_invalid",
    }
    for case in manifest["cases"]:
        if case["expected"] == "declined":
            assert not BilibiliAcquisitionAdapter().supports(case["source_url"])
            continue
        fetcher = FrozenFetcher(fixture(case["response_fixture"]))
        if case["expected"] == "partial":
            result = acquire_web_document(
                case["source_url"],
                fetcher,  # type: ignore[arg-type]
                adapters=DEFAULT_PLATFORM_ACQUISITION_ADAPTERS,
            )
            assert result.extraction is not None
            assert result.extraction.status == "partial"
        else:
            with pytest.raises(PlatformAcquisitionError, match=case["expected"]):
                acquire_web_document(
                    case["source_url"],
                    fetcher,  # type: ignore[arg-type]
                    adapters=DEFAULT_PLATFORM_ACQUISITION_ADAPTERS,
                )


class FrozenFetcher:
    def __init__(
        self,
        response: bytes,
        *,
        primary_error: str = "web_fetch_failed",
        fallback_error: str = "",
        fallback_resolved_url: str = "",
        content_type: str = "application/json",
    ) -> None:
        self.response = response
        self.primary_error = primary_error
        self.fallback_error = fallback_error
        self.fallback_resolved_url = fallback_resolved_url
        self.content_type = content_type
        self.calls: list[tuple[str, bool]] = []

    def fetch(self, url: str, *, allow_json: bool = False) -> WebFetchResult:
        self.calls.append((url, allow_json))
        if len(self.calls) == 1:
            raise WebFetchError(self.primary_error)
        if self.fallback_error:
            raise WebFetchError(self.fallback_error)
        return WebFetchResult(
            safe_original_url=url,
            resolved_url=self.fallback_resolved_url or url,
            canonical_url=self.fallback_resolved_url or url,
            content_type=self.content_type,
            body=self.response,
            redirect_chain=(url,),
        )


@pytest.mark.parametrize(
    "url",
    [
        VIDEO_URL,
        "https://m.bilibili.com/video/BV1AB411C7D9/",
        "https://bilibili.com/video/BV1AB411C7D9?spm=synthetic",
    ],
)
def test_bilibili_adapter_accepts_only_exact_video_identity_shapes(url):
    assert BilibiliAcquisitionAdapter().supports(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.bilibili.com.evil.example/video/BV1AB411C7D9",
        "https://www.bilibili.com/read/BV1AB411C7D9",
        "https://www.bilibili.com/video/av123",
        "https://www.bilibili.com/video/BVshort",
        "https://user:secret@www.bilibili.com/video/BV1AB411C7D9",
        "https://www.bilibili.com/video/BV1AB411C7D9?token=synthetic",
        "https://www.bilibili.com/video/BV1AB411C7D9?cookie=synthetic",
        "https://www.bilibili.com/video/BV1AB411C7D9?api_key=synthetic",
    ],
)
def test_bilibili_adapter_rejects_lookalike_non_video_and_credential_shapes(url):
    assert not BilibiliAcquisitionAdapter().supports(url)


def test_primary_success_does_not_consult_platform_adapter():
    class PrimarySuccess:
        def __init__(self) -> None:
            self.calls = 0

        def fetch(self, url: str, *, allow_json: bool = False) -> WebFetchResult:
            self.calls += 1
            assert not allow_json
            return WebFetchResult(url, url, url, "text/html", b"<html></html>")

    fetcher = PrimarySuccess()
    result = acquire_web_document(
        VIDEO_URL,
        fetcher,  # type: ignore[arg-type]
        adapters=DEFAULT_PLATFORM_ACQUISITION_ADAPTERS,
    )

    assert fetcher.calls == 1
    assert result.fallback_used is False
    assert result.extraction is None
    assert result.raw_role == "raw_html"


def test_bilibili_fallback_is_exactly_once_and_builds_partial_extraction():
    fetcher = FrozenFetcher(fixture("public_metadata_success.json"))

    result = acquire_web_document(
        VIDEO_URL,
        fetcher,  # type: ignore[arg-type]
        adapters=DEFAULT_PLATFORM_ACQUISITION_ADAPTERS,
    )

    assert fetcher.calls == [
        (VIDEO_URL, False),
        ("https://api.bilibili.com/x/web-interface/view?bvid=BV1AB411C7D9", True),
    ]
    assert result.fallback_used is True
    assert result.primary_safe_error_code == "web_fetch_failed"
    assert result.fallback_redirect_count == 1
    assert result.raw_role == "raw_platform_metadata"
    assert result.raw_filename == "raw-bilibili-metadata.json"
    assert result.fetched.safe_original_url == VIDEO_URL
    assert result.fetched.resolved_url == VIDEO_URL
    assert result.extraction is not None
    assert result.extraction.engine == "perclip-bilibili-acquisition"
    assert result.extraction.engine_version == "v1"
    assert result.extraction.title == "Synthetic frozen video title"
    assert result.extraction.author == "Synthetic frozen creator"
    assert result.extraction.text.startswith("Synthetic frozen public description")
    assert result.extraction.status == "partial"
    assert result.extraction.quality_reason == "video_description_without_transcript"
    assert result.extraction.canonical_url == VIDEO_URL


@pytest.mark.parametrize(
    "primary_error",
    [
        "unsupported_url",
        "dns_resolution_failed",
        "private_address_blocked",
        "redirect_limit_exceeded",
        "redirect_missing_location",
    ],
)
def test_security_and_identity_failures_never_use_platform_fallback(primary_error):
    fetcher = FrozenFetcher(
        fixture("public_metadata_success.json"),
        primary_error=primary_error,
    )

    with pytest.raises(WebFetchError, match=primary_error):
        acquire_web_document(
            VIDEO_URL,
            fetcher,  # type: ignore[arg-type]
            adapters=DEFAULT_PLATFORM_ACQUISITION_ADAPTERS,
        )

    assert fetcher.calls == [(VIDEO_URL, False)]


def test_non_bilibili_failure_never_uses_platform_fallback():
    fetcher = FrozenFetcher(fixture("public_metadata_success.json"))

    with pytest.raises(WebFetchError, match="web_fetch_failed"):
        acquire_web_document(
            "https://example.com/video/BV1AB411C7D9",
            fetcher,  # type: ignore[arg-type]
            adapters=DEFAULT_PLATFORM_ACQUISITION_ADAPTERS,
        )

    assert len(fetcher.calls) == 1


@pytest.mark.parametrize(
    ("fixture_name", "safe_error_code"),
    [
        ("public_metadata_rejected.json", "bilibili_metadata_unavailable"),
        ("public_metadata_missing_description.json", "bilibili_metadata_insufficient"),
        ("public_metadata_malformed.json", "bilibili_metadata_invalid"),
    ],
)
def test_frozen_failure_shapes_fail_closed(fixture_name, safe_error_code):
    fetcher = FrozenFetcher(fixture(fixture_name))

    with pytest.raises(PlatformAcquisitionError, match=safe_error_code):
        acquire_web_document(
            VIDEO_URL,
            fetcher,  # type: ignore[arg-type]
            adapters=DEFAULT_PLATFORM_ACQUISITION_ADAPTERS,
        )

    assert len(fetcher.calls) == 2


def test_identity_mismatch_and_fallback_fetch_failure_are_finite():
    mismatch = fixture("public_metadata_success.json").replace(
        b"BV1AB411C7D9", b"BV1ZZ411C7D9"
    )
    with pytest.raises(PlatformAcquisitionError, match="bilibili_identity_mismatch"):
        acquire_web_document(
            VIDEO_URL,
            FrozenFetcher(mismatch),  # type: ignore[arg-type]
            adapters=DEFAULT_PLATFORM_ACQUISITION_ADAPTERS,
        )
    with pytest.raises(PlatformAcquisitionError, match="bilibili_acquisition_fetch_failed"):
        acquire_web_document(
            VIDEO_URL,
            FrozenFetcher(
                fixture("public_metadata_success.json"),
                fallback_error="upstream_http_error",
            ),  # type: ignore[arg-type]
            adapters=DEFAULT_PLATFORM_ACQUISITION_ADAPTERS,
        )


def test_fallback_redirect_to_another_public_host_is_rejected():
    fetcher = FrozenFetcher(
        fixture("public_metadata_success.json"),
        fallback_resolved_url="https://public.example/metadata",
    )

    with pytest.raises(PlatformAcquisitionError, match="bilibili_metadata_source_mismatch"):
        acquire_web_document(
            VIDEO_URL,
            fetcher,  # type: ignore[arg-type]
            adapters=DEFAULT_PLATFORM_ACQUISITION_ADAPTERS,
        )

    assert len(fetcher.calls) == 2


@pytest.mark.parametrize("content_type", ["text/html", "text/plain"])
def test_valid_json_body_with_non_json_mime_is_rejected(content_type):
    fetcher = FrozenFetcher(
        fixture("public_metadata_success.json"),
        content_type=content_type,
    )

    with pytest.raises(
        PlatformAcquisitionError,
        match="bilibili_metadata_content_type_invalid",
    ):
        acquire_web_document(
            VIDEO_URL,
            fetcher,  # type: ignore[arg-type]
            adapters=DEFAULT_PLATFORM_ACQUISITION_ADAPTERS,
        )

    assert len(fetcher.calls) == 2
