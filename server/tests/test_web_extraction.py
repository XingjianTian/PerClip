from __future__ import annotations

import gzip
import socket

import pytest
import perclip_ingest.web_extraction as web_extraction

from perclip_ingest.web_extraction import (
    ProxyDohResolver,
    SafeWebFetcher,
    WebFetchError,
    canonicalize_url,
    extract_html,
    resolve_public_addresses,
)


def test_canonical_url_removes_fragment_and_known_tracking_without_changing_content_query():
    assert canonicalize_url(
        "HTTPS://Example.COM:443/article?id=42&utm_source=test&gclid=secret#comments"
    ) == "https://example.com/article?id=42"


def test_canonical_url_drops_sensitive_query_values():
    assert canonicalize_url(
        "https://example.com/path?id=7&token=private&api_key=private"
        "&poc_token=temporary&signature=signed&xsec_token=session"
    ) == "https://example.com/path?id=7"


@pytest.mark.parametrize(
    "value",
    [
        "file:///etc/passwd",
        "http://user:password@example.com/",
        "http://example.com:99999/",
        "//example.com/path",
    ],
)
def test_canonical_url_rejects_unsafe_forms(value):
    with pytest.raises(WebFetchError):
        canonicalize_url(value)


def test_dns_policy_rejects_if_any_resolution_is_not_public(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(WebFetchError, match="private_address_blocked"):
        resolve_public_addresses("example.com", 443)


def test_proxy_doh_resolver_accepts_only_public_answers(monkeypatch):
    resolver = ProxyDohResolver(proxy_host="127.0.0.1", proxy_port=7890, timeout_seconds=1)
    monkeypatch.setattr(
        resolver,
        "_query",
        lambda _hostname, record_type: ["93.184.216.34"] if record_type == "A" else [],
    )
    assert resolver.resolve("example.com", 443) == ["93.184.216.34"]

    monkeypatch.setattr(
        resolver,
        "_query",
        lambda _hostname, record_type: ["198.18.0.10"] if record_type == "A" else [],
    )
    with pytest.raises(WebFetchError, match="private_address_blocked"):
        resolver.resolve("example.com", 443)


def test_proxy_mode_requires_loopback_ip_endpoint():
    with pytest.raises(WebFetchError, match="proxy_endpoint_not_loopback"):
        SafeWebFetcher(
            max_bytes=1024,
            timeout_seconds=1,
            proxy_host="proxy.example",
            proxy_port=7890,
        )


def test_proxy_tunnel_connects_to_validated_ip_not_origin_hostname(monkeypatch):
    observed: dict[str, object] = {}

    class FakeSocket:
        pass

    class FakeConnection:
        def __init__(self, host, port, timeout):
            observed["proxy"] = (host, port, timeout)
            self.sock = FakeSocket()

        def set_tunnel(self, host, port):
            observed["tunnel"] = (host, port)

        def connect(self):
            observed["connected"] = True

        def close(self):
            observed["closed"] = True

    monkeypatch.setattr(web_extraction.http.client, "HTTPConnection", FakeConnection)

    sock = web_extraction._open_proxy_tunnel(
        "127.0.0.1", 7890, "93.184.216.34", 443, 2.5
    )

    assert isinstance(sock, FakeSocket)
    assert observed["proxy"] == ("127.0.0.1", 7890, 2.5)
    assert observed["tunnel"] == ("93.184.216.34", 443)


def test_proxy_https_keeps_origin_sni_and_host_after_ip_validation(monkeypatch):
    observed: dict[str, object] = {}

    class FakeSocket:
        def close(self):
            observed["socket_closed"] = True

    class FakeTlsContext:
        def wrap_socket(self, sock, server_hostname):
            observed["sni"] = server_hostname
            return sock

    class FakeResponse:
        status = 200

        def getheader(self, name):
            return None

        def getheaders(self):
            return [("content-type", "text/plain")]

        def read(self, _limit):
            return b"public body"

    class FakeConnection:
        def __init__(self, host, port, timeout):
            observed["request_connection"] = (host, port, timeout)
            self.sock = None

        def request(self, method, path, headers):
            observed["request"] = (method, path, headers)

        def getresponse(self):
            return FakeResponse()

    monkeypatch.setattr(
        web_extraction,
        "_open_proxy_tunnel",
        lambda proxy_host, proxy_port, address, port, timeout: (
            observed.update(tunnel=(proxy_host, proxy_port, address, port, timeout))
            or FakeSocket()
        ),
    )
    monkeypatch.setattr(web_extraction.ssl, "create_default_context", FakeTlsContext)
    monkeypatch.setattr(web_extraction.http.client, "HTTPConnection", FakeConnection)
    fetcher = SafeWebFetcher(
        max_bytes=1024,
        timeout_seconds=1,
        proxy_host="127.0.0.1",
        proxy_port=7890,
        address_resolver=lambda _host, _port: ["93.184.216.34"],
    )

    status, headers, body = fetcher._request_once("https://example.com/article?id=7")

    assert (status, headers["content-type"], body) == (200, "text/plain", b"public body")
    assert observed["tunnel"] == ("127.0.0.1", 7890, "93.184.216.34", 443, 1)
    assert observed["sni"] == "example.com"
    assert observed["request"][2]["Host"] == "example.com"
    assert observed["request"][2]["User-Agent"] == "PerClip-Extractor/1.0"
    assert "Accept-Language" not in observed["request"][2]


def test_platform_request_profile_is_exact_host_only(monkeypatch):
    observed_headers: list[dict[str, str]] = []

    class FakeSocket:
        def close(self):
            pass

    class FakeResponse:
        status = 200

        def getheader(self, _name):
            return None

        def getheaders(self):
            return [("content-type", "text/html")]

        def read(self, _limit):
            return b"<html></html>"

    class FakeConnection:
        def __init__(self, _host, _port, timeout):
            assert timeout == 1
            self.sock = None

        def request(self, _method, _path, headers):
            observed_headers.append(headers)

        def getresponse(self):
            return FakeResponse()

    monkeypatch.setattr(web_extraction.socket, "create_connection", lambda *_args, **_kwargs: FakeSocket())
    monkeypatch.setattr(web_extraction.http.client, "HTTPConnection", FakeConnection)
    fetcher = SafeWebFetcher(
        max_bytes=1024,
        timeout_seconds=1,
        address_resolver=lambda _host, _port: ["93.184.216.34"],
    )

    fetcher._request_once("http://www.douyin.com/video/123")
    fetcher._request_once("http://www.douyin.com.evil.example/video/123")

    assert observed_headers[0]["User-Agent"].startswith("Mozilla/5.0")
    assert observed_headers[0]["Accept-Language"].startswith("zh-CN")
    assert observed_headers[0]["Accept"].startswith("text/html,application/xhtml+xml")
    assert observed_headers[0]["Sec-Fetch-Mode"] == "navigate"
    assert observed_headers[0]["Upgrade-Insecure-Requests"] == "1"
    assert observed_headers[1]["User-Agent"] == "PerClip-Extractor/1.0"
    assert "Accept-Language" not in observed_headers[1]
    assert "Sec-Fetch-Mode" not in observed_headers[1]


def test_redirect_is_revalidated_and_tracking_is_removed(monkeypatch):
    fetcher = SafeWebFetcher(max_bytes=1024, timeout_seconds=1)
    seen: list[str] = []

    def fake_request(url):
        seen.append(url)
        if len(seen) == 1:
            return 302, {"location": "https://example.org/final?utm_source=x&id=7"}, b""
        return 200, {"content-type": "text/plain"}, b"final"

    monkeypatch.setattr(fetcher, "_request_once", fake_request)
    result = fetcher.fetch("https://example.com/start")

    assert seen == ["https://example.com/start", "https://example.org/final?id=7"]
    assert result.canonical_url == "https://example.org/final?id=7"


@pytest.mark.parametrize("encoding", ["", "identity", " Identity "])
def test_fetch_preserves_identity_encoded_body(monkeypatch, encoding):
    fetcher = SafeWebFetcher(max_bytes=1024, timeout_seconds=1)
    monkeypatch.setattr(
        fetcher,
        "_request_once",
        lambda _url: (
            200,
            {"content-type": "text/plain", "content-encoding": encoding},
            b"plain body",
        ),
    )

    assert fetcher.fetch("https://example.com/plain").body == b"plain body"


def test_fetch_decodes_gzip_within_decompressed_limit(monkeypatch):
    fetcher = SafeWebFetcher(max_bytes=1024, timeout_seconds=1)
    monkeypatch.setattr(
        fetcher,
        "_request_once",
        lambda _url: (
            200,
            {"content-type": "text/html", "content-encoding": "GZip"},
            gzip.compress(b"<html><body>decoded</body></html>"),
        ),
    )

    assert fetcher.fetch("https://example.com/compressed").body == (
        b"<html><body>decoded</body></html>"
    )


def test_fetch_rejects_gzip_that_exceeds_decompressed_limit(monkeypatch):
    fetcher = SafeWebFetcher(max_bytes=64, timeout_seconds=1)
    monkeypatch.setattr(
        fetcher,
        "_request_once",
        lambda _url: (
            200,
            {"content-type": "text/html", "content-encoding": "gzip"},
            gzip.compress(b"x" * 65),
        ),
    )

    with pytest.raises(WebFetchError, match="response_too_large"):
        fetcher.fetch("https://example.com/compressed")


def test_fetch_rejects_invalid_or_unsupported_content_encoding(monkeypatch):
    fetcher = SafeWebFetcher(max_bytes=1024, timeout_seconds=1)
    responses = iter(
        [
            (200, {"content-type": "text/html", "content-encoding": "gzip"}, b"invalid"),
            (
                200,
                {"content-type": "text/html", "content-encoding": "br"},
                b"encoded",
            ),
            (
                200,
                {"content-type": "text/html", "content-encoding": "gzip, br"},
                b"encoded",
            ),
        ]
    )
    monkeypatch.setattr(fetcher, "_request_once", lambda _url: next(responses))

    with pytest.raises(WebFetchError, match="invalid_content_encoding"):
        fetcher.fetch("https://example.com/invalid-gzip")
    with pytest.raises(WebFetchError, match="unsupported_content_encoding"):
        fetcher.fetch("https://example.com/brotli")
    with pytest.raises(WebFetchError, match="unsupported_content_encoding"):
        fetcher.fetch("https://example.com/multiple")


def test_json_content_type_requires_explicit_internal_opt_in(monkeypatch):
    fetcher = SafeWebFetcher(max_bytes=1024, timeout_seconds=1)
    monkeypatch.setattr(
        fetcher,
        "_request_once",
        lambda _url: (200, {"content-type": "application/json"}, b'{"ok":true}'),
    )

    with pytest.raises(WebFetchError, match="unsupported_content_type"):
        fetcher.fetch("https://example.com/metadata")
    assert fetcher.fetch(
        "https://example.com/metadata", allow_json=True
    ).content_type == "application/json"


def test_request_rejects_duplicate_content_encoding_headers(monkeypatch):
    class FakeSocket:
        def close(self):
            pass

    class FakeResponse:
        status = 200

        def getheader(self, name):
            return None

        def getheaders(self):
            return [
                ("Content-Type", "text/html"),
                ("Content-Encoding", "br"),
                ("Content-Encoding", "gzip"),
            ]

        def read(self, _limit):
            return gzip.compress(b"<html><body>encoded</body></html>")

    class FakeConnection:
        def __init__(self, _host, _port, timeout):
            self.sock = None

        def request(self, _method, _path, headers):
            pass

        def getresponse(self):
            return FakeResponse()

    monkeypatch.setattr(
        web_extraction.socket,
        "create_connection",
        lambda *_args, **_kwargs: FakeSocket(),
    )
    monkeypatch.setattr(web_extraction.http.client, "HTTPConnection", FakeConnection)
    fetcher = SafeWebFetcher(
        max_bytes=1024,
        timeout_seconds=1,
        address_resolver=lambda _host, _port: ["93.184.216.34"],
    )

    with pytest.raises(WebFetchError, match="unsupported_content_encoding"):
        fetcher.fetch("http://example.com/multiple-headers")


def test_html_extractor_prefers_article_and_removes_navigation_scripts_and_duplicates():
    html = b"""
    <html><head><title>Useful title</title><script>secret noise</script></head>
    <body><nav>Home Products Login</nav><article>
      <h1>Useful title</h1><p>This is the durable article body with enough useful detail.</p>
      <p>This is the durable article body with enough useful detail.</p>
      <aside>Related recommendations</aside>
    </article><footer>ICP and contact noise</footer></body></html>
    """

    result = extract_html(html, "text/html")

    assert result.title == "Useful title"
    assert "durable article body" in result.text
    assert result.text.count("durable article body") == 1
    assert "Home Products" not in result.text
    assert "secret noise" not in result.text
    assert "Related recommendations" not in result.text
    assert result.status == "completed"
    assert result.quality_reason == "usable_body_extracted"


def test_structured_title_canonical_and_language_have_deterministic_precedence():
    html = b"""
    <html lang="zh-CN"><head>
      <title>HTML title</title>
      <meta property="og:title" content="OG title">
      <link rel="canonical" href="/canonical?id=7&utm_source=fixture">
      <script type="application/ld+json">
        {"headline":"JSON-LD title","author":{"name":"Synthetic Author"},
         "datePublished":"2026-07-01","inLanguage":"zh-CN"}
      </script>
    </head><body><main><h1>Heading title</h1><p>Short useful body.</p></main></body></html>
    """

    result = extract_html(html, "text/html", base_url="https://example.test/articles/source")

    assert result.status == "completed"
    assert result.title == "JSON-LD title"
    assert result.title_source == "jsonld.headline"
    assert result.canonical_url == "https://example.test/canonical?id=7"
    assert result.canonical_url_source == "html.link.canonical"
    assert (result.author, result.author_source) == ("Synthetic Author", "jsonld.author")
    assert (result.published_at, result.published_at_source) == (
        "2026-07-01",
        "jsonld.datePublished",
    )
    assert (result.language, result.language_source) == ("zh-CN", "html.lang")
    assert result.canonical_validation_result == "accepted"
    assert result.canonical_source_host == result.canonical_host == "example.test"
    assert result.canonical_cross_origin is False


def test_citation_metadata_fills_general_web_fields_and_aggregates_authors():
    html = b"""
    <html><head>
      <meta name="citation_title" content="Durable Research Title">
      <meta name="citation_author" content="First Author">
      <meta name="citation_author" content="Second Author">
      <meta name="citation_author" content="First Author">
      <meta name="citation_publication_date" content="2026-08-11">
    </head><body><main><p>Substantive research body.</p></main></body></html>
    """

    result = extract_html(html, "text/html")

    assert result.engine_version == "v7"
    assert (result.title, result.title_source) == (
        "Durable Research Title",
        "meta.citation_title",
    )
    assert (result.author, result.author_source) == (
        "First Author, Second Author",
        "meta.citation_author",
    )
    assert (result.published_at, result.published_at_source) == (
        "2026-08-11",
        "meta.citation_publication_date",
    )


def test_existing_structured_metadata_precedes_single_citation_fallbacks():
    html = b"""
    <html><head>
      <meta property="og:title" content="Preferred OG Title">
      <meta name="citation_title" content="Citation Title">
      <meta name="author" content="Preferred Author">
      <meta name="citation_author" content="Citation Author">
      <meta property="article:published_time" content="2026-08-10">
      <meta name="citation_publication_date" content="2026-08-09">
    </head><body><main><p>Substantive article body.</p></main></body></html>
    """

    result = extract_html(html, "text/html")

    assert (result.title, result.title_source) == (
        "Preferred OG Title",
        "meta.og:title",
    )
    assert (result.author, result.author_source) == (
        "Preferred Author",
        "meta.author",
    )
    assert (result.published_at, result.published_at_source) == (
        "2026-08-10",
        "meta.article:published_time",
    )


def test_publisher_site_name_and_account_identity_fill_missing_author():
    site = extract_html(
        b'<html><head><title>Guide</title><meta property="og:site_name" content="Example Docs"></head>'
        b'<body><main><p>Useful body.</p></main></body></html>',
        "text/html",
        base_url="https://docs.example.test/guide",
    )
    assert (site.author, site.author_source) == ("Example Docs", "meta.og:site_name")

    host = extract_html(
        b"<html><head><title>Guide</title></head><body><main><p>Useful body.</p></main></body></html>",
        "text/html",
        base_url="https://publisher.example.test/guide",
    )
    assert (host.author, host.author_source) == ("", "")

    github = extract_html(
        b"<html><head><title>Repository</title></head><body><main><p>Useful body.</p></main></body></html>",
        "text/html",
        base_url="https://github.com/openai/openai-python",
    )
    assert (github.author, github.author_source) == ("openai", "url.github_owner")


def test_html_title_precedes_citation_title_fallback():
    result = extract_html(
        b"""
        <html><head>
          <title>Preferred HTML Title</title>
          <meta name="citation_title" content="Citation Title">
        </head><body><main><p>Substantive article body.</p></main></body></html>
        """,
        "text/html",
    )

    assert (result.title, result.title_source) == (
        "Preferred HTML Title",
        "html.title",
    )


def test_html_h1_precedes_citation_title_fallback():
    result = extract_html(
        b"""
        <html><head>
          <meta name="citation_title" content="Citation Title">
        </head><body><main>
          <h1>Preferred HTML Heading</h1>
          <p>Substantive article body.</p>
        </main></body></html>
        """,
        "text/html",
    )

    assert (result.title, result.title_source) == (
        "Preferred HTML Heading",
        "html.h1",
    )


def test_jsonld_article_body_precedes_whole_page_fallback():
    result = extract_html(
        b"""
        <html><head><title>Structured article</title>
          <script type="application/ld+json">
            {"@type":"Article","articleBody":"First paragraph.\\n Second paragraph."}
          </script>
        </head><body><div>Navigation and unrelated whole-page fallback.</div></body></html>
        """,
        "text/html",
    )

    assert result.engine_version == "v7"
    assert result.text == "First paragraph. Second paragraph."
    assert "unrelated whole-page" not in result.text
    assert result.status == "completed"


def test_primary_dom_body_precedes_jsonld_article_body():
    result = extract_html(
        b"""
        <html><head><title>DOM article</title>
          <script type="application/ld+json">
            {"articleBody":"Structured fallback body."}
          </script>
        </head><body><article><p>Preferred DOM body.</p></article></body></html>
        """,
        "text/html",
    )

    assert "Preferred DOM body." in result.text
    assert "Structured fallback body." not in result.text


def test_filtered_primary_dom_falls_back_to_jsonld_article_body():
    result = extract_html(
        b"""
        <html><head><title>Structured fallback</title>
          <script type="application/ld+json">
            {"articleBody":"Usable structured article body."}
          </script>
        </head><body><article><p>x</p></article></body></html>
        """,
        "text/html",
    )

    assert result.text == "Usable structured article body."
    assert result.status == "completed"


def test_jsonld_graph_article_body_is_supported_and_non_string_is_ignored():
    graph_result = extract_html(
        b"""
        <html><head><title>Graph article</title>
          <script type="application/ld+json">
            {"@graph":[{"articleBody":{"text":"ignored"}},
                       {"articleBody":"Graph structured body."}]}
          </script>
        </head><body><div>Whole-page fallback.</div></body></html>
        """,
        "text/html",
    )
    invalid_result = extract_html(
        b"""
        <html><head><title>Invalid body</title>
          <script type="application/ld+json">{"articleBody":["ignored"]}</script>
        </head><body><div>Existing fallback body.</div></body></html>
        """,
        "text/html",
    )

    assert graph_result.text == "Graph structured body."
    assert "Existing fallback body." in invalid_result.text


def test_cross_origin_public_canonical_is_safe_metadata_and_is_not_fetched(monkeypatch):
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("canonical must not fetch")),
    )
    result = extract_html(
        b'<html><head><title>T</title><link rel="canonical" '
        b'href="https://public.example/article?id=7&utm_source=x&token=private#part">'
        b'</head><body><main><p>Useful public article body.</p></main></body></html>',
        "text/html",
        base_url="https://source.example/original",
    )

    assert result.canonical_url == "https://public.example/article?id=7"
    assert result.canonical_source_host == "source.example"
    assert result.canonical_host == "public.example"
    assert result.canonical_cross_origin is True
    assert result.canonical_validation_result == "accepted"


@pytest.mark.parametrize(
    "canonical",
    [
        "http://localhost/private",
        "http://127.0.0.1/private",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/private",
        "http://[fd00::1]/private",
        "http://user:password@public.example/private",
        "file:///private",
    ],
)
def test_unsafe_document_canonical_is_rejected(canonical):
    result = extract_html(
        f'<html><head><title>T</title><link rel="canonical" href="{canonical}"></head>'
        '<body><main><p>Useful body.</p></main></body></html>'.encode(),
        "text/html",
        base_url="https://source.example/original",
    )

    assert result.canonical_url == ""
    assert result.canonical_url_source == ""
    assert result.canonical_validation_result.startswith("rejected_")
