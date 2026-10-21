"""Materialize the synthetic Stage 22.2A Q0-Web corpus.

This script is deterministic: it writes only self-authored CC0 fixtures below
its own directory and derives every manifest hash from the emitted bytes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LICENSE = "CC0-1.0"
FIXTURE_VERSION = "q0-web-v1"


def write(relative: str, content: str | bytes) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = content if isinstance(content, bytes) else content.encode("utf-8")
    path.write_bytes(payload)


def html(title: str, paragraphs: list[str], noise: list[str] | None = None, *, head: str = "") -> str:
    noisy = noise or []
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{title}</title>{head}</head>
<body><header>合成站点页眉</header><nav>首页 登录 分享</nav>
<main><article><h1>{title}</h1>{body}</article></main>
<aside>{noise}</aside><footer>© 2099 Synthetic Fixture</footer></body></html>
""".format(
        title=title,
        head=head,
        body="".join(f"<p>{item}</p>" for item in paragraphs),
        noise="".join(f"<p>{item}</p>" for item in noisy),
    )


def response_plan(entry_url: str, body_fixture: str, *, canonical_url: str = "") -> dict[str, object]:
    return {
        "entry_url": entry_url,
        "max_redirects": 5,
        "steps": [
            {
                "url": entry_url,
                "resolution": "public",
                "connect_address": "validated",
                "status": 200,
                "headers": {"content-type": "text/html; charset=utf-8"},
                "body_fixture": body_fixture,
                "canonical_url": canonical_url,
            }
        ],
    }


def plan(relative: str, payload: dict[str, object]) -> None:
    write(relative, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def sha256(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def expected(
    title: str,
    anchors: list[str],
    excluded: list[str],
    canonical_url: str,
    state: str,
    tags: list[str],
    route: str,
    recall: bool,
    safe_error: str = "",
) -> dict[str, object]:
    return {
        "title": title,
        "body_anchors": anchors,
        "excluded": excluded,
        "canonical_url": canonical_url,
        "state": state,
        "safe_error": safe_error,
        "tags": tags,
        "route": route,
        "recall_eligible": recall,
    }


def main() -> None:
    quick = "离线队列复盘\n今天验证离线队列\n飞行模式下先进入本地队列\n重连后保持顺序\n"
    long_note = "长文整理实验\n" + "\n".join(
        f"第{index}节{'目标' if index == 1 else '事实'}：合成事实 {index:02d} 保持可追溯。"
        for index in range(1, 13)
    ) + "\n第十二节结论：固定语料用于比较当前基线。\n"
    structured = """# 可恢复任务设计

## 背景
任务在中断后必须保留原始输入。

```text
demo credential placeholder: [redacted]
```

<!-- synthetic editorial note -->
## 验证清单
检查幂等、租约与安全错误。
"""
    write("text/quick-note.txt", quick)
    write("text/long-note.txt", long_note)
    write("text/structured-note.md", structured)

    web_cases = {
        "G04": ("blog-basic.html", "本地优先的知识整理", ["本地优先减少入口摩擦。", "统一收集后再做确定性清洗。", "原始内容始终可追溯。"], ["订阅通讯", "推荐课程"], "https://example.test/articles/local-first"),
        "G05": ("news-tracking.html", "阅读清单工具发布测试版", ["工具今天发布测试版。", "团队将记录离线反馈。", "下月复盘反馈。"], ["接受 Cookie", "实时行情", "相关新闻"], "https://example.test/news/reading-tool-beta"),
        "G06": ("github-readme.html", "PerClip Fixture Runner", ["## Install", "Run the local deterministic evaluator.", "## License", "Synthetic fixtures use CC0."], ["Repository navigation", "File tree reactions"], "https://example.test/repos/perclip-fixture-runner"),
        "G07": ("technical-docs.html", "Idempotent request API", ["Stable request identifiers prevent duplicate writes.", "The first accepted result is durable.", "Replay returns the same result."], ["Version picker", "Was this helpful", "Related cards"], "https://example.test/docs/idempotent-requests"),
        "G08": ("paginated-part-1.html", "内容清洗的边界", ["正文从第一页开始。", "本页只保留已经完整获得的事实。", "后续页未自动抓取。"], ["第 1 页 / 共 3 页", "下一页精彩预告"], "https://example.test/cleaning/boundaries"),
        "G09": ("redirect-final.html", "重定向后的规范地址", ["最终页面保留正文。", "每一跳都重新验证。", "来源链可审计。"], ["正在跳转"], "https://example.test/final/redirected"),
        "G18": ("relative-canonical.html", "相对规范链接", ["规范地址可安全解析。", "相对链接基于最终响应地址。", "查询参数被保留。"], ["Alternate language"], "https://example.test/articles/canonical?id=7"),
        "G19": ("qa-jsonld-title.html", "如何判断网页正文提取质量？", ["先定义正文范围。", "检查必要事实是否保留。", "再比较噪声比例。"], ["author@example.invalid", "回答评论", "相关问题"], "https://example.test/questions/extraction-quality"),
        "G20": ("social-og-title.html", "三步整理每周阅读清单", ["先统一收集入口。", "工作日只做轻量标记。", "周末完成回顾。"], ["点赞 999", "评论区", "推荐流"], "https://example.test/posts/weekly-reading"),
        "G21": ("no-title.html", "", ["正文首句作为候选。", "后续句子提供确定性内容。", "不得编造站点名。"], ["Untitled"], "https://example.test/articles/no-title"),
        "G22": ("spa-shell.html", "", ["需要浏览器渲染"], ["bundle.synthetic.js", "preload-manifest"], "https://example.test/app/note/42"),
        "G39": ("bilingual.html", "Local-first 知识工作流", ["Capture locally before enrichment.", "Keep deterministic lineage.", "保留原始 provenance。"], ["Language switcher", "Translated navigation"], "https://example.test/articles/bilingual"),
    }
    for fixture_id, (filename, title, paragraphs, noise, _canonical) in web_cases.items():
        head = ""
        if fixture_id == "G18":
            head = '<link rel="canonical" href="/articles/canonical?id=7"><link rel="alternate" href="/en">'
        elif fixture_id == "G19":
            head = '<script type="application/ld+json">{"author":"author@example.invalid"}</script>'
        elif fixture_id == "G20":
            head = '<meta property="og:title" content="三步整理每周阅读清单">'
        if fixture_id == "G21":
            write(f"web/{filename}", html("", paragraphs, noise, head=head).replace("<title></title>", ""))
        elif fixture_id == "G22":
            write(f"web/{filename}", "<!doctype html><div id=app>需要浏览器渲染</div><script src=bundle.synthetic.js></script><link rel=preload href=preload-manifest>")
        else:
            write(f"web/{filename}", html(title, paragraphs, noise, head=head))

    noisy_facts = [f"有效事实 {index:02d}：固定压力样本保持顺序。" for index in range(1, 26)]
    noisy_page = html(
        "鲁棒清洗的压力样本",
        ["有效正文第一段。", *noisy_facts, "有效正文最终结论。"],
        [*[f"推荐内容 {index:02d}" for index in range(1, 61)], *[f"评论噪声 {index:03d}" for index in range(1, 101)], "法律页脚"],
    )
    write("web/long-noisy.html", noisy_page)

    duplicate_body = html(
        "同一文章的两个入口",
        ["规范地址用于聚合。", "两个来源事件仍然独立。", "来源事件仍分别保留。"],
        ["UTM 分享按钮"],
    )
    write("web/duplicate-variants.html", duplicate_body)

    # Successful and partial HTTP plans.
    plan_urls = {
        "G04": "https://example.test/articles/local-first",
        "G05": "https://example.test/news/reading-tool-beta?utm_source=fixture&ref=share",
        "G06": "https://example.test/repos/perclip-fixture-runner",
        "G07": "https://example.test/docs/idempotent-requests",
        "G08": "https://example.test/cleaning/boundaries?page=1",
        "G18": "https://example.test/start/canonical",
        "G19": "https://example.test/questions/extraction-quality",
        "G20": "https://example.test/posts/weekly-reading",
        "G21": "https://example.test/articles/no-title",
        "G22": "https://example.test/app/note/42",
        "G39": "https://example.test/articles/bilingual",
        "G40": "https://example.test/stress/long-noisy",
    }
    body_for = {
        "G04": "web/blog-basic.html", "G05": "web/news-tracking.html",
        "G06": "web/github-readme.html", "G07": "web/technical-docs.html",
        "G08": "web/paginated-part-1.html", "G18": "web/relative-canonical.html",
        "G19": "web/qa-jsonld-title.html", "G20": "web/social-og-title.html",
        "G21": "web/no-title.html", "G22": "web/spa-shell.html",
        "G39": "web/bilingual.html", "G40": "web/long-noisy.html",
    }
    for fixture_id, entry_url in plan_urls.items():
        plan(f"response-plans/{fixture_id}.json", response_plan(entry_url, body_for[fixture_id]))

    plan("response-plans/G09.json", {
        "entry_url": "https://example.test/start?utm_source=fixture",
        "max_redirects": 5,
        "steps": [
            {"url": "https://example.test/start", "resolution": "public", "connect_address": "validated", "status": 302, "headers": {"location": "/middle?ref=share"}},
            {"url": "https://example.test/middle", "resolution": "public", "connect_address": "validated", "status": 307, "headers": {"location": "/final/redirected"}},
            {"url": "https://example.test/final/redirected", "resolution": "public", "connect_address": "validated", "status": 200, "headers": {"content-type": "text/html"}, "body_fixture": "web/redirect-final.html"},
        ],
    })
    plan("response-plans/G10.json", {
        "entry_url": "https://example.test/loop-a", "max_redirects": 3,
        "steps": [
            {"url": "https://example.test/loop-a", "resolution": "public", "connect_address": "validated", "status": 302, "headers": {"location": "/loop-b"}},
            {"url": "https://example.test/loop-b", "resolution": "public", "connect_address": "validated", "status": 302, "headers": {"location": "/loop-a"}},
        ],
    })
    plan("response-plans/G11.json", {"entry_url": "http://127.0.0.1/private", "steps": [{"url": "http://127.0.0.1/private", "resolution": "private", "connect_address": "blocked"}]})
    plan("response-plans/G12.json", {"entry_url": "http://[::1]/private", "steps": [{"url": "http://[::1]/private", "resolution": "private", "connect_address": "blocked"}]})
    plan("response-plans/G13.json", {"entry_url": "https://rebind.example.test/article", "steps": [{"url": "https://rebind.example.test/article", "resolution": "public", "connect_address": "private_rebind"}]})
    plan("response-plans/G14.json", {"entry_url": "https://example.test/slow/article", "steps": [{"url": "https://example.test/slow/article", "resolution": "public", "connect_address": "validated", "error": "timeout"}]})
    plan("response-plans/G15.json", {"entry_url": "https://example.test/large/article", "steps": [{"url": "https://example.test/large/article", "resolution": "public", "connect_address": "validated", "status": 200, "headers": {"content-type": "text/html", "content-length": "8193"}, "body_size": 8193}], "max_bytes": 8192})
    plan("response-plans/G16.json", {"entry_url": "https://example.test/mismatch", "steps": [{"url": "https://example.test/mismatch", "resolution": "public", "connect_address": "validated", "status": 200, "headers": {"content-type": "image/png"}, "inline_body": "<html><p>mislabeled payload</p></html>"}]})
    plan("response-plans/G38.json", {
        "entry_url": "https://example.test/articles/same-content?utm_source=alpha",
        "variant_urls": ["https://example.test/articles/same-content?utm_source=alpha", "https://example.test/articles/same-content?ref=beta"],
        "steps": [{"url": "https://example.test/articles/same-content", "resolution": "public", "connect_address": "validated", "status": 200, "headers": {"content-type": "text/html"}, "body_fixture": "web/duplicate-variants.html"}],
    })

    share = {
        "text": "缓存刷新检查\n覆盖安装后检查桌面图标\n清除仅测试包缓存\n记录 OEM 差异",
        "url": "https://example.test/checklists/launcher-cache",
        "source_app": "Synthetic Share Sheet",
    }
    write("shares/text-and-url.json", json.dumps(share, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    write("files/unsupported.bin", b"PERCLIP_SYNTHETIC_UNSUPPORTED_BINARY\x00\x01\x02")

    cases: list[dict[str, object]] = []

    def add(
        fixture_id: str,
        source_class: str,
        fixture_path: str,
        input_fields: dict[str, object],
        expected_fields: dict[str, object],
        response_plan_path: str = "",
        extra: dict[str, object] | None = None,
    ) -> None:
        paths = [fixture_path] + ([response_plan_path] if response_plan_path and response_plan_path != fixture_path else [])
        cases.append({
            "fixture_version": FIXTURE_VERSION,
            "id": fixture_id,
            "tier": "q0-web",
            "source_class": source_class,
            "license": LICENSE,
            "fixture_path": fixture_path,
            "response_plan": response_plan_path,
            "artifacts": [
                {"path": path, "sha256": sha256(path), "license": LICENSE, "source_class": source_class}
                for path in paths
            ],
            "input": input_fields,
            "expected": expected_fields,
            **(extra or {}),
        })

    add("G01", "android_quick_text", "text/quick-note.txt", {"source_type": "text", "title_hint": "离线队列复盘", "mime_type": "text/plain"}, expected("离线队列复盘", ["今天验证离线队列", "重连后保持顺序"], [], "", "completed", ["Android", "离线队列"], "工作方法", True))
    add("G02", "long_plain_text", "text/long-note.txt", {"source_type": "text", "title_hint": "长文整理实验", "mime_type": "text/plain"}, expected("长文整理实验", ["第一节目标", "合成事实 06", "第十二节结论"], ["-----"], "", "completed", ["长文", "整理"], "研究资料", True))
    add("G03", "markdown", "text/structured-note.md", {"source_type": "text", "title_hint": "可恢复任务设计", "mime_type": "text/markdown"}, expected("可恢复任务设计", ["## 背景", "## 验证清单"], ["demo credential placeholder", "synthetic editorial note"], "", "completed", ["任务系统", "可靠性"], "研究资料", True))

    web_expected = {
        "G04": expected("本地优先的知识整理", ["本地优先减少入口摩擦", "原始内容始终可追溯"], ["合成站点页眉", "订阅通讯", "推荐课程"], "https://example.test/articles/local-first", "completed", ["知识管理", "本地优先"], "研究资料", True),
        "G05": expected("阅读清单工具发布测试版", ["工具今天发布测试版", "下月复盘反馈"], ["接受 Cookie", "实时行情", "相关新闻"], "https://example.test/news/reading-tool-beta", "completed", ["产品动态", "阅读"], "研究资料", True),
        "G06": expected("PerClip Fixture Runner", ["## Install", "## License"], ["Repository navigation", "File tree reactions"], "https://example.test/repos/perclip-fixture-runner", "completed", ["GitHub", "测试工具"], "工作方法", True),
        "G07": expected("Idempotent request API", ["Stable request identifiers", "Replay returns the same result"], ["Version picker", "Was this helpful", "Related cards"], "https://example.test/docs/idempotent-requests", "completed", ["幂等", "API"], "研究资料", True),
        "G08": expected("内容清洗的边界", ["正文从第一页开始", "后续页未自动抓取"], ["第 1 页 / 共 3 页", "下一页精彩预告"], "https://example.test/cleaning/boundaries", "partial", ["内容清洗", "网页"], "研究资料", True),
        "G09": expected("重定向后的规范地址", ["最终页面保留正文", "来源链可审计"], ["正在跳转"], "https://example.test/final/redirected", "completed", ["URL", "溯源"], "研究资料", True),
        "G18": expected("相对规范链接", ["规范地址可安全解析", "查询参数被保留"], ["Alternate language"], "https://example.test/articles/canonical?id=7", "completed", ["canonical", "URL"], "研究资料", True),
        "G19": expected("如何判断网页正文提取质量？", ["先定义正文范围", "再比较噪声比例"], ["author@example.invalid", "回答评论", "相关问题"], "https://example.test/questions/extraction-quality", "completed", ["质量评估", "问答"], "研究资料", True),
        "G20": expected("三步整理每周阅读清单", ["先统一收集入口", "周末完成回顾"], ["点赞 999", "评论区", "推荐流"], "https://example.test/posts/weekly-reading", "completed", ["阅读", "生活方式"], "生活记录", True),
        "G21": expected("正文首句作为候选", ["正文首句作为候选", "不得编造站点名"], ["Untitled"], "https://example.test/articles/no-title", "partial", ["标题回退", "网页"], "研究资料", True),
        "G22": expected("动态页面未完整读取", ["需要浏览器渲染"], ["bundle.synthetic.js", "preload-manifest"], "https://example.test/app/note/42", "partial", ["动态网页", "待增强"], "收件箱", False),
        "G39": expected("Local-first 知识工作流", ["Capture locally", "保留原始 provenance"], ["Language switcher", "Translated navigation"], "https://example.test/articles/bilingual", "completed", ["双语", "knowledge workflow"], "研究资料", True),
        "G40": expected("鲁棒清洗的压力样本", ["有效正文第一段", "有效事实 13", "有效正文最终结论"], ["推荐内容 30", "评论噪声 050", "法律页脚"], "https://example.test/stress/long-noisy", "completed", ["压力测试", "内容清洗"], "研究资料", True),
    }
    for fixture_id in ["G04", "G05", "G06", "G07", "G08", "G09"]:
        fixture = "web/redirect-final.html" if fixture_id == "G09" else body_for[fixture_id]
        add(fixture_id, "synthetic_web", fixture, {"source_type": "url", "url": json.loads((ROOT / f"response-plans/{fixture_id}.json").read_text())["entry_url"], "mime_type": "text/html"}, web_expected[fixture_id], f"response-plans/{fixture_id}.json")

    failures = {
        "G10": ("redirect_loop", "https://example.test/loop-a", "redirect_limit_exceeded", "无法读取网页"),
        "G11": ("loopback_block", "http://127.0.0.1/private", "private_address_blocked", "受限地址"),
        "G12": ("private_ipv6_block", "http://[::1]/private", "private_address_blocked", "受限地址"),
        "G13": ("dns_rebind", "https://rebind.example.test/article", "private_address_blocked", "地址校验失败"),
        "G14": ("timeout", "https://example.test/slow/article", "web_fetch_failed", "网页读取超时"),
        "G15": ("oversize", "https://example.test/large/article", "response_too_large", "响应超过安全上限"),
        "G16": ("mime_mismatch", "https://example.test/mismatch", "unsupported_content_type", "内容类型不匹配"),
    }
    for fixture_id, (source_class, url, safe_error, fallback) in failures.items():
        add(fixture_id, source_class, f"response-plans/{fixture_id}.json", {"source_type": "url", "url": url, "mime_type": "text/html"}, expected(fallback, [], ["mislabeled payload"] if fixture_id == "G16" else [], url, "failed", ["抓取失败"], "收件箱", False, safe_error), f"response-plans/{fixture_id}.json")

    add("G17", "unsupported_binary", "files/unsupported.bin", {"source_type": "file", "filename": "unsupported.bin", "mime_type": "application/octet-stream"}, expected("unsupported.bin", [], ["PERCLIP_SYNTHETIC_UNSUPPORTED_BINARY"], "", "failed", ["不支持格式"], "收件箱", False, "unsupported_media_type"))
    for fixture_id in ["G18", "G19", "G20", "G21", "G22"]:
        add(fixture_id, "synthetic_web", body_for[fixture_id], {"source_type": "url", "url": plan_urls[fixture_id], "mime_type": "text/html"}, web_expected[fixture_id], f"response-plans/{fixture_id}.json")
    add("G37", "share_text_url", "shares/text-and-url.json", {"source_type": "text", "title_hint": "缓存刷新检查", "mime_type": "text/plain"}, expected("缓存刷新检查", ["覆盖安装后检查桌面图标", "记录 OEM 差异"], ["share-app boilerplate"], "https://example.test/checklists/launcher-cache", "completed", ["Android", "图标测试"], "工作方法", True))
    add("G38", "canonical_duplicate", "web/duplicate-variants.html", {"source_type": "url", "url": "https://example.test/articles/same-content?utm_source=alpha", "mime_type": "text/html"}, expected("同一文章的两个入口", ["规范地址用于聚合", "来源事件仍分别保留"], ["UTM 分享按钮"], "https://example.test/articles/same-content", "completed", ["去重", "canonical"], "研究资料", True), "response-plans/G38.json", {"duplicate_group": "same-content"})
    add("G39", "bilingual_web", "web/bilingual.html", {"source_type": "url", "url": plan_urls["G39"], "mime_type": "text/html"}, web_expected["G39"], "response-plans/G39.json")
    add("G40", "long_noisy_web", "web/long-noisy.html", {"source_type": "url", "url": plan_urls["G40"], "mime_type": "text/html"}, web_expected["G40"], "response-plans/G40.json")

    assert [case["id"] for case in cases] == [f"G{index:02d}" for index in range(1, 23)] + ["G37", "G38", "G39", "G40"]
    write("manifest.jsonl", "".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n" for case in cases))
    write("LICENSES.md", """# Q0-Web fixture licenses

All 26 Stage 22.2A fixtures and response plans are original synthetic works
created for PerClip and dedicated under CC0-1.0. They use only reserved
`.test`/`.invalid` names, loopback literals required by SSRF cases, and
fictional content. No production URL, credential, token, private message,
device identifier, paywalled excerpt, or third-party page copy is included.

Each `manifest.jsonl` row repeats the license and records SHA-256, source class,
and path for every artifact consumed by that case.
""")


if __name__ == "__main__":
    main()
