from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from urllib.parse import quote


class RuntimeAuditError(ValueError):
    pass


_STRICT_DECIMAL = re.compile(r"[0-9]+\Z")


def _alias(prefix: str, value: object) -> str:
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _require_offline_snapshot(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise RuntimeAuditError("audit database is unavailable")
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{resolved}{suffix}")
        try:
            if sidecar.is_file() and sidecar.stat().st_size > 0:
                raise RuntimeAuditError(
                    "audit database is not a consistent offline snapshot; "
                    "create a consistent snapshot first"
                )
        except OSError as error:
            raise RuntimeAuditError("audit database snapshot cannot be verified") from error
    return resolved


def _connect_immutable(path: Path) -> sqlite3.Connection:
    resolved = _require_offline_snapshot(path)
    uri = f"file:{quote(resolved.as_posix())}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _require_columns(
    connection: sqlite3.Connection,
    table: str,
    required: set[str],
) -> None:
    columns = {
        str(row["name"])
        for row in connection.execute(f"pragma table_info({table})").fetchall()
    }
    if not required.issubset(columns):
        raise RuntimeAuditError("audit database schema is unsupported")


def _load_snapshot(path: Path | None) -> dict[str, object]:
    if path is None:
        return {"documents": [], "chunks": []}
    if not path.resolve().is_file():
        raise RuntimeAuditError("RAGFlow audit snapshot is unavailable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeAuditError("RAGFlow audit snapshot is invalid") from error
    if not isinstance(payload, dict):
        raise RuntimeAuditError("RAGFlow audit snapshot is invalid")
    documents = payload.get("documents")
    chunks = payload.get("chunks")
    if not isinstance(documents, list) or not isinstance(chunks, list):
        raise RuntimeAuditError("RAGFlow audit snapshot is invalid")
    validated_documents: list[dict[str, object]] = []
    for item in documents:
        if not isinstance(item, dict):
            raise RuntimeAuditError("RAGFlow audit snapshot is invalid")
        document_id = item.get("id")
        run = item.get("run") if "run" in item else None
        chunk_count = item.get("chunk_count")
        if not isinstance(document_id, str) or not document_id.strip():
            raise RuntimeAuditError("RAGFlow audit snapshot is invalid")
        if isinstance(run, bool) or (
            run is not None and not isinstance(run, (int, str))
        ):
            raise RuntimeAuditError("RAGFlow audit snapshot is invalid")
        if isinstance(run, str) and not run:
            raise RuntimeAuditError("RAGFlow audit snapshot is invalid")
        if isinstance(chunk_count, bool):
            raise RuntimeAuditError("RAGFlow audit snapshot is invalid")
        if isinstance(chunk_count, int):
            parsed_chunk_count = chunk_count
        elif isinstance(chunk_count, str) and _STRICT_DECIMAL.fullmatch(chunk_count):
            parsed_chunk_count = int(chunk_count)
        else:
            raise RuntimeAuditError("RAGFlow audit snapshot is invalid")
        if parsed_chunk_count < 0:
            raise RuntimeAuditError("RAGFlow audit snapshot is invalid")
        validated_documents.append(
            {
                "id": document_id,
                "run": run,
                "run_present": "run" in item,
                "chunk_count": parsed_chunk_count,
            }
        )

    validated_chunks: list[dict[str, object]] = []
    for item in chunks:
        if not isinstance(item, dict):
            raise RuntimeAuditError("RAGFlow audit snapshot is invalid")
        chunk_id = item.get("id")
        document_id = item.get("document_id")
        has_vector = item.get("has_vector")
        if not isinstance(chunk_id, str) or not chunk_id.strip():
            raise RuntimeAuditError("RAGFlow audit snapshot is invalid")
        if not isinstance(document_id, str) or not document_id.strip():
            raise RuntimeAuditError("RAGFlow audit snapshot is invalid")
        if not isinstance(has_vector, bool):
            raise RuntimeAuditError("RAGFlow audit snapshot is invalid")
        validated_chunks.append(
            {
                "id": chunk_id,
                "document_id": document_id,
                "has_vector": has_vector,
            }
        )
    return {"documents": validated_documents, "chunks": validated_chunks}


def _run_count_key(item: dict[str, object]) -> str:
    if not item["run_present"] or item["run"] is None:
        return "unknown"
    return str(item["run"])


def audit_runtime(
    *,
    perclip_db: Path,
    personalclips_db: Path | None = None,
    ragflow_snapshot: Path | None = None,
) -> dict[str, object]:
    with _connect_immutable(perclip_db) as connection:
        _require_columns(
            connection,
            "clips",
            {
                "client_request_id",
                "source_type",
                "archive_status",
                "ragflow_document_id",
            },
        )
        perclip_rows = connection.execute(
            """
            select source_type, archive_status, ragflow_document_id
            from clips
            """
        ).fetchall()

    personal_rows: list[sqlite3.Row] = []
    if personalclips_db is not None:
        with _connect_immutable(personalclips_db) as connection:
            _require_columns(
                connection,
                "items",
                {"source_type", "status", "ragflow_document_id"},
            )
            personal_rows = connection.execute(
                "select source_type, status, ragflow_document_id from items"
            ).fetchall()

    snapshot = _load_snapshot(ragflow_snapshot)
    documents = snapshot["documents"]
    chunks = snapshot["chunks"]

    perclip_doc_rows = [
        str(row["ragflow_document_id"])
        for row in perclip_rows
        if str(row["ragflow_document_id"] or "")
    ]
    personal_doc_rows = [
        str(row["ragflow_document_id"])
        for row in personal_rows
        if str(row["ragflow_document_id"] or "")
    ]
    perclip_ids = set(perclip_doc_rows)
    personal_ids = set(personal_doc_rows)
    ragflow_ids = {str(item["id"]) for item in documents}
    chunk_document_ids = {
        str(item.get("document_id") or "")
        for item in chunks
        if str(item.get("document_id") or "")
    }

    duplicate_groups = [
        {
            "document_alias": _alias("doc", document_id),
            "clip_rows": count,
        }
        for document_id, count in sorted(Counter(perclip_doc_rows).items())
        if count > 1
    ]
    chunk_counts = Counter(
        str(item.get("document_id") or "")
        for item in chunks
        if str(item.get("document_id") or "")
    )
    orphan_chunks = sorted(chunk_document_ids - ragflow_ids)
    document_chunk_counts = [
        int(item["chunk_count"])
        for item in documents
    ]

    return {
        "mode": "read_only_offline",
        "privacy": {
            "content_fields_read": False,
            "identifiers": "sha256_aliases_only",
            "paths_emitted": False,
        },
        "perclip": {
            "clip_rows": len(perclip_rows),
            "unique_document_ids": len(perclip_ids),
            "missing_document_ids": sum(
                not bool(str(row["ragflow_document_id"] or ""))
                for row in perclip_rows
            ),
            "source_counts": dict(sorted(Counter(
                str(row["source_type"] or "unknown") for row in perclip_rows
            ).items())),
            "archive_status_counts": dict(sorted(Counter(
                str(row["archive_status"] or "unknown") for row in perclip_rows
            ).items())),
            "duplicate_document_groups": duplicate_groups,
        },
        "personalclips": {
            "item_rows": len(personal_rows),
            "unique_document_ids": len(personal_ids),
            "status_counts": dict(sorted(Counter(
                str(row["status"] or "unknown") for row in personal_rows
            ).items())),
        },
        "ragflow": {
            "document_rows": len(documents),
            "run_counts": dict(sorted(Counter(
                _run_count_key(item) for item in documents
            ).items())),
            "database_chunk_sum": sum(document_chunk_counts),
            "zero_chunk_documents": sum(count == 0 for count in document_chunk_counts),
            "snapshot_chunks": len(chunks),
            "vector_chunks": sum(bool(item.get("has_vector")) for item in chunks),
            "orphan_chunk_documents": [
                {
                    "document_alias": _alias("doc", document_id),
                    "chunks": chunk_counts[document_id],
                }
                for document_id in orphan_chunks
            ],
        },
        "reconciliation": {
            "perclip_in_ragflow": len(perclip_ids & ragflow_ids),
            "perclip_only": len(perclip_ids - ragflow_ids),
            "ragflow_not_perclip": len(ragflow_ids - perclip_ids),
            "personalclips_in_ragflow": len(personal_ids & ragflow_ids),
            "personalclips_only": len(personal_ids - ragflow_ids),
            "three_way": len(perclip_ids & personal_ids & ragflow_ids),
        },
        "database_mutated": False,
        "ragflow_mutated": False,
        "network_used": False,
    }
