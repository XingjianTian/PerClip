from __future__ import annotations

import gzip
import http.client
import io
import ipaddress
import json
import re
import socket
import ssl
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from .metadata_normalization import normalize_title_author


TRACKING_QUERY_KEYS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "spm",
}
SENSITIVE_QUERY_KEYS = {
    "access_token", "api_key", "apikey", "auth", "authorization", "cookie",
    "password", "passwd", "poc_token", "secret", "session", "sessionid",
    "signature", "token", "xsec_token",
}
ALLOWED_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "aside", "form", "button"}
BLOCK_HINTS = re.compile(
    r"(?i)(nav|menu|footer|sidebar|comment|recommend|related|advert|cookie|breadcrumb|share)"
)
DOH_ENDPOINT_ADDRESS = "1.1.1.1"
DOH_ENDPOINT_HOST = "cloudflare-dns.com"
DOH_RESPONSE_LIMIT = 64 * 1024
PLATFORM_BROWSER_COMPATIBLE_HOSTS = frozenset(
    {"douyin.com", "www.douyin.com", "zhihu.com", "www.zhihu.com", "zhuanlan.zhihu.com"}
)
PLATFORM_BROWSER_COMPATIBLE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class WebFetchError(ValueError):
    pass


def _decode_content_body(body: bytes, content_encoding: str, max_bytes: int) -> bytes:
    encoding = content_encoding.strip().casefold()
    if not encoding or encoding == "identity":
        return body
    if encoding != "gzip":
        raise WebFetchError("unsupported_content_encoding")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            decoded = stream.read(max_bytes + 1)
    except (EOFError, OSError) as error:
        raise WebFetchError("invalid_content_encoding") from error
    if len(decoded) > max_bytes:
        raise WebFetchError("response_too_large")
    return decoded


@dataclass(frozen=True)
class WebFetchResult:
    safe_original_url: str
    resolved_url: str
    canonical_url: str
    content_type: str
    body: bytes
    redirect_chain: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtractionResult:
    engine: str
    engine_version: str
    title: str
    text: str
    quality_score: float
    status: str
    quality_reason: str = ""
    title_source: str = ""
    canonical_url: str = ""
    canonical_url_source: str = ""
    canonical_validation_result: str = "not_present"
    canonical_source_host: str = ""
    canonical_host: str = ""
    canonical_cross_origin: bool = False
    author: str = ""
    author_source: str = ""
    published_at: str = ""
    published_at_source: str = ""
    language: str = ""
    language_source: str = ""


def canonicalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise WebFetchError("unsupported_url")
    host = parsed.hostname.lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError as error:
        raise WebFetchError("unsupported_url") from error
    default_port = 80 if parsed.scheme.lower() == "http" else 443
    formatted_host = f"[{host}]" if ":" in host else host
    netloc = formatted_host if not port or port == default_port else f"{formatted_host}:{port}"
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in TRACKING_QUERY_KEYS
        and key.lower() not in SENSITIVE_QUERY_KEYS
    ]
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, urlencode(query, doseq=True), ""))


def validate_document_canonical(value: str, *, base_url: str) -> tuple[str, str, str, bool, str]:
    """Validate metadata only; this deliberately performs no DNS lookup or fetch."""
    try:
        candidate = canonicalize_url(urljoin(base_url, value))
        source = canonicalize_url(base_url)
    except WebFetchError:
        return "", "", "", False, "rejected_invalid_url"
    parsed = urlsplit(candidate)
    host = (parsed.hostname or "").casefold().rstrip(".")
    source_host = (urlsplit(source).hostname or "").casefold().rstrip(".")
    internal_name = (
        host == "localhost"
        or host.endswith(".localhost")
        or host.endswith(".local")
        or host.endswith(".internal")
        or host.endswith(".lan")
        or host.endswith(".home.arpa")
        or host == "metadata.google.internal"
        or "." not in host
    )
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if internal_name or (literal is not None and not literal.is_global):
        return "", source_host, host, host != source_host, "rejected_non_public_host"
    return candidate, source_host, host, host != source_host, "accepted"


def _validate_public_addresses(addresses: list[str]) -> list[str]:
    validated: list[str] = []
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as error:
            raise WebFetchError("dns_resolution_failed") from error
        if not ip.is_global:
            raise WebFetchError("private_address_blocked")
        normalized = str(ip)
        if normalized not in validated:
            validated.append(normalized)
    if not validated:
        raise WebFetchError("dns_resolution_failed")
    return validated


def resolve_public_addresses(hostname: str, port: int) -> list[str]:
    try:
        records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise WebFetchError("dns_resolution_failed") from error
    return _validate_public_addresses([str(record[4][0]) for record in records])


def _validate_loopback_proxy(host: str, port: int) -> tuple[str, int]:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise WebFetchError("proxy_endpoint_not_loopback") from error
    if not address.is_loopback or not 1 <= port <= 65535:
        raise WebFetchError("proxy_endpoint_not_loopback")
    return str(address), port


def _open_proxy_tunnel(
    proxy_host: str,
    proxy_port: int,
    target_address: str,
    target_port: int,
    timeout_seconds: float,
) -> socket.socket:
    """Open CONNECT to an already validated IP, never an origin hostname."""

    proxy_host, proxy_port = _validate_loopback_proxy(proxy_host, proxy_port)
    target = ipaddress.ip_address(target_address)
    if not target.is_global:
        raise WebFetchError("private_address_blocked")
    tunnel_host = f"[{target}]" if target.version == 6 else str(target)
    connection = http.client.HTTPConnection(proxy_host, proxy_port, timeout=timeout_seconds)
    connection.set_tunnel(tunnel_host, target_port)
    try:
        connection.connect()
    except (OSError, http.client.HTTPException) as error:
        connection.close()
        raise WebFetchError("proxy_connect_failed") from error
    if connection.sock is None:
        connection.close()
        raise WebFetchError("proxy_connect_failed")
    raw_socket = connection.sock
    connection.sock = None
    return raw_socket


class ProxyDohResolver:
    """Resolve origins through a fixed public DoH IP over a loopback proxy."""

    def __init__(self, *, proxy_host: str, proxy_port: int, timeout_seconds: float) -> None:
        self.proxy_host, self.proxy_port = _validate_loopback_proxy(proxy_host, proxy_port)
        self.timeout_seconds = timeout_seconds
        _validate_public_addresses([DOH_ENDPOINT_ADDRESS])

    def resolve(self, hostname: str, _port: int) -> list[str]:
        addresses = [*self._query(hostname, "A"), *self._query(hostname, "AAAA")]
        return _validate_public_addresses(addresses)

    def _query(self, hostname: str, record_type: str) -> list[str]:
        raw_socket = _open_proxy_tunnel(
            self.proxy_host,
            self.proxy_port,
            DOH_ENDPOINT_ADDRESS,
            443,
            self.timeout_seconds,
        )
        try:
            tls_socket = ssl.create_default_context().wrap_socket(
                raw_socket,
                server_hostname=DOH_ENDPOINT_HOST,
            )
            connection = http.client.HTTPConnection(
                DOH_ENDPOINT_HOST,
                443,
                timeout=self.timeout_seconds,
            )
            connection.sock = tls_socket
            query = urlencode({"name": hostname, "type": record_type})
            connection.request(
                "GET",
                f"/dns-query?{query}",
                headers={
                    "Host": DOH_ENDPOINT_HOST,
                    "Accept": "application/dns-json",
                    "User-Agent": "PerClip-Extractor/1.0",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            payload = response.read(DOH_RESPONSE_LIMIT + 1)
            if response.status != 200 or len(payload) > DOH_RESPONSE_LIMIT:
                raise WebFetchError("dns_resolution_failed")
            decoded = json.loads(payload)
            if not isinstance(decoded, dict) or decoded.get("Status") != 0:
                return []
            expected_type = 1 if record_type == "A" else 28
            answers = decoded.get("Answer") or []
            if not isinstance(answers, list):
                raise WebFetchError("dns_resolution_failed")
            return [
                str(answer.get("data"))
                for answer in answers
                if isinstance(answer, dict) and answer.get("type") == expected_type
            ]
        except (OSError, ssl.SSLError, http.client.HTTPException, TypeError, ValueError) as error:
            if isinstance(error, WebFetchError):
                raise
            raise WebFetchError("dns_resolution_failed") from error
        finally:
            try:
                raw_socket.close()
            except OSError:
                pass


class SafeWebFetcher:
    def __init__(
        self,
        *,
        max_bytes: int,
        timeout_seconds: float,
        max_redirects: int = 5,
        proxy_host: str | None = None,
        proxy_port: int | None = None,
        address_resolver: Callable[[str, int], list[str]] | None = None,
    ) -> None:
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        if (proxy_host is None) != (proxy_port is None):
            raise WebFetchError("invalid_proxy_configuration")
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        if proxy_host is not None and proxy_port is not None:
            self.proxy_host, self.proxy_port = _validate_loopback_proxy(proxy_host, proxy_port)
            self.address_resolver = address_resolver or ProxyDohResolver(
                proxy_host=self.proxy_host,
                proxy_port=self.proxy_port,
                timeout_seconds=timeout_seconds,
            ).resolve
        else:
            self.address_resolver = address_resolver or resolve_public_addresses

    def fetch(self, url: str, *, allow_json: bool = False) -> WebFetchResult:
        original = canonicalize_url(url)
        current = original
        redirect_chain: list[str] = []
        for redirect_count in range(self.max_redirects + 1):
            status, headers, body = self._request_once(current)
            if status in REDIRECT_STATUSES:
                if redirect_count >= self.max_redirects:
                    raise WebFetchError("redirect_limit_exceeded")
                location = headers.get("location", "").strip()
                if not location:
                    raise WebFetchError("redirect_missing_location")
                current = canonicalize_url(urljoin(current, location))
                redirect_chain.append(current)
                continue
            if status < 200 or status >= 300:
                raise WebFetchError("upstream_http_error")
            content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            allowed_content_types = (
                ALLOWED_CONTENT_TYPES | {"application/json"}
                if allow_json
                else ALLOWED_CONTENT_TYPES
            )
            if content_type not in allowed_content_types:
                raise WebFetchError("unsupported_content_type")
            body = _decode_content_body(
                body,
                headers.get("content-encoding", ""),
                self.max_bytes,
            )
            return WebFetchResult(
                safe_original_url=original,
                resolved_url=current,
                canonical_url=canonicalize_url(current),
                content_type=content_type,
                body=body,
                redirect_chain=tuple(redirect_chain),
            )
        raise WebFetchError("redirect_limit_exceeded")

    def _request_once(self, url: str) -> tuple[int, dict[str, str], bytes]:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        address = self.address_resolver(host, port)[0]
        if self.proxy_host is not None and self.proxy_port is not None:
            raw_socket = _open_proxy_tunnel(
                self.proxy_host,
                self.proxy_port,
                address,
                port,
                self.timeout_seconds,
            )
        else:
            raw_socket = socket.create_connection((address, port), timeout=self.timeout_seconds)
        try:
            if parsed.scheme == "https":
                raw_socket = ssl.create_default_context().wrap_socket(raw_socket, server_hostname=host)
            connection = http.client.HTTPConnection(host, port, timeout=self.timeout_seconds)
            connection.sock = raw_socket
            path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            request_headers = {
                "Host": parsed.netloc,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
                "Accept-Encoding": "gzip, identity",
                "User-Agent": "PerClip-Extractor/1.0",
                "Connection": "close",
            }
            if host.casefold().rstrip(".") in PLATFORM_BROWSER_COMPATIBLE_HOSTS:
                request_headers["User-Agent"] = PLATFORM_BROWSER_COMPATIBLE_USER_AGENT
                request_headers["Accept"] = (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,image/apng,*/*;q=0.8"
                )
                request_headers["Accept-Language"] = "zh-CN,zh;q=0.9,en;q=0.8"
                request_headers["Cache-Control"] = "no-cache"
                request_headers["Pragma"] = "no-cache"
                request_headers["Sec-Fetch-Dest"] = "document"
                request_headers["Sec-Fetch-Mode"] = "navigate"
                request_headers["Sec-Fetch-Site"] = "none"
                request_headers["Sec-Fetch-User"] = "?1"
                request_headers["Upgrade-Insecure-Requests"] = "1"
            connection.request(
                "GET",
                path,
                headers=request_headers,
            )
            response = connection.getresponse()
            declared = response.getheader("content-length")
            if declared and declared.isdigit() and int(declared) > self.max_bytes:
                raise WebFetchError("response_too_large")
            body = response.read(self.max_bytes + 1)
            if len(body) > self.max_bytes:
                raise WebFetchError("response_too_large")
            headers: dict[str, str] = {}
            for key, value in response.getheaders():
                normalized_key = key.lower()
                if normalized_key == "content-encoding" and normalized_key in headers:
                    headers[normalized_key] = f"{headers[normalized_key]}, {value}"
                else:
                    headers[normalized_key] = value
            return response.status, headers, body
        except (OSError, ssl.SSLError, http.client.HTTPException) as error:
            raise WebFetchError("web_fetch_failed") from error
        finally:
            try:
                raw_socket.close()
            except OSError:
                pass


class ReadableHtmlExtractor(HTMLParser):
    engine = "perclip-readable-html"
    engine_version = "v7"

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._preferred_depth = 0
        self._title_depth = 0
        self._h1_depth = 0
        self._json_ld_depth = 0
        self._title: list[str] = []
        self._h1: list[str] = []
        self._json_ld: list[str] = []
        self._json_ld_body = ""
        self._preferred: list[str] = []
        self._fallback: list[str] = []
        self._raw_text: list[str] = []
        self._metadata: dict[str, tuple[str, str]] = {}
        self._citation_authors: list[str] = []
        self._canonical_href = ""
        self._has_script = False
        self._has_primary_container = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        values = {key.lower(): (value or "") for key, value in attrs}
        if normalized == "html" and values.get("lang", "").strip():
            self._metadata.setdefault("language", (values["lang"].strip(), "html.lang"))
        if normalized == "meta":
            key = (values.get("property") or values.get("name") or "").strip().lower()
            content = values.get("content", "").strip()
            mapping = {
                "og:title": ("og_title", "meta.og:title"),
                "og:site_name": ("site_name", "meta.og:site_name"),
                "application-name": ("site_name", "meta.application-name"),
                "citation_title": ("citation_title", "meta.citation_title"),
                "author": ("author", "meta.author"),
                "article:author": ("author", "meta.article:author"),
                "article:published_time": ("published_at", "meta.article:published_time"),
                "datepublished": ("published_at", "meta.datePublished"),
                "citation_publication_date": (
                    "citation_published_at",
                    "meta.citation_publication_date",
                ),
            }
            if content and key == "citation_author":
                if content not in self._citation_authors:
                    self._citation_authors.append(content)
            elif content and key in mapping:
                field, source = mapping[key]
                self._metadata.setdefault(field, (content, source))
        if normalized == "link":
            relations = {item.casefold() for item in values.get("rel", "").split()}
            if "canonical" in relations and values.get("href", "").strip():
                self._canonical_href = values["href"].strip()
        if normalized == "script":
            self._has_script = True
            if values.get("type", "").split(";", 1)[0].strip().lower() == "application/ld+json":
                self._json_ld_depth += 1
                return
        attributes = " ".join(value or "" for key, value in attrs if key in {"class", "id", "role"})
        if self._skip_depth or normalized in SKIP_TAGS or BLOCK_HINTS.search(attributes):
            self._skip_depth += 1
            return
        if normalized in {"article", "main"}:
            self._preferred_depth += 1
            self._has_primary_container = True
        if normalized == "title":
            self._title_depth += 1
        if normalized == "h1":
            self._h1_depth += 1
        if normalized in {"p", "div", "section", "h1", "h2", "h3", "li", "br"}:
            self._append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized == "script" and self._json_ld_depth:
            self._json_ld_depth -= 1
            self._consume_json_ld()
            return
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if normalized in {"article", "main"} and self._preferred_depth:
            self._preferred_depth -= 1
        if normalized == "title" and self._title_depth:
            self._title_depth -= 1
        if normalized == "h1" and self._h1_depth:
            self._h1_depth -= 1
        if normalized in {"p", "div", "section", "h1", "h2", "h3", "li"}:
            self._append("\n")

    def handle_data(self, data: str) -> None:
        if self._json_ld_depth:
            self._json_ld.append(data)
            return
        raw_text = unescape(data).strip()
        if raw_text:
            self._raw_text.append(raw_text)
        if self._skip_depth:
            return
        text = unescape(data).strip()
        if not text:
            return
        if self._title_depth:
            self._title.append(text)
        if self._h1_depth:
            self._h1.append(text)
        self._append(text)

    def _append(self, text: str) -> None:
        self._fallback.append(text)
        if self._preferred_depth:
            self._preferred.append(text)

    def _consume_json_ld(self) -> None:
        payload = "".join(self._json_ld).strip()
        self._json_ld.clear()
        if not payload:
            return
        try:
            decoded = json.loads(payload)
        except (TypeError, ValueError):
            return
        nodes = decoded if isinstance(decoded, list) else [decoded]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            graph = node.get("@graph")
            candidates = graph if isinstance(graph, list) else [node]
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                headline = str(candidate.get("headline") or "").strip()
                if headline:
                    self._metadata.setdefault("jsonld_headline", (headline, "jsonld.headline"))
                article_body = candidate.get("articleBody")
                if isinstance(article_body, str) and article_body.strip() and not self._json_ld_body:
                    self._json_ld_body = " ".join(unescape(article_body).split())
                author = candidate.get("author")
                if isinstance(author, dict):
                    author = author.get("name")
                if isinstance(author, list):
                    author = ", ".join(
                        str(item.get("name") if isinstance(item, dict) else item).strip()
                        for item in author
                    )
                if str(author or "").strip():
                    self._metadata.setdefault("author", (str(author).strip(), "jsonld.author"))
                publisher = candidate.get("publisher")
                if isinstance(publisher, dict):
                    publisher = publisher.get("name")
                if str(publisher or "").strip():
                    self._metadata.setdefault("publisher", (str(publisher).strip(), "jsonld.publisher"))
                published = str(candidate.get("datePublished") or "").strip()
                if published:
                    self._metadata.setdefault("published_at", (published, "jsonld.datePublished"))
                language = str(candidate.get("inLanguage") or "").strip()
                if language:
                    self._metadata.setdefault("language", (language, "jsonld.inLanguage"))

    def result(self, *, base_url: str = "") -> ExtractionResult:
        def usable_lines(source: list[str]) -> list[str]:
            lines: list[str] = []
            seen: set[str] = set()
            for raw_line in " ".join(source).splitlines():
                line = " ".join(raw_line.split()).strip()
                if len(line) < 2 or line in seen or BLOCK_HINTS.fullmatch(line):
                    continue
                seen.add(line)
                lines.append(line)
            return lines

        lines = usable_lines(self._preferred)
        if not lines and self._json_ld_body:
            lines = usable_lines([self._json_ld_body])
        if not lines:
            lines = usable_lines(self._fallback)
        text = "\n\n".join(lines).strip()
        score = min(1.0, len(text) / 1200) if text else 0.0
        title_candidates = [
            self._metadata.get("jsonld_headline", ("", "")),
            self._metadata.get("og_title", ("", "")),
            (" ".join(self._title).strip(), "html.title"),
            (" ".join(self._h1).strip(), "html.h1"),
            self._metadata.get("citation_title", ("", "")),
        ]
        title, title_source = next(
            ((value, source_name) for value, source_name in title_candidates if value.strip()),
            ("", ""),
        )
        if not title and lines:
            title, title_source = lines[0][:300], "body.first_line"
        canonical = ""
        canonical_source = ""
        canonical_validation = "not_present"
        canonical_source_host = ""
        canonical_host = ""
        canonical_cross_origin = False
        if self._canonical_href and base_url:
            (
                canonical,
                canonical_source_host,
                canonical_host,
                canonical_cross_origin,
                canonical_validation,
            ) = validate_document_canonical(self._canonical_href, base_url=base_url)
            if canonical:
                canonical_source = "html.link.canonical"
        raw_lower = " ".join(self._raw_text).casefold()
        paginated = bool(re.search(r"(?:第\s*\d+\s*页\s*/\s*共\s*\d+\s*页|next\s+page|下一页)", raw_lower))
        browser_shell = (
            self._has_script
            and not self._has_primary_container
            and not self._json_ld_body
            and len(text) < 240
        )
        if not text:
            status, reason = "failed", "no_usable_body"
        elif paginated:
            status, reason = "partial", "additional_pages_not_fetched"
        elif browser_shell:
            status, reason = "partial", "browser_render_required"
        elif title_source == "body.first_line":
            status, reason = "partial", "title_metadata_missing_body_fallback"
        else:
            status, reason = "completed", "usable_body_extracted"
        author, author_source = self._metadata.get("author", ("", ""))
        if len(self._citation_authors) > 1 or (not author and self._citation_authors):
            author = ", ".join(self._citation_authors)
            author_source = "meta.citation_author"
        if not author:
            author, author_source = self._metadata.get(
                "publisher", self._metadata.get("site_name", ("", ""))
            )
        if not author and base_url:
            parsed_source = urlsplit(base_url)
            source_host = (parsed_source.hostname or "").casefold().rstrip(".")
            path_parts = [part for part in parsed_source.path.split("/") if part]
            if source_host == "github.com" and path_parts:
                author, author_source = path_parts[0], "url.github_owner"
        published, published_source = self._metadata.get(
            "published_at",
            self._metadata.get("citation_published_at", ("", "")),
        )
        language, language_source = self._metadata.get("language", ("", ""))
        normalized_metadata = normalize_title_author(
            title=title,
            author=author,
            base_url=base_url,
        )
        return ExtractionResult(
            engine=self.engine,
            engine_version=self.engine_version,
            title=normalized_metadata.title,
            text=text,
            quality_score=round(score, 3),
            status=status,
            quality_reason=reason,
            title_source=title_source,
            canonical_url=canonical,
            canonical_url_source=canonical_source,
            canonical_validation_result=canonical_validation,
            canonical_source_host=canonical_source_host,
            canonical_host=canonical_host,
            canonical_cross_origin=canonical_cross_origin,
            author=normalized_metadata.author,
            author_source=author_source,
            published_at=published[:100],
            published_at_source=published_source,
            language=language[:40],
            language_source=language_source,
        )


def extract_html(body: bytes, content_type: str, *, base_url: str = "") -> ExtractionResult:
    text = body.decode("utf-8", errors="replace")
    if content_type == "text/plain":
        cleaned = "\n\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())
        score = min(1.0, len(cleaned) / 1200) if cleaned else 0.0
        return ExtractionResult(
            engine="perclip-plain-text",
            engine_version="v3",
            title="",
            text=cleaned,
            quality_score=round(score, 3),
            status="completed" if cleaned else "failed",
            quality_reason="usable_body_extracted" if cleaned else "no_usable_body",
            title_source="",
        )
    parser = ReadableHtmlExtractor()
    parser.feed(text)
    return parser.result(base_url=base_url)
