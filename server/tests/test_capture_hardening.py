from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from perclip_ingest.config import Settings
from perclip_ingest.main import create_app
from perclip_ingest.storage import ClipStore


HEADERS = {"Authorization": "Bearer secret"}


def api(tmp_path) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))


def part_data(index: int, *, count: int = 3) -> dict[str, str]:
    return {
        "source_type": "file",
        "client_request_id": f"parent-1:{index}:note-{index}.txt",
        "client_batch_id": "batch-1",
        "parent_client_request_id": "parent-1:",
        "client_part_index": str(index),
        "client_part_count": str(count),
        "part_role": "file",
        "source_intent": "share",
        "captured_timezone": "Asia/Shanghai",
    }


def test_mobile_clip_multipart_capture_maps_each_part_and_batch_status(tmp_path):
    client = api(tmp_path)
    responses = []
    for index in range(3):
        response = client.post(
            "/api/mobile-clips", headers=HEADERS, data=part_data(index),
            files={"file": (f"note-{index}.txt", f"part-{index}".encode(), "text/plain")},
        )
        assert response.status_code == 200
        responses.append(response.json())
        assert response.json()["capture"] == {
            "client_batch_id": "batch-1", "parent_client_request_id": "parent-1:",
            "part_index": index, "part_count": 3, "part_role": "file",
        }
        assert "original_path" not in response.text and "storage_uri" not in response.text

    status = client.get("/api/mobile-clips/batch/batch-1", headers=HEADERS)
    assert status.status_code == 200
    assert status.json()["received_count"] == 3
    assert status.json()["expected_count"] == 3
    assert status.json()["complete"] is True
    assert [item["part_index"] for item in status.json()["clips"]] == [0, 1, 2]

    capture = client.get(f"/api/mobile-clips/{responses[0]['clip_id']}/capture", headers=HEADERS)
    assert capture.status_code == 200
    payload = capture.json()
    assert payload["capture"]["client_batch_id"] == "batch-1"
    assert payload["capture"]["source_intent"] == "share"
    assert payload["capture"]["content_fingerprint"] == responses[0]["content_hash"]
    assert payload["routing"]["status"] == "available"
    assert payload["enrichment"]["status"] == "not_started"
    assert "original_path" not in json.dumps(payload) and "ragflow_document_id" not in json.dumps(payload)


def test_duplicate_part_replay_returns_same_clip_and_preserves_metadata(tmp_path):
    client = api(tmp_path)
    first = client.post(
        "/api/mobile-clips", headers=HEADERS, data=part_data(0, count=1),
        files={"file": ("note-0.txt", b"part", "text/plain")},
    )
    replay = client.post(
        "/api/mobile-clips", headers=HEADERS, data=part_data(0, count=1),
        files={"file": ("note-0.txt", b"part", "text/plain")},
    )
    assert first.status_code == replay.status_code == 200
    assert replay.json()["duplicate"] is True
    assert replay.json()["clip_id"] == first.json()["clip_id"]
    metadata = ClipStore(tmp_path).find_normalized_metadata_by_request_id("parent-1:0:note-0.txt")
    assert metadata is not None
    assert metadata.metadata["capture"]["part_count"] == 1
    assert metadata.metadata["capture"]["original_filename"] == "note-0.txt"
    batch = client.get("/api/mobile-clips/batch/batch-1", headers=HEADERS).json()
    assert batch["received_count"] == 1
    assert len(batch["clips"]) == 1


def test_capture_validation_rejects_invalid_ids_indexes_and_fingerprints(tmp_path):
    client = api(tmp_path)
    base = {"source_type": "text", "text": "body", "client_request_id": "capture-invalid"}
    invalids = [
        {"client_batch_id": "bad space"},
        {"client_part_index": "3", "client_part_count": "3"},
        {"client_part_index": "0", "client_part_count": "101"},
        {"part_role": "archive"},
        {"source_intent": "background"},
        {"content_fingerprint": "not-a-hash"},
    ]
    for fields in invalids:
        response = client.post("/api/mobile-clips", headers=HEADERS, data={**base, **fields})
        assert response.status_code == 422


def test_capture_batch_relationship_validation_accepts_supported_shapes(tmp_path):
    client = api(tmp_path)

    empty_batch_multipart = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={
            "source_type": "text", "text": "invalid", "client_request_id": "local-1:0",
            "client_part_index": "0", "client_part_count": "2",
        },
    )
    missing_parent = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={
            "source_type": "text", "text": "invalid", "client_request_id": "batch-part-0",
            "client_batch_id": "batch-missing-parent", "client_part_index": "0",
            "client_part_count": "1",
        },
    )
    missing_request_id = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={
            "source_type": "text", "text": "invalid", "client_batch_id": "batch-missing-request",
            "parent_client_request_id": "parent:", "client_part_index": "0",
            "client_part_count": "1",
        },
    )

    assert empty_batch_multipart.status_code == 422
    assert missing_parent.status_code == 422
    assert missing_request_id.status_code == 422

    single = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={"source_type": "text", "text": "single", "client_request_id": "single-parent:"},
    )
    one_part_batch = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={
            "source_type": "text", "text": "legacy attachment", "client_request_id": "legacy-part",
            "client_batch_id": "legacy-one-part", "parent_client_request_id": "legacy-parent:",
            "client_part_index": "0", "client_part_count": "1", "part_role": "text",
        },
    )
    multipart_parts = [
        client.post(
            "/api/mobile-clips", headers=HEADERS,
            data={
                "source_type": "text", "text": f"part {index}",
                "client_request_id": f"opaque-request-{index}",
                "client_batch_id": "valid-multipart", "parent_client_request_id": "shared-parent:",
                "client_part_index": str(index), "client_part_count": "2", "part_role": "text",
            },
        )
        for index in (1, 0)
    ]

    assert single.status_code == 200
    assert one_part_batch.status_code == 200
    assert all(response.status_code == 200 for response in multipart_parts)
    multipart_status = client.get("/api/mobile-clips/batch/valid-multipart", headers=HEADERS).json()
    assert multipart_status["status"] == "completed"
    assert [clip["client_request_id"] for clip in multipart_status["clips"]] == [
        "opaque-request-0", "opaque-request-1",
    ]


def test_batch_endpoint_requires_auth_and_never_creates_missing_parts(tmp_path):
    client = api(tmp_path)
    assert client.get("/api/mobile-clips/batch/batch-1").status_code == 401
    client.post("/api/mobile-clips", headers=HEADERS, data={**part_data(1), "client_part_count": "3"}, files={"file": ("one.txt", b"one", "text/plain")})
    result = client.get("/api/mobile-clips/batch/batch-1", headers=HEADERS).json()
    assert result["received_count"] == 1
    assert result["expected_count"] == 3
    assert result["complete"] is False
    assert len(result["clips"]) == 1


def test_out_of_order_batch_tracks_partial_then_completed_state(tmp_path):
    client = api(tmp_path)
    for index in (2, 0):
        response = client.post(
            "/api/mobile-clips", headers=HEADERS, data=part_data(index),
            files={"file": (f"note-{index}.txt", f"part-{index}".encode(), "text/plain")},
        )
        assert response.status_code == 200

    partial = client.get("/api/mobile-clips/batch/batch-1", headers=HEADERS).json()
    assert partial["status"] == "partial"
    assert partial["received_count"] == 2
    assert partial["failed_count"] == 0
    assert partial["missing_part_indices"] == [1]

    completed = client.post(
        "/api/mobile-clips", headers=HEADERS, data=part_data(1),
        files={"file": ("note-1.txt", b"part-1", "text/plain")},
    )
    assert completed.status_code == 200
    status = client.get("/api/mobile-clips/batch/batch-1", headers=HEADERS).json()
    assert status["status"] == "completed"
    assert status["complete"] is True
    assert [clip["part_index"] for clip in status["clips"]] == [0, 1, 2]


def test_failed_part_does_not_complete_batch_and_retry_recovers_it(tmp_path):
    client = api(tmp_path)
    accepted = client.post(
        "/api/mobile-clips", headers=HEADERS, data=part_data(0, count=2),
        files={"file": ("note-0.txt", b"part-0", "text/plain")},
    )
    rejected = client.post(
        "/api/mobile-clips", headers=HEADERS, data=part_data(1, count=2),
        files={"file": ("note-1.exe", b"bad", "application/x-msdownload")},
    )
    assert accepted.status_code == 200
    assert rejected.status_code == 415

    failed = client.get("/api/mobile-clips/batch/batch-1", headers=HEADERS).json()
    assert failed["status"] == "failed"
    assert failed["received_count"] == 1
    assert failed["failed_count"] == 1
    assert failed["complete"] is False

    retry = client.post(
        "/api/mobile-clips", headers=HEADERS, data=part_data(1, count=2),
        files={"file": ("note-1.txt", b"part-1", "text/plain")},
    )
    assert retry.status_code == 200
    recovered = client.get("/api/mobile-clips/batch/batch-1", headers=HEADERS).json()
    assert recovered["status"] == "completed"
    assert recovered["received_count"] == 2
    assert recovered["failed_count"] == 0


def test_batch_rejects_conflicting_parent_count_and_part_identity(tmp_path):
    client = api(tmp_path)
    first = client.post(
        "/api/mobile-clips", headers=HEADERS, data=part_data(0, count=2),
        files={"file": ("note-0.txt", b"part-0", "text/plain")},
    )
    assert first.status_code == 200

    conflicting_parent = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={**part_data(1, count=2), "parent_client_request_id": "other-parent:"},
        files={"file": ("note-1.txt", b"part-1", "text/plain")},
    )
    conflicting_count = client.post(
        "/api/mobile-clips", headers=HEADERS, data=part_data(1, count=3),
        files={"file": ("note-1.txt", b"part-1", "text/plain")},
    )
    conflicting_part = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={**part_data(0, count=2), "client_request_id": "parent-1:0:different.txt"},
        files={"file": ("different.txt", b"different", "text/plain")},
    )
    assert conflicting_parent.status_code == 422
    assert conflicting_count.status_code == 422
    assert conflicting_part.status_code == 409
    assert conflicting_part.json()["detail"] == "client_request_id already belongs to another capture part"


def test_duplicate_request_cannot_move_between_batches_or_part_indices(tmp_path):
    client = api(tmp_path)
    original = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={
            "source_type": "text", "text": "original", "client_request_id": "stable-part-request",
            "client_batch_id": "batch-a", "parent_client_request_id": "parent-a:",
            "client_part_index": "0", "client_part_count": "2", "part_role": "text",
        },
    )
    assert original.status_code == 200

    cross_batch = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={
            "source_type": "text", "text": "replay", "client_request_id": "stable-part-request",
            "client_batch_id": "batch-b", "parent_client_request_id": "parent-b:",
            "client_part_index": "0", "client_part_count": "2", "part_role": "text",
        },
    )
    changed_index = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={
            "source_type": "text", "text": "replay", "client_request_id": "stable-part-request",
            "client_batch_id": "batch-a", "parent_client_request_id": "parent-a:",
            "client_part_index": "1", "client_part_count": "2", "part_role": "text",
        },
    )

    assert cross_batch.status_code == 409
    assert changed_index.status_code == 409
    assert cross_batch.json()["detail"] == "client_request_id already belongs to another capture part"
    assert changed_index.json()["detail"] == "client_request_id already belongs to another capture part"
    assert client.get("/api/mobile-clips/batch/batch-b", headers=HEADERS).json()["received_count"] == 0
    batch_a = client.get("/api/mobile-clips/batch/batch-a", headers=HEADERS).json()
    assert batch_a["received_count"] == 1
    assert [clip["part_index"] for clip in batch_a["clips"]] == [0]


def test_duplicate_replay_cannot_change_role_parent_or_count(tmp_path):
    client = api(tmp_path)
    original = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={
            "source_type": "text", "text": "original", "client_request_id": "owned-part",
            "client_batch_id": "owned-batch", "parent_client_request_id": "owned-parent:",
            "client_part_index": "0", "client_part_count": "2", "part_role": "text",
        },
    )
    assert original.status_code == 200

    changes = [
        {"part_role": "url"},
        {"parent_client_request_id": "different-parent:"},
        {"client_part_count": "3"},
    ]
    for change in changes:
        replay = client.post(
            "/api/mobile-clips", headers=HEADERS,
            data={
                "source_type": "text", "text": "replay", "client_request_id": "owned-part",
                "client_batch_id": "owned-batch", "parent_client_request_id": "owned-parent:",
                "client_part_index": "0", "client_part_count": "2", "part_role": "text",
                **change,
            },
        )
        assert replay.status_code == 409
        assert replay.json()["detail"] == "client_request_id already belongs to another capture part"

    status = client.get("/api/mobile-clips/batch/owned-batch", headers=HEADERS).json()
    assert status["received_count"] == 1
    assert len(status["clips"]) == 1


def test_same_batch_index_cannot_change_request_id(tmp_path):
    client = api(tmp_path)
    first = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={
            "source_type": "text", "text": "first", "client_request_id": "index-owner",
            "client_batch_id": "index-batch", "parent_client_request_id": "index-parent:",
            "client_part_index": "0", "client_part_count": "2", "part_role": "text",
        },
    )
    conflict = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={
            "source_type": "text", "text": "conflict", "client_request_id": "different-request",
            "client_batch_id": "index-batch", "parent_client_request_id": "index-parent:",
            "client_part_index": "0", "client_part_count": "2", "part_role": "text",
        },
    )
    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "client_request_id already belongs to another capture part"
    status = client.get("/api/mobile-clips/batch/index-batch", headers=HEADERS).json()
    assert status["received_count"] == 1
    assert status["clips"][0]["client_request_id"] == "index-owner"


def test_legacy_duplicate_can_attach_capture_identity_without_new_clip(tmp_path):
    client = api(tmp_path)
    legacy = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={"source_type": "text", "text": "legacy", "client_request_id": "legacy-part"},
    )
    replay = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={
            "source_type": "text", "text": "legacy", "client_request_id": "legacy-part",
            "client_batch_id": "legacy-batch", "parent_client_request_id": "legacy-parent:",
            "client_part_index": "0", "client_part_count": "1", "part_role": "text",
        },
    )
    assert legacy.status_code == replay.status_code == 200
    assert replay.json()["clip_id"] == legacy.json()["clip_id"]
    assert replay.json()["capture"] == {
        "client_batch_id": "legacy-batch", "parent_client_request_id": "legacy-parent:",
        "part_index": 0, "part_count": 1, "part_role": "text",
    }
    status = client.get("/api/mobile-clips/batch/legacy-batch", headers=HEADERS).json()
    assert status["received_count"] == 1
    capture = client.get(f"/api/mobile-clips/{legacy.json()['clip_id']}/capture", headers=HEADERS).json()
    assert capture["capture"]["client_batch_id"] == "legacy-batch"
    assert capture["capture"]["parent_client_request_id"] == "legacy-parent:"


def test_legacy_single_cannot_attach_as_one_part_of_multipart_batch(tmp_path):
    client = api(tmp_path)
    legacy = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={"source_type": "text", "text": "legacy", "client_request_id": "legacy-multipart-part"},
    )
    conflict = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={
            "source_type": "text", "text": "legacy", "client_request_id": "legacy-multipart-part",
            "client_batch_id": "forbidden-batch", "parent_client_request_id": "legacy-parent:",
            "client_part_index": "0", "client_part_count": "2", "part_role": "text",
        },
    )
    assert legacy.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "client_request_id already belongs to another capture part"
    status = client.get("/api/mobile-clips/batch/forbidden-batch", headers=HEADERS).json()
    assert status["received_count"] == 0
    assert status["clips"] == []


def test_single_capture_keeps_legacy_identity_without_fabricated_batch(tmp_path):
    client = api(tmp_path)
    first = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={"source_type": "text", "text": "single", "client_request_id": "local-1:"},
    )
    replay = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={"source_type": "text", "text": "single", "client_request_id": "local-1:"},
    )
    assert first.status_code == replay.status_code == 200
    assert first.json()["client_request_id"] == "local-1:"
    assert first.json()["capture"]["client_batch_id"] == ""
    assert replay.json()["clip_id"] == first.json()["clip_id"]


def test_capture_status_auth_validation_not_found_and_redaction(tmp_path):
    client = api(tmp_path)
    created = client.post(
        "/api/mobile-clips", headers=HEADERS,
        data={"source_type": "url", "url": "https://example.com", "client_request_id": "url-1:"},
    )
    clip_id = created.json()["clip_id"]
    assert client.get(f"/api/mobile-clips/{clip_id}/capture").status_code == 401
    assert client.get("/api/mobile-clips/not-an-int/capture", headers=HEADERS).status_code == 422
    assert client.get("/api/mobile-clips/999999/capture", headers=HEADERS).status_code == 404

    response = client.get(f"/api/mobile-clips/{clip_id}/capture", headers=HEADERS)
    assert response.status_code == 200
    forbidden = (
        "original_path", "storage_uri", "/Users/", "/Volumes/", "ragflow_dataset_id",
        "ragflow_document_id", "Authorization", "token", "cookie", "password", "traceback",
    )
    assert all(value not in response.text for value in forbidden)


def test_mobile_response_golden_fields_match_on_duplicate_and_are_path_safe(tmp_path):
    client = api(tmp_path)
    data = {"source_type": "image", "client_request_id": "image-1:image.png"}
    first = client.post(
        "/api/mobile-clips", headers=HEADERS, data=data,
        files={"file": ("image.png", b"png bytes", "image/png")},
    )
    replay = client.post(
        "/api/mobile-clips", headers=HEADERS, data=data,
        files={"file": ("image.png", b"png bytes", "image/png")},
    )
    assert first.status_code == replay.status_code == 200
    required = {
        "ok", "clip_id", "client_request_id", "duplicate", "title", "platform",
        "content_hash", "filename", "size_bytes", "ragflow_document_id", "archive_status", "capture",
    }
    assert set(first.json()) == required
    assert set(replay.json()) == required
    for key in required - {"duplicate"}:
        assert replay.json()[key] == first.json()[key]
    assert first.json()["duplicate"] is False
    assert replay.json()["duplicate"] is True
    assert "original_path" not in first.text and "storage_uri" not in first.text


def test_capture_storage_migration_is_idempotent_and_indexed(tmp_path):
    store = ClipStore(tmp_path)
    store.init()
    store.init()
    with sqlite3.connect(store.db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(clips)")}
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {
        "capture_client_batch_id", "capture_parent_client_request_id", "capture_part_index",
        "capture_part_count", "capture_part_role",
    } <= columns
    assert "capture_part_attempts" in tables
    assert "idx_clips_capture_batch" in indexes
    assert "idx_capture_part_attempts_batch" in indexes
    assert "idx_capture_part_attempts_batch_request" in indexes


def test_capture_attempt_unique_index_migration_rejects_legacy_conflicts(tmp_path):
    store = ClipStore(tmp_path)
    store.init()
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("drop index idx_capture_part_attempts_batch_request")
        for index in (0, 1):
            connection.execute(
                """
                insert into capture_part_attempts (
                    client_batch_id, part_index, parent_client_request_id, client_request_id,
                    part_count, part_role, status, error_code, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("legacy-conflict", index, "parent:", "same-request", 2, "file", "received", "", "now"),
            )
    with pytest.raises(ValueError, match="capture attempt ownership conflict"):
        store.init()
