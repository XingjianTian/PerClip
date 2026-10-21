from __future__ import annotations

import json
import re
from dataclasses import replace
from html import unescape
from html.parser import HTMLParser
from typing import Protocol, Sequence
from urllib.parse import urlsplit

from .web_extraction import ExtractionResult, extract_html


class PlatformHtmlAdapter(Protocol):
    """A platform parser that may decline a document without changing it."""

    def supports(self, *, base_url: str, content_type: str) -> bool: ...

    def extract(
        self,
        body: bytes,
        content_type: str,
        *,
        base_url: str,
    ) -> ExtractionResult | None: ...


def _normalize_meta_value(value: str, *, limit: int) -> str:
    return " ".join(unescape(value).split())[:limit].strip()


class _BilibiliMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.descriptions: dict[str, str] = {}
        self.video_tags: list[str] = []
        self.keywords = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "meta":
            return
        values = {key.casefold(): (value or "") for key, value in attrs}
        key = (values.get("property") or values.get("name") or "").strip().casefold()
        content = values.get("content", "")
        if key in {"og:description", "description"}:
            normalized = _normalize_meta_value(content, limit=4000)
            if normalized:
                self.descriptions.setdefault(key, normalized)
        elif key == "video:tag":
            normalized = _normalize_meta_value(content, limit=80)
            if normalized:
                self.video_tags.append(normalized)
        elif key == "keywords" and not self.keywords:
            self.keywords = _normalize_meta_value(content, limit=1200)


class BilibiliHtmlAdapter:
    engine = "perclip-bilibili-html"
    engine_version = "v2"
    supported_hosts = frozenset({"bilibili.com", "www.bilibili.com", "m.bilibili.com"})
    max_tags = 12

    def supports(self, *, base_url: str, content_type: str) -> bool:
        host = (urlsplit(base_url).hostname or "").casefold().rstrip(".")
        mime_type = content_type.split(";", 1)[0].strip().casefold()
        return host in self.supported_hosts and mime_type in {
            "text/html",
            "application/xhtml+xml",
        }

    def extract(
        self,
        body: bytes,
        content_type: str,
        *,
        base_url: str,
    ) -> ExtractionResult | None:
        common = extract_html(body, content_type, base_url=base_url)
        parser = _BilibiliMetaParser()
        parser.feed(body.decode("utf-8", errors="replace"))
        description = parser.descriptions.get(
            "og:description",
            parser.descriptions.get("description", ""),
        )
        tag_candidates = [
            *parser.video_tags,
            *(item for item in re.split(r"[,，]", parser.keywords) if item.strip()),
        ]
        tags: list[str] = []
        seen: set[str] = set()
        for candidate in tag_candidates:
            tag = _normalize_meta_value(candidate, limit=80)
            if not tag or tag in seen:
                continue
            seen.add(tag)
            tags.append(tag)
            if len(tags) >= self.max_tags:
                break
        if not description and not tags:
            return None
        lines = [description] if description else []
        if tags:
            lines.append(f"标签：{'、'.join(tags)}")
        text = "\n\n".join(lines)
        return replace(
            common,
            engine=self.engine,
            engine_version=self.engine_version,
            text=text,
            quality_score=round(min(1.0, len(text) / 1200), 3),
            status="partial",
            quality_reason="video_description_without_transcript",
        )


class _SourceFaithfulPlatformParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.json_ld: list[object] = []
        self._json_ld_depth = 0
        self._json_ld_parts: list[str] = []
        self._author_depth = 0
        self._author_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.casefold()
        values = {key.casefold(): (value or "") for key, value in attrs}
        if normalized == "meta":
            key = (values.get("property") or values.get("name") or "").strip().casefold()
            content = _normalize_meta_value(values.get("content", ""), limit=4000)
            if key and content:
                self.meta.setdefault(key, content)
        if normalized == "script" and values.get("type", "").split(";", 1)[0].strip().casefold() == "application/ld+json":
            self._json_ld_depth += 1
            return
        classes = set(values.get("class", "").split())
        if self._author_depth:
            self._author_depth += 1
        elif values.get("itemprop", "").casefold() == "author" or "AuthorInfo-name" in classes:
            self._author_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._json_ld_depth:
            self._json_ld_depth -= 1
            payload = "".join(self._json_ld_parts).strip()
            self._json_ld_parts.clear()
            if payload:
                try:
                    self.json_ld.append(json.loads(payload))
                except (TypeError, ValueError):
                    pass
            return
        if self._author_depth:
            self._author_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._json_ld_depth:
            self._json_ld_parts.append(data)
            return
        if self._author_depth:
            value = _normalize_meta_value(data, limit=300)
            if value:
                self._author_parts.append(value)

    @property
    def author_text(self) -> str:
        return _normalize_meta_value(" ".join(self._author_parts), limit=300)


def _json_ld_nodes(value: object):
    if isinstance(value, list):
        for item in value:
            yield from _json_ld_nodes(item)
    elif isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, (list, dict)):
            yield from _json_ld_nodes(graph)


class DouyinHtmlAdapter:
    engine = "perclip-douyin-html"
    engine_version = "v1"
    supported_hosts = frozenset({"douyin.com", "www.douyin.com"})
    supported_path = re.compile(r"^/(?:video|note)/\d+/?$")

    def supports(self, *, base_url: str, content_type: str) -> bool:
        parsed = urlsplit(base_url)
        mime_type = content_type.split(";", 1)[0].strip().casefold()
        return (
            (parsed.hostname or "").casefold().rstrip(".") in self.supported_hosts
            and bool(self.supported_path.fullmatch(parsed.path))
            and mime_type in {"text/html", "application/xhtml+xml"}
        )

    @staticmethod
    def _creator(parser: _SourceFaithfulPlatformParser) -> str:
        for payload in parser.json_ld:
            for node in _json_ld_nodes(payload):
                if node.get("@type") != "BreadcrumbList":
                    continue
                entries = node.get("itemListElement")
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict) or str(entry.get("position")) != "2":
                        continue
                    item = entry.get("item")
                    if isinstance(item, dict):
                        item_url = str(item.get("@id") or item.get("url") or "")
                        item_name = item.get("name")
                    else:
                        item_url = str(item or "")
                        item_name = entry.get("name")
                    parsed = urlsplit(item_url)
                    host = (parsed.hostname or "").casefold().rstrip(".")
                    name = _normalize_meta_value(str(item_name or ""), limit=300)
                    if host in DouyinHtmlAdapter.supported_hosts and parsed.path.startswith("/user/") and name:
                        return name
        return ""

    def extract(self, body: bytes, content_type: str, *, base_url: str) -> ExtractionResult | None:
        common = extract_html(body, content_type, base_url=base_url)
        parser = _SourceFaithfulPlatformParser()
        parser.feed(body.decode("utf-8", errors="replace"))
        description = parser.meta.get("og:description", parser.meta.get("description", ""))
        author = self._creator(parser)
        if not description or not author:
            return None
        title = common.title
        title_source = common.title_source
        video_title = parser.meta.get("lark:url:video_title", "")
        if video_title:
            title = re.sub(r"\s*[-_|]\s*抖音\s*$", "", video_title).strip()
            title_source = "meta.lark:url:video_title"
        return replace(
            common,
            engine=self.engine,
            engine_version=self.engine_version,
            title=title,
            title_source=title_source,
            author=author,
            author_source="jsonld.breadcrumb.creator",
            text=description,
            quality_score=round(min(1.0, len(description) / 1200), 3),
            status="partial",
            quality_reason="source_faithful_platform_summary",
        )


class ZhihuHtmlAdapter:
    engine = "perclip-zhihu-html"
    engine_version = "v1"
    answer_hosts = frozenset({"zhihu.com", "www.zhihu.com"})
    column_hosts = frozenset({"zhuanlan.zhihu.com"})
    answer_path = re.compile(r"^/question/\d+/answer/\d+/?$")
    column_path = re.compile(r"^/p/\d+/?$")
    answer_author = re.compile(r"\s+-\s+(.+?)\s+的回答\s*$")

    def supports(self, *, base_url: str, content_type: str) -> bool:
        parsed = urlsplit(base_url)
        host = (parsed.hostname or "").casefold().rstrip(".")
        mime_type = content_type.split(";", 1)[0].strip().casefold()
        path_supported = (
            host in self.answer_hosts and bool(self.answer_path.fullmatch(parsed.path))
        ) or (
            host in self.column_hosts and bool(self.column_path.fullmatch(parsed.path))
        )
        return path_supported and mime_type in {"text/html", "application/xhtml+xml"}

    def extract(self, body: bytes, content_type: str, *, base_url: str) -> ExtractionResult | None:
        common = extract_html(body, content_type, base_url=base_url)
        parser = _SourceFaithfulPlatformParser()
        parser.feed(body.decode("utf-8", errors="replace"))
        description = parser.meta.get("og:description", parser.meta.get("description", ""))
        parsed = urlsplit(base_url)
        if (parsed.hostname or "").casefold().rstrip(".") in self.answer_hosts:
            match = self.answer_author.search(parser.meta.get("og:title", ""))
            author = _normalize_meta_value(match.group(1), limit=300) if match else ""
            author_source = "meta.og:title.answer_author"
        else:
            author = parser.author_text or common.author
            author_source = "html.itemprop.author" if parser.author_text else common.author_source
        if not description or not author:
            return None
        return replace(
            common,
            engine=self.engine,
            engine_version=self.engine_version,
            author=author,
            author_source=author_source,
            text=description,
            quality_score=round(min(1.0, len(description) / 1200), 3),
            status="partial",
            quality_reason="source_faithful_platform_summary",
        )


class W3cRecommendationHtmlAdapter:
    """Recover an explicitly named publisher from W3C recommendation pages."""

    engine = "perclip-w3c-recommendation-html"
    engine_version = "v1"
    supported_hosts = frozenset({"w3.org", "www.w3.org"})
    supported_path = re.compile(r"^/TR/[^/]+/?$")
    recommendation_signal = re.compile(r"\bW3C\s+Recommendation\b", re.IGNORECASE)
    publisher_signal = re.compile(r"\bWorld\s+Wide\s+Web\s+Consortium\b", re.IGNORECASE)

    def supports(self, *, base_url: str, content_type: str) -> bool:
        parsed = urlsplit(base_url)
        mime_type = content_type.split(";", 1)[0].strip().casefold()
        return (
            (parsed.hostname or "").casefold().rstrip(".") in self.supported_hosts
            and bool(self.supported_path.fullmatch(parsed.path))
            and mime_type in {"text/html", "application/xhtml+xml"}
        )

    def extract(self, body: bytes, content_type: str, *, base_url: str) -> ExtractionResult | None:
        decoded = unescape(body.decode("utf-8", errors="replace"))
        visible = " ".join(re.sub(r"<[^>]+>", " ", decoded).split())
        if not self.recommendation_signal.search(visible) or not self.publisher_signal.search(visible):
            return None
        common = extract_html(body, content_type, base_url=base_url)
        if common.author:
            return common
        return replace(
            common,
            engine=self.engine,
            engine_version=self.engine_version,
            author="World Wide Web Consortium",
            author_source="html.explicit.w3c_publisher",
        )


DEFAULT_PLATFORM_HTML_ADAPTERS: tuple[PlatformHtmlAdapter, ...] = (
    BilibiliHtmlAdapter(),
    DouyinHtmlAdapter(),
    ZhihuHtmlAdapter(),
    W3cRecommendationHtmlAdapter(),
)


def extract_html_with_adapters(
    body: bytes,
    content_type: str,
    *,
    base_url: str = "",
    adapters: Sequence[PlatformHtmlAdapter] = (),
) -> ExtractionResult:
    """Use the first applicable adapter result, then the common extractor."""

    for adapter in adapters:
        if not adapter.supports(base_url=base_url, content_type=content_type):
            continue
        result = adapter.extract(body, content_type, base_url=base_url)
        if result is not None:
            return result
    return extract_html(body, content_type, base_url=base_url)
