from __future__ import annotations

import sqlite3
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi.testclient import TestClient

from perclip_ingest.config import Settings
from perclip_ingest.main import create_app
from perclip_ingest.ingest_adapters import json_envelope_to_command, multipart_envelope_to_command
from perclip_ingest.ingest_models import IngestResult
from perclip_ingest.ingest_service import receipt_recovery_policy, request_signature
from perclip_ingest.knowledge_base_store import KnowledgeBaseStore
from perclip_ingest.storage import ClipStore
from tests.test_ingest_v1_json import envelope


AUTH = {"Authorization": "Bearer secret"}
LEGACY_RESPONSE_KEYS = {
    "ok", "clip_id", "client_request_id", "duplicate", "title", "platform",
    "content_hash", "filename", "size_bytes", "ragflow_document_id", "archive_status", "capture",
}


def client(tmp_path) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))


def claim(store: ClipStore, *, receipt_id: str = "ir_" + "a" * 32, signature: str = "sig-a"):
    return store.claim_ingest_receipt(
        receipt_id=receipt_id,
        client_request_id="wechat:message:123",
        contract_version="perclip.ingest.v1",
        source_adapter="wechat_bot",
        request_signature=signature,
        capture_client_batch_id="batch-123",
        capture_parent_client_request_id="parent:123",
        capture_part_index=0,
        capture_part_count=2,
        capture_part_role="text",
        target_knowledge_base_id="kb-safe",
    )


def test_ingest_receipt_migration_is_idempotent(tmp_path):
    store = ClipStore(tmp_path)
    store.init()
    store.init()

    with sqlite3.connect(store.db_path) as db:
        columns = {row[1] for row in db.execute("pragma table_info(ingest_receipts)")}
        indexes = {row[0] for row in db.execute("select name from sqlite_master where type='index'")}

    assert {
        "receipt_id", "client_request_id", "clip_id", "contract_version",
        "source_adapter", "request_signature", "status", "archive_status",
        "metadata_status", "error_code", "capture_client_batch_id",
        "capture_parent_client_request_id", "capture_part_index",
        "capture_part_count", "capture_part_role", "target_knowledge_base_id",
        "created_at", "updated_at",
    } <= columns
    assert "idx_ingest_receipts_clip_id" in indexes


def test_claim_returns_original_receipt_for_replay_and_exposes_conflict_fields(tmp_path):
    store = ClipStore(tmp_path)
    store.init()

    first, created = claim(store)
    replay, replay_created = claim(
        store, receipt_id="ir_" + "b" * 32, signature="sig-a"
    )
    changed, changed_created = claim(
        store, receipt_id="ir_" + "c" * 32, signature="sig-changed"
    )

    assert created is True
    assert replay_created is False
    assert changed_created is False
    assert replay.receipt_id == changed.receipt_id == first.receipt_id
    assert replay.request_signature == "sig-a"
    assert changed.request_signature != "sig-changed"
    assert store.find_ingest_receipt_by_request_id(first.client_request_id) == first


def test_receipt_query_requires_auth_and_uses_uniform_404(tmp_path):
    api = client(tmp_path)

    assert api.get("/api/ingest/v1/receipts/ir_" + "0" * 32).status_code == 401
    missing = api.get("/api/ingest/v1/receipts/ir_" + "0" * 32, headers=AUTH)
    malformed = api.get("/api/ingest/v1/receipts/not-a-receipt", headers=AUTH)

    assert missing.status_code == malformed.status_code == 404
    assert missing.json() == malformed.json() == {"detail": "ingest receipt not found"}


def test_receipt_query_projects_only_safe_status_capture_and_routing(tmp_path):
    api = client(tmp_path)
    store = ClipStore(tmp_path)
    receipt, _ = claim(store)

    response = api.get(f"/api/ingest/v1/receipts/{receipt.receipt_id}", headers=AUTH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "processing"
    assert payload["capture"] == {
        "client_batch_id": "batch-123",
        "parent_client_request_id": "parent:123",
        "part_index": 0,
        "part_count": 2,
        "part_role": "text",
    }
    assert payload["routing"] == {
        "status": "requested",
        "knowledge_base_id": "kb-safe",
        "decision_type": "",
    }
    serialized = response.text.lower()
    for forbidden in (
        "request_signature", "original_path", "storage_uri", "ragflow",
        "dataset", "document_id", "authorization", "token", "password",
    ):
        assert forbidden not in serialized


def test_strict_claim_exact_replay_reuses_receipt_and_changed_payload_conflicts(tmp_path):
    api = client(tmp_path)
    body = {
        "contract_version": "perclip.ingest.v1",
        "client_request_id": "api:strict:123",
        "source": {
            "adapter": "api", "client_id": "client-1", "event_id": "event-1",
            "source_app": "API", "account_hint": "",
        },
        "clip": {
            "source_type": "text", "title_hint": "", "note": "", "text": "stable body",
            "url": "", "mime_type": "text/plain",
            "captured_at": "2026-07-12T10:00:00+08:00",
            "captured_timezone": "Asia/Shanghai", "device_name": "",
        },
        "capture": {
            "client_batch_id": "", "parent_client_request_id": "", "part_index": 0,
            "part_count": 1, "part_role": "single", "source_intent": "share",
            "content_fingerprint": "",
        },
        "routing": {"target_knowledge_base_id": ""},
    }

    first = api.post("/api/ingest/v1/clips", headers=AUTH, json=body)
    replay = api.post("/api/ingest/v1/clips", headers=AUTH, json=body)
    changed_body = {**body, "clip": {**body["clip"], "text": "changed body"}}
    conflict = api.post("/api/ingest/v1/clips", headers=AUTH, json=changed_body)

    assert first.status_code == replay.status_code == 200
    assert first.json()["duplicate"] is False
    assert replay.json()["duplicate"] is True
    assert replay.json()["receipt_id"] == first.json()["receipt_id"]
    assert replay.json()["clip_id"] == first.json()["clip_id"]
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "ingest request conflicts with existing receipt"}


class BlockingArchiver:
    def __init__(self):
        self.started = Event()
        self.release = Event()
        self.calls = 0

    async def archive(self, payload):
        self.calls += 1
        self.started.set()
        assert self.release.wait(5)
        return type("Outcome", (), {"ok": True, "title": "strict", "original_path": "",
                                     "ragflow_document_id": "", "message": ""})()


class FailingArchiver:
    def __init__(self):
        self.calls = 0

    async def archive(self, payload):
        self.calls += 1
        return type("Outcome", (), {"ok": False, "title": "", "original_path": "",
                                     "ragflow_document_id": "", "message": "sensitive upstream body"})()


class CountingArchiver:
    def __init__(self):
        self.calls = 0

    async def archive(self, payload):
        self.calls += 1
        return type("Outcome", (), {"ok": True, "title": "saved", "original_path": "",
                                     "ragflow_document_id": "", "message": ""})()


class FlakyArchiver:
    def __init__(self):
        self.calls = 0

    async def archive(self, payload):
        self.calls += 1
        return type("Outcome", (), {"ok": self.calls > 1, "title": "saved", "original_path": "",
                                     "ragflow_document_id": "", "message": "temporary failure"})()


def test_legacy_request_cannot_take_over_processing_strict_receipt(tmp_path):
    archiver = BlockingArchiver()
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret"), archiver_override=archiver))
    strict_body = envelope("concurrent-id", "strict body")

    with ThreadPoolExecutor(max_workers=2) as pool:
        strict_future = pool.submit(api.post, "/api/ingest/v1/clips", headers=AUTH, json=strict_body)
        assert archiver.started.wait(5)
        legacy = api.post("/api/mobile-clips", headers=AUTH,
                          data={"source_type": "text", "text": "legacy body",
                                "client_request_id": "concurrent-id"})
        archiver.release.set()
        strict = strict_future.result(timeout=5)

    assert legacy.status_code == 409
    assert legacy.json() == {"detail": "client_request_id belongs to a strict ingest receipt"}
    assert strict.status_code == 200
    receipt = ClipStore(tmp_path).find_ingest_receipt_by_request_id("concurrent-id")
    raw = ClipStore(tmp_path).find_raw_fields_by_client_request_id("concurrent-id")
    assert receipt is not None and receipt.status == "received" and receipt.error_code == ""
    assert raw is not None and raw.text == "strict body"
    assert archiver.calls == 1


def test_archive_failure_keeps_one_failed_receipt_and_never_rearchives_exact_retry(tmp_path):
    archiver = FailingArchiver()
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret"), archiver_override=archiver))
    body = envelope("archive-failure", "body")

    first = api.post("/api/ingest/v1/clips", headers=AUTH, json=body)
    receipt = ClipStore(tmp_path).find_ingest_receipt_by_request_id("archive-failure")
    replay = api.post("/api/ingest/v1/clips", headers=AUTH, json=body)

    assert first.status_code == 502
    assert first.json() == {"detail": "archive failed"}
    assert replay.status_code == 409
    assert receipt is not None and receipt.status == "failed"
    assert receipt.error_code == "archive_error"
    assert receipt.clip_id == ""
    assert ClipStore(tmp_path).find_by_request_id("archive-failure") is None
    assert archiver.calls == 1
    status = api.get(f"/api/ingest/v1/receipts/{receipt.receipt_id}", headers=AUTH)
    assert status.status_code == 200
    assert status.json()["error_code"] == "archive_error"


def test_exact_strict_replay_runs_canonical_side_effects_only_once(tmp_path):
    archiver = CountingArchiver()
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret"), archiver_override=archiver))
    body = envelope("single-orchestration", "stable")

    first = api.post("/api/ingest/v1/clips", headers=AUTH, json=body)
    replay = api.post("/api/ingest/v1/clips", headers=AUTH, json=body)

    assert first.status_code == replay.status_code == 200
    assert replay.json()["duplicate"] is True
    assert archiver.calls == 1
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        assert db.execute("select count(*) from clips where client_request_id=?", ("single-orchestration",)).fetchone()[0] == 1
        assert db.execute("select count(*) from clip_metadata where client_request_id=?", ("single-orchestration",)).fetchone()[0] == 1
        assert db.execute("select count(*) from clip_route_decisions where client_request_id=?", ("single-orchestration",)).fetchone()[0] == 1
        assert db.execute("select count(*) from ingest_receipts where client_request_id=?", ("single-orchestration",)).fetchone()[0] == 1


def test_legacy_archive_failure_marks_receipt_failed_and_retry_reuses_it(tmp_path):
    archiver = FlakyArchiver()
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret"), archiver_override=archiver))
    data = {"source_type": "text", "text": "legacy", "client_request_id": "legacy-retry"}

    failed = api.post("/api/mobile-clips", headers=AUTH, data=data)
    first_receipt = ClipStore(tmp_path).find_ingest_receipt_by_request_id("legacy-retry")
    retried = api.post("/api/mobile-clips", headers=AUTH, data=data)
    final_receipt = ClipStore(tmp_path).find_ingest_receipt_by_request_id("legacy-retry")

    assert failed.status_code == 502
    assert first_receipt is not None and first_receipt.status == "failed"
    assert first_receipt.error_code == "archive_error"
    assert retried.status_code == 200 and retried.json()["duplicate"] is False
    assert final_receipt is not None and final_receipt.receipt_id == first_receipt.receipt_id
    assert final_receipt.status == "received" and final_receipt.error_code == ""
    assert archiver.calls == 2


def test_strict_signature_covers_source_device_and_safe_asset_basename():
    body = envelope("signature-fields", "stable")
    base = json_envelope_to_command(body)
    source_changed = json_envelope_to_command({**body, "source": {**body["source"], "source_app": "Other"}})
    device_changed = json_envelope_to_command({**body, "clip": {**body["clip"], "device_name": "Other"}})
    assert request_signature(base) != request_signature(source_changed)
    assert request_signature(base) != request_signature(device_changed)

    binary = {**body, "clip": {**body["clip"], "source_type": "file", "text": "", "mime_type": "text/plain"}}
    traversal = multipart_envelope_to_command(binary, filename="../safe.txt", mime_type="text/plain", payload=b"x")
    basename = multipart_envelope_to_command(binary, filename="safe.txt", mime_type="text/plain", payload=b"x")
    renamed = multipart_envelope_to_command(binary, filename="changed.txt", mime_type="text/plain", payload=b"x")
    assert request_signature(traversal) == request_signature(basename)
    assert request_signature(basename) != request_signature(renamed)


def test_strict_replay_conflicts_when_source_app_or_device_changes(tmp_path):
    api = client(tmp_path)
    base = envelope("semantic-signature", "stable")
    assert api.post("/api/ingest/v1/clips", headers=AUTH, json=base).status_code == 200
    source_changed = {**base, "source": {**base["source"], "source_app": "Other"}}
    device_changed = {**base, "clip": {**base["clip"], "device_name": "Other"}}
    assert api.post("/api/ingest/v1/clips", headers=AUTH, json=source_changed).status_code == 409
    assert api.post("/api/ingest/v1/clips", headers=AUTH, json=device_changed).status_code == 409


def test_post_store_failure_reconciles_without_rearchive_or_resave(tmp_path, monkeypatch):
    archiver = CountingArchiver()
    original_metadata_save = ClipStore.save_normalized_metadata
    calls = {"metadata": 0, "save": 0}
    original_clip_save = ClipStore.save

    def fail_metadata_once(self, *args, **kwargs):
        calls["metadata"] += 1
        if calls["metadata"] == 1:
            raise RuntimeError("sensitive metadata failure")
        return original_metadata_save(self, *args, **kwargs)

    def count_clip_save(self, *args, **kwargs):
        calls["save"] += 1
        return original_clip_save(self, *args, **kwargs)

    monkeypatch.setattr(ClipStore, "save_normalized_metadata", fail_metadata_once)
    monkeypatch.setattr(ClipStore, "save", count_clip_save)
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret"), archiver_override=archiver))
    body = envelope("post-store-repair", "stable")

    failed = api.post("/api/ingest/v1/clips", headers=AUTH, json=body)
    receipt = ClipStore(tmp_path).find_ingest_receipt_by_request_id("post-store-repair")
    replay = api.post("/api/ingest/v1/clips", headers=AUTH, json=body)

    assert failed.status_code == 500
    assert failed.json() == {"detail": "ingest finalization failed"}
    assert receipt is not None and receipt.status == "failed" and receipt.clip_id
    assert receipt.error_code == "post_store_repairable"
    assert replay.status_code == 200 and replay.json()["duplicate"] is True
    assert replay.json()["receipt_id"] == receipt.receipt_id
    assert archiver.calls == calls["save"] == 1
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        assert db.execute("select count(*) from clips where client_request_id='post-store-repair'").fetchone()[0] == 1
        assert db.execute("select count(*) from clip_route_decisions where client_request_id='post-store-repair'").fetchone()[0] == 1


def test_receipt_recovery_policy_matrix():
    assert receipt_recovery_policy("strict_v1") == (True, False)
    assert receipt_recovery_policy("legacy_mobile") == (True, True)


def test_legacy_metadata_failure_recovers_existing_clip_without_rearchive_or_resave(tmp_path, monkeypatch):
    archiver = CountingArchiver()
    original_metadata_save = ClipStore.save_normalized_metadata
    original_clip_save = ClipStore.save
    calls = {"metadata": 0, "save": 0}

    def fail_metadata_once(self, *args, **kwargs):
        calls["metadata"] += 1
        if calls["metadata"] == 1:
            raise RuntimeError("private path /tmp/should-not-leak")
        return original_metadata_save(self, *args, **kwargs)

    def count_clip_save(self, *args, **kwargs):
        calls["save"] += 1
        return original_clip_save(self, *args, **kwargs)

    monkeypatch.setattr(ClipStore, "save_normalized_metadata", fail_metadata_once)
    monkeypatch.setattr(ClipStore, "save", count_clip_save)
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret"), archiver_override=archiver))
    data = {"source_type": "text", "text": "original", "client_request_id": "legacy-post-store"}

    failed = api.post("/api/mobile-clips", headers=AUTH, data=data)
    receipt = ClipStore(tmp_path).find_ingest_receipt_by_request_id("legacy-post-store")
    replay = api.post("/api/mobile-clips", headers=AUTH, data={**data, "text": "changed legacy body"})
    final_receipt = ClipStore(tmp_path).find_ingest_receipt_by_request_id("legacy-post-store")

    assert failed.status_code == 500
    assert failed.json() == {"detail": "ingest finalization failed"}
    assert "should-not-leak" not in failed.text
    assert receipt is not None and receipt.status == "failed" and receipt.clip_id
    assert replay.status_code == 200 and set(replay.json()) == LEGACY_RESPONSE_KEYS
    assert replay.json()["duplicate"] is True
    assert replay.json()["clip_id"] == receipt.clip_id
    assert final_receipt is not None and final_receipt.receipt_id == receipt.receipt_id
    assert final_receipt.status == "received" and final_receipt.metadata_status == "available"
    assert archiver.calls == calls["save"] == 1


def test_legacy_receipt_finish_failure_recovers_with_golden_response(tmp_path, monkeypatch):
    archiver = CountingArchiver()
    original_finish = ClipStore.finish_ingest_receipt
    original_save = ClipStore.save
    failed_once = False
    save_calls = 0

    def fail_received_once(self, *args, **kwargs):
        nonlocal failed_once
        if kwargs.get("status") == "received" and not failed_once:
            failed_once = True
            raise RuntimeError("receipt backend detail")
        return original_finish(self, *args, **kwargs)

    def count_save(self, *args, **kwargs):
        nonlocal save_calls
        save_calls += 1
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(ClipStore, "finish_ingest_receipt", fail_received_once)
    monkeypatch.setattr(ClipStore, "save", count_save)
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret"), archiver_override=archiver))
    data = {"source_type": "text", "text": "stable", "client_request_id": "legacy-finish-repair"}
    failed = api.post("/api/mobile-clips", headers=AUTH, data=data)
    receipt = ClipStore(tmp_path).find_ingest_receipt_by_request_id("legacy-finish-repair")
    replay = api.post("/api/mobile-clips", headers=AUTH, data=data)

    assert failed.status_code == 500 and failed.json() == {"detail": "ingest finalization failed"}
    assert receipt is not None and receipt.status == "failed" and receipt.clip_id
    assert replay.status_code == 200 and set(replay.json()) == LEGACY_RESPONSE_KEYS
    assert replay.json()["duplicate"] is True and replay.json()["clip_id"] == receipt.clip_id
    final_receipt = ClipStore(tmp_path).find_ingest_receipt_by_request_id("legacy-finish-repair")
    assert final_receipt is not None and final_receipt.receipt_id == receipt.receipt_id
    assert final_receipt.status == "received"
    assert archiver.calls == save_calls == 1


def test_legacy_failed_with_clip_recovery_cannot_change_capture_ownership(tmp_path, monkeypatch):
    original = ClipStore.save_normalized_metadata
    failed_once = False

    def fail_once(self, *args, **kwargs):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise RuntimeError("metadata failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ClipStore, "save_normalized_metadata", fail_once)
    api = client(tmp_path)
    original_data = {
        "source_type": "text", "text": "stable", "client_request_id": "legacy-owned-repair",
        "client_batch_id": "owned-batch", "parent_client_request_id": "owned-parent:",
        "client_part_index": "0", "client_part_count": "2", "part_role": "text",
    }
    assert api.post("/api/mobile-clips", headers=AUTH, data=original_data).status_code == 500
    changes = [
        {"client_batch_id": "other-batch", "parent_client_request_id": "other-parent:"},
        {"client_part_index": "1"},
        {"part_role": "url"},
    ]
    for change in changes:
        conflict = api.post("/api/mobile-clips", headers=AUTH, data={**original_data, **change})
        assert conflict.status_code == 409
        assert conflict.json() == {"detail": "client_request_id already belongs to another capture part"}


def test_route_failure_is_repairable_without_rearchive(tmp_path, monkeypatch):
    archiver = CountingArchiver()
    original = KnowledgeBaseStore.save_route_decision
    calls = 0

    def fail_once(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("sensitive route failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(KnowledgeBaseStore, "save_route_decision", fail_once)
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret"), archiver_override=archiver))
    body = envelope("route-repair", "stable")
    failed = api.post("/api/ingest/v1/clips", headers=AUTH, json=body)
    replay = api.post("/api/ingest/v1/clips", headers=AUTH, json=body)
    assert failed.status_code == 500 and failed.json() == {"detail": "ingest finalization failed"}
    assert replay.status_code == 200 and replay.json()["duplicate"] is True
    assert archiver.calls == 1


def test_receipt_finish_failure_is_repairable_without_second_clip(tmp_path, monkeypatch):
    original = ClipStore.finish_ingest_receipt
    failed_once = False

    def fail_received_once(self, *args, **kwargs):
        nonlocal failed_once
        if kwargs.get("status") == "received" and not failed_once:
            failed_once = True
            raise RuntimeError("sensitive receipt failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ClipStore, "finish_ingest_receipt", fail_received_once)
    api = client(tmp_path)
    body = envelope("receipt-finish-repair", "stable")
    failed = api.post("/api/ingest/v1/clips", headers=AUTH, json=body)
    replay = api.post("/api/ingest/v1/clips", headers=AUTH, json=body)
    assert failed.status_code == 500 and failed.json() == {"detail": "ingest finalization failed"}
    assert replay.status_code == 200 and replay.json()["duplicate"] is True
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        assert db.execute("select count(*) from clips where client_request_id='receipt-finish-repair'").fetchone()[0] == 1


def test_canonical_ingest_result_has_no_ragflow_or_storage_identifiers():
    fields = set(IngestResult.__dataclass_fields__)
    assert not {"ragflow_document_id", "ragflow_dataset_id", "original_path", "storage_uri"} & fields


def test_v1_actual_body_limit_rejects_missing_content_length_without_side_effects(tmp_path):
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret",
                                         max_file_bytes=64, max_request_bytes=128)))
    request = api.build_request("POST", "/api/ingest/v1/clips", headers={**AUTH, "content-type": "application/json"},
                                content=json.dumps(envelope("oversized-body", "x" * 500)).encode())
    del request.headers["content-length"]
    response = api.send(request)
    assert response.status_code == 413
    assert response.json() == {"detail": "request too large"}
    assert ClipStore(tmp_path).find_by_request_id("oversized-body") is None
    assert ClipStore(tmp_path).find_ingest_receipt_by_request_id("oversized-body") is None


def test_lock_conflicts_do_not_create_processing_receipts(tmp_path):
    store = ClipStore(tmp_path)
    store.init()
    request_token = store.acquire_request_lock_token("request-lock-conflict")
    assert request_token
    api = client(tmp_path)
    blocked = api.post("/api/ingest/v1/clips", headers=AUTH,
                       json=envelope("request-lock-conflict", "stable"))
    assert blocked.status_code == 409
    assert store.find_ingest_receipt_by_request_id("request-lock-conflict") is None
    store.release_request_lock_token("request-lock-conflict", request_token)

    batch_body = envelope("batch-lock-conflict", "stable")
    batch_body["capture"].update(client_batch_id="locked-batch", parent_client_request_id="parent:",
                                 part_index=0, part_count=1, part_role="text")
    batch_token = store.acquire_request_lock_token("capture-batch:locked-batch")
    assert batch_token
    blocked = api.post("/api/ingest/v1/clips", headers=AUTH, json=batch_body)
    assert blocked.status_code == 409
    assert store.find_ingest_receipt_by_request_id("batch-lock-conflict") is None
    store.release_request_lock_token("capture-batch:locked-batch", batch_token)


def test_active_and_stale_processing_receipt_recovery_reuses_id_and_rejects_takeover(tmp_path):
    store = ClipStore(tmp_path)
    store.init()
    body = envelope("stale-recovery", "stable")
    command = json_envelope_to_command(body)
    receipt, _ = store.claim_ingest_receipt(
        receipt_id="ir_" + "d" * 32, client_request_id=command.client_request_id,
        contract_version=command.contract_version, source_adapter=command.source.adapter,
        request_signature=request_signature(command),
    )
    api = client(tmp_path)
    active = api.post("/api/ingest/v1/clips", headers=AUTH, json=body)
    assert active.status_code == 409

    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.execute("update ingest_receipts set updated_at='2000-01-01T00:00:00+00:00' where receipt_id=?",
                   (receipt.receipt_id,))
    changed = {**body, "clip": {**body["clip"], "text": "changed"}}
    assert api.post("/api/ingest/v1/clips", headers=AUTH, json=changed).status_code == 409
    recovered = api.post("/api/ingest/v1/clips", headers=AUTH, json=body)
    assert recovered.status_code == 200
    assert recovered.json()["receipt_id"] == receipt.receipt_id
    assert store.find_ingest_receipt_by_request_id("stale-recovery").status == "received"
