from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from perclip_ingest.config import Settings
from perclip_ingest.main import create_app


HEADERS = {"Authorization": "Bearer secret"}
MOBILE_RESPONSE_KEYS = {
    "ok",
    "clip_id",
    "client_request_id",
    "duplicate",
    "title",
    "platform",
    "content_hash",
    "filename",
    "size_bytes",
    "ragflow_document_id",
    "archive_status",
    "capture",
}
CAPTURE_KEYS = {
    "client_batch_id",
    "parent_client_request_id",
    "part_index",
    "part_count",
    "part_role",
}
FORBIDDEN_OUTPUT_MARKERS = (
    "original_path",
    "storage_uri",
    "/Users/",
    "/Volumes/",
    "Authorization",
    "traceback",
)


def api(tmp_path) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))


def post_clip(
    client: TestClient,
    source_type: str,
    request_id: str,
    *,
    changed: bool = False,
):
    suffix = "changed" if changed else "original"
    data = {
        "source_type": source_type,
        "client_request_id": request_id,
        "title_hint": f"{source_type}-{suffix}",
    }
    files = None
    if source_type == "text":
        data["text"] = f"text-{suffix}"
    elif source_type == "url":
        data["url"] = f"https://example.com/{suffix}"
    elif source_type == "image":
        files = {"file": (f"{suffix}.png", f"png-{suffix}".encode(), "image/png")}
    elif source_type == "file":
        files = {"file": (f"{suffix}.pdf", f"pdf-{suffix}".encode(), "application/pdf")}
    else:  # pragma: no cover - protects this test helper's contract
        raise AssertionError(source_type)
    return client.post("/api/mobile-clips", headers=HEADERS, data=data, files=files)


@pytest.mark.parametrize("source_type", ["text", "url", "image", "file"])
def test_legacy_mobile_type_matrix_keeps_exact_safe_receipt_and_changed_payload_replay(
    tmp_path, source_type
):
    client = api(tmp_path)
    request_id = f"compat-{source_type}"

    first = post_clip(client, source_type, request_id)
    replay = post_clip(client, source_type, request_id, changed=True)

    assert first.status_code == replay.status_code == 200
    first_payload = first.json()
    replay_payload = replay.json()
    assert set(first_payload) == set(replay_payload) == MOBILE_RESPONSE_KEYS
    assert set(first_payload["capture"]) == CAPTURE_KEYS
    assert first_payload["capture"] == {
        "client_batch_id": "",
        "parent_client_request_id": "",
        "part_index": 0,
        "part_count": 1,
        "part_role": "single",
    }
    assert first_payload["duplicate"] is False
    assert replay_payload["duplicate"] is True
    for key in MOBILE_RESPONSE_KEYS - {"duplicate"}:
        assert replay_payload[key] == first_payload[key]
    serialized = json.dumps([first_payload, replay_payload])
    assert all(marker not in serialized for marker in FORBIDDEN_OUTPUT_MARKERS)


def batch_part(index: int, *, request_id: str | None = None) -> dict[str, str]:
    return {
        "source_type": "text",
        "text": f"part-{index}",
        "client_request_id": request_id or f"compat-parent:{index}",
        "client_batch_id": "compat-batch",
        "parent_client_request_id": "compat-parent:",
        "client_part_index": str(index),
        "client_part_count": "3",
        "part_role": "text",
        "source_intent": "share",
        "captured_timezone": "Asia/Shanghai",
    }


def test_zero_based_batch_status_and_part_ownership_are_legacy_compatible(tmp_path):
    client = api(tmp_path)

    for index in (2, 0):
        assert client.post("/api/mobile-clips", headers=HEADERS, data=batch_part(index)).status_code == 200

    partial = client.get("/api/mobile-clips/batch/compat-batch", headers=HEADERS)
    assert partial.status_code == 200
    assert partial.json() == {
        "ok": True,
        "client_batch_id": "compat-batch",
        "received_count": 2,
        "expected_count": 3,
        "failed_count": 0,
        "missing_part_indices": [1],
        "status": "partial",
        "complete": False,
        "clips": [
            {
                "clip_id": partial.json()["clips"][0]["clip_id"],
                "client_request_id": "compat-parent:0",
                "part_index": 0,
                "part_role": "text",
                "source_type": "text",
                "filename": partial.json()["clips"][0]["filename"],
                "created_at": partial.json()["clips"][0]["created_at"],
            },
            {
                "clip_id": partial.json()["clips"][1]["clip_id"],
                "client_request_id": "compat-parent:2",
                "part_index": 2,
                "part_role": "text",
                "source_type": "text",
                "filename": partial.json()["clips"][1]["filename"],
                "created_at": partial.json()["clips"][1]["created_at"],
            },
        ],
    }

    conflict = client.post(
        "/api/mobile-clips", headers=HEADERS, data=batch_part(0, request_id="other-owner")
    )
    assert conflict.status_code == 409
    assert conflict.json() == {
        "detail": "client_request_id already belongs to another capture part"
    }

    assert client.post("/api/mobile-clips", headers=HEADERS, data=batch_part(1)).status_code == 200
    completed = client.get("/api/mobile-clips/batch/compat-batch", headers=HEADERS).json()
    assert completed["status"] == "completed"
    assert completed["complete"] is True
    assert completed["received_count"] == completed["expected_count"] == 3
    assert completed["missing_part_indices"] == []
    assert [clip["part_index"] for clip in completed["clips"]] == [0, 1, 2]


def test_capture_status_shape_redaction_and_error_details(tmp_path):
    client = api(tmp_path)
    created = client.post("/api/mobile-clips", headers=HEADERS, data=batch_part(0))
    assert created.status_code == 200
    clip_id = created.json()["clip_id"]

    unauthorized = client.get(f"/api/mobile-clips/{clip_id}/capture")
    missing = client.get("/api/mobile-clips/999999/capture", headers=HEADERS)
    invalid_batch = client.get("/api/mobile-clips/batch/bad%20batch", headers=HEADERS)
    assert unauthorized.status_code == 401
    assert unauthorized.json() == {"detail": "invalid mobile ingest token"}
    assert missing.status_code == 404
    assert missing.json() == {"detail": "clip not found"}
    assert invalid_batch.status_code == 422
    assert invalid_batch.json() == {"detail": "invalid client_batch_id"}

    response = client.get(f"/api/mobile-clips/{clip_id}/capture", headers=HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "ok",
        "clip_id",
        "client_request_id",
        "capture",
        "routing",
        "enrichment",
        "ragflow_sync",
        "metadata_status",
    }
    assert payload["capture"] == {
        "client_batch_id": "compat-batch",
        "parent_client_request_id": "compat-parent:",
        "part_index": 0,
        "part_count": 3,
        "part_role": "text",
        "original_filename": created.json()["filename"],
        "original_mime_type": "",
        "source_intent": "share",
        "captured_timezone": "Asia/Shanghai",
        "content_fingerprint": created.json()["content_hash"],
    }
    assert payload["routing"] == {
        "status": "available",
        "knowledge_base_id": "kb_default",
        "decision_type": "default",
    }
    assert payload["enrichment"] == {"status": "not_started"}
    assert payload["ragflow_sync"] == {"status": "not_started", "phase": ""}
    assert payload["metadata_status"] == "available"
    serialized = json.dumps(payload)
    assert "ragflow_document_id" not in serialized
    assert "ragflow_dataset_id" not in serialized
    assert all(marker not in serialized for marker in FORBIDDEN_OUTPUT_MARKERS)


@pytest.mark.parametrize(
    ("fields", "detail"),
    [
        ({"source_type": "unknown", "text": "x"}, "unsupported source_type"),
        ({"source_type": "text"}, "empty clip payload"),
        (
            {"source_type": "text", "text": "x", "client_batch_id": "bad batch"},
            "invalid client_batch_id",
        ),
        (
            {"source_type": "text", "text": "x", "part_role": "archive"},
            "invalid part_role",
        ),
        (
            {"source_type": "text", "text": "x", "content_fingerprint": "not-a-hash"},
            "invalid content_fingerprint",
        ),
    ],
)
def test_legacy_mobile_validation_error_details(tmp_path, fields, detail):
    response = api(tmp_path).post("/api/mobile-clips", headers=HEADERS, data=fields)
    assert response.status_code == 422
    assert response.json() == {"detail": detail}
