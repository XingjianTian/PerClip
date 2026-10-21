from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from perclip_ingest.config import Settings
from perclip_ingest.main import create_app
from perclip_ingest.recall import balanced_select, candidate_from_row, graph_for, recent_candidates, topic_id, topic_labels
from perclip_ingest.storage import ClipStore


HEADERS = {"Authorization": "Bearer secret"}


def public_id(api, internal_id: int) -> str:
    response = api.get(f"/api/recall/clips/{internal_id}", headers=HEADERS)
    assert response.status_code == 200
    return response.json()["clip"]["clip_id"]


def client(tmp_path) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))


def save_clip(tmp_path, api: TestClient, *, request_id: str, title: str, text: str, tags: list[str], captured_at: str | None = None) -> int:
    response = api.post(
        "/api/mobile-clips",
        headers=HEADERS,
        data={
            "source_type": "text",
            "title_hint": title,
            "text": text,
            "client_request_id": request_id,
            "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
            "source_app": "Reader",
        },
    )
    assert response.status_code == 200
    store = ClipStore(tmp_path)
    raw = store.find_raw_fields_by_client_request_id(request_id)
    assert raw is not None
    store.save_enrichment(
        clip_id=raw.id,
        client_request_id=request_id,
        knowledge_base_id="kb_default",
        route_decision_id=None,
        engine="deterministic.v1",
        status="completed",
        title=title,
        summary=text,
        tags=tags,
        language="en",
        extracted_text=text,
    )
    return raw.id


def test_recall_overview_returns_stable_graph_and_redacts_raw_fallback(tmp_path):
    api = client(tmp_path)
    clip_id = save_clip(tmp_path, api, request_id="recall-one", title="Agent tools", text="token=not-for-api", tags=["AI Agent", "text"])

    response = api.get("/api/recall/overview", headers=HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["new_topic_count"] == 1
    assert payload["graph"]["nodes"][0]["id"] == "unclassified"
    stable_id = public_id(api, clip_id)
    assert any(node["id"] == f"clip:{stable_id}" for node in payload["graph"]["nodes"])
    rendered = str(payload)
    assert "not-for-api" not in rendered
    assert "original_path" not in rendered


def test_recall_session_balances_topics_and_persists_actions(tmp_path):
    api = client(tmp_path)
    first = save_clip(tmp_path, api, request_id="recall-a", title="A", text="alpha", tags=["Topic A"])
    second = save_clip(tmp_path, api, request_id="recall-b", title="B", text="beta", tags=["Topic B"])
    save_clip(tmp_path, api, request_id="recall-c", title="C", text="gamma", tags=["Topic A"])

    started = api.post("/api/recall/sessions", headers=HEADERS, json={"days": 7, "limit": 2})

    assert started.status_code == 200
    payload = started.json()
    assert {"days", "window", "snapshot_key", "window_start", "window_end"} <= payload["session"].keys()
    assert payload["session"]["days"] == 7
    assert payload["session"]["window"] == {"days": 7, "start": payload["session"]["window_start"], "end": payload["session"]["window_end"]}
    assert len(payload["session"]["snapshot_key"]) == 32
    assert public_id(api, second) in {item["clip_id"] for item in payload["items"]}
    assert len(payload["items"]) == 2
    assert {tuple(item["topic_ids"]) for item in payload["items"]} == {("unclassified",)}
    session_id = payload["session"]["id"]
    recalled_clip_id = payload["items"][0]["clip_id"]
    action = api.post(f"/api/recall/sessions/{session_id}/items/{recalled_clip_id}/events", headers=HEADERS, json={"action": "remembered"})
    assert action.status_code == 200
    assert action.json()["item"]["state"] == "remembered"
    fetched = api.get(f"/api/recall/sessions/{session_id}/items", headers=HEADERS)
    assert fetched.status_code == 200
    assert next(item for item in fetched.json()["items"] if item["clip_id"] == recalled_clip_id)["state"] == "remembered"


def test_recall_rejects_invalid_day_and_action_values(tmp_path):
    api = client(tmp_path)
    assert api.get("/api/recall/overview?days=31", headers=HEADERS).status_code == 422
    clip = save_clip(tmp_path, api, request_id="recall-invalid", title="Clip", text="body", tags=["Topic"])
    session = api.post("/api/recall/sessions", headers=HEADERS, json={"days": 7}).json()["session"]["id"]
    assert api.post(f"/api/recall/sessions/{session}/items/{clip}/actions", headers=HEADERS, json={"action": "wrong"}).status_code == 422


def test_recall_range_covers_seven_natural_utc_days(tmp_path):
    api = client(tmp_path)
    response = api.get("/api/recall/overview?days=7", headers=HEADERS)
    assert response.status_code == 200
    payload = response.json()
    start = datetime.fromisoformat(payload["range_start"])
    end = datetime.fromisoformat(payload["range_end"])
    assert start.time().isoformat() == "00:00:00"
    assert start.date() == end.date() - timedelta(days=6)


def test_new_topic_count_uses_complete_previous_natural_day_window(tmp_path, monkeypatch):
    fixed_now = datetime(2026, 7, 10, 10, tzinfo=timezone.utc)
    monkeypatch.setattr("perclip_ingest.main.utc_now", lambda: fixed_now)
    api = client(tmp_path)
    save_clip(tmp_path, api, request_id="previous-late", title="Previous", text="body", tags=["Stable Topic"], captured_at="2026-07-09T23:30:00+00:00")
    save_clip(tmp_path, api, request_id="current", title="Current", text="body", tags=["Stable Topic", "Current Topic"], captured_at="2026-07-10T09:00:00+00:00")

    payload = api.get("/api/recall/overview?days=1", headers=HEADERS).json()

    assert payload["metrics"]["new_topic_count"] == 0


def test_credential_only_raw_fallback_is_excluded(tmp_path):
    api = client(tmp_path)
    response = api.post("/api/mobile-clips", headers=HEADERS, data={"source_type": "text", "text": "Authorization: Bearer only-a-secret", "client_request_id": "credential-only", "captured_at": datetime.now(timezone.utc).isoformat()})
    assert response.status_code == 200
    overview = api.get("/api/recall/overview", headers=HEADERS).json()
    assert overview["highlights"] == []
    assert "only-a-secret" not in str(overview)


def test_deterministic_score_precedes_recency_inside_each_balanced_topic_bucket():
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    raw = lambda ident, captured: SimpleNamespace(id=ident, title_hint="", filename="", note="", text="body", url="", source_type="text", source_app="Reader", captured_at=captured.isoformat(), created_at=captured.isoformat())
    rich = SimpleNamespace(status="completed", title="Rich", summary="summary", extracted_text="body", tags=["Topic A"])
    plain = SimpleNamespace(status="completed", title="", summary="", extracted_text="", tags=["Topic A"])
    candidates = recent_candidates([(raw(1, now - timedelta(days=2)), rich, ""), (raw(2, now), plain, "")], days=7, now=now)
    assert candidates[0].clip_id == "1"
    assert candidates[0].score > candidates[1].score
    assert [candidate.clip_id for candidate in balanced_select(candidates, limit=2, recalled_clip_ids=set())] == ["1", "2"]


def test_recall_uses_latest_completed_enrichment_when_newer_enrichment_failed(tmp_path):
    api = client(tmp_path)
    clip_id = save_clip(tmp_path, api, request_id="recall-completed", title="Completed title", text="completed body", tags=["Completed Topic"])
    ClipStore(tmp_path).save_enrichment(
        clip_id=clip_id,
        client_request_id="recall-completed",
        knowledge_base_id="kb_default",
        route_decision_id=None,
        engine="deterministic.v1",
        status="failed",
        title="Failed title",
        summary="",
        tags=["Failed Topic"],
        language="",
        extracted_text="",
        error_code="failure",
        error_message="failure",
    )
    overview = api.get("/api/recall/overview", headers=HEADERS)
    assert overview.status_code == 200
    clip = next(item for item in overview.json()["highlights"] if item["clip_id"] == public_id(api, clip_id))
    assert clip["title"] == "Completed title"
    assert clip["topic_ids"] == ["unclassified"]


def test_source_faithful_share_title_remains_recallable_when_rich_enrichment_fails():
    now = datetime.now(timezone.utc).isoformat()
    raw = SimpleNamespace(
        id=1, client_request_id="minimal-url", title_hint="Shared source title",
        filename="", note="", text="", url="https://example.test/item",
        source_type="url", source_app="Share", captured_at=now, created_at=now,
        archive_status="local", active_enrichment_invalid=False, active_url="https://example.test/item",
    )
    enrichment = SimpleNamespace(
        status="failed", error_code="recall_ineligible:browser_render_required",
        title="", summary="", extracted_text="", tags=[],
    )

    candidate = candidate_from_row(raw, enrichment, "Inbox")

    assert candidate is not None
    assert candidate.title == "Shared source title"
    assert "Shared source title" in candidate.summary


def test_session_actions_are_snapshotted_idempotent_and_terminal(tmp_path):
    api = client(tmp_path)
    clip_id = save_clip(tmp_path, api, request_id="snapshot", title="Before", text="before", tags=["Snapshot"])
    started = api.post("/api/recall/sessions", headers=HEADERS, json={"days": 7, "limit": 1})
    item = started.json()["current_item"]
    session_id = started.json()["session"]["id"]
    action_url = f"/api/recall/sessions/{session_id}/items/{item['id']}/action"
    reveal = api.post(action_url, headers=HEADERS, json={"action": "reveal", "client_action_id": "reveal-1"})
    assert reveal.status_code == 200 and reveal.json()["current_item"]["id"] == item["id"]
    assert api.post(action_url, headers=HEADERS, json={"action": "reveal", "client_action_id": "reveal-1"}).status_code == 200
    ClipStore(tmp_path).save_enrichment(clip_id=clip_id, client_request_id="snapshot", knowledge_base_id="", route_decision_id=None, engine="deterministic.v1", status="completed", title="After", summary="after", tags=["Changed"], language="en", extracted_text="after")
    assert api.get(f"/api/recall/sessions/{session_id}", headers=HEADERS).json()["items"][0]["title"] == "Before"
    remembered = api.post(action_url, headers=HEADERS, json={"action": "remembered", "client_action_id": "remember-1"})
    assert remembered.status_code == 200 and remembered.json()["session"]["status"] == "completed"
    assert api.post(action_url, headers=HEADERS, json={"action": "later", "client_action_id": "later-after-complete"}).json()["item"]["state"] == "remembered"


def test_recall_new_contract_rejects_unauthorized_limits_and_missing_action_id(tmp_path):
    api = client(tmp_path)
    assert api.get("/api/recall/overview").status_code == 401
    assert api.post("/api/recall/sessions", headers=HEADERS, json={"limit": 21}).status_code == 422
    save_clip(tmp_path, api, request_id="strict-action", title="Strict", text="body", tags=["Strict"])
    started = api.post("/api/recall/sessions", headers=HEADERS, json={"limit": 1}).json()
    response = api.post(f"/api/recall/sessions/{started['session']['id']}/items/{started['current_item']['id']}/action", headers=HEADERS, json={"action": "open_original"})
    assert response.status_code == 422


def test_all_recall_reads_require_auth_and_safe_clip_excludes_internal_fields(tmp_path):
    api = client(tmp_path)
    clip_id = save_clip(tmp_path, api, request_id="safe", title="Safe", text="body", tags=["Topic"])
    for path in ("/api/recall/overview", "/api/recall/weekly-review", f"/api/recall/clips/{clip_id}", f"/api/recall/topics/{topic_id('Topic')}"):
        assert api.get(path).status_code == 401
    safe = api.get(f"/api/recall/clips/{clip_id}", headers=HEADERS)
    assert safe.status_code == 200
    rendered = str(safe.json())
    assert "original_path" not in rendered and "ragflow_document_id" not in rendered and "dataset" not in rendered


def test_recall_numeric_alias_and_public_id_are_identical_stable_and_never_leak_internal_ids(tmp_path):
    api = client(tmp_path)
    internal = save_clip(tmp_path, api, request_id="public-recall", title="Public", text="body", tags=["Public"])
    public = public_id(api, internal)
    numeric_detail = api.get(f"/api/recall/clips/{internal}", headers=HEADERS).json()
    public_detail = api.get(f"/api/recall/clips/{public}", headers=HEADERS).json()
    assert numeric_detail == public_detail
    assert public.startswith("pc_")

    session = api.post("/api/recall/sessions", headers=HEADERS, json={"limit": 1}).json()
    overview = api.get("/api/recall/overview", headers=HEADERS).json()
    domain = api.get("/api/recall/domain", headers=HEADERS).json()
    serialized = json.dumps([numeric_detail, session, overview, domain])
    assert f'"clip_id": "{internal}"' not in serialized
    assert f'"id": "clip:{internal}"' not in serialized
    assert "internal_clip_id" not in serialized
    assert all(item["clip_id"].startswith("pc_") for item in session["items"])
    assert all(memory["id"].startswith("clip:pc_") for memory in domain["memories"])

    restarted = client(tmp_path)
    assert public_id(restarted, internal) == public


def test_mobile_payload_audit_rejects_internal_recall_identity_shapes():
    from perclip_ingest.quality_read_model import audit_quality_payload

    for payload in (
        {"internal_clip_id": "1"},
        {"clip_id": "1"},
        {"id": "clip:1"},
        {"event_id": 7},
        {"id": "7"},
    ):
        with pytest.raises(ValueError):
            audit_quality_payload(payload)


def test_topic_normalization_fallback_and_graph_bounds_are_deterministic(tmp_path):
    labels = topic_labels(tags=[" text ", " AI  Agent ", "ai agent", "One", "Two", "Three", "Four"], knowledge_base_name="KB", source_app="App", source_type="text")
    assert [label for _, label in labels] == ["AI Agent", "One", "Two"]
    assert labels[0][0] == topic_id("ai agent")
    api = client(tmp_path)
    for index in range(15):
        save_clip(tmp_path, api, request_id=f"graph-{index}", title=f"T{index}", text="body", tags=[f"Topic {index}"])
    first = api.get("/api/recall/overview", headers=HEADERS).json()["graph"]
    second = api.get("/api/recall/overview", headers=HEADERS).json()["graph"]
    assert first == second and len(first["nodes"]) <= 18 and len(first["edges"]) <= 36
    assert {node["color_slot"] for node in first["nodes"]} <= {0, 1, 2, 3}


def test_topic_filters_weekly_and_active_snapshot_reuse(tmp_path):
    api = client(tmp_path)
    one = save_clip(tmp_path, api, request_id="topic-one", title="One", text="body", tags=["Filter Topic"])
    save_clip(tmp_path, api, request_id="topic-two", title="Two", text="body", tags=["Filter Topic"])
    identifier = "unclassified"
    assert api.get("/api/recall/topics/topic:missing", headers=HEADERS).status_code == 404
    first = api.post("/api/recall/sessions", headers=HEADERS, json={"topic_id": identifier, "limit": 2}).json()
    second = api.post("/api/recall/sessions", headers=HEADERS, json={"topic_id": identifier, "limit": 2}).json()
    assert first["session"]["id"] == second["session"]["id"]
    action = api.post(f"/api/recall/sessions/{first['session']['id']}/items/{first['items'][0]['id']}/action", headers=HEADERS, json={"action":"later", "client_action_id":"filter-later"})
    assert action.status_code == 200
    assert all(item["clip_id"] != first["items"][0]["clip_id"] for item in api.get(f"/api/recall/topics/{identifier}?filter=unrecalled", headers=HEADERS).json()["items"])
    assert api.get(f"/api/recall/topics/{identifier}?filter=frequent", headers=HEADERS).status_code == 200
    weekly = api.get("/api/recall/weekly-review", headers=HEADERS).json()
    assert weekly["summary"]["saved_count"] >= 2 and not weekly["most_recalled"] and len(weekly["top_topics"]) <= 10 and len(weekly["suggested_items"]) <= 10


def test_created_at_fallback_and_migration_is_idempotent(tmp_path):
    store = ClipStore(tmp_path); store.init(); store.init()
    row = SimpleNamespace(id=1, client_request_id="fallback", title_hint="Created", filename="", note="", text="body", url="", source_type="text", source_app="Reader", captured_at="bad", created_at="2026-07-10T00:00:00+00:00")
    candidate = candidate_from_row(row, None, "")
    assert candidate is not None and candidate.captured_at.startswith("2026-07-10")


def test_active_session_is_resumed_after_remembered_action(tmp_path):
    api = client(tmp_path)
    save_clip(tmp_path, api, request_id="resume-a", title="A", text="a", tags=["Resume"])
    save_clip(tmp_path, api, request_id="resume-b", title="B", text="b", tags=["Resume"])
    started = api.post("/api/recall/sessions", headers=HEADERS, json={"limit": 2}).json()
    assert started["progress"]["current_position"] == 1
    action = api.post(f"/api/recall/sessions/{started['session']['id']}/items/{started['current_item']['id']}/action", headers=HEADERS, json={"action": "remembered", "client_action_id": "resume-remember"})
    assert action.json()["progress"]["current_position"] == 2
    resumed = api.post("/api/recall/sessions", headers=HEADERS, json={"limit": 2}).json()
    assert resumed["session"]["id"] == started["session"]["id"]
    assert resumed["session"]["window"] == started["session"]["window"]
    assert resumed["session"]["snapshot_key"] == started["session"]["snapshot_key"]
    assert resumed["progress"]["current_position"] == 2
    assert any(item["state"] == "remembered" for item in resumed["items"])


def test_active_session_is_resumed_after_later_action(tmp_path):
    api = client(tmp_path)
    save_clip(tmp_path, api, request_id="later-a", title="A", text="a", tags=["Later"])
    save_clip(tmp_path, api, request_id="later-b", title="B", text="b", tags=["Later"])
    started = api.post("/api/recall/sessions", headers=HEADERS, json={"limit": 2}).json()
    api.post(f"/api/recall/sessions/{started['session']['id']}/items/{started['current_item']['id']}/action", headers=HEADERS, json={"action": "later", "client_action_id": "resume-later"})
    assert api.post("/api/recall/sessions", headers=HEADERS, json={"limit": 2}).json()["session"]["id"] == started["session"]["id"]


def test_new_source_snapshot_can_create_new_session_and_completed_is_not_reused_as_active(tmp_path):
    api = client(tmp_path)
    save_clip(tmp_path, api, request_id="source-a", title="A", text="a", tags=["Source"])
    first = api.post("/api/recall/sessions", headers=HEADERS, json={"limit": 2}).json()
    save_clip(tmp_path, api, request_id="source-b", title="B", text="b", tags=["Source"])
    changed = api.post("/api/recall/sessions", headers=HEADERS, json={"limit": 2}).json()
    assert changed["session"]["id"] != first["session"]["id"]
    completed_first = api.post(f"/api/recall/sessions/{changed['session']['id']}/items/{changed['current_item']['id']}/action", headers=HEADERS, json={"action": "remembered", "client_action_id": "done-a"}).json()
    api.post(f"/api/recall/sessions/{changed['session']['id']}/items/{completed_first['current_item']['id']}/action", headers=HEADERS, json={"action": "remembered", "client_action_id": "done-b"})
    assert api.post("/api/recall/sessions", headers=HEADERS, json={"limit": 2}).json()["session"]["id"] != changed["session"]["id"]


def test_topic_weekly_and_action_collision_contracts(tmp_path):
    api = client(tmp_path)
    first = save_clip(tmp_path, api, request_id="contract-a", title="A", text="a", tags=["Contract"])
    second = save_clip(tmp_path, api, request_id="contract-b", title="B", text="b", tags=["Contract"])
    started = api.post("/api/recall/sessions", headers=HEADERS, json={"limit": 2}).json()
    session_id, item = started["session"]["id"], started["current_item"]
    url = f"/api/recall/sessions/{session_id}/items/{item['id']}/action"
    assert api.post(url, headers=HEADERS, json={"action": "remembered", "client_action_id": "collision"}).status_code == 200
    different_action = api.post(url, headers=HEADERS, json={"action": "later", "client_action_id": "collision"})
    assert different_action.status_code == 409 and different_action.json()["detail"] == "client_action_id already used for another recall action"
    other = next(value for value in started["items"] if value["id"] != item["id"])
    collision = api.post(f"/api/recall/sessions/{session_id}/items/{other['id']}/action", headers=HEADERS, json={"action": "later", "client_action_id": "collision"})
    assert collision.status_code == 409 and collision.json()["detail"] == "client_action_id already used for another recall action"
    terminal = api.post(url, headers=HEADERS, json={"action": "later", "client_action_id": "new-terminal"})
    assert terminal.status_code == 200 and terminal.json()["item"]["state"] == "remembered"
    with ClipStore(tmp_path).connect() as db:
        assert db.execute("select count(*) from recall_events where item_id = ? and action in ('remembered', 'later')", (item["id"],)).fetchone()[0] == 1
    other_session = api.post("/api/recall/sessions", headers=HEADERS, json={"days": 6, "limit": 1}).json()
    session_collision = api.post(f"/api/recall/sessions/{other_session['session']['id']}/items/{other_session['current_item']['id']}/action", headers=HEADERS, json={"action": "remembered", "client_action_id": "collision"})
    assert session_collision.status_code == 409 and session_collision.json()["detail"] == "client_action_id already used for another recall action"
    topic = api.get("/api/recall/topics/unclassified", headers=HEADERS).json()
    assert {"recall_count", "score", "recalled_in_window"} <= topic["items"][0].keys()
    assert "unrecalled_count" in topic["metrics"]
    weekly = api.get("/api/recall/weekly-review", headers=HEADERS).json()
    assert weekly["top_topics"][0]["recall_count"] == 1
    assert weekly["most_recalled"][0]["clip_id"] == item["clip_id"]
    assert "token" not in weekly["summary_text"].lower()


def test_later_then_remembered_keeps_one_terminal_event(tmp_path):
    api = client(tmp_path)
    save_clip(tmp_path, api, request_id="terminal-later", title="Later", text="body", tags=["Terminal"])
    started = api.post("/api/recall/sessions", headers=HEADERS, json={"limit": 1}).json()
    item = started["current_item"]
    url = f"/api/recall/sessions/{started['session']['id']}/items/{item['id']}/action"
    assert api.post(url, headers=HEADERS, json={"action": "later", "client_action_id": "later-first"}).status_code == 200
    repeated = api.post(url, headers=HEADERS, json={"action": "remembered", "client_action_id": "remember-after-later"})
    assert repeated.status_code == 200 and repeated.json()["item"]["state"] == "later"
    with ClipStore(tmp_path).connect() as db:
        assert db.execute("select count(*) from recall_events where item_id = ? and action in ('remembered', 'later')", (item["id"],)).fetchone()[0] == 1


def test_weekly_most_recalled_excludes_later_and_orders_remembered(tmp_path):
    api = client(tmp_path)
    save_clip(tmp_path, api, request_id="weekly-c", title="C", text="body", tags=["Weekly"])
    save_clip(tmp_path, api, request_id="weekly-a", title="A", text="body", tags=["Weekly"])
    save_clip(tmp_path, api, request_id="weekly-b", title="B", text="body", tags=["Weekly"])
    started = api.post("/api/recall/sessions", headers=HEADERS, json={"limit": 3}).json()
    session_id = started["session"]["id"]
    first, second, third = started["items"]
    assert api.post(f"/api/recall/sessions/{session_id}/items/{first['id']}/action", headers=HEADERS, json={"action": "later", "client_action_id": "weekly-later"}).status_code == 200
    after_later = api.get("/api/recall/weekly-review", headers=HEADERS).json()
    assert after_later["most_recalled"] == []
    assert api.post(f"/api/recall/sessions/{session_id}/items/{second['id']}/action", headers=HEADERS, json={"action": "remembered", "client_action_id": "weekly-remember-b"}).status_code == 200
    assert api.post(f"/api/recall/sessions/{session_id}/items/{third['id']}/action", headers=HEADERS, json={"action": "remembered", "client_action_id": "weekly-remember-c"}).status_code == 200

    most_recalled = api.get("/api/recall/weekly-review", headers=HEADERS).json()["most_recalled"]

    assert [item["clip_id"] for item in most_recalled] == sorted([second["clip_id"], third["clip_id"]])
    assert all(item["recall_count"] > 0 for item in most_recalled)

    second_session = api.post("/api/recall/sessions", headers=HEADERS, json={"limit": 3}).json()
    repeated_item = next(item for item in second_session["items"] if item["clip_id"] == third["clip_id"])
    assert api.post(f"/api/recall/sessions/{second_session['session']['id']}/items/{repeated_item['id']}/action", headers=HEADERS, json={"action": "remembered", "client_action_id": "weekly-remember-c-again"}).status_code == 200

    most_recalled = api.get("/api/recall/weekly-review", headers=HEADERS).json()["most_recalled"]

    assert most_recalled[0]["clip_id"] == third["clip_id"]
    assert [item["recall_count"] for item in most_recalled[:2]] == [2, 1]


def test_fresh_schema_has_only_formal_recall_tables_and_indexes(tmp_path):
    store = ClipStore(tmp_path)
    store.init(); store.init()
    with store.connect() as db:
        tables = {row[0] for row in db.execute("select name from sqlite_master where type = 'table'")}
        indexes = {row[0] for row in db.execute("select name from sqlite_master where type = 'index'")}
    assert {"recall_sessions", "recall_session_items", "recall_events"} <= tables
    assert "recall_items" not in tables
    assert {"idx_clips_created_at", "idx_clips_captured_at"} <= indexes
