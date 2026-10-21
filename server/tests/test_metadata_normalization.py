from __future__ import annotations

from perclip_ingest.metadata_normalization import normalize_title_author


def test_common_normalization_is_mechanical_and_idempotent() -> None:
    first = normalize_title_author(
        title="  Research&nbsp;Title\u200b  With   Evidence  ",
        author="  First&nbsp;Author   and  Second Author  ",
        base_url="https://example.test/article",
    )
    second = normalize_title_author(
        title=first.title,
        author=first.author,
        base_url="https://example.test/article",
    )

    assert first.title == "Research Title With Evidence"
    assert first.author == "First Author and Second Author"
    assert (second.title, second.author) == (first.title, first.author)
    assert second.title_changed is False
    assert second.author_changed is False


def test_bilibili_profile_removes_only_anchored_site_wrappers() -> None:
    normalized = normalize_title_author(
        title="从 LLM 到 Agent Skill_哔哩哔哩_bilibili",
        author="UP主： 马克的技术工作坊",
        base_url="https://www.bilibili.com/video/BVsynthetic",
    )

    assert normalized.title == "从 LLM 到 Agent Skill"
    assert normalized.author == "马克的技术工作坊"
    assert normalized.title_changed is True
    assert normalized.author_changed is True


def test_bilibili_profile_preserves_semantic_words_and_unknown_suffixes() -> None:
    normalized = normalize_title_author(
        title="为什么创作者选择 Bilibili 作为发布平台",
        author="UP主文化观察",
        base_url="https://m.bilibili.com/video/BVsynthetic",
    )

    assert normalized.title == "为什么创作者选择 Bilibili 作为发布平台"
    assert normalized.author == "UP主文化观察"


def test_bilibili_rules_do_not_apply_to_lookalike_hosts() -> None:
    normalized = normalize_title_author(
        title="Research title_哔哩哔哩_bilibili",
        author="UP主：Author",
        base_url="https://www.bilibili.com.evil.example/video/BVsynthetic",
    )

    assert normalized.title == "Research title_哔哩哔哩_bilibili"
    assert normalized.author == "UP主：Author"


def test_empty_wrapper_result_fails_conservatively() -> None:
    normalized = normalize_title_author(
        title="_哔哩哔哩_bilibili",
        author="UP主：",
        base_url="https://www.bilibili.com/video/BVsynthetic",
    )

    assert normalized.title == "_哔哩哔哩_bilibili"
    assert normalized.author == "UP主："


def test_bilibili_suffix_is_removed_before_display_length_cap() -> None:
    normalized = normalize_title_author(
        title=("A" * 300) + "_哔哩哔哩_bilibili",
        author="Author",
        base_url="https://www.bilibili.com/video/BVsynthetic",
    )

    assert normalized.title == "A" * 300


def test_common_normalization_preserves_joining_controls() -> None:
    title = "خود\u200cکار"
    author = "Family 👩\u200d👩\u200d👧\u200d👦"

    first = normalize_title_author(
        title=title,
        author=author,
        base_url="https://example.test/article",
    )
    second = normalize_title_author(
        title=first.title,
        author=first.author,
        base_url="https://example.test/article",
    )

    assert first.title == title
    assert first.author == author
    assert first.title_changed is False
    assert first.author_changed is False
    assert (second.title, second.author) == (title, author)
    assert second.title_changed is False
    assert second.author_changed is False
