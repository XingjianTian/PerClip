from __future__ import annotations

import json
import socket
import sqlite3
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from perclip_ingest.config import RagflowSettings, Settings
from perclip_ingest.main import create_app
from perclip_ingest.pipeline_store import PIPELINE_STAGES, PipelineStore
from perclip_ingest.ragflow_adapter import (
    RagflowAdapterError,
    RagflowDocumentRef,
    RagflowUnsupportedError,
)
from perclip_ingest.ragflow_index import (
    RagflowChunkSummary,
    RagflowDocumentStatus,
    RagflowVectorEvidence,
)
from perclip_ingest.web_extraction import ProxyDohResolver, WebFetchError, WebFetchResult
from perclip_ingest.worker import PipelineWorker


AUTH = {"Authorization": "Bearer secret"}


class ManualClock:
    def __init__(self) -> None:
        self.value = datetime.now(timezone.utc) + timedelta(seconds=1)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, *, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


def worker_settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        ingest_token="secret",
        processing_mode="worker",
        asset_root=tmp_path / "PersonalClips",
        deployment_environment="test",
    )


def test_worker_uses_proxy_doh_only_for_explicit_loopback_transport(
    tmp_path, monkeypatch
):
    direct = PipelineWorker(worker_settings(tmp_path / "direct"))
    assert direct.web_fetcher.proxy_host is None
    assert direct.web_fetcher.proxy_port is None
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.10", 443))
        ],
    )
    with pytest.raises(WebFetchError, match="private_address_blocked"):
        direct.web_fetcher.address_resolver("www.bilibili.com", 443)

    proxied_settings = replace(
        worker_settings(tmp_path / "proxied"),
        web_fetch_proxy_host="127.0.0.1",
        web_fetch_proxy_port=7890,
    )
    proxied = PipelineWorker(proxied_settings)
    assert proxied.web_fetcher.proxy_host == "127.0.0.1"
    assert proxied.web_fetcher.proxy_port == 7890
    resolver = proxied.web_fetcher.address_resolver.__self__
    assert isinstance(resolver, ProxyDohResolver)
    monkeypatch.setattr(
        resolver,
        "_query",
        lambda _hostname, record_type: (
            ["93.184.216.34"] if record_type == "A" else []
        ),
    )
    assert proxied.web_fetcher.address_resolver("www.bilibili.com", 443) == [
        "93.184.216.34"
    ]


def strict_text() -> dict[str, object]:
    return {
        "contract_version": "perclip.ingest.v1",
        "client_request_id": "wechat:test:event-1",
        "source": {
            "adapter": "wechat_bot",
            "client_id": "connector-test",
            "event_id": "event-1",
            "source_app": "WeChat",
            "account_hint": "",
        },
        "clip": {
            "source_type": "text",
            "title_hint": "Worker test",
            "note": "",
            "text": " durable   pipeline \n\n test ",
            "url": "",
            "mime_type": "text/plain",
            "captured_at": "2026-07-21T10:00:00+08:00",
            "captured_timezone": "Asia/Shanghai",
            "device_name": "",
        },
        "capture": {
            "client_batch_id": "",
            "parent_client_request_id": "",
            "part_index": 0,
            "part_count": 1,
            "part_role": "text",
            "source_intent": "share",
            "content_fingerprint": "",
        },
        "routing": {"target_knowledge_base_id": ""},
    }


def distinct_payload(identifier: str) -> dict[str, object]:
    payload = strict_text()
    payload["client_request_id"] = f"wechat:test:{identifier}"
    payload["source"]["event_id"] = identifier
    payload["clip"]["captured_at"] = datetime.now(timezone.utc).isoformat()
    return payload


class RecordingRagflowAdapter:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, str, bool]] = []
        self.meta_updates: list[tuple[str, str]] = []
        self.metadata: dict[str, dict[str, object]] = {}
        self.status_reads: dict[str, int] = {}

    def find_document_by_operation_key(self, dataset_id, operation_key):
        return []

    def upload_document(self, dataset_id, name, content_or_path, meta_fields=None, dry_run=True):
        self.uploads.append((dataset_id, name, content_or_path, dry_run))
        return RagflowDocumentRef(
            dataset_id=dataset_id,
            document_id=f"{'plan' if dry_run else 'doc'}-{len(self.uploads)}",
            name=name,
            meta_fields=meta_fields or {},
            dry_run=dry_run,
        )

    def update_document_meta(self, dataset_id, document_id, meta_fields, dry_run=True):
        self.meta_updates.append((dataset_id, document_id))
        self.metadata[document_id] = dict(meta_fields)
        return {"ok": True}

    def request_parse(self, dataset_id, document_id):
        self.status_reads[document_id] = 0

    def get_document_status(self, dataset_id, document_id):
        count = self.status_reads.get(document_id, -1)
        self.status_reads[document_id] = count + 1
        status = "unstart" if count < 0 else "done"
        return RagflowDocumentStatus(document_id, status, self.metadata.get(document_id, {}))

    def get_chunk_summary(self, dataset_id, document_id):
        return RagflowChunkSummary(document_id, 2)

    def get_vector_evidence(self, dataset_id, document_id):
        return RagflowVectorEvidence(document_id, 2)


class FailingIndexAdapter(RecordingRagflowAdapter):
    def __init__(self, failure: Exception) -> None:
        super().__init__()
        self.failure = failure
        self.calls: list[str] = []

    def find_document_by_operation_key(self, dataset_id, operation_key):
        self.calls.append("find_document_by_operation_key")
        raise self.failure


class StatusIndexAdapter(RecordingRagflowAdapter):
    def __init__(self, status: str) -> None:
        super().__init__()
        self.status = status

    def get_document_status(self, dataset_id, document_id):
        return RagflowDocumentStatus(
            document_id, self.status, self.metadata.get(document_id, {})
        )


class ParseFailureAdapter(RecordingRagflowAdapter):
    def request_parse(self, dataset_id, document_id):
        raise RagflowAdapterError("synthetic parse failure")


class UnsupportedVerificationAdapter(RecordingRagflowAdapter):
    def get_vector_evidence(self, dataset_id, document_id):
        raise RagflowUnsupportedError("synthetic verification unsupported")


def test_worker_mode_durably_accepts_then_runs_versioned_pipeline(tmp_path):
    settings = worker_settings(tmp_path)
    api = TestClient(create_app(settings))

    payload = strict_text()
    payload["clip"]["captured_at"] = datetime.now(timezone.utc).isoformat()
    accepted = api.post("/api/ingest/v1/clips", headers=AUTH, json=payload)

    assert accepted.status_code == 202
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["archive_status"] == "accepted"
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        source = db.execute(
            "select adapter, client_id, event_id, deployment_environment from source_events"
        ).fetchone()
        identity = db.execute("select public_id from clip_identities").fetchone()
        jobs = db.execute("select stage, status from outbox_jobs order by id").fetchall()
    assert source == ("wechat_bot", "connector-test", "event-1", "test")
    assert identity[0].startswith("pc_")
    assert jobs == [("archive_original", "pending")]

    worker = PipelineWorker(settings)
    for _stage in PIPELINE_STAGES:
        assert worker.run_once(limit=1) == 1

    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        stages = db.execute(
            "select stage, status from processing_runs order by id"
        ).fetchall()
        assets = db.execute("select role from assets order by role").fetchall()
        clip_status = db.execute("select archive_status from clips").fetchone()[0]
    assert stages == [(stage, "completed") for stage in PIPELINE_STAGES]
    assert {row[0] for row in assets} == {
        "staged_original", "original", "extracted_text", "clean_markdown"
    }
    assert clip_status == "archived"
    assert list((tmp_path / "PersonalClips").glob("pc_*/derived/clean_markdown.md"))
    processing = api.get(
        f"/api/clips/{accepted.json()['clip_id']}/processing", headers=AUTH
    )
    assert processing.status_code == 200
    assert [run["stage"] for run in processing.json()["runs"]] == list(PIPELINE_STAGES)
    quality = api.get(
        f"/api/clips/{accepted.json()['clip_id']}/quality", headers=AUTH
    ).json()["quality_read"]
    assert quality["topic_assignment"]["contract_version"] == "perclip.topic-assignment.v1"
    assert quality["topic_assignment"]["primary"]["topic_id"]
    knowledge_changes = api.get("/api/knowledge/changes", headers=AUTH).json()["changes"]
    assert any(change["reason"] == "association_upsert" for change in knowledge_changes)
    planet = api.get("/api/memory-planet?window=week", headers=AUTH)
    assert planet.status_code == 200
    assert planet.json()["planet"]["contract_version"] == "perclip.memory-planet.v1"
    assert planet.json()["planet"]["topics"][0]["memories"][0]["clip_id"].startswith("pc_")
    serialized = processing.text
    assert "storage_uri" not in serialized
    assert "dataset_id" not in serialized
    assert "document_id" not in serialized


def test_derived_generation_does_not_overwrite_prior_asset_bytes(tmp_path):
    settings = worker_settings(tmp_path)
    api = TestClient(create_app(settings))
    accepted = api.post(
        "/api/ingest/v1/clips", headers=AUTH, json=strict_text()
    ).json()
    worker = PipelineWorker(settings)
    raw = worker.store.find_raw_fields_by_clip_id(int(accepted["clip_id"]))
    assert raw is not None

    first_id = worker._write_derived_text(
        raw, role="clean_markdown", text="synthetic generation one"
    )
    second_id = worker._write_derived_text(
        raw, role="clean_markdown", text="synthetic generation two"
    )
    first = worker.pipeline.find_asset(first_id)
    second = worker.pipeline.find_asset(second_id)

    assert first is not None and second is not None
    assert first["storage_uri"] != second["storage_uri"]
    assert worker._read_asset_text(first) == "synthetic generation one"
    assert worker._read_asset_text(second) == "synthetic generation two"


@pytest.mark.parametrize("mode", ["off", "qa"])
def test_ragflow_off_and_qa_modes_make_no_remote_calls(tmp_path, mode):
    settings = Settings(
        data_dir=tmp_path,
        ingest_token="secret",
        processing_mode="worker",
        asset_root=tmp_path / "PersonalClips",
        deployment_environment="test",
        ragflow=RagflowSettings(
            base_url="http://unreachable.invalid",
            api_key="private-key",
            enable_real_sync=True,
            mode=mode,
            sync_allow_dataset_ids=frozenset({"private-dataset-id"}),
        ),
    )
    api = TestClient(create_app(settings))
    target = api.post(
        "/api/knowledge-bases",
        headers=AUTH,
        json={
            "name": f"{mode} mode target",
            "ragflow_dataset_id": "private-dataset-id",
        },
    ).json()["knowledge_base"]
    payload = distinct_payload(f"{mode}-mode")
    payload["routing"]["target_knowledge_base_id"] = target["id"]
    accepted = api.post("/api/ingest/v1/clips", headers=AUTH, json=payload)
    adapter = FailingIndexAdapter(RagflowAdapterError("must not be called"))
    worker = PipelineWorker(settings, ragflow_adapter_override=adapter)

    for _stage in PIPELINE_STAGES:
        assert worker.run_once(limit=1) == 1

    assert adapter.calls == []
    metadata = api.get(
        f"/api/clips/{accepted.json()['clip_id']}/enrichment", headers=AUTH
    ).json()["processing"]
    assert metadata["latest_index_attempt"]["status"] == (
        "disabled" if mode == "off" else "capability_only"
    )
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        assert db.execute(
            "select archive_status, metadata_status from ingest_receipts"
        ).fetchone() == ("ready", "available")
    assert api.get(
        f"/api/knowledge-bases/{target['id']}/clips", headers=AUTH
    ).json()["items"]
    assert api.get("/api/recall/overview", headers=AUTH).json()["highlights"]


@pytest.mark.parametrize(
    "failure_case",
    ["offline", "parse_failed", "parse_timeout", "remote_failed", "unsupported"],
)
def test_core_is_ready_and_readable_before_independent_index_failure(
    tmp_path, failure_case
):
    settings = Settings(
        data_dir=tmp_path,
        ingest_token="secret",
        processing_mode="worker",
        asset_root=tmp_path / "PersonalClips",
        deployment_environment="test",
        ragflow=RagflowSettings(
            base_url="http://unreachable.invalid",
            api_key="private-key",
            enable_real_sync=True,
            mode="index",
            sync_allow_dataset_ids=frozenset({"private-dataset-id"}),
            index_poll_timeout_seconds=0.001,
            index_poll_backoff_seconds=0.0001,
        ),
    )
    api = TestClient(create_app(settings))
    target = api.post(
        "/api/knowledge-bases",
        headers=AUTH,
        json={
            "name": "Core ready target",
            "ragflow_dataset_id": "private-dataset-id",
        },
    ).json()["knowledge_base"]
    payload = distinct_payload("core-ready-index-independent")
    payload["routing"]["target_knowledge_base_id"] = target["id"]
    accepted = api.post("/api/ingest/v1/clips", headers=AUTH, json=payload)
    if failure_case == "offline":
        adapter = FailingIndexAdapter(RagflowAdapterError("synthetic offline"))
    elif failure_case == "parse_failed":
        adapter = ParseFailureAdapter()
    elif failure_case == "parse_timeout":
        adapter = StatusIndexAdapter("running")
    elif failure_case == "remote_failed":
        adapter = StatusIndexAdapter("failed")
    else:
        adapter = UnsupportedVerificationAdapter()
    worker = PipelineWorker(
        settings,
        ragflow_adapter_override=adapter,
        sleep=lambda _seconds: None,
    )

    for _stage in PIPELINE_STAGES[:-1]:
        assert worker.run_once(limit=1) == 1
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        receipt = db.execute(
            "select archive_status, metadata_status from ingest_receipts"
        ).fetchone()
    assert receipt == ("ready", "available")
    knowledge = api.get(
        f"/api/knowledge-bases/{target['id']}/clips", headers=AUTH
    )
    recall = api.get("/api/recall/overview", headers=AUTH)
    assert knowledge.status_code == recall.status_code == 200
    assert len(knowledge.json()["items"]) == 1
    assert recall.json()["highlights"]

    assert worker.run_once(limit=1) == 0
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        assert db.execute(
            "select archive_status, metadata_status from ingest_receipts"
        ).fetchone() == ("ready", "available")


def test_pipeline_job_claim_is_lease_owned_and_expired_lease_is_recovered(tmp_path):
    settings = worker_settings(tmp_path)
    api = TestClient(create_app(settings))
    assert api.post("/api/ingest/v1/clips", headers=AUTH, json=strict_text()).status_code == 202
    pipeline = PipelineStore(tmp_path)

    first = pipeline.claim(limit=1, lease_seconds=-1)
    second = pipeline.claim(limit=1)

    assert len(first) == len(second) == 1
    assert first[0].id == second[0].id
    assert first[0].lease_token != second[0].lease_token
    assert second[0].attempt_count == 2
    assert pipeline.complete(first[0]) is False
    assert pipeline.complete(second[0]) is True


def test_worker_claims_only_the_job_about_to_run_and_heartbeats_a_long_stage(tmp_path):
    settings = worker_settings(tmp_path)
    api = TestClient(create_app(settings))
    assert api.post("/api/ingest/v1/clips", headers=AUTH, json=distinct_payload("lease-a")).status_code == 202
    assert api.post("/api/ingest/v1/clips", headers=AUTH, json=distinct_payload("lease-b")).status_code == 202
    clock = ManualClock()
    worker = PipelineWorker(settings, lease_seconds=10, lease_heartbeat_seconds=0.001, clock=clock)
    original = worker._run_stage
    original_renew = worker.pipeline.renew_lease
    entered = threading.Event()
    release = threading.Event()
    heartbeat_ready = threading.Event()
    allow_renewal = threading.Event()
    heartbeat_renewed = threading.Event()

    def slow_first(job):
        entered.set()
        assert release.wait(timeout=2)
        return original(job)

    def observed_renewal(job, *, lease_seconds):
        heartbeat_ready.set()
        assert allow_renewal.wait(timeout=2)
        renewed = original_renew(job, lease_seconds=lease_seconds)
        heartbeat_renewed.set()
        return renewed

    worker._run_stage = slow_first
    worker.pipeline.renew_lease = observed_renewal
    thread = threading.Thread(target=lambda: worker.run_once(limit=2))
    thread.start()
    assert entered.wait(timeout=1)
    assert heartbeat_ready.wait(timeout=1)

    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        states = db.execute(
            "select status, count(*) from outbox_jobs group by status order by status"
        ).fetchall()
        first_running_id = db.execute(
            "select id from outbox_jobs where status='running'"
        ).fetchone()[0]
    assert states == [("pending", 1), ("running", 1)]
    clock.advance(seconds=9)
    allow_renewal.set()
    assert heartbeat_renewed.wait(timeout=1)
    clock.advance(seconds=2)

    competing = PipelineStore(tmp_path, clock=clock).claim(limit=1, lease_seconds=10)
    assert len(competing) == 1
    assert competing[0].id != first_running_id

    release.set()
    thread.join(timeout=3)
    assert not thread.is_alive()
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        states_by_id = db.execute(
            "select id, status, lease_token from outbox_jobs order by id"
        ).fetchall()
    assert states_by_id[0] == (first_running_id, "completed", "")
    assert states_by_id[1][1] == "running"
    assert states_by_id[1][2] == competing[0].lease_token


def test_lease_renewal_and_completion_reject_an_old_token_after_reclaim(tmp_path):
    settings = worker_settings(tmp_path)
    api = TestClient(create_app(settings))
    assert api.post("/api/ingest/v1/clips", headers=AUTH, json=strict_text()).status_code == 202
    clock = ManualClock()
    pipeline = PipelineStore(tmp_path, clock=clock)
    old = pipeline.claim(limit=1, lease_seconds=10)[0]
    clock.advance(seconds=11)
    current = pipeline.claim(limit=1, lease_seconds=10)[0]

    assert pipeline.renew_lease(old, lease_seconds=10) is False
    assert pipeline.complete(old) is False
    assert pipeline.fail(old, safe_error_code="stale", retryable=False) is False
    assert pipeline.renew_lease(current, lease_seconds=10) is True
    assert pipeline.complete(current) is True


def test_worker_startup_recovers_interrupted_acceptance_registration(tmp_path):
    settings = worker_settings(tmp_path)
    api = TestClient(create_app(settings))
    assert api.post("/api/ingest/v1/clips", headers=AUTH, json=strict_text()).status_code == 202

    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.execute("delete from outbox_jobs")
        db.execute("delete from assets")
        db.execute("delete from clip_knowledge_bases")
        db.execute("delete from source_events")
        db.execute("delete from clip_identities")

    PipelineWorker(settings)

    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        assert db.execute("select count(*) from clip_identities").fetchone()[0] == 1
        assert db.execute("select count(*) from source_events").fetchone()[0] == 1
        assert db.execute("select stage, status from outbox_jobs").fetchone() == (
            "archive_original",
            "pending",
        )


def test_default_only_replay_keeps_one_automatic_capture_time_association(tmp_path):
    settings = worker_settings(tmp_path)
    api = TestClient(create_app(settings))
    capture_target = api.post(
        "/api/knowledge-bases",
        headers=AUTH,
        json={"name": "Capture-time default"},
    ).json()["knowledge_base"]
    next_default = api.post(
        "/api/knowledge-bases",
        headers=AUTH,
        json={"name": "Next default"},
    ).json()["knowledge_base"]
    payload = strict_text()
    payload["client_request_id"] = "worker-default-only-replay"
    payload["source"]["event_id"] = "worker-default-only-replay"
    payload["routing"] = {
        "mode": "default_only",
        "target_knowledge_base_id": capture_target["id"],
    }

    first = api.post("/api/ingest/v1/clips", headers=AUTH, json=payload)
    assert api.post(
        f"/api/knowledge-bases/{next_default['id']}/set-default",
        headers=AUTH,
    ).status_code == 200
    assert api.post(
        f"/api/knowledge-bases/{capture_target['id']}/archive",
        headers=AUTH,
    ).status_code == 200
    replay = api.post("/api/ingest/v1/clips", headers=AUTH, json=payload)

    assert first.status_code == replay.status_code == 202
    assert replay.json()["duplicate"] is True
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        decision = db.execute(
            """
            select id, knowledge_base_id, decision_type, manual_override
            from clip_route_decisions where client_request_id = ?
            """,
            ("worker-default-only-replay",),
        ).fetchall()
        association = db.execute(
            """
            select knowledge_base_id, association_type, route_decision_id
            from clip_knowledge_bases
            where clip_id = (select clip_id from ingest_receipts where client_request_id = ?)
            """,
            ("worker-default-only-replay",),
        ).fetchall()
    assert len(decision) == 1
    assert decision[0][1:] == (capture_target["id"], "default", 0)
    assert association == [(capture_target["id"], "automatic", decision[0][0])]


def test_clip_can_index_into_multiple_knowledge_bases_and_detach_non_primary(tmp_path):
    settings = worker_settings(tmp_path)
    api = TestClient(create_app(settings))
    created = api.post(
        "/api/knowledge-bases",
        headers=AUTH,
        json={
            "name": "Research",
            "ragflow_dataset_id": "dataset-research",
            "ragflow_dataset_name": "Research",
        },
    ).json()["knowledge_base"]
    payload = strict_text()
    accepted = api.post("/api/ingest/v1/clips", headers=AUTH, json=payload)
    clip_id = accepted.json()["clip_id"]
    worker = PipelineWorker(settings)
    for _stage in PIPELINE_STAGES:
        assert worker.run_once(limit=1) == 1

    associated = api.post(
        f"/api/clips/{clip_id}/knowledge-bases/{created['id']}", headers=AUTH
    )
    assert associated.status_code == 200
    assert len(associated.json()["knowledge_bases"]) == 2
    assert worker.run_once(limit=1) == 1

    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        rows = db.execute(
            "select knowledge_base_id, dataset_id, status from index_documents order by dataset_id"
        ).fetchall()
    assert rows == [(created["id"], "dataset-research", "planned")]

    detached = api.delete(
        f"/api/clips/{clip_id}/knowledge-bases/{created['id']}", headers=AUTH
    )
    assert detached.status_code == 200
    assert len(detached.json()["knowledge_bases"]) == 1
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        status = db.execute(
            "select status from index_documents where knowledge_base_id=?", (created["id"],)
        ).fetchone()[0]
    assert status == "detached_pending_cleanup"


def test_metadata_rebuild_preserves_connector_provenance(tmp_path):
    settings = worker_settings(tmp_path)
    api = TestClient(create_app(settings))
    target = api.post(
        "/api/knowledge-bases", headers=AUTH, json={"name": "Moved target"}
    ).json()["knowledge_base"]
    accepted = api.post("/api/ingest/v1/clips", headers=AUTH, json=strict_text())
    clip_id = accepted.json()["clip_id"]
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.execute("delete from clip_metadata where clip_id=?", (int(clip_id),))

    moved = api.post(
        f"/api/clips/{clip_id}/move",
        headers=AUTH,
        json={"target_knowledge_base_id": target["id"]},
    )
    assert moved.status_code == 200
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        metadata = db.execute(
            "select metadata_json from clip_metadata where clip_id=?", (int(clip_id),)
        ).fetchone()[0]
    provenance = json.loads(metadata)["provenance"]
    assert provenance["launcher_type"] == "wechat_bot"
    assert provenance["launcher_id"] == "connector-test"
    assert provenance["source_message_id"] == "event-1"


def test_dedicated_connector_token_is_ingest_only_and_adapter_scoped(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        ingest_token="admin-secret",
        processing_mode="worker",
        connector_tokens={"wechat_bot": "wechat-secret"},
    )
    api = TestClient(create_app(settings))

    accepted = api.post(
        "/api/ingest/v1/clips",
        headers={"Authorization": "Bearer wechat-secret"},
        json=strict_text(),
    )
    different = strict_text()
    different["client_request_id"] = "wechat:test:event-2"
    admin_with_wrong_scope = api.post(
        "/api/ingest/v1/clips",
        headers={"Authorization": "Bearer admin-secret"},
        json=different,
    )
    connector_query = api.get(
        "/api/knowledge-bases",
        headers={"Authorization": "Bearer wechat-secret"},
    )
    connector_receipt = api.get(
        f"/api/ingest/v1/receipts/{accepted.json()['receipt_id']}",
        headers={"Authorization": "Bearer wechat-secret"},
    )
    android = strict_text()
    android["client_request_id"] = "android:test:event-3"
    android["source"] = {
        "adapter": "android",
        "client_id": "device-test",
        "event_id": "event-3",
        "source_app": "PerClip",
        "account_hint": "",
    }
    android_receipt = api.post(
        "/api/ingest/v1/clips",
        headers={"Authorization": "Bearer admin-secret"},
        json=android,
    )
    cross_adapter_receipt = api.get(
        f"/api/ingest/v1/receipts/{android_receipt.json()['receipt_id']}",
        headers={"Authorization": "Bearer wechat-secret"},
    )

    assert accepted.status_code == 202
    assert admin_with_wrong_scope.status_code == 403
    assert connector_query.status_code == 401
    assert connector_receipt.status_code == 200
    assert android_receipt.status_code == 202
    assert cross_adapter_receipt.status_code == 403


def test_worker_error_codes_do_not_derive_from_private_paths():
    code = PipelineWorker._safe_error_code(OSError("missing /private/user/content.txt"))

    assert code == "asset_io_failed"
    assert "private" not in code


def test_source_event_identity_cannot_be_reassigned_to_another_request(tmp_path):
    api = TestClient(create_app(worker_settings(tmp_path)))
    assert api.post("/api/ingest/v1/clips", headers=AUTH, json=strict_text()).status_code == 202
    duplicate_event = strict_text()
    duplicate_event["client_request_id"] = "wechat:test:different-request"

    rejected = api.post("/api/ingest/v1/clips", headers=AUTH, json=duplicate_event)

    assert rejected.status_code == 409
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        assert db.execute("select count(*) from clips").fetchone()[0] == 1
        assert db.execute("select count(*) from source_events").fetchone()[0] == 1


def test_web_clean_projection_drives_enrichment_metadata_and_recall(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        ingest_token="secret",
        processing_mode="worker",
        asset_root=tmp_path / "PersonalClips",
        deployment_environment="test",
        enable_web_fetch=True,
    )
    api = TestClient(create_app(settings))
    payload = distinct_payload("web-projection")
    payload["clip"].update(
        {
            "source_type": "url",
            "title_hint": "",
            "text": "",
            "url": "https://example.com/article?utm_source=test&id=7",
            "mime_type": "text/html",
        }
    )
    accepted = api.post("/api/ingest/v1/clips", headers=AUTH, json=payload)
    worker = PipelineWorker(settings)
    worker.web_fetcher.fetch = lambda _url: WebFetchResult(
        safe_original_url="https://example.com/article?id=7",
        resolved_url="https://example.org/final?id=7",
        canonical_url="https://example.org/final?id=7",
        content_type="text/html",
        body=(
            b"<html><head><title>Processed knowledge title</title></head><body><article>"
            b"<h1>Processed knowledge title</h1><p>Durable projection body explains "
            b"knowledge quality and semantic retrieval in detail for testing.</p>"
            b"</article><footer>noise</footer></body></html>"
        ),
    )
    for _stage in PIPELINE_STAGES[:3]:
        assert worker.run_once(limit=1) == 1

    clip_id = accepted.json()["clip_id"]
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        assert db.execute(
            "select engine, engine_version, status from outbox_jobs "
            "where clip_id=? and stage='enrich'",
            (int(clip_id),),
        ).fetchone() == ("deterministic.v7", "v7", "pending")

    assert worker.run_once(limit=1) == 1
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        assert db.execute(
            "select engine, engine_version, status from processing_runs "
            "where clip_id=? and stage='enrich'",
            (int(clip_id),),
        ).fetchone() == ("deterministic.v7", "v7", "completed")

    for _stage in PIPELINE_STAGES[4:]:
        assert worker.run_once(limit=1) == 1

    enrichment = api.get(f"/api/clips/{clip_id}/enrichment", headers=AUTH).json()["enrichment"]
    assert enrichment["title"] == "Processed knowledge title"
    assert "Durable projection body" in enrichment["summary"]
    assert "Durable projection body" in enrichment["extracted_text"]
    assert enrichment["language"] == "en"
    assert enrichment["engine"] == "deterministic.v7"
    assert enrichment["tags"] == []
    assert enrichment["key_points"] == [
        "Processed knowledge title",
        "Durable projection body explains knowledge quality and semantic retrieval in detail for testing.",
    ]
    assert enrichment["summary"] != "URL: https://example.com/article?utm_source=test&id=7"
    metadata = json.loads(
        sqlite3.connect(tmp_path / "perclip.sqlite3").execute(
            "select metadata_json from clip_metadata where clip_id=?", (int(clip_id),)
        ).fetchone()[0]
    )
    assert metadata["projection"]["canonical_url"] == "https://example.org/final?id=7"
    assert metadata["projection"]["title"] == "Processed knowledge title"
    assert metadata["projection"]["extraction_status"] in {"partial", "completed"}
    assert isinstance(metadata["projection"]["quality_score"], float)
    title_field = metadata["projection"]["structured_metadata"]["title"]
    assert title_field["value"] == "Processed knowledge title"
    assert title_field["source"] == "html.title"
    assert title_field["engine_version"] == "v7"
    assert len(title_field["input_hash"]) == len(title_field["output_hash"]) == 64
    author_field = metadata["projection"]["structured_metadata"]["author"]
    assert (author_field["value"], author_field["source"]) == (
        "未明确来源", "policy.explicit_unknown_source",
    )
    assert author_field["resolution_state"] == "explicit_unknown"
    assert metadata["projection"]["structured_metadata"]["core_content"]["resolution_state"] == "resolved"
    assert metadata["processing"]["latest_attempted_projection"] == metadata["projection"]
    assert metadata["processing"]["latest_successful_projection"] == metadata["projection"]
    assert metadata["enrichment"]["key_points"] == enrichment["key_points"]
    assert metadata["processing"]["raw_fallback_used"] is False
    assert metadata["clip"]["text"] == enrichment["extracted_text"]
    overview = api.get("/api/recall/overview", headers=AUTH).json()
    public_clip_id = PipelineStore(tmp_path).public_id_for(int(clip_id))
    memory = next(item for item in overview["highlights"] if item["clip_id"] == public_clip_id)
    assert memory["title"] == "Processed knowledge title"
    assert "Durable projection body" in memory["summary"]


def test_web_worker_uses_bilibili_public_metadata_adapter(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        ingest_token="secret",
        processing_mode="worker",
        asset_root=tmp_path / "PersonalClips",
        deployment_environment="test",
        enable_web_fetch=True,
    )
    api = TestClient(create_app(settings))
    payload = distinct_payload("bilibili-adapter")
    payload["clip"].update(
        {
            "source_type": "url",
            "title_hint": "",
            "text": "",
            "url": "https://www.bilibili.com/video/BVsynthetic",
            "mime_type": "text/html",
        }
    )
    accepted = api.post("/api/ingest/v1/clips", headers=AUTH, json=payload)
    worker = PipelineWorker(settings)
    worker.web_fetcher.fetch = lambda _url: WebFetchResult(
        safe_original_url="https://www.bilibili.com/video/BVsynthetic",
        resolved_url="https://www.bilibili.com/video/BVsynthetic",
        canonical_url="https://www.bilibili.com/video/BVsynthetic",
        content_type="text/html",
        body="""
        <html><head>
          <meta property="og:title" content="Synthetic video title_哔哩哔哩_bilibili">
          <meta name="author" content="UP主： Synthetic UP">
          <meta property="og:description" content="Useful public video description.">
          <meta property="video:tag" content="Knowledge">
        </head><body><script>dynamic shell</script></body></html>
        """.encode(),
    )
    for _stage in PIPELINE_STAGES:
        assert worker.run_once(limit=1) == 1

    clip_id = accepted.json()["clip_id"]
    enrichment = api.get(f"/api/clips/{clip_id}/enrichment", headers=AUTH).json()["enrichment"]
    assert enrichment["title"] == "Synthetic video title"
    assert enrichment["extracted_text"] == (
        "Useful public video description.\n\n标签：Knowledge"
    )
    metadata = json.loads(
        sqlite3.connect(tmp_path / "perclip.sqlite3").execute(
            "select metadata_json from clip_metadata where clip_id=?", (int(clip_id),)
        ).fetchone()[0]
    )
    assert metadata["projection"]["extraction_status"] == "partial"
    assert metadata["projection"]["structured_metadata"]["title"]["value"] == (
        "Synthetic video title"
    )
    assert metadata["projection"]["structured_metadata"]["author"]["value"] == "Synthetic UP"
    assert metadata["projection"]["structured_metadata"]["author"]["resolution_state"] == "resolved"
    assert metadata["projection"]["structured_metadata"]["title"]["engine_version"] == "v2"
    assert metadata["processing"]["quality_reason"] == (
        "video_description_without_transcript"
    )
    quality = api.get(f"/api/clips/{clip_id}/quality", headers=AUTH).json()["quality_read"]
    assert quality["active_content"]["title"] == "Synthetic video title"
    assert metadata["projection"]["raw_fallback_used"] is False


def test_web_worker_uses_single_bilibili_acquisition_fallback(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        ingest_token="secret",
        processing_mode="worker",
        asset_root=tmp_path / "PersonalClips",
        deployment_environment="test",
        enable_web_fetch=True,
    )
    api = TestClient(create_app(settings))
    video_url = "https://www.bilibili.com/video/BV1AB411C7D9"
    payload = distinct_payload("bilibili-acquisition-adapter")
    payload["clip"].update(
        {
            "source_type": "url",
            "title_hint": "",
            "text": "",
            "url": video_url,
            "mime_type": "text/html",
        }
    )
    accepted = api.post("/api/ingest/v1/clips", headers=AUTH, json=payload)
    worker = PipelineWorker(settings)
    calls: list[tuple[str, bool]] = []
    frozen = (
        Path(__file__).parents[2]
        / "tests/fixtures/stage24/bilibili_acquisition/public_metadata_success.json"
    ).read_bytes()

    def fetch(url: str, *, allow_json: bool = False) -> WebFetchResult:
        calls.append((url, allow_json))
        if len(calls) == 1:
            raise WebFetchError("web_fetch_failed")
        return WebFetchResult(url, url, url, "application/json", frozen)

    worker.web_fetcher.fetch = fetch
    for _stage in PIPELINE_STAGES:
        assert worker.run_once(limit=1) == 1

    assert calls == [
        (video_url, False),
        ("https://api.bilibili.com/x/web-interface/view?bvid=BV1AB411C7D9", True),
    ]
    clip_id = accepted.json()["clip_id"]
    enrichment = api.get(
        f"/api/clips/{clip_id}/enrichment", headers=AUTH
    ).json()["enrichment"]
    assert enrichment["title"] == "Synthetic frozen video title"
    assert enrichment["extracted_text"].startswith(
        "Synthetic frozen public description"
    )
    metadata = json.loads(
        sqlite3.connect(tmp_path / "perclip.sqlite3").execute(
            "select metadata_json from clip_metadata where clip_id=?", (int(clip_id),)
        ).fetchone()[0]
    )
    structured = metadata["projection"]["structured_metadata"]
    assert structured["title"]["engine"] == "perclip-bilibili-acquisition"
    assert metadata["projection"]["extraction_status"] == "partial"
    assert metadata["projection"]["recall_eligible"] is True
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        assert db.execute(
            "select count(*) from assets where clip_id=? and role='raw_platform_metadata'",
            (int(clip_id),),
        ).fetchone()[0] == 1


def test_failed_bilibili_fallback_is_terminal_and_never_retried(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        ingest_token="secret",
        processing_mode="worker",
        asset_root=tmp_path / "PersonalClips",
        deployment_environment="test",
        enable_web_fetch=True,
    )
    api = TestClient(create_app(settings))
    video_url = "https://www.bilibili.com/video/BV1AB411C7D9"
    payload = distinct_payload("bilibili-terminal-fallback")
    payload["clip"].update(
        {
            "source_type": "url",
            "title_hint": "",
            "text": "",
            "url": video_url,
            "mime_type": "text/html",
        }
    )
    accepted = api.post("/api/ingest/v1/clips", headers=AUTH, json=payload)
    assert accepted.status_code == 202
    worker = PipelineWorker(settings)
    calls: list[tuple[str, bool]] = []

    def fetch(url: str, *, allow_json: bool = False) -> WebFetchResult:
        calls.append((url, allow_json))
        if not allow_json:
            raise WebFetchError("web_fetch_failed")
        raise WebFetchError("upstream_http_error")

    worker.web_fetcher.fetch = fetch
    assert worker.run_once(limit=1) == 1  # archive_original
    assert worker.run_once(limit=1) == 0  # terminal extract failure
    assert calls == [
        (video_url, False),
        ("https://api.bilibili.com/x/web-interface/view?bvid=BV1AB411C7D9", True),
    ]

    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        extract_job = db.execute(
            "select status, attempt_count, max_attempts, safe_error_code "
            "from outbox_jobs where stage='extract'"
        ).fetchone()
    assert extract_job == (
        "failed",
        1,
        5,
        "bilibili_acquisition_fetch_failed",
    )

    for _stage in ("clean", "enrich", "classify_topic", "route", "index"):
        assert worker.run_once(limit=1) == 1
    assert worker.run_once(limit=1) == 0
    assert len(calls) == 2


def test_file_clean_projection_changes_enrichment_from_filename_to_body(tmp_path):
    settings = worker_settings(tmp_path)
    api = TestClient(create_app(settings))
    payload = distinct_payload("file-projection")
    payload["source"]["adapter"] = "api"
    payload["clip"].update(
        {"source_type": "file", "title_hint": "", "text": "", "mime_type": "text/plain"}
    )
    payload["capture"]["part_role"] = "file"
    accepted = api.post(
        "/api/ingest/v1/clips/multipart",
        headers=AUTH,
        data={"envelope_json": json.dumps(payload)},
        files={
            "file": (
                "generic-name.txt",
                b"Semantic File Heading\nNavigation\nThe cleaned document body carries projection evidence.",
                "text/plain",
            )
        },
    )
    assert accepted.status_code == 202
    worker = PipelineWorker(settings)
    for _stage in PIPELINE_STAGES:
        assert worker.run_once(limit=1) == 1

    enrichment = api.get(
        f"/api/clips/{accepted.json()['clip_id']}/enrichment", headers=AUTH
    ).json()["enrichment"]
    assert enrichment["title"] == "Semantic File Heading"
    assert "cleaned document body" in enrichment["extracted_text"]
    assert enrichment["summary"] != "File: generic-name.txt (text/plain)"


def test_terminal_extract_failure_keeps_raw_memory_and_continues_with_safe_fallback(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        ingest_token="secret",
        processing_mode="worker",
        asset_root=tmp_path / "PersonalClips",
        enable_web_fetch=True,
    )
    api = TestClient(create_app(settings))
    payload = distinct_payload("web-fallback")
    payload["clip"].update(
        {"source_type": "url", "text": "", "url": "https://example.com/fallback"}
    )
    accepted = api.post("/api/ingest/v1/clips", headers=AUTH, json=payload)
    worker = PipelineWorker(settings)
    assert worker.run_once(limit=1) == 1
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.execute("update outbox_jobs set max_attempts=1 where stage='extract'")
    worker.web_fetcher.fetch = lambda _url: (_ for _ in ()).throw(RuntimeError("extract failed"))
    assert worker.run_once(limit=1) == 0
    for _stage in ("clean", "enrich", "classify_topic", "route", "index"):
        assert worker.run_once(limit=1) == 1

    clip_id = accepted.json()["clip_id"]
    enrichment = api.get(f"/api/clips/{clip_id}/enrichment", headers=AUTH).json()["enrichment"]
    assert enrichment["extracted_text"] == ""
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        failed = db.execute(
            "select status, safe_error_code from processing_runs where stage='extract'"
        ).fetchone()
        asset_metadata = json.loads(db.execute(
            "select metadata_json from assets where clip_id=? and role='extracted_text' order by created_at desc limit 1",
            (int(clip_id),),
        ).fetchone()[0])
    assert failed == ("failed", "pipeline_stage_failed")
    fields = asset_metadata["extraction"]["fields"]
    assert (fields["title"]["value"], fields["title"]["source"]) == ("Worker test", "user.title_hint")
    assert (fields["author"]["value"], fields["author"]["source"]) == (
        "未明确来源", "policy.explicit_unknown_source",
    )
    assert fields["author"]["resolution_state"] == "explicit_unknown"
    assert (fields["core_content"]["value"], fields["core_content"]["source"]) == (
        "内容暂不可用", "policy.explicit_unavailable_content",
    )
    assert fields["core_content"]["resolution_state"] == "explicit_unavailable"
    recall = api.get("/api/recall/domain?days=30&memory_limit=200", headers=AUTH).json()
    assert any(item["client_request_id"] == payload["client_request_id"] for item in recall["memories"])


def test_failed_url_with_explicit_dataset_keeps_intent_and_never_calls_ragflow(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        ingest_token="secret",
        processing_mode="worker",
        asset_root=tmp_path / "PersonalClips",
        enable_web_fetch=True,
    )
    api = TestClient(create_app(settings))
    target = api.post(
        "/api/knowledge-bases",
        headers=AUTH,
        json={"name": "Manual target", "ragflow_dataset_id": "dataset-manual"},
    ).json()["knowledge_base"]
    payload = distinct_payload("failed-explicit-index-gate")
    payload["routing"]["target_knowledge_base_id"] = target["id"]
    payload["clip"].update(
        {
            "source_type": "url",
            "text": "",
            "url": "https://example.com/failure?token=must-not-leak",
        }
    )
    accepted = api.post("/api/ingest/v1/clips", headers=AUTH, json=payload)
    adapter = RecordingRagflowAdapter()
    worker = PipelineWorker(settings, ragflow_adapter_override=adapter)
    assert worker.run_once(limit=1) == 1
    worker.web_fetcher.fetch = lambda _url: (_ for _ in ()).throw(RuntimeError("synthetic"))
    assert worker.run_once(limit=1) == 0
    for _stage in ("clean", "enrich", "classify_topic", "route", "index"):
        assert worker.run_once(limit=1) == 1

    clip_id = accepted.json()["clip_id"]
    associations = api.get(f"/api/clips/{clip_id}/knowledge-bases", headers=AUTH).json()["knowledge_bases"]
    assert [item["knowledge_base_id"] for item in associations] == [target["id"]]
    assert adapter.uploads == []
    assert adapter.meta_updates == []
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        metadata_text = db.execute(
            "select metadata_json from clip_metadata where clip_id=?", (int(clip_id),)
        ).fetchone()[0]
        assert db.execute("select count(*) from index_documents").fetchone()[0] == 0
    metadata = json.loads(metadata_text)
    assert metadata["processing"]["active_index"]["status"] == "not_indexed"
    assert metadata["processing"]["latest_index_attempt"]["status"] == "skipped_quality_gate"
    assert metadata["processing"]["active_projection"]["index_eligible"] is False
    assert "must-not-leak" not in metadata_text


def test_unsupported_binary_with_dataset_is_not_indexed(tmp_path):
    settings = worker_settings(tmp_path)
    api = TestClient(create_app(settings))
    target = api.post(
        "/api/knowledge-bases",
        headers=AUTH,
        json={"name": "Binary target", "ragflow_dataset_id": "dataset-binary"},
    ).json()["knowledge_base"]
    payload = distinct_payload("unsupported-binary-index-gate")
    payload["source"]["adapter"] = "api"
    payload["routing"]["target_knowledge_base_id"] = target["id"]
    payload["clip"].update(
        {"source_type": "file", "title_hint": "", "text": "", "mime_type": "application/octet-stream"}
    )
    payload["capture"]["part_role"] = "file"
    accepted = api.post(
        "/api/ingest/v1/clips/multipart",
        headers=AUTH,
        data={"envelope_json": json.dumps(payload)},
        files={"file": ("unsupported.bin", b"synthetic printable bytes", "application/octet-stream")},
    )
    adapter = RecordingRagflowAdapter()
    worker = PipelineWorker(settings, ragflow_adapter_override=adapter)
    for _stage in PIPELINE_STAGES:
        assert worker.run_once(limit=1) == 1

    assert accepted.status_code == 202
    assert adapter.uploads == []
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        metadata = json.loads(db.execute(
            "select metadata_json from clip_metadata where clip_id=?", (int(accepted.json()["clip_id"]),)
        ).fetchone()[0])
    assert metadata["processing"]["active_index"]["status"] == "not_indexed"
    assert metadata["processing"]["latest_index_attempt"]["status"] == "skipped_quality_gate"
    assert metadata["processing"]["active_projection"]["safe_error_code"] == "unsupported_media_type"


def test_success_failed_reprocess_and_retry_keep_then_advance_active_projection(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        ingest_token="secret",
        processing_mode="worker",
        asset_root=tmp_path / "PersonalClips",
        enable_web_fetch=True,
    )
    api = TestClient(create_app(settings))
    target = api.post(
        "/api/knowledge-bases",
        headers=AUTH,
        json={"name": "Lifecycle target", "ragflow_dataset_id": "dataset-lifecycle"},
    ).json()["knowledge_base"]
    payload = distinct_payload("projection-lifecycle")
    payload["routing"]["target_knowledge_base_id"] = target["id"]
    payload["clip"].update(
        {"source_type": "url", "title_hint": "", "text": "", "url": "https://example.com/lifecycle"}
    )
    accepted = api.post("/api/ingest/v1/clips", headers=AUTH, json=payload)
    adapter = RecordingRagflowAdapter()
    worker = PipelineWorker(settings, ragflow_adapter_override=adapter)

    def fetched(title: str, body: str) -> WebFetchResult:
        return WebFetchResult(
            safe_original_url="https://example.com/lifecycle",
            resolved_url="https://example.com/lifecycle",
            canonical_url="https://example.com/lifecycle",
            content_type="text/html",
            body=f"<html><head><title>{title}</title></head><body><main><p>{body}</p></main></body></html>".encode(),
        )

    worker.web_fetcher.fetch = lambda _url: fetched("First success", "First durable successful body.")
    for _stage in PIPELINE_STAGES:
        assert worker.run_once(limit=1) == 1
    clip_id = int(accepted.json()["clip_id"])
    first = api.get(f"/api/clips/{clip_id}/enrichment", headers=AUTH).json()["enrichment"]
    first_processing = api.get(f"/api/clips/{clip_id}/processing", headers=AUTH).json()
    first_active_projection = dict(first_processing["projection_state"]["active_projection"])
    first_active_index = dict(first_processing["index_state"]["active_index"])
    assert first_active_index["status"] == "not_indexed"
    assert first_processing["index_state"]["latest_index_attempt"]["status"] == "planned"
    first_recall = api.get("/api/recall/overview", headers=AUTH).json()
    public_clip_id = PipelineStore(tmp_path).public_id_for(clip_id)
    assert any(item["clip_id"] == public_clip_id for item in first_recall["highlights"])
    assert adapter.uploads == []

    pipeline = PipelineStore(tmp_path)
    failed_job = pipeline.enqueue(
        clip_id=clip_id,
        stage="extract",
        engine="builtin-extractor",
        engine_version="v3",
        input_hash="failed-reprocess-v3",
    )
    worker.web_fetcher.fetch = lambda _url: (_ for _ in ()).throw(RuntimeError("synthetic"))
    assert worker.run_once(limit=1) == 0
    for _stage in ("clean", "enrich", "classify_topic", "route", "index"):
        assert worker.run_once(limit=1) == 1

    after_failure = api.get(f"/api/clips/{clip_id}/enrichment", headers=AUTH).json()
    assert after_failure["enrichment"]["title"] == first["title"]
    assert after_failure["processing"]["latest_attempted_projection"]["extraction_status"] == "failed"
    assert after_failure["processing"]["active_projection"]["extraction_status"] == "completed"
    assert after_failure["processing"]["active_projection"]["source_asset_id"] == first_active_projection["source_asset_id"]
    assert after_failure["processing"]["latest_successful_projection"] == first_active_projection
    assert after_failure["processing"]["active_index"] == first_active_index
    assert after_failure["processing"]["latest_index_attempt"]["status"] == "skipped_no_new_projection"
    assert after_failure["processing"]["latest_index_attempt"]["reason"] == "no_new_eligible_projection"
    recall_after_failure = api.get("/api/recall/overview", headers=AUTH).json()
    assert any(item["clip_id"] == public_clip_id for item in recall_after_failure["highlights"])
    assert adapter.uploads == []

    pipeline.retry_failed_job(job_id=failed_job.id, request_id="lifecycle-retry", authorized=True)
    worker.web_fetcher.fetch = lambda _url: fetched("Retry success", "Second durable successful body.")
    for _stage in PIPELINE_STAGES[1:]:
        assert worker.run_once(limit=1) == 1

    after_retry = api.get(f"/api/clips/{clip_id}/enrichment", headers=AUTH).json()
    assert after_retry["enrichment"]["title"] == "Retry success"
    assert after_retry["processing"]["active_projection"]["extraction_status"] == "completed"
    assert after_retry["processing"]["active_projection"]["source_asset_id"] != first_active_projection["source_asset_id"]
    assert after_retry["processing"]["active_index"] == first_active_index
    assert after_retry["processing"]["latest_index_attempt"]["status"] == "planned"
    assert adapter.uploads == []


def test_success_unusable_partial_reprocess_preserves_active_knowledge_recall_and_index(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        ingest_token="secret",
        processing_mode="worker",
        asset_root=tmp_path / "PersonalClips",
        enable_web_fetch=True,
    )
    api = TestClient(create_app(settings))
    target = api.post(
        "/api/knowledge-bases",
        headers=AUTH,
        json={"name": "Partial lifecycle", "ragflow_dataset_id": "dataset-partial-lifecycle"},
    ).json()["knowledge_base"]
    payload = distinct_payload("projection-partial-lifecycle")
    payload["routing"]["target_knowledge_base_id"] = target["id"]
    payload["clip"].update(
        {"source_type": "url", "title_hint": "", "text": "", "url": "https://example.com/partial-lifecycle"}
    )
    accepted = api.post("/api/ingest/v1/clips", headers=AUTH, json=payload)
    clip_id = int(accepted.json()["clip_id"])
    adapter = RecordingRagflowAdapter()
    worker = PipelineWorker(settings, ragflow_adapter_override=adapter)

    def fetched(title: str, body: str) -> WebFetchResult:
        return WebFetchResult(
            safe_original_url="https://example.com/partial-lifecycle",
            resolved_url="https://example.com/partial-lifecycle",
            canonical_url="https://example.com/partial-lifecycle",
            content_type="text/html",
            body=f"<html><head><title>{title}</title></head><body><main><p>{body}</p></main></body></html>".encode(),
        )

    worker.web_fetcher.fetch = lambda _url: fetched(
        "Stable active title", "Stable active body remains the Knowledge and Recall source."
    )
    for _stage in PIPELINE_STAGES:
        assert worker.run_once(limit=1) == 1
    first = api.get(f"/api/clips/{clip_id}/enrichment", headers=AUTH).json()
    first_processing = first["processing"]
    first_active = dict(first_processing["active_projection"])
    first_active_id = first_processing["recall_enrichment_resolution"]["active_enrichment_id"]
    first_index = dict(first_processing["active_index"])
    assert first_index["status"] == "not_indexed"
    assert adapter.uploads == []

    pipeline = PipelineStore(tmp_path)
    pipeline.enqueue(
        clip_id=clip_id,
        stage="extract",
        engine="builtin-extractor",
        engine_version="v3",
        input_hash="unusable-partial-reprocess-v3",
    )
    worker.web_fetcher.fetch = lambda _url: WebFetchResult(
        safe_original_url="https://example.com/partial-lifecycle",
        resolved_url="https://example.com/partial-lifecycle",
        canonical_url="https://example.com/partial-lifecycle",
        content_type="text/html",
        body=(
            b"<html><head><title>Unusable shell</title><script>render()</script></head>"
            b"<body><div>Loading synthetic application shell.</div></body></html>"
        ),
    )
    for _stage in PIPELINE_STAGES[1:]:
        assert worker.run_once(limit=1) == 1

    after_partial = api.get(f"/api/clips/{clip_id}/enrichment", headers=AUTH).json()
    partial_processing = after_partial["processing"]
    assert after_partial["enrichment"]["title"] == "Stable active title"
    assert "Stable active body" in after_partial["enrichment"]["extracted_text"]
    assert partial_processing["latest_attempted_projection"]["extraction_status"] == "partial"
    assert partial_processing["latest_attempted_projection"]["recall_eligible"] is False
    assert partial_processing["latest_successful_projection"] == first_active
    assert partial_processing["active_projection"] == first_active
    assert partial_processing["recall_enrichment_resolution"]["active_enrichment_id"] == first_active_id
    assert partial_processing["active_index"] == first_index
    assert partial_processing["latest_index_attempt"]["status"] == "skipped_no_new_projection"
    assert partial_processing["latest_index_attempt"]["reason"] == "no_new_eligible_projection"
    recall = api.get("/api/recall/overview", headers=AUTH).json()
    public_clip_id = PipelineStore(tmp_path).public_id_for(clip_id)
    memory = next(item for item in recall["highlights"] if item["clip_id"] == public_clip_id)
    assert memory["title"] == "Stable active title"
    assert "Stable active body" in memory["summary"]
    assert adapter.uploads == []

    pipeline.enqueue(
        clip_id=clip_id,
        stage="extract",
        engine="builtin-extractor",
        engine_version="v3",
        input_hash="usable-retry-after-partial-v3",
    )
    worker.web_fetcher.fetch = lambda _url: fetched(
        "Usable retry title", "Usable retry body now advances active content."
    )
    for _stage in PIPELINE_STAGES[1:]:
        assert worker.run_once(limit=1) == 1
    after_retry = api.get(f"/api/clips/{clip_id}/enrichment", headers=AUTH).json()
    assert after_retry["enrichment"]["title"] == "Usable retry title"
    assert after_retry["processing"]["active_projection"]["source_asset_id"] != first_active["source_asset_id"]
    assert after_retry["processing"]["active_index"] == first_index
    assert after_retry["processing"]["latest_index_attempt"]["status"] == "planned"
    retry_recall = api.get("/api/recall/overview", headers=AUTH).json()
    retry_memory = next(item for item in retry_recall["highlights"] if item["clip_id"] == public_clip_id)
    assert retry_memory["title"] == "Usable retry title"
    assert adapter.uploads == []


def test_active_content_without_dataset_can_be_rescheduled_after_mapping(tmp_path):
    settings = worker_settings(tmp_path)
    api = TestClient(create_app(settings))
    target = api.post(
        "/api/knowledge-bases", headers=AUTH, json={"name": "Dataset later"}
    ).json()["knowledge_base"]
    payload = distinct_payload("dataset-added-later")
    payload["routing"]["target_knowledge_base_id"] = target["id"]
    accepted = api.post("/api/ingest/v1/clips", headers=AUTH, json=payload)
    clip_id = int(accepted.json()["clip_id"])
    adapter = RecordingRagflowAdapter()
    worker = PipelineWorker(settings, ragflow_adapter_override=adapter)
    for _stage in PIPELINE_STAGES:
        assert worker.run_once(limit=1) == 1

    first = api.get(f"/api/clips/{clip_id}/processing", headers=AUTH).json()
    active_projection_id = first["projection_state"]["active_projection"]["source_asset_id"]
    assert first["index_state"]["active_index"]["status"] == "not_indexed"
    assert first["index_state"]["active_index"]["projection_id"] == active_projection_id
    assert first["index_state"]["active_index"]["reason"] == "no_dataset_mapping"
    assert first["index_state"]["latest_index_attempt"]["status"] == "skipped_no_dataset_mapping"
    assert adapter.uploads == []

    updated = api.patch(
        f"/api/knowledge-bases/{target['id']}",
        headers=AUTH,
        json={"ragflow_dataset_id": "dataset-added-later", "ragflow_dataset_name": "Added later"},
    )
    assert updated.status_code == 200
    rescheduled = api.post(
        f"/api/clips/{clip_id}/knowledge-bases/{target['id']}", headers=AUTH
    )
    assert rescheduled.status_code == 200
    assert worker.run_once(limit=1) == 1

    final = api.get(f"/api/clips/{clip_id}/processing", headers=AUTH).json()
    assert final["index_state"]["active_index"]["status"] == "not_indexed"
    assert final["index_state"]["active_index"]["projection_id"] == active_projection_id
    assert final["index_state"]["latest_index_attempt"]["status"] == "planned"
    assert adapter.uploads == []


def test_recall_active_enrichment_join_uses_legacy_fallback_only_when_pointer_absent(tmp_path):
    settings = worker_settings(tmp_path)
    api = TestClient(create_app(settings))
    accepted = api.post(
        "/api/ingest/v1/clips", headers=AUTH, json=distinct_payload("recall-active-resolution")
    )
    clip_id = int(accepted.json()["clip_id"])
    worker = PipelineWorker(settings)
    for _stage in PIPELINE_STAGES:
        assert worker.run_once(limit=1) == 1

    active_summary = api.get(f"/api/clips/{clip_id}/processing", headers=AUTH).json()
    assert active_summary["recall_enrichment_resolution"]["status"] == "active"

    database = tmp_path / "perclip.sqlite3"
    with sqlite3.connect(database) as db:
        metadata = json.loads(
            db.execute("select metadata_json from clip_metadata where clip_id=?", (clip_id,)).fetchone()[0]
        )
        metadata["processing"].pop("active_enrichment_id")
        db.execute(
            "update clip_metadata set metadata_json=? where clip_id=?",
            (json.dumps(metadata, ensure_ascii=False, sort_keys=True), clip_id),
        )
    legacy_summary = api.get(f"/api/clips/{clip_id}/processing", headers=AUTH).json()
    assert legacy_summary["recall_enrichment_resolution"]["status"] == "legacy_latest_completed"
    legacy_recall = api.get("/api/recall/overview", headers=AUTH).json()
    public_clip_id = PipelineStore(tmp_path).public_id_for(clip_id)
    assert any(item["clip_id"] == public_clip_id for item in legacy_recall["highlights"])

    with sqlite3.connect(database) as db:
        metadata["processing"]["active_enrichment_id"] = 999999
        db.execute(
            "update clip_metadata set metadata_json=? where clip_id=?",
            (json.dumps(metadata, ensure_ascii=False, sort_keys=True), clip_id),
        )
    broken_summary = api.get(f"/api/clips/{clip_id}/processing", headers=AUTH).json()
    assert broken_summary["recall_enrichment_resolution"] == {
        "status": "missing_active_enrichment",
        "active_enrichment_id": 999999,
        "selected_enrichment_id": None,
    }
    broken_recall = api.get("/api/recall/overview", headers=AUTH).json()
    assert not any(item["clip_id"] == public_clip_id for item in broken_recall["highlights"])
    enrichment = api.get(f"/api/clips/{clip_id}/enrichment", headers=AUTH)
    assert enrichment.status_code == 409
    assert enrichment.json()["detail"] == "active enrichment reference is missing"


def test_failed_job_retry_is_authorized_audited_and_idempotent(tmp_path):
    settings = worker_settings(tmp_path)
    api = TestClient(create_app(settings))
    accepted = api.post("/api/ingest/v1/clips", headers=AUTH, json=strict_text())
    worker = PipelineWorker(settings)
    original = worker._run_stage
    worker._run_stage = lambda _job: (_ for _ in ()).throw(RuntimeError("bad config"))
    assert worker.run_once(limit=1) == 0
    pipeline = PipelineStore(tmp_path)
    failed = pipeline.get_job(1)
    assert failed is not None and failed.status == "failed"

    with pytest.raises(ValueError, match="authorization"):
        pipeline.retry_failed_job(job_id=failed.id, request_id="retry-1")
    reopened, changed = pipeline.retry_failed_job(
        job_id=failed.id, request_id="retry-1", authorized=True
    )
    replay, replay_changed = pipeline.retry_failed_job(
        job_id=failed.id, request_id="retry-1", authorized=True
    )
    assert changed is True and replay_changed is False
    assert reopened.id == replay.id == failed.id
    event = pipeline.list_control_events(clip_id=int(accepted.json()["clip_id"]))[0]
    assert event["previous_status"] == "failed"
    assert event["previous_safe_error_code"] == "pipeline_stage_failed"

    leased = pipeline.claim(limit=1)[0]
    with pytest.raises(ValueError, match="terminal failed"):
        pipeline.retry_failed_job(
            job_id=leased.id, request_id="retry-running", authorized=True
        )
    assert pipeline.fail(leased, safe_error_code="config_still_bad", retryable=False)
    pipeline.retry_failed_job(job_id=leased.id, request_id="retry-2", authorized=True)
    worker._run_stage = original
    assert worker.run_once(limit=1) == 1


def test_planned_index_can_be_promoted_to_real_sync_without_duplicate_upload(tmp_path):
    dry_settings = worker_settings(tmp_path)
    api = TestClient(create_app(dry_settings))
    target = api.post(
        "/api/knowledge-bases",
        headers=AUTH,
        json={"name": "Index target", "ragflow_dataset_id": "dataset-test"},
    ).json()["knowledge_base"]
    payload = distinct_payload("index-promotion")
    payload["routing"]["target_knowledge_base_id"] = target["id"]
    accepted = api.post("/api/ingest/v1/clips", headers=AUTH, json=payload)
    dry_adapter = RecordingRagflowAdapter()
    dry_worker = PipelineWorker(dry_settings, ragflow_adapter_override=dry_adapter)
    for _stage in PIPELINE_STAGES:
        assert dry_worker.run_once(limit=1) == 1
    clip_id = int(accepted.json()["clip_id"])
    pipeline = PipelineStore(tmp_path)
    assert pipeline.find_index_document(
        clip_id=clip_id,
        knowledge_base_id=target["id"],
        index_provider="ragflow",
        dataset_id="dataset-test",
    )["status"] == "planned"

    promoted, changed = pipeline.promote_planned_index(
        clip_id=clip_id, request_id="promote-1", authorized=True
    )
    replay, replay_changed = pipeline.promote_planned_index(
        clip_id=clip_id, request_id="promote-1", authorized=True
    )
    assert changed is True and replay_changed is False and promoted.id == replay.id

    real_settings = Settings(
        data_dir=tmp_path,
        ingest_token="secret",
        processing_mode="worker",
        asset_root=tmp_path / "PersonalClips",
        deployment_environment="isolated-staging",
        ragflow=RagflowSettings(
            base_url="https://ragflow.invalid",
            api_key="fake-key",
            enable_real_sync=True,
            sync_allow_dataset_ids=frozenset({"dataset-test"}),
        ),
    )
    real_adapter = RecordingRagflowAdapter()
    real_worker = PipelineWorker(real_settings, ragflow_adapter_override=real_adapter)
    assert real_worker.run_once(limit=1) == 1
    assert len(real_adapter.uploads) == 1
    assert real_adapter.uploads[0][3] is False
    assert real_adapter.metadata["doc-1"]["topic_ids"] == real_worker.topic_store.active_topic_ids(
        clip_id
    )
    assert real_adapter.metadata["doc-1"]["topic_taxonomy_version"]
    assert real_adapter.metadata["doc-1"]["topic_assignment_generation"]
    indexed = pipeline.find_index_document(
        clip_id=clip_id,
        knowledge_base_id=target["id"],
        index_provider="ragflow",
        dataset_id="dataset-test",
    )
    assert indexed["status"] == "indexed_verified"

    override = api.put(
        f"/api/clips/{clip_id}/topic-assignment",
        headers=AUTH,
        json={"topic_id": "ai_ml"},
    )
    assert override.status_code == 200
    assert real_worker.run_once(limit=1) == 1
    assert len(real_adapter.uploads) == 2
    assert real_adapter.metadata["doc-2"]["topic_ids"] == ["ai_ml"]
    assert (
        real_adapter.metadata["doc-2"]["topic_assignment_generation"]
        == override.json()["topic_assignment"]["assignment_generation"]
    )
    assert pipeline.find_active_index(
        clip_id=clip_id,
        knowledge_base_id=target["id"],
        index_provider="ragflow",
        dataset_id="dataset-test",
    )["document_id"] == "doc-2"

    pipeline.enqueue(
        clip_id=clip_id,
        stage="index",
        engine="ragflow",
        engine_version="v1",
        input_hash="unchanged-content-recheck",
    )
    assert real_worker.run_once(limit=1) == 1
    assert len(real_adapter.uploads) == 2
