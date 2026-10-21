from __future__ import annotations

import json
import sqlite3

import pytest

from perclip_ingest.config import RagflowSettings, Settings
from perclip_ingest.pipeline_store import PipelineStore
from perclip_ingest.ragflow_adapter import (
    RagflowAdapterError,
    RagflowDocumentRef,
    RagflowUnsupportedError,
)
from perclip_ingest.ragflow_index import (
    RagflowChunkSummary,
    RagflowDocumentMatch,
    RagflowDocumentStatus,
    RagflowVectorEvidence,
    build_index_metadata,
)
from perclip_ingest.storage import ClipStore
from perclip_ingest.worker import PipelineWorker


class ScriptedAdapter:
    def __init__(self) -> None:
        self.lookup_responses: list[list[RagflowDocumentMatch]] = [[]]
        self.statuses = ["unstart", "running", "done"]
        self.upload_error: Exception | None = None
        self.parse_error: Exception | None = None
        self.verification_error: Exception | None = None
        self.chunk_count = 2
        self.vector_count = 2
        self.uploads = 0
        self.parse_requests = 0
        self.metadata: dict[str, object] = {}

    def find_document_by_operation_key(self, dataset_id, operation_key):
        if len(self.lookup_responses) > 1:
            return self.lookup_responses.pop(0)
        return self.lookup_responses[0]

    def upload_document(
        self, dataset_id, name, content_or_path, meta_fields=None, dry_run=True
    ):
        self.uploads += 1
        if self.upload_error:
            raise self.upload_error
        return RagflowDocumentRef(
            dataset_id, "doc-new", name, meta_fields or {}, dry_run=False
        )

    def update_document_meta(
        self, dataset_id, document_id, meta_fields, dry_run=True
    ):
        self.metadata = dict(meta_fields)
        return {"ok": True}

    def request_parse(self, dataset_id, document_id):
        self.parse_requests += 1
        if self.parse_error:
            raise self.parse_error

    def get_document_status(self, dataset_id, document_id):
        value = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return RagflowDocumentStatus(document_id, value, self.metadata)

    def get_chunk_summary(self, dataset_id, document_id):
        if self.verification_error:
            raise self.verification_error
        return RagflowChunkSummary(document_id, self.chunk_count)

    def get_vector_evidence(self, dataset_id, document_id):
        if self.verification_error:
            raise self.verification_error
        return RagflowVectorEvidence(document_id, self.vector_count)


def initialize_clip(tmp_path) -> None:
    ClipStore(tmp_path).init()
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.execute(
            """
            insert into clips(
                id, client_request_id, source_type, title_hint, note, text, url,
                mime_type, device_name, source_app, captured_at, filename,
                size_bytes, original_path, content_hash, created_at
            ) values (1, 'request', 'text', '', '', 'body', '', 'text/plain',
                '', 'test', '2026-01-01T00:00:00Z', '', 0, '', 'hash',
                '2026-01-01T00:00:00Z')
            """
        )


def worker_and_attempt(tmp_path, adapter, *, key: str = "a" * 64):
    initialize_clip(tmp_path)
    settings = Settings(
        data_dir=tmp_path,
        ingest_token="secret",
        ragflow=RagflowSettings(
            base_url="http://ragflow",
            api_key="key",
            enable_real_sync=True,
            sync_allow_dataset_ids=frozenset({"dataset"}),
            index_poll_timeout_seconds=0.01,
            index_poll_backoff_seconds=0.001,
        ),
    )
    worker = PipelineWorker(settings, ragflow_adapter_override=adapter, sleep=lambda _: None)
    metadata = build_index_metadata(
        clip_public_id="pc_1",
        generation_public_id="gen_1",
        knowledge_base_id="kb",
        topic_ids=[],
        source_type="text",
        language="",
        quality_status="completed",
        content_hash="b" * 64,
        operation_key=key,
    )
    worker.pipeline.ensure_index_attempt(
        operation_key=key,
        clip_id=1,
        knowledge_base_id="kb",
        index_provider="ragflow",
        dataset_id="dataset",
        generation_id="gen_1",
        content_hash="b" * 64,
        metadata_json=json.dumps(metadata),
        status="planned",
    )
    return worker, metadata


def run_index(worker, metadata, key: str = "a" * 64):
    worker._index_one(
        dataset_id="dataset",
        operation_key=key,
        public_id="pc_1",
        content_or_path="content",
        metadata=metadata,
    )


def test_upload_parse_poll_and_verify_are_persisted_before_activation(tmp_path):
    adapter = ScriptedAdapter()
    worker, metadata = worker_and_attempt(tmp_path, adapter)
    run_index(worker, metadata)
    attempt = worker.pipeline.find_index_attempt(operation_key="a" * 64)
    active = worker.pipeline.find_active_index(
        clip_id=1,
        knowledge_base_id="kb",
        index_provider="ragflow",
        dataset_id="dataset",
    )
    assert attempt["status"] == "indexed_verified"
    assert attempt["remote_status"] == "done"
    assert attempt["chunk_count"] == attempt["vector_count"] == 2
    assert active["operation_key"] == "a" * 64
    assert adapter.uploads == adapter.parse_requests == 1


def test_unknown_upload_outcome_recovers_one_remote_match_without_second_upload(tmp_path):
    adapter = ScriptedAdapter()
    adapter.upload_error = RagflowAdapterError("timeout")
    adapter.lookup_responses = [
        [],
        [RagflowDocumentMatch("doc-recovered", "a" * 64, {})],
    ]
    adapter.statuses = ["done"]
    worker, metadata = worker_and_attempt(tmp_path, adapter)
    run_index(worker, metadata)
    attempt = worker.pipeline.find_index_attempt(operation_key="a" * 64)
    assert attempt["document_id"] == "doc-recovered"
    assert attempt["status"] == "indexed_verified"
    assert adapter.uploads == 1


def test_restart_after_remote_upload_before_local_commit_recovers_without_upload(tmp_path):
    adapter = ScriptedAdapter()
    adapter.lookup_responses = [
        [RagflowDocumentMatch("doc-after-crash", "a" * 64, {})]
    ]
    adapter.statuses = ["done"]
    worker, metadata = worker_and_attempt(tmp_path, adapter)
    worker.pipeline.update_index_attempt(
        operation_key="a" * 64, status="uploading"
    )
    run_index(worker, metadata)
    attempt = worker.pipeline.find_index_attempt(operation_key="a" * 64)
    assert attempt["document_id"] == "doc-after-crash"
    assert attempt["status"] == "indexed_verified"
    assert adapter.uploads == 0


def test_multiple_remote_operation_matches_fail_terminal_without_deletion(tmp_path):
    adapter = ScriptedAdapter()
    adapter.lookup_responses = [
        [
            RagflowDocumentMatch("doc-1", "a" * 64, {}),
            RagflowDocumentMatch("doc-2", "a" * 64, {}),
        ]
    ]
    worker, metadata = worker_and_attempt(tmp_path, adapter)
    with pytest.raises(ValueError, match="ambiguous"):
        run_index(worker, metadata)
    attempt = worker.pipeline.find_index_attempt(operation_key="a" * 64)
    assert attempt["status"] == "failed_terminal"
    assert attempt["safe_error_code"] == "remote_operation_ambiguous"
    assert adapter.uploads == 0


def test_parse_failure_is_retryable_and_retry_checks_status_before_parse(tmp_path):
    adapter = ScriptedAdapter()
    adapter.parse_error = RagflowAdapterError("parse unavailable")
    worker, metadata = worker_and_attempt(tmp_path, adapter)
    with pytest.raises(RagflowAdapterError):
        run_index(worker, metadata)
    assert worker.pipeline.find_index_attempt(operation_key="a" * 64)["status"] == (
        "failed_retryable"
    )
    adapter.parse_error = None
    adapter.statuses = ["done"]
    run_index(worker, metadata)
    assert adapter.uploads == 1
    assert adapter.parse_requests == 1


def test_done_without_chunks_fails_terminal_and_keeps_old_active_index(tmp_path):
    adapter = ScriptedAdapter()
    worker, metadata = worker_and_attempt(tmp_path, adapter)
    old_key = "f" * 64
    worker.pipeline.ensure_index_attempt(
        operation_key=old_key,
        clip_id=1,
        knowledge_base_id="kb",
        index_provider="ragflow",
        dataset_id="dataset",
        generation_id="gen_old",
        content_hash="c" * 64,
        metadata_json="{}",
        status="indexed_verified",
    )
    worker.pipeline.update_index_attempt(
        operation_key=old_key,
        status="indexed_verified",
        document_id="doc-old",
        remote_status="done",
        chunk_count=1,
        vector_count=1,
    )
    worker.pipeline.activate_verified_index(operation_key=old_key)
    adapter.statuses = ["done"]
    adapter.chunk_count = 0
    with pytest.raises(ValueError, match="without_chunks"):
        run_index(worker, metadata)
    active = worker.pipeline.find_active_index(
        clip_id=1,
        knowledge_base_id="kb",
        index_provider="ragflow",
        dataset_id="dataset",
    )
    assert active["operation_key"] == old_key
    assert worker.pipeline.find_index_attempt(operation_key="a" * 64)["status"] == (
        "failed_terminal"
    )


def test_poll_timeout_is_retryable_and_remote_failed_is_terminal(tmp_path):
    adapter = ScriptedAdapter()
    adapter.statuses = ["running"]
    worker, metadata = worker_and_attempt(tmp_path, adapter)
    with pytest.raises(RagflowAdapterError, match="timeout"):
        run_index(worker, metadata)
    assert worker.pipeline.find_index_attempt(operation_key="a" * 64)["status"] == (
        "failed_retryable"
    )

    other_tmp = tmp_path / "other"
    other_tmp.mkdir()
    failed_adapter = ScriptedAdapter()
    failed_adapter.statuses = ["failed"]
    failed_worker, failed_metadata = worker_and_attempt(other_tmp, failed_adapter)
    with pytest.raises(ValueError, match="remote_status_failed"):
        run_index(failed_worker, failed_metadata)
    assert failed_worker.pipeline.find_index_attempt(operation_key="a" * 64)["status"] == (
        "failed_terminal"
    )


def test_unsupported_verification_fails_closed(tmp_path):
    adapter = ScriptedAdapter()
    adapter.statuses = ["done"]
    adapter.verification_error = RagflowUnsupportedError("unsupported")
    worker, metadata = worker_and_attempt(tmp_path, adapter)
    with pytest.raises(RagflowUnsupportedError):
        run_index(worker, metadata)
    attempt = worker.pipeline.find_index_attempt(operation_key="a" * 64)
    assert attempt["status"] == "failed_terminal"
    assert attempt["safe_error_code"] == "remote_verification_unsupported"
