from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol


INDEX_CONTRACT_VERSION = "perclip-ragflow-index.v1"
REMOTE_DOCUMENT_STATUSES = frozenset(
    {"unstart", "running", "scheduled", "done", "failed", "cancelled", "missing", "unknown"}
)
LOCAL_INDEX_STATUSES = frozenset(
    {
        "planned",
        "uploading",
        "uploaded",
        "parse_requested",
        "parsing",
        "indexed_verified",
        "failed_retryable",
        "failed_terminal",
        "detached_pending_cleanup",
        "deleted_verified",
    }
)


@dataclass(frozen=True)
class RagflowDocumentMatch:
    document_id: str
    operation_key: str
    meta_fields: Mapping[str, Any]


@dataclass(frozen=True)
class RagflowDocumentStatus:
    document_id: str
    status: str
    meta_fields: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.status not in REMOTE_DOCUMENT_STATUSES:
            raise ValueError("unsupported RAGFlow document status")


@dataclass(frozen=True)
class RagflowChunkSummary:
    document_id: str
    chunk_count: int

    def __post_init__(self) -> None:
        if isinstance(self.chunk_count, bool) or self.chunk_count < 0:
            raise ValueError("invalid RAGFlow chunk count")


@dataclass(frozen=True)
class RagflowVectorEvidence:
    document_id: str
    vector_count: int
    covered_chunk_count: int | None = None
    evidence_type: str = "explicit_chunk_vector_flag"

    def __post_init__(self) -> None:
        if isinstance(self.vector_count, bool) or self.vector_count < 0:
            raise ValueError("invalid RAGFlow vector count")
        if (
            self.covered_chunk_count is not None
            and (
                isinstance(self.covered_chunk_count, bool)
                or self.covered_chunk_count < 0
            )
        ):
            raise ValueError("invalid RAGFlow vector coverage")

    @property
    def present(self) -> bool:
        return self.vector_count > 0

    @property
    def coverage_count(self) -> int:
        return (
            self.vector_count
            if self.covered_chunk_count is None
            else self.covered_chunk_count
        )


@dataclass(frozen=True)
class IndexVerification:
    verified: bool
    safe_error_code: str


def canonical_content_hash(content: str | bytes) -> str:
    payload = content if isinstance(content, bytes) else content.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_operation_key(
    *,
    provider: str,
    dataset_id: str,
    clip_public_id: str,
    generation_public_id: str,
    content_hash: str,
    association_intent_id: str = "",
    index_contract_version: str = INDEX_CONTRACT_VERSION,
) -> str:
    material = "\0".join(
        (
            provider.strip(),
            dataset_id.strip(),
            clip_public_id.strip(),
            generation_public_id.strip(),
            content_hash.strip().lower(),
            association_intent_id.strip(),
            index_contract_version,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def deterministic_document_name(clip_public_id: str, operation_key: str) -> str:
    return f"{clip_public_id}-{operation_key}.md"


def build_index_metadata(
    *,
    clip_public_id: str,
    generation_public_id: str,
    knowledge_base_id: str,
    topic_ids: Iterable[str],
    source_type: str,
    language: str,
    quality_status: str,
    content_hash: str,
    operation_key: str,
    topic_taxonomy_version: str = "",
    topic_assignment_generation: str = "",
) -> dict[str, Any]:
    if source_type not in {"text", "url", "file", "image", "audio"}:
        raise ValueError("unsupported index source type")
    if quality_status not in {"completed", "partial"}:
        raise ValueError("unsupported index quality status")
    return {
        "perclip_clip_id": clip_public_id,
        "perclip_generation": generation_public_id,
        "knowledge_base_id": knowledge_base_id,
        "topic_ids": sorted({str(item) for item in topic_ids if str(item)}),
        "topic_taxonomy_version": str(topic_taxonomy_version),
        "topic_assignment_generation": str(topic_assignment_generation),
        "source_type": source_type,
        "language": language,
        "quality_status": quality_status,
        "content_hash": content_hash,
        "operation_key": operation_key,
        "index_contract_version": INDEX_CONTRACT_VERSION,
    }


def verify_index(
    *,
    status: RagflowDocumentStatus,
    chunks: RagflowChunkSummary,
    vectors: RagflowVectorEvidence,
    expected_metadata: Mapping[str, Any],
) -> IndexVerification:
    if status.status != "done":
        return IndexVerification(False, f"remote_status_{status.status}")
    if chunks.chunk_count <= 0:
        return IndexVerification(False, "remote_done_without_chunks")
    if not vectors.present:
        return IndexVerification(False, "remote_done_without_vectors")
    if vectors.coverage_count != chunks.chunk_count:
        return IndexVerification(False, "remote_vector_coverage_incomplete")
    if vectors.vector_count != chunks.chunk_count:
        return IndexVerification(False, "remote_vector_count_mismatch")
    for field in expected_metadata:
        if status.meta_fields.get(field) != expected_metadata.get(field):
            return IndexVerification(False, "remote_metadata_mismatch")
    return IndexVerification(True, "")


def safe_hash_alias(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_cleanup_manifest(
    *,
    dataset_id: str,
    document_id: str,
    operation_key: str,
    before_status: str,
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "schema": "perclip-ragflow-cleanup.v1",
        "dry_run": bool(dry_run),
        "target": {
            "dataset_alias": safe_hash_alias(dataset_id),
            "document_id_alias": safe_hash_alias(document_id),
            "operation_alias": safe_hash_alias(operation_key),
        },
        "before": {"local_status": before_status},
        "after": {
            "required_local_status": "deleted_verified",
            "document_status": "missing",
            "chunk_count": 0,
            "vector_count": 0,
        },
    }


class CleanupStore(Protocol):
    def find_index_attempt(self, *, operation_key: str) -> dict[str, object] | None:
        ...

    def update_index_attempt(
        self,
        *,
        operation_key: str,
        status: str,
        document_id: str | None = None,
        remote_status: str | None = None,
        chunk_count: int | None = None,
        vector_count: int | None = None,
        safe_error_code: str | None = None,
    ) -> dict[str, object]:
        ...

    def finalize_index_deletion(self, *, operation_key: str) -> None:
        ...


class CleanupAdapter(Protocol):
    def request_delete(self, dataset_id: str, document_id: str) -> None:
        ...

    def verify_deleted(
        self, dataset_id: str, document_id: str
    ) -> tuple[RagflowDocumentStatus, RagflowChunkSummary, RagflowVectorEvidence]:
        ...


def cleanup_index_document(
    *,
    store: CleanupStore,
    adapter: CleanupAdapter,
    operation_key: str,
    allowed_dataset_ids: frozenset[str],
    dry_run: bool = True,
    authorized: bool = False,
) -> dict[str, Any]:
    attempt = store.find_index_attempt(operation_key=operation_key)
    if attempt is None:
        raise ValueError("index cleanup target not found")
    dataset_id = str(attempt["dataset_id"])
    document_id = str(attempt["document_id"])
    before_status = str(attempt["status"])
    manifest = build_cleanup_manifest(
        dataset_id=dataset_id,
        document_id=document_id,
        operation_key=operation_key,
        before_status=before_status,
        dry_run=dry_run,
    )
    if dry_run:
        return manifest
    if not authorized:
        raise ValueError("index cleanup authorization required")
    if dataset_id not in allowed_dataset_ids:
        raise ValueError("index cleanup dataset is not allowlisted")
    if not document_id:
        raise ValueError("index cleanup document id is missing")
    if before_status == "deleted_verified":
        return manifest
    if before_status != "detached_pending_cleanup":
        raise ValueError("index cleanup target is not detached")
    adapter.request_delete(dataset_id, document_id)
    status, chunks, vectors = adapter.verify_deleted(dataset_id, document_id)
    if not deletion_is_verified(status, chunks, vectors):
        store.update_index_attempt(
            operation_key=operation_key,
            status="detached_pending_cleanup",
            remote_status=status.status,
            chunk_count=chunks.chunk_count,
            vector_count=vectors.vector_count,
            safe_error_code="remote_delete_not_verified",
        )
        raise ValueError("remote_delete_not_verified")
    store.finalize_index_deletion(operation_key=operation_key)
    return manifest


def deletion_is_verified(
    status: RagflowDocumentStatus,
    chunks: RagflowChunkSummary,
    vectors: RagflowVectorEvidence,
) -> bool:
    return status.status == "missing" and chunks.chunk_count == 0 and vectors.vector_count == 0


def verify_asset_manifest(assets: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seen_hashes: dict[str, int] = {}
    for asset in assets:
        reference = str(asset.get("source_asset_reference") or "")
        role = str(asset.get("role") or "")
        content_hash = str(asset.get("content_hash") or "")
        storage_uri = str(asset.get("storage_uri") or "")
        path = Path(storage_uri)
        readable = bool(storage_uri) and path.is_file() and os.access(path, os.R_OK)
        actual_size = path.stat().st_size if readable else 0
        actual_hash = file_sha256(path) if readable else ""
        missing = not readable
        if actual_hash:
            seen_hashes[actual_hash] = seen_hashes.get(actual_hash, 0) + 1
        rows.append(
            {
                "source_asset_alias": safe_hash_alias(reference),
                "role": role,
                "expected_hash_alias": safe_hash_alias(content_hash),
                "actual_hash_alias": safe_hash_alias(actual_hash) if actual_hash else "",
                "hash_matches": bool(actual_hash and actual_hash == content_hash),
                "size_bytes": actual_size,
                "readable": readable,
                "missing": missing,
                "_actual_hash": actual_hash,
            }
        )
    for row in rows:
        digest = str(row.pop("_actual_hash"))
        row["duplicate_hash"] = bool(digest and seen_hashes[digest] > 1)
    return {
        "schema": "perclip-asset-verification.v1",
        "asset_count": len(rows),
        "missing_count": sum(1 for row in rows if row["missing"]),
        "duplicate_hash_count": sum(1 for row in rows if row["duplicate_hash"]),
        "assets": rows,
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compact_metadata_json(metadata: Mapping[str, Any]) -> str:
    return json.dumps(dict(metadata), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
