import sqlite3

import pytest

from perclip_ingest.knowledge_base_store import KnowledgeBaseStore
from perclip_ingest.routing import RoutingPreviewError, RoutingPreviewInput, extract_domain, preview_route


def store_for(tmp_path) -> KnowledgeBaseStore:
    store = KnowledgeBaseStore(tmp_path)
    store.init()
    return store


def add_kb(store: KnowledgeBaseStore, name: str):
    return store.create_knowledge_base(name=name)


def test_manual_override_has_highest_priority(tmp_path):
    store = store_for(tmp_path)
    manual = add_kb(store, "Manual")
    source = add_kb(store, "Source")
    store.create_routing_rule(
        name="Chrome",
        rule_type="source_app",
        pattern="Chrome",
        target_knowledge_base_id=source.id,
    )

    preview = preview_route(
        store,
        RoutingPreviewInput(source_app="Chrome", target_knowledge_base_id=manual.id),
    )

    assert preview.knowledge_base_id == manual.id
    assert preview.decision_type == "manual"
    assert preview.manual_override is True
    assert "manual override" in preview.reason


def test_source_app_beats_url_domain(tmp_path):
    store = store_for(tmp_path)
    source = add_kb(store, "Source")
    domain = add_kb(store, "Domain")
    store.create_routing_rule(name="GitHub app", rule_type="source_app", pattern="GitHub", target_knowledge_base_id=source.id)
    store.create_routing_rule(name="GitHub domain", rule_type="url_domain", pattern="github.com", target_knowledge_base_id=domain.id)

    preview = preview_route(store, RoutingPreviewInput(source_app="GitHub", url="https://github.com/openai"))

    assert preview.knowledge_base_id == source.id
    assert preview.matched_rule_ids != []
    assert len(preview.matched_rule_ids) == 2


def test_url_domain_beats_mime_and_file_extension(tmp_path):
    store = store_for(tmp_path)
    domain = add_kb(store, "Domain")
    pdf = add_kb(store, "PDF")
    store.create_routing_rule(name="GitHub", rule_type="url_domain", pattern="github.com", target_knowledge_base_id=domain.id)
    store.create_routing_rule(name="PDF mime", rule_type="mime_type", pattern="application/pdf", target_knowledge_base_id=pdf.id)
    store.create_routing_rule(name="PDF ext", rule_type="file_extension", pattern=".pdf", target_knowledge_base_id=pdf.id)

    preview = preview_route(
        store,
        RoutingPreviewInput(url="https://docs.github.com/demo.pdf", mime_type="application/pdf", filename="demo.pdf"),
    )

    assert preview.knowledge_base_id == domain.id
    assert len(preview.matched_rule_ids) == 3


def test_mime_and_file_extension_beat_keyword(tmp_path):
    store = store_for(tmp_path)
    image = add_kb(store, "Images")
    keyword = add_kb(store, "Keyword")
    store.create_routing_rule(name="Image wildcard", rule_type="mime_type", pattern="image/*", target_knowledge_base_id=image.id)
    store.create_routing_rule(name="PerClip", rule_type="keyword", pattern="PerClip", target_knowledge_base_id=keyword.id)

    preview = preview_route(
        store,
        RoutingPreviewInput(mime_type="image/png", title_hint="PerClip screenshot", filename="screen.png"),
    )

    assert preview.knowledge_base_id == image.id
    assert preview.decision_type == "rule"
    assert "image/*" in preview.reason


def test_file_extension_beats_keyword_when_mime_does_not_match(tmp_path):
    store = store_for(tmp_path)
    pdf = add_kb(store, "PDF")
    keyword = add_kb(store, "Keyword")
    store.create_routing_rule(name="PDF ext", rule_type="file_extension", pattern="pdf", target_knowledge_base_id=pdf.id)
    store.create_routing_rule(name="PerClip", rule_type="keyword", pattern="PerClip", target_knowledge_base_id=keyword.id)

    preview = preview_route(store, RoutingPreviewInput(filename="demo.pdf", title_hint="PerClip"))

    assert preview.knowledge_base_id == pdf.id


def test_keyword_beats_default(tmp_path):
    store = store_for(tmp_path)
    keyword = add_kb(store, "Keyword")
    store.create_routing_rule(name="PerClip", rule_type="keyword", pattern="perclip", target_knowledge_base_id=keyword.id)

    preview = preview_route(store, RoutingPreviewInput(title_hint="PERCLIP notes"))

    assert preview.knowledge_base_id == keyword.id
    assert preview.decision_type == "rule"


def test_default_only_uses_active_capture_time_default_and_bypasses_rules(tmp_path):
    store = store_for(tmp_path)
    rule_target = add_kb(store, "Rule target")
    capture_time_default = add_kb(store, "Capture-time default")
    store.create_routing_rule(
        name="PerClip",
        rule_type="keyword",
        pattern="PerClip",
        target_knowledge_base_id=rule_target.id,
    )

    preview = preview_route(
        store,
        RoutingPreviewInput(
            text="PerClip",
            target_knowledge_base_id=capture_time_default.id,
            routing_mode="default_only",
        ),
    )

    assert preview.knowledge_base_id == capture_time_default.id
    assert preview.decision_type == "default"
    assert preview.matched_rule_ids == []
    assert preview.manual_override is False
    assert preview.confidence == 1.0
    assert "capture-time default" in preview.reason


@pytest.mark.parametrize("unavailable_kind", ["archived", "deleted", "unknown"])
def test_default_only_unavailable_capture_time_default_falls_back_to_current_default(tmp_path, unavailable_kind):
    store = store_for(tmp_path)
    capture_time_default = add_kb(store, "Old default")
    current_default = store.get_default_knowledge_base()
    assert current_default is not None
    if unavailable_kind == "archived":
        store.archive_knowledge_base(capture_time_default.id)
        target_id = capture_time_default.id
    elif unavailable_kind == "deleted":
        store.delete_knowledge_base(capture_time_default.id)
        target_id = capture_time_default.id
    else:
        target_id = "kb_unknown"

    preview = preview_route(
        store,
        RoutingPreviewInput(target_knowledge_base_id=target_id, routing_mode="default_only"),
    )

    assert preview.knowledge_base_id == current_default.id
    assert preview.decision_type == "default"
    assert preview.manual_override is False
    assert preview.matched_rule_ids == []
    assert "unavailable" in preview.reason


def test_default_only_without_capture_time_target_uses_current_default(tmp_path):
    store = store_for(tmp_path)
    current_default = store.get_default_knowledge_base()
    assert current_default is not None

    preview = preview_route(store, RoutingPreviewInput(routing_mode="default_only"))

    assert preview.knowledge_base_id == current_default.id
    assert preview.decision_type == "default"
    assert preview.manual_override is False
    assert preview.matched_rule_ids == []
    assert "current default" in preview.reason


def test_default_only_without_available_current_default_returns_stable_error(tmp_path):
    store = store_for(tmp_path)
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.execute("update knowledge_bases set is_default = 0")

    with pytest.raises(RoutingPreviewError, match="default knowledge base is missing"):
        preview_route(
            store,
            RoutingPreviewInput(target_knowledge_base_id="kb_unknown", routing_mode="default_only"),
        )


def test_unknown_routing_mode_is_rejected(tmp_path):
    store = store_for(tmp_path)

    with pytest.raises(RoutingPreviewError, match="unsupported routing mode"):
        preview_route(store, RoutingPreviewInput(routing_mode="future_mode"))


def test_no_rule_match_routes_to_default(tmp_path):
    store = store_for(tmp_path)
    default = store.get_default_knowledge_base()
    assert default is not None

    preview = preview_route(store, RoutingPreviewInput(title_hint="nothing"))

    assert preview.knowledge_base_id == default.id
    assert preview.decision_type == "default"
    assert preview.confidence == 0.5
    assert "fallback default" in preview.reason


def test_disabled_rule_does_not_participate(tmp_path):
    store = store_for(tmp_path)
    target = add_kb(store, "Target")
    default = store.get_default_knowledge_base()
    assert default is not None
    store.create_routing_rule(
        name="Disabled",
        enabled=False,
        rule_type="keyword",
        pattern="PerClip",
        target_knowledge_base_id=target.id,
    )

    preview = preview_route(store, RoutingPreviewInput(title_hint="PerClip"))

    assert preview.knowledge_base_id == default.id
    assert preview.matched_rule_ids == []


def test_rule_priority_within_same_type(tmp_path):
    store = store_for(tmp_path)
    high = add_kb(store, "High")
    low = add_kb(store, "Low")
    store.create_routing_rule(name="Low priority", rule_type="keyword", pattern="PerClip", target_knowledge_base_id=low.id, priority=50)
    high_rule = store.create_routing_rule(
        name="High priority",
        rule_type="keyword",
        pattern="PerClip",
        target_knowledge_base_id=high.id,
        priority=1,
    )

    preview = preview_route(store, RoutingPreviewInput(text="PerClip"))

    assert preview.knowledge_base_id == high.id
    assert preview.matched_rule_id == high_rule.id
    assert len(preview.matched_rule_ids) == 2


def test_rule_with_archived_target_is_skipped_with_explanatory_reason(tmp_path):
    store = store_for(tmp_path)
    target = add_kb(store, "Target")
    rule = store.create_routing_rule(name="Target", rule_type="keyword", pattern="PerClip", target_knowledge_base_id=target.id)
    store.archive_knowledge_base(target.id)
    default = store.get_default_knowledge_base()
    assert default is not None

    preview = preview_route(store, RoutingPreviewInput(text="PerClip"))

    assert preview.knowledge_base_id == default.id
    assert preview.matched_rule_ids == [rule.id]
    assert "archived or deleted" in preview.reason


def test_missing_default_returns_explanatory_error(tmp_path):
    store = store_for(tmp_path)
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.execute("update knowledge_bases set is_default = 0")

    with pytest.raises(RoutingPreviewError, match="default knowledge base is missing"):
        preview_route(store, RoutingPreviewInput(text="nothing"))


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/openai/perclip", "github.com"),
        ("", ""),
        ("not a url with spaces", ""),
        ("github.com", "github.com"),
        ("https://user@example.com:8443/path", "example.com"),
    ],
)
def test_extract_domain_handles_url_variants(url, expected):
    assert extract_domain(url) == expected
