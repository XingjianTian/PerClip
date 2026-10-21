from __future__ import annotations

import json
import sqlite3
import time

from fastapi.testclient import TestClient

from perclip_ingest.config import RagflowSettings, Settings
from perclip_ingest.main import create_app
from perclip_ingest.ragflow_adapter import HttpRagflowAdapter, RagflowAdapterError, RagflowDocumentRef
from perclip_ingest.storage import ClipStore


def client(tmp_path, settings: Settings | None = None, ragflow_adapter_override=None):
    app = create_app(
        settings or Settings(data_dir=tmp_path, ingest_token="secret"),
        ragflow_adapter_override=ragflow_adapter_override,
    )
    return TestClient(app)


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer secret"}


def legacy_response_keys() -> set[str]:
    return {
        "ok",
        "duplicate",
        "title",
        "platform",
        "clip_id",
        "client_request_id",
        "content_hash",
        "filename",
        "size_bytes",
        "ragflow_document_id",
        "archive_status",
        "capture",
    }


def clip_id_for_request(tmp_path, client_request_id: str) -> int:
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        return int(
            db.execute(
                "select id from clips where client_request_id = ?",
                (client_request_id,),
            ).fetchone()[0]
        )


def metadata_for_request(tmp_path, client_request_id: str) -> dict[str, object]:
    metadata = ClipStore(tmp_path).find_normalized_metadata_by_request_id(client_request_id)
    assert metadata is not None
    return metadata.metadata


def upload_text(api: TestClient, request_id: str, *, target_knowledge_base_id: str = "", text: str = "sync body"):
    data = {
        "source_type": "text",
        "title_hint": request_id,
        "text": text,
        "client_request_id": request_id,
    }
    if target_knowledge_base_id:
        data["target_knowledge_base_id"] = target_knowledge_base_id
    response = api.post("/api/mobile-clips", headers=auth_headers(), data=data)
    assert response.status_code == 200
    return response


def create_kb(api: TestClient, name: str, dataset_id: str = "") -> dict[str, object]:
    response = api.post(
        "/api/knowledge-bases",
        headers=auth_headers(),
        json={"name": name, "ragflow_dataset_id": dataset_id, "ragflow_dataset_name": f"{name} dataset"},
    )
    assert response.status_code == 200
    return response.json()["knowledge_base"]


def enrich(api: TestClient, request_id: str) -> dict[str, object]:
    response = api.post(f"/api/clips/{request_id}/enrich", headers=auth_headers())
    assert response.status_code == 200
    return response.json()["enrichment"]


def set_ragflow_document_id(tmp_path, request_id: str, document_id: str) -> None:
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.execute(
            "update clips set ragflow_document_id = ? where client_request_id = ?",
            (document_id, request_id),
        )


def sync_jobs(tmp_path) -> list[dict[str, object]]:
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("select * from ragflow_sync_jobs order by id asc").fetchall()
    return [dict(row) for row in rows]


def real_sync_settings(tmp_path, allowed_dataset_ids: frozenset[str] = frozenset({"dataset-test"})) -> Settings:
    return Settings(
        data_dir=tmp_path,
        ingest_token="secret",
        ragflow=RagflowSettings(
            base_url="http://ragflow.test",
            api_key="test-ragflow-key",
            enable_real_sync=True,
            sync_allow_dataset_ids=allowed_dataset_ids,
        ),
    )


class FakeExecuteAdapter:
    def __init__(self, *, fail_upload: bool = False, fail_meta: bool = False):
        self.fail_upload = fail_upload
        self.fail_meta = fail_meta
        self.uploads: list[tuple[str, str]] = []
        self.meta_updates: list[tuple[str, str]] = []

    def upload_document(self, dataset_id, name, content, meta_fields, dry_run):
        if self.fail_upload:
            raise RagflowAdapterError("api_key=private authorization=cookie password=secret")
        self.uploads.append((dataset_id, name))
        return RagflowDocumentRef(dataset_id=dataset_id, document_id="remote-document-1", name=name, meta_fields=meta_fields, dry_run=False)

    def update_document_meta(self, dataset_id, document_id, meta_fields, dry_run):
        if self.fail_meta:
            raise RagflowAdapterError("api_key=private authorization=cookie password=secret")
        self.meta_updates.append((dataset_id, document_id))
        return {"remote_document_changed": True}


def prepare_executable_sync(api: TestClient, request_id: str, dataset_id: str = "dataset-test") -> None:
    target = create_kb(api, f"{request_id} target", dataset_id)
    upload_text(api, request_id, target_knowledge_base_id=target["id"])
    enrich(api, request_id)


def test_clip_ragflow_sync_dry_run_requires_token(tmp_path):
    response = client(tmp_path).post("/api/clips/1/ragflow-sync/dry-run")

    assert response.status_code == 401


def test_clip_ragflow_sync_dry_run_returns_404_for_missing_clip(tmp_path):
    response = client(tmp_path).post("/api/clips/999/ragflow-sync/dry-run", headers=auth_headers())

    assert response.status_code == 404


def test_clip_ragflow_sync_rejects_ambiguous_android_prefix(tmp_path):
    api = client(tmp_path)
    for index in [1, 2]:
        response = api.post(
            "/api/mobile-clips",
            headers=auth_headers(),
            data={"source_type": "file", "client_request_id": f"sync-prefix:{index}:file.txt"},
            files={"file": (f"part-{index}.txt", b"part", "text/plain")},
        )
        assert response.status_code == 200

    response = api.post("/api/clips/sync-prefix/ragflow-sync/dry-run", headers=auth_headers())

    assert response.status_code == 409
    assert response.json()["detail"] == "multiple clip parts require batch sync"


def test_clip_ragflow_sync_blocks_when_dataset_mapping_missing(tmp_path):
    api = client(tmp_path)
    upload_text(api, "sync-no-dataset")
    enrich(api, "sync-no-dataset")

    response = api.post("/api/clips/sync-no-dataset/ragflow-sync/dry-run", headers=auth_headers())

    assert response.status_code == 200
    sync = response.json()["sync"]
    assert sync["operation"] == "skip_no_dataset"
    assert sync["status"] == "blocked"
    assert sync["dry_run"] is True
    assert sync["remote_document_changed"] is False
    assert sync["reason"] == "target knowledge base has no ragflow dataset mapping"


def test_clip_ragflow_sync_blocks_when_enrichment_missing(tmp_path):
    api = client(tmp_path)
    target = create_kb(api, "Sync Missing Enrichment", "dataset-sync")
    upload_text(api, "sync-no-enrichment", target_knowledge_base_id=target["id"])

    response = api.post("/api/clips/sync-no-enrichment/ragflow-sync/dry-run", headers=auth_headers())

    assert response.status_code == 200
    sync = response.json()["sync"]
    assert sync["operation"] == "skip_no_enrichment"
    assert sync["status"] == "blocked"
    assert sync["ragflow_dataset_id"] == "dataset-sync"
    assert sync["plan"] == {"target_dataset_id": "dataset-sync", "dry_run": True}


def test_clip_ragflow_sync_execute_requires_explicit_real_sync_gates(tmp_path):
    api = client(tmp_path)
    target = create_kb(api, "Sync Execute Gate", "dataset-test")
    upload_text(api, "sync-execute-gate", target_knowledge_base_id=target["id"])
    enrich(api, "sync-execute-gate")

    response = api.post("/api/clips/sync-execute-gate/ragflow-sync/execute", headers=auth_headers())

    assert response.status_code == 422
    assert "PERCLIP_ENABLE_REAL_RAGFLOW_SYNC" in response.json()["detail"]
    assert sync_jobs(tmp_path) == []


def test_clip_ragflow_sync_execute_rejects_dataset_outside_allowlist_without_remote_state(tmp_path):
    settings = real_sync_settings(tmp_path, frozenset({"dataset-allowed"}))
    api = client(tmp_path, settings, ragflow_adapter_override=HttpRagflowAdapter(settings.ragflow))
    prepare_executable_sync(api, "sync-execute-not-allowed", "dataset-other")

    response = api.post("/api/clips/sync-execute-not-allowed/ragflow-sync/execute", headers=auth_headers())

    assert response.status_code == 200
    assert response.json()["sync"]["status"] == "blocked"
    assert ClipStore(tmp_path).find_raw_fields_by_client_request_id("sync-execute-not-allowed").ragflow_document_id == ""
    assert sync_jobs(tmp_path)[0]["status"] == "blocked"


def test_clip_ragflow_sync_execute_records_completed_remote_upload(tmp_path):
    adapter = FakeExecuteAdapter()
    api = client(tmp_path, real_sync_settings(tmp_path), ragflow_adapter_override=adapter)
    prepare_executable_sync(api, "sync-execute-success")

    response = api.post("/api/clips/sync-execute-success/ragflow-sync/execute", headers=auth_headers())

    assert response.status_code == 200
    sync = response.json()["sync"]
    assert sync["status"] == "completed"
    assert sync["dry_run"] is False
    assert sync["remote_document_changed"] is True
    assert sync["ragflow_document_id"] == "remote-document-1"
    assert ClipStore(tmp_path).find_raw_fields_by_client_request_id("sync-execute-success").ragflow_document_id == "remote-document-1"
    assert metadata_for_request(tmp_path, "sync-execute-success")["ragflow_sync"]["ragflow_document_id"] == "remote-document-1"
    assert adapter.uploads == [("dataset-test", "perclip-1.md")]
    assert adapter.meta_updates == [("dataset-test", "remote-document-1")]


def test_clip_ragflow_sync_execute_records_partial_upload_when_meta_update_fails(tmp_path):
    adapter = FakeExecuteAdapter(fail_meta=True)
    api = client(tmp_path, real_sync_settings(tmp_path), ragflow_adapter_override=adapter)
    prepare_executable_sync(api, "sync-execute-meta-failure")

    response = api.post("/api/clips/sync-execute-meta-failure/ragflow-sync/execute", headers=auth_headers())

    assert response.status_code == 502
    assert response.json()["detail"] == "RAGFlow document metadata update failed"
    assert ClipStore(tmp_path).find_raw_fields_by_client_request_id("sync-execute-meta-failure").ragflow_document_id == "remote-document-1"
    job = sync_jobs(tmp_path)[0]
    assert job["operation"] == "upload_document"
    assert job["status"] == "failed"
    assert job["dry_run"] == 0
    assert job["remote_document_changed"] == 1
    assert job["ragflow_document_id"] == "remote-document-1"
    assert json.loads(job["plan_json"])["meta_fields_written"] is False
    metadata = metadata_for_request(tmp_path, "sync-execute-meta-failure")["ragflow_sync"]
    assert metadata["status"] == "failed"
    assert metadata["ragflow_document_id"] == "remote-document-1"
    for payload in [response.text, json.dumps(job), json.dumps(metadata)]:
        assert "api_key" not in payload.lower()
        assert "authorization" not in payload.lower()
        assert "cookie" not in payload.lower()
        assert "password" not in payload.lower()
        assert "secret" not in payload.lower()
    adapter.fail_meta = False
    retry = api.post("/api/clips/sync-execute-meta-failure/ragflow-sync/execute", headers=auth_headers())
    assert retry.status_code == 200
    assert retry.json()["sync"]["operation"] == "update_meta_fields"
    assert adapter.uploads == [("dataset-test", "perclip-1.md")]


def test_clip_ragflow_sync_execute_does_not_record_remote_state_when_upload_fails(tmp_path):
    api = client(tmp_path, real_sync_settings(tmp_path), ragflow_adapter_override=FakeExecuteAdapter(fail_upload=True))
    prepare_executable_sync(api, "sync-execute-upload-failure")

    response = api.post("/api/clips/sync-execute-upload-failure/ragflow-sync/execute", headers=auth_headers())

    assert response.status_code == 422
    assert response.json()["detail"] == "RAGFlow document upload failed"
    assert ClipStore(tmp_path).find_raw_fields_by_client_request_id("sync-execute-upload-failure").ragflow_document_id == ""
    job = sync_jobs(tmp_path)[0]
    assert job["status"] == "failed"
    assert job["remote_document_changed"] == 0


def test_clip_ragflow_sync_plans_upload_document_and_updates_metadata(tmp_path):
    api = client(tmp_path)
    target = create_kb(api, "Sync Upload", "dataset-upload")
    upload = upload_text(api, "sync-upload", target_knowledge_base_id=target["id"], text="upload body")
    enrich(api, "sync-upload")
    before = metadata_for_request(tmp_path, "sync-upload")

    response = api.post("/api/clips/sync-upload/ragflow-sync/dry-run", headers=auth_headers())

    assert set(upload.json()) == legacy_response_keys()
    assert response.status_code == 200
    sync = response.json()["sync"]
    assert sync["operation"] == "upload_document"
    assert sync["status"] == "planned"
    assert sync["ragflow_dataset_id"] == "dataset-upload"
    assert sync["ragflow_document_id"] == ""
    assert sync["plan"]["target_dataset_id"] == "dataset-upload"
    assert sync["plan"]["title"] == "sync-upload"
    assert sync["plan"]["summary"] == "upload body"
    assert sync["plan"]["tags"] == ["text", "knowledge-base"]
    assert sync["plan"]["dry_run"] is True
    jobs = sync_jobs(tmp_path)
    assert len(jobs) == 1
    assert jobs[0]["operation"] == "upload_document"
    assert jobs[0]["dry_run"] == 1
    assert jobs[0]["remote_document_changed"] == 0
    assert json.loads(jobs[0]["plan_json"])["dry_run"] is True

    metadata = metadata_for_request(tmp_path, "sync-upload")
    assert metadata["clip"] == before["clip"]
    assert metadata["routing"] == before["routing"]
    assert metadata["enrichment"] == before["enrichment"]
    assert metadata["processing"] == before["processing"]
    assert metadata["ragflow_sync"]["operation"] == "upload_document"
    assert metadata["ragflow_sync"]["remote_document_changed"] is False


def test_clip_ragflow_sync_plans_update_meta_fields_for_existing_document(tmp_path):
    api = client(tmp_path)
    target = create_kb(api, "Sync Update", "dataset-update")
    upload_text(api, "sync-update", target_knowledge_base_id=target["id"], text="update body")
    set_ragflow_document_id(tmp_path, "sync-update", "doc-existing")
    enrich(api, "sync-update")

    response = api.post("/api/clips/sync-update/ragflow-sync/dry-run", headers=auth_headers())

    assert response.status_code == 200
    sync = response.json()["sync"]
    assert sync["operation"] == "update_meta_fields"
    assert sync["status"] == "planned"
    assert sync["ragflow_document_id"] == "doc-existing"
    assert sync["plan"]["existing_document_id"] == "doc-existing"
    assert sync["plan"]["meta_fields"] == {
        "summary": "update body",
        "tags": ["text", "knowledge-base"],
        "language": "en",
    }


def test_moved_clip_with_required_reindex_plans_reindex_after_move(tmp_path):
    api = client(tmp_path)
    source = create_kb(api, "Sync Source", "dataset-source")
    target = create_kb(api, "Sync Target", "dataset-target")
    upload_text(api, "sync-reindex", target_knowledge_base_id=source["id"], text="reindex body")
    set_ragflow_document_id(tmp_path, "sync-reindex", "doc-reindex")
    enrich(api, "sync-reindex")
    clip_id = clip_id_for_request(tmp_path, "sync-reindex")
    move = api.post(
        f"/api/clips/{clip_id}/move",
        headers=auth_headers(),
        json={"target_knowledge_base_id": target["id"]},
    )
    assert move.status_code == 200

    response = api.post("/api/clips/sync-reindex/ragflow-sync/dry-run", headers=auth_headers())

    assert response.status_code == 200
    sync = response.json()["sync"]
    assert sync["operation"] == "reindex_after_move"
    assert sync["status"] == "planned"
    assert sync["ragflow_dataset_id"] == "dataset-target"
    assert sync["ragflow_document_id"] == "doc-reindex"
    assert sync["route_decision_id"] == move.json()["route_decision"]["id"]
    assert sync["plan"]["existing_document_id"] == "doc-reindex"
    assert sync["plan"]["reindex_status"] == "required"


def test_get_latest_ragflow_sync_returns_latest_or_404(tmp_path):
    api = client(tmp_path)
    target = create_kb(api, "Sync Latest", "dataset-latest")
    upload_text(api, "sync-latest", target_knowledge_base_id=target["id"])
    enrich(api, "sync-latest")

    missing = api.get("/api/clips/sync-latest/ragflow-sync", headers=auth_headers())
    first = api.post("/api/clips/sync-latest/ragflow-sync/dry-run", headers=auth_headers())
    second = api.post("/api/clips/sync-latest/ragflow-sync/dry-run", headers=auth_headers())
    latest = api.get("/api/clips/sync-latest/ragflow-sync", headers=auth_headers())

    assert missing.status_code == 404
    assert missing.json()["detail"] == "ragflow sync not found"
    assert first.status_code == 200
    assert second.status_code == 200
    assert latest.status_code == 200
    assert latest.json()["sync"]["created_at"] == second.json()["sync"]["created_at"]


def test_ragflow_sync_metadata_and_outputs_do_not_include_known_secrets(tmp_path):
    api = client(tmp_path)
    target = create_kb(api, "Sync Credential", "dataset-credential")
    upload_text(
        api,
        "sync-credential",
        target_knowledge_base_id=target["id"],
        text="token=abc api_key=def password=hunter cookie=session authorization=bearer",
    )
    enrich(api, "sync-credential")

    response = api.post("/api/clips/sync-credential/ragflow-sync/dry-run", headers=auth_headers())

    assert response.status_code == 200
    payload = json.dumps(response.json(), ensure_ascii=False).lower()
    metadata_payload = json.dumps(
        metadata_for_request(tmp_path, "sync-credential")["ragflow_sync"],
        ensure_ascii=False,
    ).lower()
    sqlite_payload = json.dumps(sync_jobs(tmp_path), ensure_ascii=False).lower()
    for forbidden in [
        "secret",
        "token",
        "api_key",
        "password",
        "cookie",
        "authorization",
        "change-me-server-side-ragflow-key",
        "change-me-baidu-api-key",
        "nas-password",
        "ssh-password",
        "cloud-secret",
        "social-token",
    ]:
        assert forbidden not in payload
        assert forbidden not in metadata_payload
        assert forbidden not in sqlite_payload


def test_run_pending_ragflow_sync_dry_run_respects_limit_counts_and_is_dry_run(tmp_path):
    api = client(tmp_path)
    target = create_kb(api, "Sync Batch", "dataset-batch")
    upload_text(api, "sync-batch-planned", target_knowledge_base_id=target["id"])
    upload_text(api, "sync-batch-blocked")
    upload_text(api, "sync-batch-later", target_knowledge_base_id=target["id"])
    enrich(api, "sync-batch-planned")
    enrich(api, "sync-batch-blocked")
    enrich(api, "sync-batch-later")

    first = api.post("/api/ragflow-sync/run-pending-dry-run", headers=auth_headers(), json={"limit": 2})
    second = api.post("/api/ragflow-sync/run-pending-dry-run", headers=auth_headers(), json={"limit": 10})

    assert first.status_code == 200
    assert first.json()["processed"] == 2
    assert first.json()["planned"] == 1
    assert first.json()["blocked"] == 1
    assert all(item["dry_run"] is True for item in first.json()["items"])
    assert all(item["remote_document_changed"] is False for item in first.json()["items"])
    assert second.status_code == 200
    assert second.json()["processed"] == 1
    assert second.json()["planned"] == 1
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        remote_changes = db.execute("select sum(remote_document_changed) from ragflow_sync_jobs").fetchone()[0]
        dry_runs = db.execute("select count(*) from ragflow_sync_jobs where dry_run = 1").fetchone()[0]
    assert remote_changes == 0
    assert dry_runs == 3


def test_run_pending_ragflow_sync_rejects_invalid_limit(tmp_path):
    api = client(tmp_path)

    response = api.post("/api/ragflow-sync/run-pending-dry-run", headers=auth_headers(), json={"limit": 101})

    assert response.status_code == 422


def test_ragflow_sync_table_is_created_when_migrating_old_database(tmp_path):
    store = ClipStore(tmp_path)
    store.init()

    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        tables = {row[0] for row in db.execute("select name from sqlite_master where type = 'table'")}
        plan_default = db.execute(
            """
            select dflt_value from pragma_table_info('ragflow_sync_jobs')
            where name = 'plan_json'
            """
        ).fetchone()[0]

    assert "ragflow_sync_jobs" in tables
    assert plan_default == "'{}'"


def test_real_sync_replay_does_not_repeat_remote_update(tmp_path):
    adapter = FakeExecuteAdapter()
    api = client(tmp_path, real_sync_settings(tmp_path), ragflow_adapter_override=adapter)
    prepare_executable_sync(api, "sync-idempotent")
    set_ragflow_document_id(tmp_path, "sync-idempotent", "doc-existing")

    first = api.post("/api/clips/sync-idempotent/ragflow-sync/execute", headers=auth_headers())
    second = api.post("/api/clips/sync-idempotent/ragflow-sync/execute", headers=auth_headers())

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["idempotent_replay"] is True
    assert adapter.uploads == []
    assert adapter.meta_updates == [("dataset-test", "doc-existing")]


def test_ragflow_sync_lock_rejects_active_and_recovers_stale_lock(tmp_path):
    store = ClipStore(tmp_path)
    store.init()

    assert store.acquire_ragflow_sync_lock("clip-1", now_epoch=1_000)
    assert not store.acquire_ragflow_sync_lock("clip-1", now_epoch=1_001)
    assert store.acquire_ragflow_sync_lock("clip-1", now_epoch=2_000)


def test_execute_rejects_active_persistent_lock_and_releases_its_own_lock(tmp_path):
    adapter = FakeExecuteAdapter()
    api = client(tmp_path, real_sync_settings(tmp_path), ragflow_adapter_override=adapter)
    prepare_executable_sync(api, "sync-locked")
    clip_id = clip_id_for_request(tmp_path, "sync-locked")
    store = ClipStore(tmp_path)
    assert store.acquire_ragflow_sync_lock(clip_id, now_epoch=int(time.time()))

    blocked = api.post("/api/clips/sync-locked/ragflow-sync/execute", headers=auth_headers())
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "ragflow sync already running"

    store.release_ragflow_sync_lock(clip_id)
    completed = api.post("/api/clips/sync-locked/ragflow-sync/execute", headers=auth_headers())
    assert completed.status_code == 200
    assert store.acquire_ragflow_sync_lock(clip_id, now_epoch=int(time.time()))


def test_existing_document_meta_failure_is_retryable_without_remote_change(tmp_path):
    adapter = FakeExecuteAdapter(fail_meta=True)
    api = client(tmp_path, real_sync_settings(tmp_path), ragflow_adapter_override=adapter)
    prepare_executable_sync(api, "sync-existing-meta-failure")
    set_ragflow_document_id(tmp_path, "sync-existing-meta-failure", "doc-existing")

    response = api.post("/api/clips/sync-existing-meta-failure/ragflow-sync/execute", headers=auth_headers())

    assert response.status_code == 502
    job = sync_jobs(tmp_path)[0]
    assert job["operation"] == "update_meta_fields"
    assert job["remote_document_changed"] == 0
    assert job["ragflow_document_id"] == "doc-existing"
    assert adapter.uploads == []


def test_real_pending_sync_rejects_disabled_and_invalid_limit(tmp_path):
    api = client(tmp_path)

    disabled = api.post("/api/ragflow-sync/run-pending", headers=auth_headers())
    invalid = client(tmp_path, real_sync_settings(tmp_path)).post(
        "/api/ragflow-sync/run-pending", headers=auth_headers(), json={"limit": 51},
    )

    assert disabled.status_code == 422
    assert invalid.status_code == 422


def test_real_pending_sync_executes_serial_meta_update(tmp_path):
    adapter = FakeExecuteAdapter()
    api = client(tmp_path, real_sync_settings(tmp_path), ragflow_adapter_override=adapter)
    prepare_executable_sync(api, "sync-batch-real")
    set_ragflow_document_id(tmp_path, "sync-batch-real", "doc-batch")

    response = api.post("/api/ragflow-sync/run-pending", headers=auth_headers(), json={"limit": 1})

    assert response.status_code == 200
    assert response.json()["processed"] == 1
    assert response.json()["completed"] == 1
    assert response.json()["failed"] == 0
    assert adapter.uploads == []
    assert adapter.meta_updates == [("dataset-test", "doc-batch")]


def test_initial_upload_completed_replay_makes_no_remote_calls(tmp_path):
    adapter = FakeExecuteAdapter()
    api = client(tmp_path, real_sync_settings(tmp_path), ragflow_adapter_override=adapter)
    prepare_executable_sync(api, "sync-initial-replay")

    first = api.post("/api/clips/sync-initial-replay/ragflow-sync/execute", headers=auth_headers())
    second = api.post("/api/clips/sync-initial-replay/ragflow-sync/execute", headers=auth_headers())

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["idempotent_replay"] is True
    assert adapter.uploads == [("dataset-test", "perclip-1.md")]
    assert adapter.meta_updates == [("dataset-test", "remote-document-1")]
    assert [job["status"] for job in sync_jobs(tmp_path)] == ["completed"]


def test_pending_batch_scans_past_completed_queue_head(tmp_path):
    adapter = FakeExecuteAdapter()
    api = client(tmp_path, real_sync_settings(tmp_path), ragflow_adapter_override=adapter)
    request_ids = [f"sync-fair-{index}" for index in range(5)]
    for request_id in request_ids:
        prepare_executable_sync(api, request_id)
    for request_id in request_ids[:3]:
        assert api.post(f"/api/clips/{request_id}/ragflow-sync/execute", headers=auth_headers()).status_code == 200
    adapter.uploads.clear()
    adapter.meta_updates.clear()

    response = api.post("/api/ragflow-sync/run-pending", headers=auth_headers(), json={"limit": 2})

    assert response.status_code == 200
    assert response.json()["processed"] == 2
    assert response.json()["completed"] == 2
    assert [item["client_request_id"] for item in response.json()["items"]] == request_ids[3:]
    assert len(adapter.uploads) == 2
    assert len(adapter.meta_updates) == 2


def test_pending_batch_skips_unchanged_blocked_queue_head(tmp_path):
    adapter = FakeExecuteAdapter()
    api = client(tmp_path, real_sync_settings(tmp_path), ragflow_adapter_override=adapter)
    upload_text(api, "sync-blocked-head")
    enrich(api, "sync-blocked-head")
    prepare_executable_sync(api, "sync-after-blocked")

    blocked = api.post("/api/clips/sync-blocked-head/ragflow-sync/execute", headers=auth_headers())
    response = api.post("/api/ragflow-sync/run-pending", headers=auth_headers(), json={"limit": 1})

    assert blocked.status_code == 200
    assert blocked.json()["sync"]["status"] == "blocked"
    assert response.status_code == 200
    assert [item["client_request_id"] for item in response.json()["items"]] == ["sync-after-blocked"]


def test_pending_batch_skips_unchanged_reindex_blocked_queue_head(tmp_path):
    adapter = FakeExecuteAdapter()
    api = client(
        tmp_path,
        real_sync_settings(tmp_path, frozenset({"dataset-source", "dataset-target"})),
        ragflow_adapter_override=adapter,
    )
    source = create_kb(api, "Reindex Source", "dataset-source")
    target = create_kb(api, "Reindex Target", "dataset-target")
    upload_text(api, "sync-reindex-head", target_knowledge_base_id=source["id"])
    set_ragflow_document_id(tmp_path, "sync-reindex-head", "doc-reindex")
    enrich(api, "sync-reindex-head")
    move = api.post(
        f"/api/clips/{clip_id_for_request(tmp_path, 'sync-reindex-head')}/move",
        headers=auth_headers(),
        json={"target_knowledge_base_id": target["id"]},
    )
    assert move.status_code == 200
    direct = api.post("/api/clips/sync-reindex-head/ragflow-sync/execute", headers=auth_headers())
    assert direct.status_code == 409
    assert [job["error_code"] for job in sync_jobs(tmp_path)] == ["ragflow_reindex_required"]

    upload_text(api, "sync-after-reindex", target_knowledge_base_id=target["id"])
    enrich(api, "sync-after-reindex")
    first_batch = api.post("/api/ragflow-sync/run-pending", headers=auth_headers(), json={"limit": 1})
    second_batch = api.post("/api/ragflow-sync/run-pending", headers=auth_headers(), json={"limit": 1})

    assert first_batch.status_code == 200
    assert [item["client_request_id"] for item in first_batch.json()["items"]] == ["sync-after-reindex"]
    assert second_batch.status_code == 200
    assert second_batch.json()["processed"] == 0
    reindex_jobs = [job for job in sync_jobs(tmp_path) if job["client_request_id"] == "sync-reindex-head"]
    assert len(reindex_jobs) == 1
    assert adapter.uploads == [("dataset-target", "perclip-2.md")]
    assert adapter.meta_updates == [("dataset-target", "remote-document-1")]

    enrich(api, "sync-reindex-head")
    reevaluated = api.post("/api/ragflow-sync/run-pending", headers=auth_headers(), json={"limit": 1})

    assert reevaluated.status_code == 200
    assert reevaluated.json()["blocked"] == 1
    assert reevaluated.json()["items"][0]["client_request_id"] == "sync-reindex-head"
    reindex_jobs = [job for job in sync_jobs(tmp_path) if job["client_request_id"] == "sync-reindex-head"]
    assert len(reindex_jobs) == 2
    assert adapter.uploads == [("dataset-target", "perclip-2.md")]
    assert adapter.meta_updates == [("dataset-target", "remote-document-1")]


def test_pending_batch_reevaluates_changed_enrichment_snapshot(tmp_path):
    adapter = FakeExecuteAdapter()
    api = client(tmp_path, real_sync_settings(tmp_path), ragflow_adapter_override=adapter)
    prepare_executable_sync(api, "sync-enrichment-changed")
    assert api.post("/api/clips/sync-enrichment-changed/ragflow-sync/execute", headers=auth_headers()).status_code == 200
    enrich(api, "sync-enrichment-changed")
    adapter.uploads.clear()
    adapter.meta_updates.clear()

    response = api.post("/api/ragflow-sync/run-pending", headers=auth_headers(), json={"limit": 1})

    assert response.status_code == 200
    assert response.json()["completed"] == 1
    assert adapter.uploads == []
    assert adapter.meta_updates == [("dataset-test", "remote-document-1")]


def test_pending_batch_limit_counts_actionable_candidates_across_requests(tmp_path):
    adapter = FakeExecuteAdapter()
    api = client(tmp_path, real_sync_settings(tmp_path), ragflow_adapter_override=adapter)
    request_ids = [f"sync-actionable-{index}" for index in range(3)]
    for request_id in request_ids:
        prepare_executable_sync(api, request_id)

    first = api.post("/api/ragflow-sync/run-pending", headers=auth_headers(), json={"limit": 2})
    second = api.post("/api/ragflow-sync/run-pending", headers=auth_headers(), json={"limit": 2})

    assert first.status_code == 200
    assert [item["client_request_id"] for item in first.json()["items"]] == request_ids[:2]
    assert second.status_code == 200
    assert [item["client_request_id"] for item in second.json()["items"]] == request_ids[2:]


def test_pending_batch_reevaluates_blocked_allowlist_after_configuration_change(tmp_path):
    adapter = FakeExecuteAdapter()
    blocked_api = client(
        tmp_path,
        real_sync_settings(tmp_path, frozenset({"dataset-other"})),
        ragflow_adapter_override=adapter,
    )
    prepare_executable_sync(blocked_api, "sync-allowlist-changed")
    assert blocked_api.post("/api/clips/sync-allowlist-changed/ragflow-sync/execute", headers=auth_headers()).status_code == 200

    allowed_api = client(
        tmp_path,
        real_sync_settings(tmp_path),
        ragflow_adapter_override=adapter,
    )
    response = allowed_api.post("/api/ragflow-sync/run-pending", headers=auth_headers(), json={"limit": 1})

    assert response.status_code == 200
    assert response.json()["completed"] == 1
    assert adapter.uploads == [("dataset-test", "perclip-1.md")]
