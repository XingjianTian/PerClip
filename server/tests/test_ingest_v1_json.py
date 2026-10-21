from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from perclip_ingest.config import Settings
from perclip_ingest.main import create_app
from perclip_ingest.storage import ClipStore


HEADERS = {"Authorization": "Bearer secret"}


def api(tmp_path):
    return TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))


def envelope(request_id="wechat:message:123", text="示例内容"):
    return {
        "contract_version": "perclip.ingest.v1",
        "client_request_id": request_id,
        "source": {"adapter": "wechat_bot", "client_id": "bot-main", "event_id": "message-123",
                   "source_app": "WeChat", "account_hint": ""},
        "clip": {"source_type": "text", "title_hint": "", "note": "", "text": text, "url": "",
                 "mime_type": "text/plain", "captured_at": "2026-07-12T10:00:00+08:00",
                 "captured_timezone": "Asia/Shanghai", "device_name": ""},
        "capture": {"client_batch_id": "", "parent_client_request_id": "", "part_index": 0,
                    "part_count": 1, "part_role": "text", "source_intent": "share",
                    "content_fingerprint": ""},
        "routing": {"target_knowledge_base_id": ""},
    }


def test_json_v1_ingests_and_exact_replay_returns_same_receipt(tmp_path):
    client = api(tmp_path)
    first = client.post("/api/ingest/v1/clips", headers=HEADERS, json=envelope())
    replay = client.post("/api/ingest/v1/clips", headers=HEADERS, json=envelope())
    assert first.status_code == replay.status_code == 200
    assert first.json()["duplicate"] is False
    assert replay.json()["duplicate"] is True
    assert first.json()["clip_id"] == replay.json()["clip_id"]
    assert first.json()["receipt_id"] == replay.json()["receipt_id"]
    forbidden = ("original_path", "storage_uri", "ragflow", "dataset", "authorization")
    assert not any(value in replay.text.lower() for value in forbidden)


def test_json_v1_changed_deterministic_fields_conflict(tmp_path):
    client = api(tmp_path)
    assert client.post("/api/ingest/v1/clips", headers=HEADERS, json=envelope()).status_code == 200
    changes = []
    changed_text = envelope(text="changed"); changes.append(changed_text)
    changed_adapter = envelope(); changed_adapter["source"]["adapter"] = "webhook"; changes.append(changed_adapter)
    changed_client = envelope(); changed_client["source"]["client_id"] = "bot-other"; changes.append(changed_client)
    changed_event = envelope(); changed_event["source"]["event_id"] = "message-999"; changes.append(changed_event)
    changed_capture = envelope(); changed_capture["capture"]["source_intent"] = "manual"; changes.append(changed_capture)
    changed_route = envelope(); changed_route["routing"]["target_knowledge_base_id"] = "kb_default"; changes.append(changed_route)
    for body in changes:
        response = client.post("/api/ingest/v1/clips", headers=HEADERS, json=body)
        assert response.status_code == 409


def test_json_v1_changed_url_conflicts_for_same_request_id(tmp_path):
    client = api(tmp_path)
    first = envelope("url-replay", "")
    first["clip"].update(source_type="url", text="", url="https://example.com/first", mime_type="text/uri-list")
    changed = envelope("url-replay", "")
    changed["clip"].update(source_type="url", text="", url="https://example.com/second", mime_type="text/uri-list")
    assert client.post("/api/ingest/v1/clips", headers=HEADERS, json=first).status_code == 200
    assert client.post("/api/ingest/v1/clips", headers=HEADERS, json=changed).status_code == 409


def test_json_v1_default_only_preserves_capture_time_target(tmp_path):
    client = api(tmp_path)
    target = client.post(
        "/api/knowledge-bases",
        headers=HEADERS,
        json={"name": "JSON capture default"},
    ).json()["knowledge_base"]
    body = envelope("json-default-only", "captured before the default changes")
    body["routing"] = {
        "mode": "default_only",
        "target_knowledge_base_id": target["id"],
    }

    response = client.post("/api/ingest/v1/clips", headers=HEADERS, json=body)

    assert response.status_code == 200
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        decision = db.execute(
            """
            select knowledge_base_id, decision_type, manual_override, matched_rule_ids_json
            from clip_route_decisions where client_request_id = ?
            """,
            ("json-default-only",),
        ).fetchone()
    assert decision == (target["id"], "default", 0, "[]")


def test_json_v1_rejects_schema_auth_bounds_timezone_binary_and_encoded_payload(tmp_path):
    client = api(tmp_path)
    assert client.post("/api/ingest/v1/clips", json=envelope()).status_code == 401
    unknown = envelope(); unknown["surprise"] = True
    assert client.post("/api/ingest/v1/clips", headers=HEADERS, json=unknown).status_code == 422
    unknown_nested = envelope(); unknown_nested["clip"]["extra"] = "x"
    assert client.post("/api/ingest/v1/clips", headers=HEADERS, json=unknown_nested).status_code == 422
    naive = envelope(); naive["clip"]["captured_at"] = "2026-07-12T10:00:00"
    assert client.post("/api/ingest/v1/clips", headers=HEADERS, json=naive).status_code == 422
    binary = envelope(); binary["clip"]["source_type"] = "file"
    assert client.post("/api/ingest/v1/clips", headers=HEADERS, json=binary).status_code == 422
    encoded = envelope(text="data:text/plain;base64,SGVsbG8=")
    assert client.post("/api/ingest/v1/clips", headers=HEADERS, json=encoded).status_code == 422
    empty = envelope(text=""); empty["clip"]["note"] = ""; empty["clip"]["url"] = ""
    assert client.post("/api/ingest/v1/clips", headers=HEADERS, json=empty).status_code == 422


def test_strict_v1_cannot_reuse_legacy_mobile_id(tmp_path):
    client = api(tmp_path)
    legacy = client.post("/api/mobile-clips", headers=HEADERS,
                         data={"source_type": "text", "text": "legacy", "client_request_id": "shared-id"})
    strict = client.post("/api/ingest/v1/clips", headers=HEADERS, json=envelope("shared-id", "legacy"))
    assert legacy.status_code == 200
    assert strict.status_code == 409


def test_strict_v1_cannot_reuse_pre_receipt_legacy_clip_id(tmp_path):
    store = ClipStore(tmp_path)
    store.init()
    store.save(client_request_id="pre-stage20", source_type="text", title_hint="legacy", note="",
               text="legacy", url="", mime_type="text/plain", device_name="", source_app="Android",
               captured_at="2026-07-12T10:00:00+08:00", filename="", payload=b"")
    client = api(tmp_path)
    response = client.post("/api/ingest/v1/clips", headers=HEADERS,
                           json=envelope("pre-stage20", "legacy"))
    assert response.status_code == 409
