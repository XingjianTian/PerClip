from __future__ import annotations

from perclip_ingest.recall import RecallCandidate, topic_id
from perclip_ingest.recall_domain import build_recall_domain, domain_payload

from test_recall import HEADERS, client, public_id, save_clip


def candidate(clip_id: str, *labels: str, score: int = 10) -> RecallCandidate:
    return RecallCandidate(
        internal_clip_id=clip_id, clip_id=clip_id, client_request_id=f"request-{clip_id}", title=f"Title {clip_id}",
        summary="summary", reveal_text="body", source_type="text", source_app="Reader",
        url="", filename="", captured_at="2026-07-10T09:00:00+00:00", knowledge_base_name="",
        tags=list(labels), topics=[(topic_id(label), label) for label in labels], score=score,
    )


def build(items, **kwargs):
    return build_recall_domain(items, days=30, window_start="2026-06-11T00:00:00+00:00", window_end="2026-07-10T23:59:59+00:00", **kwargs)


def test_canonical_identity_label_color_and_key_are_stable_across_input_order():
    first = build([candidate("1", "AI Agent"), candidate("2", "ai agent"), candidate("3", "AI agent")])
    second = build([candidate("3", "AI agent"), candidate("1", "AI Agent"), candidate("2", "ai agent")])
    identifier = topic_id("AI Agent")
    first_topic = next(item for item in first.topics if item.id == identifier)
    second_topic = next(item for item in second.topics if item.id == identifier)
    assert first_topic.label == second_topic.label == "AI Agent"
    assert first_topic.color_slot == second_topic.color_slot
    assert first_topic.rotation_seed == second_topic.rotation_seed
    assert first.snapshot_key == second.snapshot_key


def test_canonical_snapshot_ignores_preferences_but_projection_applies_them():
    preferred = topic_id("Preferred")
    muted = topic_id("Muted")
    items = [candidate("1", "Preferred"), candidate("2", "Muted")]
    plain = build(items)
    with_preferences = build(items, preferences={"preferred_topic_ids": [preferred], "muted_topic_ids": [muted]})
    assert plain == with_preferences
    projected = domain_payload(with_preferences, preferences={"preferred_topic_ids": [preferred], "muted_topic_ids": [muted]})
    assert preferred in {topic["id"] for topic in projected["topics"]}
    assert muted not in {topic["id"] for topic in projected["topics"]}


def test_projection_repairs_primary_topic_and_keeps_relations_referentially_integral():
    alpha, beta = topic_id("Alpha"), topic_id("Beta")
    snapshot = build([candidate("1", "Alpha", "Beta"), candidate("2", "Beta")])
    payload = domain_payload(snapshot, topic_limit=1, memory_limit=10, topic_id=beta)
    topic_ids = {item["id"] for item in payload["topics"]}
    memory_ids = {item["id"] for item in payload["memories"]}
    for memory in payload["memories"]:
        assert memory["primary_topic_id"] in topic_ids
        assert set(memory["topic_ids"]) <= topic_ids
    for relation in payload["relations"]:
        assert relation["source"] in topic_ids
        assert relation["target"] in (topic_ids | memory_ids)


def test_domain_endpoint_reuses_clip_and_topic_identities_without_sensitive_source_data(tmp_path):
    api = client(tmp_path)
    clip = save_clip(tmp_path, api, request_id="domain", title="Agent", text="body", tags=["AI Agent"])
    response = api.get("/api/recall/domain?days=30&topic_limit=10&memory_limit=2", headers=HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert "unclassified" in {item["id"] for item in payload["topics"]}
    assert f"clip:{public_id(api, clip)}" in {item["id"] for item in payload["memories"]}
    assert {edge["type"] for edge in payload["relations"]} <= {"contains", "co_occurs"}
    assert "original_path" not in str(payload) and "ragflow_document_id" not in str(payload)
