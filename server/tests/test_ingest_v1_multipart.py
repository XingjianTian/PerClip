from __future__ import annotations

import json
from fastapi.testclient import TestClient

from perclip_ingest.config import Settings
from perclip_ingest.main import create_app
from perclip_ingest.storage import ClipStore


HEADERS = {"Authorization": "Bearer secret"}


def api(tmp_path):
    return TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))


def envelope(request_id="upload-1", *, index=0, count=1):
    return {
        "contract_version": "perclip.ingest.v1", "client_request_id": request_id,
        "source": {"adapter": "api", "client_id": "importer", "event_id": request_id,
                   "source_app": "Importer", "account_hint": ""},
        "clip": {"source_type": "file", "title_hint": "", "note": "", "text": "", "url": "",
                 "mime_type": "text/plain", "captured_at": "2026-07-12T10:00:00+08:00",
                 "captured_timezone": "Asia/Shanghai", "device_name": ""},
        "capture": {"client_batch_id": "batch-v1" if count > 1 else "",
                    "parent_client_request_id": "parent-v1" if count > 1 else "",
                    "part_index": index, "part_count": count, "part_role": "file",
                    "source_intent": "share", "content_fingerprint": ""},
        "routing": {"target_knowledge_base_id": ""},
    }


def post(client, body, payload=b"hello", filename="../unsafe.txt", mime="text/plain"):
    return client.post("/api/ingest/v1/clips/multipart", headers=HEADERS,
                       data={"envelope_json": json.dumps(body)},
                       files={"file": (filename, payload, mime)})


def test_multipart_v1_exact_replay_and_changed_bytes_conflict(tmp_path):
    client = api(tmp_path)
    first = post(client, envelope())
    replay = post(client, envelope())
    changed = post(client, envelope(), b"changed")
    assert first.status_code == replay.status_code == 200
    assert replay.json()["duplicate"] is True
    assert first.json()["receipt_id"] == replay.json()["receipt_id"]
    assert changed.status_code == 409
    assert "unsafe.txt" not in first.text


def test_multipart_v1_zero_based_batch_reuses_capture_ownership(tmp_path):
    client = api(tmp_path)
    for index in (1, 0):
        response = post(client, envelope(f"upload-{index}", index=index, count=2), f"part-{index}".encode())
        assert response.status_code == 200
    batch = client.get("/api/mobile-clips/batch/batch-v1", headers=HEADERS).json()
    assert batch["status"] == "completed"
    assert [item["part_index"] for item in batch["clips"]] == [0, 1]


def test_multipart_v1_rejects_auth_mime_missing_multiple_and_non_binary(tmp_path):
    client = api(tmp_path)
    unauthorized = client.post("/api/ingest/v1/clips/multipart",
                               data={"envelope_json": json.dumps(envelope())},
                               files={"file": ("a.txt", b"a", "text/plain")})
    assert unauthorized.status_code == 401
    assert post(client, envelope(), mime="application/x-msdownload").status_code == 415
    missing = client.post("/api/ingest/v1/clips/multipart", headers=HEADERS,
                          data={"envelope_json": json.dumps(envelope())})
    assert missing.status_code == 422
    multiple = client.post("/api/ingest/v1/clips/multipart", headers=HEADERS,
                           data={"envelope_json": json.dumps(envelope())},
                           files=[("file", ("a.txt", b"a", "text/plain")),
                                  ("file", ("b.txt", b"b", "text/plain"))])
    assert multiple.status_code == 422
    multiple_envelopes = client.post(
        "/api/ingest/v1/clips/multipart", headers=HEADERS,
        files=[("envelope_json", (None, json.dumps(envelope()))),
               ("envelope_json", (None, json.dumps(envelope("upload-other")))),
               ("file", ("a.txt", b"a", "text/plain"))],
    )
    assert multiple_envelopes.status_code == 422
    non_binary = envelope(); non_binary["clip"]["source_type"] = "text"
    assert post(client, non_binary).status_code == 422


def test_multipart_v1_actual_total_body_limit_without_content_length_has_no_side_effects(tmp_path):
    client = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret",
                                            max_file_bytes=128, max_request_bytes=256)))
    body = envelope("multipart-total-limit")
    body["clip"]["note"] = "private-multipart-sentinel-" + "x" * 400
    request = client.build_request(
        "POST", "/api/ingest/v1/clips/multipart", headers=HEADERS,
        data={"envelope_json": json.dumps(body)}, files={"file": ("small.txt", b"x", "text/plain")},
    )
    del request.headers["content-length"]
    response = client.send(request)

    assert response.status_code == 413
    assert response.json() == {"detail": "request too large"}
    assert "private-multipart-sentinel" not in response.text
    store = ClipStore(tmp_path)
    assert store.find_ingest_receipt_by_request_id("multipart-total-limit") is None
    assert store.find_by_request_id("multipart-total-limit") is None
