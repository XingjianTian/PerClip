from __future__ import annotations

import json
import sqlite3

import pytest

from perclip_ingest.pipeline_store import PipelineStore
from perclip_ingest.knowledge_base_store import KnowledgeBaseStore
from perclip_ingest.storage import ClipStore
from perclip_ingest.ragflow_index import (
    INDEX_CONTRACT_VERSION,
    RagflowChunkSummary,
    RagflowDocumentStatus,
    RagflowVectorEvidence,
    build_cleanup_manifest,
    build_index_metadata,
    build_operation_key,
    cleanup_index_document,
    deletion_is_verified,
    deterministic_document_name,
    verify_asset_manifest,
    verify_index,
)


def metadata(operation_key: str = "a" * 64) -> dict[str, object]:
    return build_index_metadata(
        clip_public_id="pc_abc",
        generation_public_id="gen_abc",
        knowledge_base_id="kb-safe",
        topic_ids=["topic-b", "topic-a", "topic-a"],
        source_type="text",
        language="",
        quality_status="completed",
        content_hash="b" * 64,
        operation_key=operation_key,
    )


def initialize_store(tmp_path) -> PipelineStore:
    ClipStore(tmp_path).init()
    KnowledgeBaseStore(tmp_path).init()
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
    store = PipelineStore(tmp_path)
    store.init()
    return store


def test_index_attempt_schema_migrates_to_association_scoped_idempotency(tmp_path):
    ClipStore(tmp_path).init()
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.executescript(
            """
            create table index_attempts (
                operation_key text primary key,
                clip_id integer not null,
                knowledge_base_id text not null,
                index_provider text not null,
                dataset_id text not null,
                generation_id text not null,
                document_id text not null default '',
                content_hash text not null,
                status text not null,
                remote_status text not null default 'unknown',
                chunk_count integer not null default 0,
                vector_count integer not null default 0,
                metadata_json text not null,
                safe_error_code text not null default '',
                created_at text not null,
                updated_at text not null,
                unique (
                    clip_id, knowledge_base_id, index_provider, dataset_id,
                    generation_id, content_hash
                )
            );
            create table active_indexes (
                clip_id integer not null,
                knowledge_base_id text not null,
                index_provider text not null,
                dataset_id text not null,
                operation_key text not null,
                document_id text not null,
                generation_id text not null,
                content_hash text not null,
                activated_at text not null,
                primary key (
                    clip_id, knowledge_base_id, index_provider, dataset_id
                )
            );
            """
        )
    store = PipelineStore(tmp_path)
    store.init()
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        columns = {
            row[1] for row in db.execute("pragma table_info(index_attempts)")
        }
    assert "association_intent_id" in columns


def test_detach_invalidates_active_index_and_reassociation_is_new_intent(tmp_path):
    store = initialize_store(tmp_path)
    knowledge_base = KnowledgeBaseStore(tmp_path).create_knowledge_base(
        name="Isolated test",
        ragflow_dataset_id="private-dataset-id",
    )
    store.associate_knowledge_base(
        clip_id=1, knowledge_base_id=knowledge_base.id
    )
    first_association = store.list_knowledge_base_associations(clip_id=1)[0]
    old_key = build_operation_key(
        provider="ragflow",
        dataset_id="private-dataset-id",
        clip_public_id="pc_abc",
        generation_public_id="gen_abc",
        content_hash="b" * 64,
        association_intent_id=str(first_association["association_intent_id"]),
    )
    store.ensure_index_attempt(
        operation_key=old_key,
        clip_id=1,
        knowledge_base_id=knowledge_base.id,
        index_provider="ragflow",
        dataset_id="private-dataset-id",
        association_intent_id=str(first_association["association_intent_id"]),
        generation_id="gen_abc",
        content_hash="b" * 64,
        metadata_json="{}",
        status="indexed_verified",
    )
    store.update_index_attempt(
        operation_key=old_key,
        status="indexed_verified",
        document_id="private-document-id",
        remote_status="done",
        chunk_count=2,
        vector_count=2,
    )
    store.activate_verified_index(operation_key=old_key)

    assert store.remove_knowledge_base_association(
        clip_id=1, knowledge_base_id=knowledge_base.id
    )
    assert store.find_active_index(
        clip_id=1,
        knowledge_base_id=knowledge_base.id,
        index_provider="ragflow",
        dataset_id="private-dataset-id",
    ) is None
    assert store.find_index_attempt(operation_key=old_key)["status"] == (
        "detached_pending_cleanup"
    )
    assert store.find_index_document(
        clip_id=1,
        knowledge_base_id=knowledge_base.id,
        index_provider="ragflow",
        dataset_id="private-dataset-id",
    )["status"] == "detached_pending_cleanup"

    store.associate_knowledge_base(
        clip_id=1, knowledge_base_id=knowledge_base.id
    )
    second_association = store.list_knowledge_base_associations(clip_id=1)[0]
    new_key = build_operation_key(
        provider="ragflow",
        dataset_id="private-dataset-id",
        clip_public_id="pc_abc",
        generation_public_id="gen_abc",
        content_hash="b" * 64,
        association_intent_id=str(second_association["association_intent_id"]),
    )
    assert second_association["association_intent_id"] != (
        first_association["association_intent_id"]
    )
    assert new_key != old_key
    assert store.find_active_index(
        clip_id=1,
        knowledge_base_id=knowledge_base.id,
        index_provider="ragflow",
        dataset_id="private-dataset-id",
    ) is None
    store.ensure_index_attempt(
        operation_key=new_key,
        clip_id=1,
        knowledge_base_id=knowledge_base.id,
        index_provider="ragflow",
        dataset_id="private-dataset-id",
        association_intent_id=str(second_association["association_intent_id"]),
        generation_id="gen_abc",
        content_hash="b" * 64,
        metadata_json="{}",
        status="indexed_verified",
    )
    store.update_index_attempt(
        operation_key=new_key,
        status="indexed_verified",
        document_id="private-new-document-id",
        remote_status="done",
        chunk_count=2,
        vector_count=2,
    )
    store.activate_verified_index(operation_key=new_key)
    store.finalize_index_deletion(operation_key=old_key)
    assert store.find_index_attempt(operation_key=old_key)["status"] == (
        "deleted_verified"
    )
    assert store.find_active_index(
        clip_id=1,
        knowledge_base_id=knowledge_base.id,
        index_provider="ragflow",
        dataset_id="private-dataset-id",
    )["operation_key"] == new_key
    assert store.find_index_document(
        clip_id=1,
        knowledge_base_id=knowledge_base.id,
        index_provider="ragflow",
        dataset_id="private-dataset-id",
    )["document_id"] == "private-new-document-id"


def test_operation_key_and_document_name_are_deterministic_and_scope_sensitive():
    kwargs = {
        "provider": "ragflow",
        "dataset_id": "dataset-a",
        "clip_public_id": "pc_abc",
        "generation_public_id": "gen_abc",
        "content_hash": "b" * 64,
    }
    first = build_operation_key(**kwargs)
    assert first == build_operation_key(**kwargs)
    assert first != build_operation_key(**{**kwargs, "dataset_id": "dataset-b"})
    assert first != build_operation_key(**{**kwargs, "generation_public_id": "gen_new"})
    assert deterministic_document_name("pc_abc", first) == f"pc_abc-{first}.md"


def test_metadata_contract_is_complete_canonical_and_private_field_free():
    value = metadata()
    assert value == {
        "perclip_clip_id": "pc_abc",
        "perclip_generation": "gen_abc",
        "knowledge_base_id": "kb-safe",
        "topic_ids": ["topic-a", "topic-b"],
        "topic_taxonomy_version": "",
        "topic_assignment_generation": "",
        "source_type": "text",
        "language": "",
        "quality_status": "completed",
        "content_hash": "b" * 64,
        "operation_key": "a" * 64,
        "index_contract_version": INDEX_CONTRACT_VERSION,
    }
    serialized = json.dumps(value)
    for forbidden in ("/Users/", "https://", "token", "device_id", "sqlite"):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("remote_status", "chunks", "vectors", "expected"),
    [
        ("done", 1, 1, (True, "")),
        ("done", 0, 1, (False, "remote_done_without_chunks")),
        ("done", 1, 0, (False, "remote_done_without_vectors")),
        ("running", 1, 1, (False, "remote_status_running")),
        ("failed", 1, 1, (False, "remote_status_failed")),
    ],
)
def test_verified_index_requires_done_chunks_vectors_and_metadata(
    remote_status, chunks, vectors, expected
):
    expected_metadata = metadata()
    result = verify_index(
        status=RagflowDocumentStatus("doc", remote_status, expected_metadata),
        chunks=RagflowChunkSummary("doc", chunks),
        vectors=RagflowVectorEvidence("doc", vectors),
        expected_metadata=expected_metadata,
    )
    assert (result.verified, result.safe_error_code) == expected


def test_verified_index_rejects_generation_or_operation_mismatch():
    expected = metadata()
    actual = {**expected, "perclip_generation": "gen_other"}
    result = verify_index(
        status=RagflowDocumentStatus("doc", "done", actual),
        chunks=RagflowChunkSummary("doc", 2),
        vectors=RagflowVectorEvidence("doc", 2),
        expected_metadata=expected,
    )
    assert result.safe_error_code == "remote_metadata_mismatch"


@pytest.mark.parametrize(
    ("chunks", "vectors", "covered", "error"),
    [
        (10, 1, 10, "remote_vector_count_mismatch"),
        (10, 9, 10, "remote_vector_count_mismatch"),
        (10, 11, 10, "remote_vector_count_mismatch"),
        (10, 10, 1, "remote_vector_coverage_incomplete"),
    ],
)
def test_verified_index_requires_exact_complete_vector_coverage(
    chunks, vectors, covered, error
):
    expected = metadata()
    result = verify_index(
        status=RagflowDocumentStatus("doc", "done", expected),
        chunks=RagflowChunkSummary("doc", chunks),
        vectors=RagflowVectorEvidence(
            "doc", vectors, covered_chunk_count=covered
        ),
        expected_metadata=expected,
    )
    assert (result.verified, result.safe_error_code) == (False, error)


def test_verified_index_checks_every_metadata_contract_field():
    expected = metadata()
    for field in expected:
        actual = dict(expected)
        actual[field] = ["different"] if isinstance(actual[field], list) else "different"
        result = verify_index(
            status=RagflowDocumentStatus("doc", "done", actual),
            chunks=RagflowChunkSummary("doc", 1),
            vectors=RagflowVectorEvidence("doc", 1, covered_chunk_count=1),
            expected_metadata=expected,
        )
        assert result.safe_error_code == "remote_metadata_mismatch"


def test_attempt_and_active_index_are_separate_and_only_verified_can_activate(tmp_path):
    store = initialize_store(tmp_path)
    operation_key = "a" * 64
    store.ensure_index_attempt(
        operation_key=operation_key,
        clip_id=1,
        knowledge_base_id="kb",
        index_provider="ragflow",
        dataset_id="dataset",
        generation_id="gen_1",
        content_hash="b" * 64,
        metadata_json=json.dumps(metadata(operation_key)),
        status="uploaded",
    )
    with pytest.raises(ValueError, match="verified"):
        store.activate_verified_index(operation_key=operation_key)
    assert store.find_active_index(
        clip_id=1,
        knowledge_base_id="kb",
        index_provider="ragflow",
        dataset_id="dataset",
    ) is None
    store.update_index_attempt(
        operation_key=operation_key,
        status="indexed_verified",
        document_id="doc-1",
        remote_status="done",
        chunk_count=2,
        vector_count=2,
    )
    store.activate_verified_index(operation_key=operation_key)
    assert store.find_active_index(
        clip_id=1,
        knowledge_base_id="kb",
        index_provider="ragflow",
        dataset_id="dataset",
    )["operation_key"] == operation_key


def test_attempt_store_rejects_unrecognized_state_and_invalid_evidence(tmp_path):
    store = initialize_store(tmp_path)
    with pytest.raises(ValueError, match="local index status"):
        store.ensure_index_attempt(
            operation_key="a" * 64,
            clip_id=1,
            knowledge_base_id="kb",
            index_provider="ragflow",
            dataset_id="dataset",
            generation_id="gen_1",
            content_hash="b" * 64,
            metadata_json="{}",
            status="indexed",
        )
    store.ensure_index_attempt(
        operation_key="a" * 64,
        clip_id=1,
        knowledge_base_id="kb",
        index_provider="ragflow",
        dataset_id="dataset",
        generation_id="gen_1",
        content_hash="b" * 64,
        metadata_json="{}",
        status="planned",
    )
    with pytest.raises(ValueError, match="evidence count"):
        store.update_index_attempt(
            operation_key="a" * 64,
            status="parsing",
            chunk_count=-1,
        )


def test_historical_indexed_compatibility_row_is_not_active_or_verified(tmp_path):
    store = initialize_store(tmp_path)
    store.upsert_index_document(
        clip_id=1,
        knowledge_base_id="kb",
        index_provider="ragflow",
        dataset_id="dataset",
        document_id="legacy-doc",
        content_hash="b" * 64,
        status="indexed",
    )
    assert store.find_index_document(
        clip_id=1,
        knowledge_base_id="kb",
        index_provider="ragflow",
        dataset_id="dataset",
    )["status"] == "indexed"
    assert store.find_active_index(
        clip_id=1,
        knowledge_base_id="kb",
        index_provider="ragflow",
        dataset_id="dataset",
    ) is None


class CleanupAdapter:
    def __init__(self, *, verified: bool = True) -> None:
        self.deleted: list[tuple[str, str]] = []
        self.verified = verified

    def request_delete(self, dataset_id, document_id):
        self.deleted.append((dataset_id, document_id))

    def verify_deleted(self, dataset_id, document_id):
        if self.verified:
            return (
                RagflowDocumentStatus(document_id, "missing", {}),
                RagflowChunkSummary(document_id, 0),
                RagflowVectorEvidence(document_id, 0),
            )
        return (
            RagflowDocumentStatus(document_id, "missing", {}),
            RagflowChunkSummary(document_id, 1),
            RagflowVectorEvidence(document_id, 1),
        )


def cleanup_store(tmp_path) -> tuple[PipelineStore, str]:
    store = initialize_store(tmp_path)
    operation_key = "c" * 64
    store.ensure_index_attempt(
        operation_key=operation_key,
        clip_id=1,
        knowledge_base_id="kb",
        index_provider="ragflow",
        dataset_id="dataset",
        generation_id="gen_1",
        content_hash="b" * 64,
        metadata_json="{}",
        status="detached_pending_cleanup",
    )
    store.update_index_attempt(
        operation_key=operation_key,
        status="detached_pending_cleanup",
        document_id="private-document-id",
    )
    return store, operation_key


def test_cleanup_dry_run_is_manifest_only_and_redacts_document_id(tmp_path):
    store, operation_key = cleanup_store(tmp_path)
    adapter = CleanupAdapter()
    manifest = cleanup_index_document(
        store=store,
        adapter=adapter,
        operation_key=operation_key,
        allowed_dataset_ids=frozenset({"dataset"}),
    )
    assert adapter.deleted == []
    assert manifest["schema"] == "perclip-ragflow-cleanup.v1"
    encoded = json.dumps(manifest)
    for private_value in ("private-document-id", '"dataset"', operation_key):
        assert private_value not in encoded


def test_cleanup_requires_authorization_allowlist_and_full_delete_evidence(tmp_path):
    store, operation_key = cleanup_store(tmp_path)
    adapter = CleanupAdapter(verified=False)
    with pytest.raises(ValueError, match="authorization"):
        cleanup_index_document(
            store=store,
            adapter=adapter,
            operation_key=operation_key,
            allowed_dataset_ids=frozenset({"dataset"}),
            dry_run=False,
        )
    with pytest.raises(ValueError, match="allowlisted"):
        cleanup_index_document(
            store=store,
            adapter=adapter,
            operation_key=operation_key,
            allowed_dataset_ids=frozenset(),
            dry_run=False,
            authorized=True,
        )
    with pytest.raises(ValueError, match="not_verified"):
        cleanup_index_document(
            store=store,
            adapter=adapter,
            operation_key=operation_key,
            allowed_dataset_ids=frozenset({"dataset"}),
            dry_run=False,
            authorized=True,
        )
    assert store.find_index_attempt(operation_key=operation_key)["status"] == (
        "detached_pending_cleanup"
    )
    adapter.verified = True
    cleanup_index_document(
        store=store,
        adapter=adapter,
        operation_key=operation_key,
        allowed_dataset_ids=frozenset({"dataset"}),
        dry_run=False,
        authorized=True,
    )
    assert store.find_index_attempt(operation_key=operation_key)["status"] == "deleted_verified"
    delete_count = len(adapter.deleted)
    cleanup_index_document(
        store=store,
        adapter=adapter,
        operation_key=operation_key,
        allowed_dataset_ids=frozenset({"dataset"}),
        dry_run=False,
        authorized=True,
    )
    assert len(adapter.deleted) == delete_count


def test_deletion_requires_document_chunks_and_vectors_to_be_absent():
    assert deletion_is_verified(
        RagflowDocumentStatus("doc", "missing", {}),
        RagflowChunkSummary("doc", 0),
        RagflowVectorEvidence("doc", 0),
    )
    assert not deletion_is_verified(
        RagflowDocumentStatus("doc", "missing", {}),
        RagflowChunkSummary("doc", 1),
        RagflowVectorEvidence("doc", 0),
    )


def test_asset_verifier_returns_only_read_only_counts_and_hash_aliases(tmp_path):
    first = tmp_path / "secret-first.md"
    second = tmp_path / "secret-second.md"
    first.write_text("same")
    second.write_text("same")
    result = verify_asset_manifest(
        [
            {
                "source_asset_reference": "/Users/alice/private/secret-first.md#row-17",
                "role": "clean_markdown",
                "content_hash": "hash",
                "storage_uri": str(first),
            },
            {
                "source_asset_reference": "internal-row-22-secret-second.md",
                "role": "clean_markdown",
                "content_hash": "hash",
                "storage_uri": str(second),
            },
            {
                "source_asset_reference": "unsafe-source-asset-ref",
                "role": "original",
                "content_hash": "missing",
                "storage_uri": str(tmp_path / "private-missing-name"),
            },
        ]
    )
    encoded = json.dumps(result)
    assert result["asset_count"] == 3
    assert result["missing_count"] == 1
    assert result["duplicate_hash_count"] == 2
    assert "secret-first" not in encoded
    assert "private-missing-name" not in encoded
    assert "same" not in encoded
    assert "/Users/alice" not in encoded
    assert "internal-row-22" not in encoded
    assert "unsafe-source-asset-ref" not in encoded
