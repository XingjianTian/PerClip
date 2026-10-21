from __future__ import annotations

from dataclasses import replace

from perclip_ingest.platform_extraction import (
    BilibiliHtmlAdapter,
    DEFAULT_PLATFORM_HTML_ADAPTERS,
    DouyinHtmlAdapter,
    W3cRecommendationHtmlAdapter,
    ZhihuHtmlAdapter,
    extract_html_with_adapters,
)
from perclip_ingest.web_extraction import ExtractionResult, extract_html


HTML = b"""
<html><head><title>Common title</title></head>
<body><main><p>Common readable body.</p></main></body></html>
"""


class FakeAdapter:
    def __init__(
        self,
        *,
        host: str,
        result: ExtractionResult | None,
        calls: list[str],
        name: str,
    ) -> None:
        self.host = host
        self.result = result
        self.calls = calls
        self.name = name

    def supports(self, *, base_url: str, content_type: str) -> bool:
        self.calls.append(f"supports:{self.name}")
        return self.host in base_url and content_type == "text/html"

    def extract(
        self,
        body: bytes,
        content_type: str,
        *,
        base_url: str,
    ) -> ExtractionResult | None:
        self.calls.append(f"extract:{self.name}")
        assert body == HTML
        assert content_type == "text/html"
        assert base_url == "https://video.example/watch/1"
        return self.result


def adapter_result(title: str) -> ExtractionResult:
    return replace(
        extract_html(HTML, "text/html"),
        engine="synthetic-platform-adapter",
        engine_version="v1",
        title=title,
    )


def test_first_non_empty_matching_adapter_result_wins_in_input_order():
    calls: list[str] = []
    result = extract_html_with_adapters(
        HTML,
        "text/html",
        base_url="https://video.example/watch/1",
        adapters=(
            FakeAdapter(host="other.example", result=adapter_result("other"), calls=calls, name="other"),
            FakeAdapter(host="video.example", result=adapter_result("first"), calls=calls, name="first"),
            FakeAdapter(host="video.example", result=adapter_result("second"), calls=calls, name="second"),
        ),
    )

    assert result.title == "first"
    assert calls == ["supports:other", "supports:first", "extract:first"]


def test_matching_adapter_may_decline_and_next_adapter_can_handle():
    calls: list[str] = []
    result = extract_html_with_adapters(
        HTML,
        "text/html",
        base_url="https://video.example/watch/1",
        adapters=(
            FakeAdapter(host="video.example", result=None, calls=calls, name="decline"),
            FakeAdapter(host="video.example", result=adapter_result("handled"), calls=calls, name="handled"),
        ),
    )

    assert result.title == "handled"
    assert calls == [
        "supports:decline",
        "extract:decline",
        "supports:handled",
        "extract:handled",
    ]


def test_no_adapter_result_is_identical_to_common_extractor_result():
    calls: list[str] = []
    expected = extract_html(HTML, "text/html", base_url="https://web.example/article")
    actual = extract_html_with_adapters(
        HTML,
        "text/html",
        base_url="https://web.example/article",
        adapters=(
            FakeAdapter(host="video.example", result=adapter_result("unused"), calls=calls, name="unused"),
        ),
    )

    assert actual == expected
    assert calls == ["supports:unused"]


BILIBILI_HTML = """
<html lang="zh-CN"><head>
  <title>Common HTML title</title>
  <meta property="og:title" content="Synthetic video title_哔哩哔哩_bilibili">
  <meta name="author" content="UP主： Synthetic UP">
  <meta property="article:published_time" content="2026-08-01">
  <meta name="description" content="Lower priority description">
  <meta property="og:description" content=" A source-faithful public video description. ">
  <meta property="video:tag" content="Topic A">
  <meta property="video:tag" content="Topic A">
  <meta name="keywords" content="Topic B, Topic A，Topic C">
</head><body><nav>Recommendations and comments</nav><script>dynamic shell</script></body></html>
""".encode()


def test_bilibili_adapter_uses_common_metadata_and_public_description_tags():
    result = extract_html_with_adapters(
        BILIBILI_HTML,
        "text/html; charset=utf-8",
        base_url="https://www.bilibili.com/video/BVsynthetic",
        adapters=DEFAULT_PLATFORM_HTML_ADAPTERS,
    )

    assert (result.engine, result.engine_version) == ("perclip-bilibili-html", "v2")
    assert (result.title, result.title_source) == ("Synthetic video title", "meta.og:title")
    assert (result.author, result.author_source) == ("Synthetic UP", "meta.author")
    assert (result.published_at, result.published_at_source) == (
        "2026-08-01",
        "meta.article:published_time",
    )
    assert result.text == (
        "A source-faithful public video description.\n\n"
        "标签：Topic A、Topic B、Topic C"
    )
    assert result.status == "partial"
    assert result.quality_reason == "video_description_without_transcript"
    assert "Recommendations" not in result.text


def test_bilibili_adapter_supports_only_exact_hosts_and_html():
    adapter = BilibiliHtmlAdapter()

    assert adapter.supports(
        base_url="https://m.bilibili.com/video/BVsynthetic",
        content_type="application/xhtml+xml",
    )
    assert not adapter.supports(
        base_url="https://www.bilibili.com.evil.example/video/BVsynthetic",
        content_type="text/html",
    )
    assert not adapter.supports(
        base_url="https://www.bilibili.com/video/BVsynthetic",
        content_type="text/plain",
    )


def test_bilibili_adapter_declines_without_description_or_tags():
    body = b"<html><head><title>Shell title</title></head><body><script>shell</script></body></html>"
    common = extract_html(
        body,
        "text/html",
        base_url="https://www.bilibili.com/video/BVsynthetic",
    )
    adapted = extract_html_with_adapters(
        body,
        "text/html",
        base_url="https://www.bilibili.com/video/BVsynthetic",
        adapters=DEFAULT_PLATFORM_HTML_ADAPTERS,
    )

    assert adapted == common


def test_bilibili_adapter_caps_first_seen_tags():
    keywords = ",".join(f"Tag {index}" for index in range(20))
    body = (
        '<html><head><meta property="og:description" content="Useful description">'
        f'<meta name="keywords" content="{keywords}"></head></html>'
    ).encode()

    result = BilibiliHtmlAdapter().extract(
        body,
        "text/html",
        base_url="https://www.bilibili.com/video/BVsynthetic",
    )

    assert result is not None
    assert result.text.split("标签：", 1)[1].split("、") == [
        f"Tag {index}" for index in range(12)
    ]


DOUYIN_HTML = """
<html><head>
  <meta property="og:title" content="Synthetic Douyin title - 抖音">
  <meta name="lark:url:video_title" content="Synthetic Douyin title - 抖音">
  <meta name="description" content="A source-faithful synthetic video summary. #topic">
  <script type="application/ld+json">
    {"@type":"BreadcrumbList","itemListElement":[
      {"position":1,"name":"抖音","item":"https://www.douyin.com/"},
      {"position":2,"name":"Synthetic Creator","item":"https://www.douyin.com/user/synthetic"}
    ]}
  </script>
</head><body><div>Comments and recommendations must not become core text.</div></body></html>
""".encode()


def test_douyin_adapter_uses_description_and_validated_creator_breadcrumb():
    result = extract_html_with_adapters(
        DOUYIN_HTML,
        "text/html",
        base_url="https://www.douyin.com/video/1234567890",
        adapters=DEFAULT_PLATFORM_HTML_ADAPTERS,
    )

    assert (result.engine, result.engine_version) == ("perclip-douyin-html", "v1")
    assert (result.title, result.title_source) == (
        "Synthetic Douyin title",
        "meta.lark:url:video_title",
    )
    assert (result.author, result.author_source) == (
        "Synthetic Creator",
        "jsonld.breadcrumb.creator",
    )
    assert result.text == "A source-faithful synthetic video summary. #topic"
    assert result.quality_reason == "source_faithful_platform_summary"
    assert "Comments" not in result.text


def test_douyin_adapter_declines_unvalidated_creator_or_lookalike_host():
    unsafe_creator = DOUYIN_HTML.replace(b"https://www.douyin.com/user/", b"https://evil.example/user/")
    assert DouyinHtmlAdapter().extract(
        unsafe_creator,
        "text/html",
        base_url="https://www.douyin.com/video/1234567890",
    ) is None
    assert not DouyinHtmlAdapter().supports(
        base_url="https://www.douyin.com.evil.example/video/1234567890",
        content_type="text/html",
    )


ZHIHU_ANSWER_HTML = """
<html><head>
  <meta property="og:title" content="Synthetic question - Synthetic Answerer 的回答">
  <meta property="og:description" content="A source-faithful synthetic answer summary.">
</head><body><main>Long page chrome and prompts must not replace the summary.</main></body></html>
""".encode()

ZHIHU_COLUMN_HTML = """
<html><head>
  <meta property="og:title" content="Synthetic column title">
  <meta name="description" content="A source-faithful synthetic column summary.">
</head><body><main><div itemprop="author"><span class="AuthorInfo-name">Synthetic Column Author</span></div></main></body></html>
""".encode()


def test_zhihu_answer_adapter_uses_exact_og_title_author_shape_and_summary():
    result = ZhihuHtmlAdapter().extract(
        ZHIHU_ANSWER_HTML,
        "text/html",
        base_url="https://www.zhihu.com/question/123/answer/456",
    )

    assert result is not None
    assert (result.author, result.author_source) == (
        "Synthetic Answerer",
        "meta.og:title.answer_author",
    )
    assert result.text == "A source-faithful synthetic answer summary."
    assert result.quality_reason == "source_faithful_platform_summary"


def test_zhihu_column_adapter_uses_explicit_author_container_and_summary():
    result = ZhihuHtmlAdapter().extract(
        ZHIHU_COLUMN_HTML,
        "text/html",
        base_url="https://zhuanlan.zhihu.com/p/123456",
    )

    assert result is not None
    assert (result.author, result.author_source) == (
        "Synthetic Column Author",
        "html.itemprop.author",
    )
    assert result.text == "A source-faithful synthetic column summary."


def test_zhihu_adapter_requires_exact_supported_paths_and_source_fields():
    adapter = ZhihuHtmlAdapter()
    assert not adapter.supports(
        base_url="https://www.zhihu.com/question/123",
        content_type="text/html",
    )
    assert not adapter.supports(
        base_url="https://zhuanlan.zhihu.com.evil.example/p/123456",
        content_type="text/html",
    )
    assert adapter.extract(
        '<meta property="og:title" content="Question - Author 的回答">'.encode(),
        "text/html",
        base_url="https://www.zhihu.com/question/123/answer/456",
    ) is None


W3C_RECOMMENDATION_HTML = b"""
<html><head><title>Synthetic Standard</title></head><body><main>
  <h1>Synthetic Standard</h1>
  <p>W3C Recommendation 25 August 2026</p>
  <p>Copyright 2026 World Wide Web Consortium.</p>
  <p>This specification defines a durable synthetic behavior.</p>
</main></body></html>
"""


def test_w3c_recommendation_adapter_uses_explicit_publisher_signal():
    result = W3cRecommendationHtmlAdapter().extract(
        W3C_RECOMMENDATION_HTML,
        "text/html",
        base_url="https://www.w3.org/TR/synthetic/",
    )

    assert result is not None
    assert (result.author, result.author_source) == (
        "World Wide Web Consortium",
        "html.explicit.w3c_publisher",
    )
    assert "durable synthetic behavior" in result.text


def test_w3c_recommendation_adapter_requires_exact_origin_path_and_signals():
    adapter = W3cRecommendationHtmlAdapter()
    assert not adapter.supports(
        base_url="https://www.w3.org.evil.example/TR/synthetic/",
        content_type="text/html",
    )
    assert not adapter.supports(
        base_url="https://www.w3.org/standards/synthetic/",
        content_type="text/html",
    )
    assert adapter.extract(
        b"<html><body><main>World Wide Web Consortium without publication status.</main></body></html>",
        "text/html",
        base_url="https://www.w3.org/TR/synthetic/",
    ) is None
