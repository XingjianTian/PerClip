from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .metadata_contract import CONTRACT_VERSION, dumps_normalized_metadata, loads_normalized_metadata


SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+")


class CaptureOwnershipConflict(ValueError):
    """A batch part or request ID is already owned by another capture identity."""


@dataclass(frozen=True)
class StoredClip:
    id: int
    duplicate: bool
    title: str
    platform: str
    original_path: str
    content_hash: str
    filename: str = ""
    size_bytes: int = 0
    ragflow_document_id: str = ""
    archive_status: str = "local"
    capture_client_batch_id: str = ""
    capture_parent_client_request_id: str = ""
    capture_part_index: int = 0
    capture_part_count: int = 1
    capture_part_role: str = "single"
    client_request_id: str = ""


@dataclass(frozen=True)
class StoredClipMetadata:
    clip_id: int
    client_request_id: str
    contract_version: str
    metadata: dict[str, object]
    created_at: str


@dataclass(frozen=True)
class StoredCapturePartAttempt:
    client_batch_id: str
    parent_client_request_id: str
    client_request_id: str
    part_index: int
    part_count: int
    part_role: str
    status: str
    error_code: str
    updated_at: str


@dataclass(frozen=True)
class StoredIngestReceipt:
    receipt_id: str
    client_request_id: str
    clip_id: str
    contract_version: str
    source_adapter: str
    request_signature: str
    status: str
    archive_status: str
    metadata_status: str
    error_code: str
    capture_client_batch_id: str
    capture_parent_client_request_id: str
    capture_part_index: int
    capture_part_count: int
    capture_part_role: str
    target_knowledge_base_id: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class StoredClipRawFields:
    id: int
    client_request_id: str
    source_type: str
    title_hint: str
    note: str
    text: str
    url: str
    mime_type: str
    device_name: str
    source_app: str
    captured_at: str
    filename: str
    size_bytes: int
    original_path: str
    content_hash: str
    ragflow_document_id: str
    archive_status: str
    created_at: str
    capture_client_batch_id: str = ""
    capture_parent_client_request_id: str = ""
    capture_part_index: int = 0
    capture_part_count: int = 1
    capture_part_role: str = "single"
    active_url: str = ""
    active_enrichment_invalid: bool = False


@dataclass(frozen=True)
class StoredClipEnrichment:
    id: int
    clip_id: str
    client_request_id: str
    knowledge_base_id: str
    route_decision_id: int | None
    engine: str
    status: str
    title: str
    summary: str
    tags: list[str]
    key_points: list[str]
    language: str
    extracted_text: str
    error_code: str
    error_message: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "clip_id": self.clip_id,
            "client_request_id": self.client_request_id,
            "knowledge_base_id": self.knowledge_base_id,
            "route_decision_id": self.route_decision_id,
            "engine": self.engine,
            "status": self.status,
            "title": self.title,
            "summary": self.summary,
            "tags": self.tags,
            "key_points": self.key_points,
            "language": self.language,
            "extracted_text": self.extracted_text,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class StoredRagflowSyncJob:
    id: int
    clip_id: str
    client_request_id: str
    knowledge_base_id: str
    ragflow_dataset_id: str
    ragflow_document_id: str
    route_decision_id: int | None
    enrichment_id: int | None
    operation: str
    status: str
    dry_run: bool
    reason: str
    plan: dict[str, object]
    remote_document_changed: bool
    attempt_key: str
    phase: str
    error_code: str
    error_message: str
    started_at: str
    finished_at: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class StoredRecallSession:
    id: str
    days: int
    kind: str
    topic_id: str
    window_start: str
    window_end: str
    snapshot_key: str
    status: str
    total_items: int
    current_position: int
    created_at: str
    updated_at: str
    completed_at: str


@dataclass(frozen=True)
class StoredRecallItem:
    id: str
    session_id: str
    clip_id: str
    client_request_id: str
    topic_id: str
    position: int
    state: str
    score: float
    title: str
    cue: str
    reveal_text: str
    summary: str
    tags: list[str]
    source_type: str
    source_label: str
    knowledge_base_name: str
    captured_at: str
    recall_count_before: int
    created_at: str
    updated_at: str
    acted_at: str


@dataclass(frozen=True)
class StoredRecallEvent:
    id: int
    client_action_id: str
    session_id: str
    item_id: str
    clip_id: str
    action: str
    created_at: str


class RecallActionCollisionError(Exception):
    """A client action id is already bound to a different Recall action."""


class RecallItemNotFoundError(Exception):
    """The requested item is absent from the requested Recall session."""


class ClipStore:
    REQUEST_LOCK_STALE_AFTER_SECONDS = 15 * 60

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.clip_dir = data_dir / "clips"
        self.db_path = data_dir / "perclip.sqlite3"

    def init(self) -> None:
        self.clip_dir.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                """
                create table if not exists clips (
                    id integer primary key autoincrement,
                    client_request_id text unique,
                    source_type text not null,
                    title_hint text not null,
                    note text not null,
                    text text not null,
                    url text not null,
                    mime_type text not null,
                    device_name text not null,
                    source_app text not null,
                    captured_at text not null,
                    filename text not null default '',
                    size_bytes integer not null default 0,
                    original_path text not null,
                    content_hash text not null,
                    ragflow_document_id text not null default '',
                    archive_status text not null default 'local',
                    capture_client_batch_id text not null default '',
                    capture_parent_client_request_id text not null default '',
                    capture_part_index integer not null default 0,
                    capture_part_count integer not null default 1,
                    capture_part_role text not null default 'single',
                    created_at text not null
                )
                """
            )
            db.execute("create index if not exists idx_clips_created_at on clips(created_at)")
            db.execute("create index if not exists idx_clips_captured_at on clips(captured_at)")
            self._ensure_column(db, "clips", "ragflow_document_id", "text not null default ''")
            self._ensure_column(db, "clips", "archive_status", "text not null default 'local'")
            self._ensure_column(db, "clips", "filename", "text not null default ''")
            self._ensure_column(db, "clips", "size_bytes", "integer not null default 0")
            self._ensure_column(db, "clips", "capture_client_batch_id", "text not null default ''")
            self._ensure_column(db, "clips", "capture_parent_client_request_id", "text not null default ''")
            self._ensure_column(db, "clips", "capture_part_index", "integer not null default 0")
            self._ensure_column(db, "clips", "capture_part_count", "integer not null default 1")
            self._ensure_column(db, "clips", "capture_part_role", "text not null default 'single'")
            db.execute("create index if not exists idx_clips_capture_batch on clips(capture_client_batch_id, capture_part_index, id)")
            db.execute(
                """
                create table if not exists request_locks (
                    client_request_id text primary key,
                    created_at_epoch integer not null,
                    lock_token text not null default ''
                )
                """
            )
            self._ensure_column(db, "request_locks", "lock_token", "text not null default ''")
            db.execute(
                """
                create table if not exists capture_part_attempts (
                    client_batch_id text not null,
                    part_index integer not null,
                    parent_client_request_id text not null,
                    client_request_id text not null,
                    part_count integer not null,
                    part_role text not null,
                    status text not null,
                    error_code text not null default '',
                    updated_at text not null,
                    primary key (client_batch_id, part_index)
                )
                """
            )
            db.execute(
                "create index if not exists idx_capture_part_attempts_batch on capture_part_attempts(client_batch_id, part_index)"
            )
            conflicting_attempt = db.execute(
                """
                select client_batch_id, client_request_id
                from capture_part_attempts
                group by client_batch_id, client_request_id
                having count(*) > 1
                limit 1
                """
            ).fetchone()
            if conflicting_attempt is not None:
                raise ValueError("capture attempt ownership conflict")
            db.execute(
                """
                create unique index if not exists idx_capture_part_attempts_batch_request
                on capture_part_attempts(client_batch_id, client_request_id)
                """
            )
            db.execute(
                """
                create table if not exists clip_metadata (
                    clip_id integer primary key,
                    client_request_id text,
                    contract_version text not null,
                    metadata_json text not null,
                    created_at text not null,
                    foreign key (clip_id) references clips(id)
                )
                """
            )
            db.execute(
                """
                create table if not exists ingest_receipts (
                    receipt_id text primary key,
                    client_request_id text unique not null,
                    clip_id text not null default '',
                    contract_version text not null,
                    source_adapter text not null,
                    request_signature text not null,
                    status text not null,
                    archive_status text not null,
                    metadata_status text not null,
                    error_code text not null default '',
                    capture_client_batch_id text not null default '',
                    capture_parent_client_request_id text not null default '',
                    capture_part_index integer not null default 0,
                    capture_part_count integer not null default 1,
                    capture_part_role text not null default 'single',
                    target_knowledge_base_id text not null default '',
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            db.execute("create index if not exists idx_ingest_receipts_clip_id on ingest_receipts(clip_id)")
            self._ensure_column(db, "ingest_receipts", "error_code", "text not null default ''")
            db.execute(
                """
                create index if not exists idx_clip_metadata_client_request_id
                on clip_metadata(client_request_id)
                """
            )
            db.execute(
                """
                create table if not exists clip_enrichments (
                    id integer primary key autoincrement,
                    clip_id text not null,
                    client_request_id text not null default '',
                    knowledge_base_id text not null default '',
                    route_decision_id integer,
                    engine text not null,
                    status text not null,
                    title text not null default '',
                    summary text not null default '',
                    tags_json text not null default '[]',
                    key_points_json text not null default '[]',
                    language text not null default '',
                    extracted_text text not null default '',
                    error_code text not null default '',
                    error_message text not null default '',
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            self._ensure_column(db, "clip_enrichments", "key_points_json", "text not null default '[]'")
            db.execute(
                """
                create index if not exists idx_clip_enrichments_clip_id
                on clip_enrichments(clip_id, id)
                """
            )
            db.execute(
                """
                create index if not exists idx_clip_enrichments_client_request_id
                on clip_enrichments(client_request_id, id)
                """
            )
            db.execute(
                """
                create table if not exists ragflow_sync_jobs (
                    id integer primary key autoincrement,
                    clip_id text not null,
                    client_request_id text not null default '',
                    knowledge_base_id text not null default '',
                    ragflow_dataset_id text not null default '',
                    ragflow_document_id text not null default '',
                    route_decision_id integer,
                    enrichment_id integer,
                    operation text not null,
                    status text not null,
                    dry_run integer not null default 1,
                    reason text not null default '',
                    plan_json text not null default '{}',
                    remote_document_changed integer not null default 0,
                    attempt_key text not null default '',
                    phase text not null default '',
                    error_code text not null default '',
                    error_message text not null default '',
                    started_at text not null default '',
                    finished_at text not null default '',
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            self._ensure_column(db, "ragflow_sync_jobs", "attempt_key", "text not null default ''")
            self._ensure_column(db, "ragflow_sync_jobs", "phase", "text not null default ''")
            self._ensure_column(db, "ragflow_sync_jobs", "error_code", "text not null default ''")
            self._ensure_column(db, "ragflow_sync_jobs", "error_message", "text not null default ''")
            self._ensure_column(db, "ragflow_sync_jobs", "started_at", "text not null default ''")
            self._ensure_column(db, "ragflow_sync_jobs", "finished_at", "text not null default ''")
            db.execute(
                """
                create index if not exists idx_ragflow_sync_jobs_clip_id
                on ragflow_sync_jobs(clip_id, id)
                """
            )
            db.execute(
                """
                create index if not exists idx_ragflow_sync_jobs_attempt_key
                on ragflow_sync_jobs(attempt_key, id)
                """
            )
            db.execute(
                """
                create table if not exists ragflow_sync_locks (
                    clip_id text primary key,
                    created_at_epoch integer not null
                )
                """
            )
            db.execute(
                """
                create index if not exists idx_ragflow_sync_jobs_client_request_id
                on ragflow_sync_jobs(client_request_id, id)
                """
            )
            db.execute(
                """
                create table if not exists recall_sessions (
                    id text primary key,
                    days integer not null default 7,
                    kind text not null default 'general',
                    topic_id text not null default '',
                    window_start text not null default '',
                    window_end text not null default '',
                    snapshot_key text not null default '',
                    status text not null default 'active',
                    total_items integer not null default 0,
                    current_position integer not null default 0,
                    created_at text not null,
                    updated_at text not null default '',
                    completed_at text not null default ''
                )
                """
            )
            for column, definition in (("days", "integer not null default 7"), ("kind", "text not null default 'general'"), ("window_start", "text not null default ''"), ("window_end", "text not null default ''"), ("snapshot_key", "text not null default ''"), ("total_items", "integer not null default 0"), ("current_position", "integer not null default 0"), ("updated_at", "text not null default ''")):
                self._ensure_column(db, "recall_sessions", column, definition)
            db.execute("create index if not exists idx_recall_sessions_active_snapshot on recall_sessions(snapshot_key, topic_id, status)")
            db.execute(
                """
                create table if not exists recall_events (
                    id integer primary key autoincrement,
                    session_id text not null,
                    clip_id text not null,
                    action text not null,
                    created_at text not null,
                    foreign key (session_id) references recall_sessions(id)
                )
                """
            )
            db.execute("create index if not exists idx_recall_events_clip_id on recall_events(clip_id, id)")
            self._ensure_column(db, "recall_events", "client_action_id", "text")
            self._ensure_column(db, "recall_events", "item_id", "text not null default ''")
            db.execute("create unique index if not exists idx_recall_events_client_action_id on recall_events(client_action_id) where client_action_id is not null and client_action_id != ''")
            db.execute(
                """create table if not exists recall_session_items (
                    id text primary key, session_id text not null, clip_id text not null,
                    client_request_id text not null default '', topic_id text not null default '',
                    position integer not null, status text not null default 'pending', score real not null,
                    title text not null, cue text not null, reveal_text text not null, summary text not null,
                    tags_json text not null default '[]', source_type text not null default '', source_label text not null default '',
                    knowledge_base_name text not null default '', captured_at text not null default '',
                    recall_count_before integer not null default 0, created_at text not null, updated_at text not null, acted_at text not null default '',
                    unique(session_id, clip_id), foreign key(session_id) references recall_sessions(id)
                )"""
            )
            db.execute("create index if not exists idx_recall_session_items_session_position on recall_session_items(session_id, position)")
            db.execute("create index if not exists idx_recall_session_items_clip_id on recall_session_items(clip_id, id)")
            db.execute("create index if not exists idx_recall_events_session_item on recall_events(session_id, item_id, id)")
            db.execute("create index if not exists idx_recall_events_clip_created on recall_events(clip_id, created_at)")
            db.execute("""create table if not exists recall_surface_events (
                id integer primary key autoincrement, client_event_id text unique not null,
                surface text not null, action text not null, node_id text not null default '',
                topic_id text not null default '', clip_id text not null default '', session_id text not null default '',
                metadata_json text not null default '{}', occurred_at text not null, created_at text not null
            )""")
            db.execute("create index if not exists idx_recall_surface_events_clip on recall_surface_events(clip_id, occurred_at)")
            db.execute("create index if not exists idx_recall_surface_events_occurred on recall_surface_events(occurred_at)")
            db.execute("create index if not exists idx_recall_surface_events_surface_action_time on recall_surface_events(surface, action, occurred_at)")
            db.execute("create index if not exists idx_recall_surface_events_topic_time on recall_surface_events(topic_id, occurred_at)")
            db.execute("create index if not exists idx_recall_surface_events_clip_action_time on recall_surface_events(clip_id, action, occurred_at)")
            db.execute("""create table if not exists recall_suppressions (
                clip_id text primary key,
                suppressed integer not null default 1,
                updated_at text not null
            )""")
            db.execute("create index if not exists idx_recall_suppressions_active on recall_suppressions(suppressed, updated_at)")
            db.execute("""create table if not exists recall_preferences (
                user_id text primary key, visible_label_count integer not null default 3,
                label_rotation_seconds integer not null default 8, default_days integer not null default 30,
                preferred_topic_ids_json text not null default '[]', muted_topic_ids_json text not null default '[]',
                include_memory_labels integer not null default 1, updated_at text not null
            )""")
            db.execute("insert or ignore into recall_preferences (user_id, updated_at) values ('default', ?)", (datetime.now(timezone.utc).isoformat(),))

    def connect(self) -> sqlite3.Connection:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    def find_by_request_id(self, client_request_id: str) -> StoredClip | None:
        normalized_request_id = normalize_client_request_id(client_request_id)
        if normalized_request_id is None:
            return None
        with self.connect() as db:
            row = db.execute(
                "select * from clips where client_request_id = ?",
                (normalized_request_id,),
            ).fetchone()
        return self._row_to_clip(row, duplicate=True) if row else None

    def claim_ingest_receipt(
        self, *, receipt_id: str, client_request_id: str, contract_version: str,
        source_adapter: str, request_signature: str, capture_client_batch_id: str = "",
        capture_parent_client_request_id: str = "", capture_part_index: int = 0,
        capture_part_count: int = 1, capture_part_role: str = "single",
        target_knowledge_base_id: str = "",
    ) -> tuple[StoredIngestReceipt, bool]:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            try:
                db.execute(
                    """
                    insert into ingest_receipts (
                        receipt_id, client_request_id, clip_id, contract_version, source_adapter,
                        request_signature, status, archive_status, metadata_status, error_code,
                        capture_client_batch_id, capture_parent_client_request_id,
                        capture_part_index, capture_part_count, capture_part_role,
                        target_knowledge_base_id, created_at, updated_at
                    ) values (?, ?, '', ?, ?, ?, 'processing', 'pending', 'pending', '', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (receipt_id, client_request_id, contract_version, source_adapter, request_signature,
                     capture_client_batch_id, capture_parent_client_request_id, capture_part_index,
                     capture_part_count, capture_part_role, target_knowledge_base_id, now, now),
                )
                row = db.execute("select * from ingest_receipts where receipt_id = ?", (receipt_id,)).fetchone()
                return self._row_to_ingest_receipt(row), True
            except sqlite3.IntegrityError:
                row = db.execute(
                    "select * from ingest_receipts where client_request_id = ?", (client_request_id,)
                ).fetchone()
                if row is None:
                    raise
                return self._row_to_ingest_receipt(row), False

    def claim_or_recover_ingest_receipt(
        self, *, receipt_id: str, client_request_id: str, contract_version: str,
        source_adapter: str, request_signature: str, stale_after_seconds: int,
        capture_client_batch_id: str = "", capture_parent_client_request_id: str = "",
        capture_part_index: int = 0, capture_part_count: int = 1,
        capture_part_role: str = "single", target_knowledge_base_id: str = "",
        recover_failed_with_clip: bool = False, recover_failed_without_clip: bool = False,
    ) -> tuple[StoredIngestReceipt, str]:
        """Claim or recover a receipt while the caller holds its request lock."""
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        with self.connect() as db:
            try:
                db.execute(
                    """
                    insert into ingest_receipts (
                        receipt_id, client_request_id, clip_id, contract_version, source_adapter,
                        request_signature, status, archive_status, metadata_status, error_code,
                        capture_client_batch_id, capture_parent_client_request_id,
                        capture_part_index, capture_part_count, capture_part_role,
                        target_knowledge_base_id, created_at, updated_at
                    ) values (?, ?, '', ?, ?, ?, 'processing', 'pending', 'pending', '', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (receipt_id, client_request_id, contract_version, source_adapter, request_signature,
                     capture_client_batch_id, capture_parent_client_request_id, capture_part_index,
                     capture_part_count, capture_part_role, target_knowledge_base_id, now_text, now_text),
                )
                row = db.execute("select * from ingest_receipts where receipt_id=?", (receipt_id,)).fetchone()
                return self._row_to_ingest_receipt(row), "created"
            except sqlite3.IntegrityError:
                row = db.execute(
                    "select * from ingest_receipts where client_request_id=?", (client_request_id,)
                ).fetchone()
                if row is None:
                    raise

            receipt = self._row_to_ingest_receipt(row)
            if (receipt.contract_version != contract_version or receipt.source_adapter != source_adapter
                    or receipt.request_signature != request_signature):
                return receipt, "conflict"
            if receipt.status == "received":
                return receipt, "received"
            if receipt.status == "processing":
                try:
                    updated_at = datetime.fromisoformat(receipt.updated_at.replace("Z", "+00:00"))
                except ValueError:
                    return receipt, "active"
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                if (now - updated_at.astimezone(timezone.utc)).total_seconds() <= stale_after_seconds:
                    return receipt, "active"
                db.execute(
                    """
                    update ingest_receipts set updated_at=?, error_code=''
                    where receipt_id=? and status='processing' and contract_version=?
                      and source_adapter=? and request_signature=?
                    """,
                    (now_text, receipt.receipt_id, contract_version, source_adapter, request_signature),
                )
                row = db.execute("select * from ingest_receipts where receipt_id=?", (receipt.receipt_id,)).fetchone()
                return self._row_to_ingest_receipt(row), "recovered"
            if receipt.status == "failed" and (
                (receipt.clip_id and recover_failed_with_clip)
                or (not receipt.clip_id and recover_failed_without_clip)
            ):
                db.execute(
                    """
                    update ingest_receipts
                    set status='processing', archive_status='pending', metadata_status='pending',
                        error_code='', updated_at=?
                    where receipt_id=? and status='failed' and contract_version=?
                      and source_adapter=? and request_signature=?
                    """,
                    (now_text, receipt.receipt_id, contract_version, source_adapter, request_signature),
                )
                row = db.execute("select * from ingest_receipts where receipt_id=?", (receipt.receipt_id,)).fetchone()
                return self._row_to_ingest_receipt(row), "reconcile" if receipt.clip_id else "recovered"
            return receipt, "failed"

    def has_active_request_lock(self, client_request_id: str) -> bool:
        normalized_request_id = normalize_client_request_id(client_request_id)
        if normalized_request_id is None:
            return False
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        stale_before_epoch = now_epoch - self.REQUEST_LOCK_STALE_AFTER_SECONDS
        with self.connect() as db:
            row = db.execute(
                """
                select 1 from request_locks
                where client_request_id=? and created_at_epoch>=?
                """,
                (normalized_request_id, stale_before_epoch),
            ).fetchone()
        return row is not None

    def find_ingest_receipt_by_id(self, receipt_id: str) -> StoredIngestReceipt | None:
        with self.connect() as db:
            row = db.execute("select * from ingest_receipts where receipt_id = ?", (receipt_id,)).fetchone()
        return self._row_to_ingest_receipt(row) if row else None

    def find_ingest_receipt_by_request_id(self, client_request_id: str) -> StoredIngestReceipt | None:
        with self.connect() as db:
            row = db.execute(
                "select * from ingest_receipts where client_request_id = ?", (client_request_id,)
            ).fetchone()
        return self._row_to_ingest_receipt(row) if row else None

    def finish_ingest_receipt(
        self, *, receipt_id: str, status: str, clip_id: str = "",
        archive_status: str, metadata_status: str, error_code: str = "",
        expected_contract_version: str = "", expected_source_adapter: str = "",
        expected_request_signature: str = "",
    ) -> StoredIngestReceipt | None:
        if status not in {"received", "failed"}:
            raise ValueError("invalid ingest receipt status")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute(
                """
                update ingest_receipts set status=?, clip_id=?, archive_status=?, metadata_status=?, error_code=?, updated_at=?
                where receipt_id=? and status='processing'
                  and (?='' or contract_version=?)
                  and (?='' or source_adapter=?)
                  and (?='' or request_signature=?)
                """,
                (status, clip_id, archive_status, metadata_status, error_code, now, receipt_id,
                 expected_contract_version, expected_contract_version,
                 expected_source_adapter, expected_source_adapter,
                 expected_request_signature, expected_request_signature),
            )
            row = db.execute("select * from ingest_receipts where receipt_id = ?", (receipt_id,)).fetchone()
        return self._row_to_ingest_receipt(row) if row else None

    def reopen_failed_ingest_receipt(
        self, *, receipt_id: str, expected_contract_version: str,
        expected_source_adapter: str, expected_request_signature: str,
    ) -> StoredIngestReceipt | None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute(
                """
                update ingest_receipts
                set status='processing', archive_status='pending', metadata_status='pending', error_code='', updated_at=?
                where receipt_id=? and status='failed' and contract_version=?
                  and source_adapter=? and request_signature=?
                """,
                (now, receipt_id, expected_contract_version, expected_source_adapter,
                 expected_request_signature),
            )
            row = db.execute("select * from ingest_receipts where receipt_id = ?", (receipt_id,)).fetchone()
        return self._row_to_ingest_receipt(row) if row else None

    def find_raw_fields_by_clip_id(self, clip_id: int) -> StoredClipRawFields | None:
        with self.connect() as db:
            row = db.execute(
                "select * from clips where id = ?",
                (clip_id,),
            ).fetchone()
        return self._row_to_raw_fields(row) if row else None

    def find_raw_fields_by_client_request_id(self, client_request_id: str) -> StoredClipRawFields | None:
        normalized_request_id = normalize_client_request_id(client_request_id)
        if normalized_request_id is None:
            return None
        with self.connect() as db:
            row = db.execute(
                "select * from clips where client_request_id = ?",
                (normalized_request_id,),
            ).fetchone()
        return self._row_to_raw_fields(row) if row else None

    def find_raw_fields_by_client_request_prefix(self, client_request_prefix: str) -> list[StoredClipRawFields]:
        normalized_prefix = normalize_client_request_id(client_request_prefix)
        if normalized_prefix is None:
            return []
        with self.connect() as db:
            rows = db.execute(
                """
                select * from clips
                where client_request_id = ? or client_request_id like ?
                order by id asc
                """,
                (normalized_prefix, f"{normalized_prefix}:%"),
            ).fetchall()
        return [self._row_to_raw_fields(row) for row in rows]

    def list_clips_by_client_batch_id(self, batch_id: str) -> list[StoredClipRawFields]:
        with self.connect() as db:
            rows = db.execute(
                "select * from clips where capture_client_batch_id = ? order by capture_part_index asc, id asc",
                (batch_id.strip(),),
            ).fetchall()
        return [self._row_to_raw_fields(row) for row in rows]

    def attach_capture_identity_if_missing(
        self, *, clip_id: int, batch_id: str, parent_id: str,
        part_index: int, part_count: int, part_role: str,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                update clips set
                    capture_client_batch_id=?, capture_parent_client_request_id=?,
                    capture_part_index=?, capture_part_count=?, capture_part_role=?
                where id=? and capture_client_batch_id=''
                """,
                (batch_id, parent_id, part_index, part_count, part_role, clip_id),
            )

    def list_capture_part_attempts_by_batch_id(self, batch_id: str) -> list[StoredCapturePartAttempt]:
        with self.connect() as db:
            rows = db.execute(
                "select * from capture_part_attempts where client_batch_id = ? order by part_index asc",
                (batch_id.strip(),),
            ).fetchall()
        return [self._row_to_capture_part_attempt(row) for row in rows]

    def validate_capture_batch_part(
        self, *, batch_id: str, parent_id: str, client_request_id: str,
        part_index: int, part_count: int, part_role: str,
    ) -> None:
        if not batch_id:
            return
        attempts = self.list_capture_part_attempts_by_batch_id(batch_id)
        for attempt in attempts:
            if attempt.parent_client_request_id != parent_id or attempt.part_count != part_count:
                raise ValueError("capture batch parent/count mismatch")
            if attempt.part_index == part_index and attempt.client_request_id != client_request_id:
                raise CaptureOwnershipConflict("capture batch part index already belongs to another request")
            if attempt.client_request_id == client_request_id and attempt.part_index != part_index:
                raise CaptureOwnershipConflict("capture request already belongs to another part index")
            if attempt.part_index == part_index and attempt.part_role != part_role:
                raise ValueError("capture batch part role mismatch")

    def upsert_capture_part_attempt(
        self, *, batch_id: str, parent_id: str, client_request_id: str,
        part_index: int, part_count: int, part_role: str, status: str, error_code: str = "",
    ) -> None:
        if not batch_id:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute(
                """
                insert into capture_part_attempts (
                    client_batch_id, part_index, parent_client_request_id, client_request_id,
                    part_count, part_role, status, error_code, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(client_batch_id, part_index) do update set
                    parent_client_request_id=excluded.parent_client_request_id,
                    client_request_id=excluded.client_request_id,
                    part_count=excluded.part_count,
                    part_role=excluded.part_role,
                    status=excluded.status,
                    error_code=excluded.error_code,
                    updated_at=excluded.updated_at
                """,
                (batch_id, part_index, parent_id, client_request_id, part_count, part_role, status, error_code, now),
            )

    def update_ragflow_document_id(self, clip_id: int, document_id: str) -> None:
        with self.connect() as db:
            db.execute("update clips set ragflow_document_id = ? where id = ?", (document_id.strip(), clip_id))

    def acquire_request_lock_token(self, client_request_id: str) -> str | None:
        normalized_request_id = normalize_client_request_id(client_request_id)
        if normalized_request_id is None:
            return "unkeyed"

        now_epoch = int(datetime.now(timezone.utc).timestamp())
        stale_before_epoch = now_epoch - self.REQUEST_LOCK_STALE_AFTER_SECONDS
        lock_token = uuid.uuid4().hex
        with self.connect() as db:
            db.execute(
                "delete from request_locks where created_at_epoch < ?",
                (stale_before_epoch,),
            )
            try:
                db.execute(
                    "insert into request_locks (client_request_id, created_at_epoch, lock_token) values (?, ?, ?)",
                    (normalized_request_id, now_epoch, lock_token),
                )
            except sqlite3.IntegrityError:
                return None
        return lock_token

    def acquire_request_lock(self, client_request_id: str) -> bool:
        return self.acquire_request_lock_token(client_request_id) is not None

    def release_request_lock_token(self, client_request_id: str, lock_token: str) -> None:
        normalized_request_id = normalize_client_request_id(client_request_id)
        if normalized_request_id is None or lock_token == "unkeyed":
            return
        with self.connect() as db:
            db.execute(
                "delete from request_locks where client_request_id = ? and lock_token = ?",
                (normalized_request_id, lock_token),
            )

    def release_request_lock(self, client_request_id: str) -> None:
        normalized_request_id = normalize_client_request_id(client_request_id)
        if normalized_request_id is None:
            return

        with self.connect() as db:
            db.execute(
                "delete from request_locks where client_request_id = ?",
                (normalized_request_id,),
            )

    def save(
        self,
        *,
        client_request_id: str,
        source_type: str,
        title_hint: str,
        note: str,
        text: str,
        url: str,
        mime_type: str,
        device_name: str,
        source_app: str,
        captured_at: str,
        filename: str,
        payload: bytes,
        archived_original_path: str = "",
        ragflow_document_id: str = "",
        archive_status: str = "local",
        capture_client_batch_id: str = "",
        capture_parent_client_request_id: str = "",
        capture_part_index: int = 0,
        capture_part_count: int = 1,
        capture_part_role: str = "single",
    ) -> StoredClip:
        now = datetime.now(timezone.utc)
        normalized_request_id = normalize_client_request_id(client_request_id)
        title = title_hint.strip() or filename or "未命名收藏"
        stored_text = text or url or note
        stored_bytes = payload or stored_text.encode()
        content_hash = hashlib.sha256(payload or f"{text}\n{url}\n{note}".encode()).hexdigest()
        folder = self.clip_dir / source_type / now.strftime("%Y") / now.strftime("%m")
        folder.mkdir(parents=True, exist_ok=True)

        safe_name = sanitize_filename(filename or f"{now.strftime('%Y-%m-%d_%H%M%S')}_{source_type}.txt")
        original_path = unique_path(folder, safe_name, content_hash)
        if payload:
            original_path.write_bytes(payload)
        else:
            original_path.write_text(stored_text, encoding="utf-8")

        try:
            with self.connect() as db:
                cursor = db.execute(
                    """
                    insert into clips (
                        client_request_id, source_type, title_hint, note, text, url, mime_type,
                        device_name, source_app, captured_at, filename, size_bytes, original_path, content_hash,
                        ragflow_document_id, archive_status, capture_client_batch_id,
                        capture_parent_client_request_id, capture_part_index, capture_part_count,
                        capture_part_role, created_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_request_id,
                        source_type,
                        title,
                        note,
                        text,
                        url,
                        mime_type,
                        device_name,
                        source_app,
                        captured_at,
                        safe_name,
                        len(stored_bytes),
                        archived_original_path or str(original_path),
                        content_hash,
                        ragflow_document_id,
                        archive_status,
                        capture_client_batch_id.strip(),
                        capture_parent_client_request_id.strip(),
                        capture_part_index,
                        capture_part_count,
                        capture_part_role.strip(),
                        now.isoformat(),
                    ),
                )
                clip_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            duplicate = self.find_by_request_id(client_request_id)
            if duplicate is None:
                raise
            original_path.unlink(missing_ok=True)
            return duplicate
        return StoredClip(
            id=clip_id,
            duplicate=False,
            title=title,
            platform="android_share",
            original_path=archived_original_path or str(original_path),
            content_hash=content_hash,
            filename=safe_name,
            size_bytes=len(stored_bytes),
            ragflow_document_id=ragflow_document_id,
            archive_status=archive_status,
            capture_client_batch_id=capture_client_batch_id.strip(),
            capture_parent_client_request_id=capture_parent_client_request_id.strip(),
            capture_part_index=capture_part_index,
            capture_part_count=capture_part_count,
            capture_part_role=capture_part_role.strip(),
            client_request_id=normalized_request_id or "",
        )

    def save_normalized_metadata(
        self,
        *,
        clip_id: int,
        client_request_id: str,
        metadata: dict[str, object],
    ) -> StoredClipMetadata:
        contract_version = str(metadata.get("contract_version", ""))
        if contract_version != CONTRACT_VERSION:
            raise ValueError("unsupported normalized metadata contract_version")

        created_at = datetime.now(timezone.utc).isoformat()
        normalized_request_id = normalize_client_request_id(client_request_id) or ""
        metadata_json = dumps_normalized_metadata(metadata)
        with self.connect() as db:
            db.execute(
                """
                insert into clip_metadata (
                    clip_id, client_request_id, contract_version, metadata_json, created_at
                )
                values (?, ?, ?, ?, ?)
                on conflict(clip_id) do update set
                    client_request_id = excluded.client_request_id,
                    contract_version = excluded.contract_version,
                    metadata_json = excluded.metadata_json,
                    created_at = excluded.created_at
                """,
                (
                    clip_id,
                    normalized_request_id,
                    contract_version,
                    metadata_json,
                    created_at,
                ),
            )
        return StoredClipMetadata(
            clip_id=clip_id,
            client_request_id=normalized_request_id,
            contract_version=contract_version,
            metadata=metadata,
            created_at=created_at,
        )

    def find_normalized_metadata_by_clip_id(self, clip_id: int) -> StoredClipMetadata | None:
        with self.connect() as db:
            row = db.execute(
                "select * from clip_metadata where clip_id = ?",
                (clip_id,),
            ).fetchone()
        return self._row_to_metadata(row) if row else None

    def find_normalized_metadata_by_request_id(self, client_request_id: str) -> StoredClipMetadata | None:
        normalized_request_id = normalize_client_request_id(client_request_id)
        if normalized_request_id is None:
            return None
        with self.connect() as db:
            row = db.execute(
                "select * from clip_metadata where client_request_id = ?",
                (normalized_request_id,),
            ).fetchone()
        return self._row_to_metadata(row) if row else None

    def save_enrichment(
        self,
        *,
        clip_id: str | int,
        client_request_id: str,
        knowledge_base_id: str,
        route_decision_id: int | None,
        engine: str,
        status: str,
        title: str,
        summary: str,
        tags: list[str],
        language: str,
        extracted_text: str,
        key_points: list[str] | None = None,
        error_code: str = "",
        error_message: str = "",
    ) -> StoredClipEnrichment:
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise ValueError("tags must be a JSON array of strings")
        normalized_key_points = [] if key_points is None else key_points
        if not isinstance(normalized_key_points, list) or any(
            not isinstance(point, str) for point in normalized_key_points
        ):
            raise ValueError("key_points must be a JSON array of strings")
        tags_json = json.dumps(tags, ensure_ascii=False, sort_keys=True)
        key_points_json = json.dumps(normalized_key_points, ensure_ascii=False, sort_keys=True)
        now = datetime.now(timezone.utc).isoformat()
        normalized_request_id = normalize_client_request_id(client_request_id) or ""
        with self.connect() as db:
            cursor = db.execute(
                """
                insert into clip_enrichments (
                    clip_id, client_request_id, knowledge_base_id, route_decision_id,
                    engine, status, title, summary, tags_json, key_points_json, language,
                    extracted_text, error_code, error_message, created_at, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(clip_id),
                    normalized_request_id,
                    knowledge_base_id.strip(),
                    route_decision_id,
                    engine,
                    status,
                    title,
                    summary,
                    tags_json,
                    key_points_json,
                    language,
                    extracted_text,
                    error_code,
                    error_message,
                    now,
                    now,
                ),
            )
            row = db.execute("select * from clip_enrichments where id = ?", (int(cursor.lastrowid),)).fetchone()
        return self._row_to_enrichment(row)

    def find_latest_enrichment_by_clip_id(self, clip_id: str | int) -> StoredClipEnrichment | None:
        with self.connect() as db:
            row = db.execute(
                """
                select * from clip_enrichments
                where clip_id = ?
                order by id desc
                limit 1
                """,
                (str(clip_id),),
            ).fetchone()
        return self._row_to_enrichment(row) if row else None

    def find_enrichment_by_id(self, enrichment_id: int) -> StoredClipEnrichment | None:
        with self.connect() as db:
            row = db.execute(
                "select * from clip_enrichments where id = ?", (int(enrichment_id),)
            ).fetchone()
        return self._row_to_enrichment(row) if row else None

    def find_latest_completed_enrichment_by_clip_id(self, clip_id: str | int) -> StoredClipEnrichment | None:
        with self.connect() as db:
            row = db.execute(
                """
                select * from clip_enrichments
                where clip_id = ? and status = 'completed'
                order by id desc
                limit 1
                """,
                (str(clip_id),),
            ).fetchone()
        return self._row_to_enrichment(row) if row else None

    def find_latest_enrichment_by_request_id(self, client_request_id: str) -> StoredClipEnrichment | None:
        normalized_request_id = normalize_client_request_id(client_request_id)
        if normalized_request_id is None:
            return None
        with self.connect() as db:
            row = db.execute(
                """
                select * from clip_enrichments
                where client_request_id = ?
                order by id desc
                limit 1
                """,
                (normalized_request_id,),
            ).fetchone()
        return self._row_to_enrichment(row) if row else None

    def list_clips_without_enrichment(self, *, limit: int) -> list[StoredClipRawFields]:
        with self.connect() as db:
            rows = db.execute(
                """
                select c.* from clips c
                where not exists (
                    select 1 from clip_enrichments e
                    where e.clip_id = cast(c.id as text)
                )
                order by c.id asc
                limit ?
                """,
                (int(limit),),
            ).fetchall()
        return [self._row_to_raw_fields(row) for row in rows]

    def save_ragflow_sync_job(
        self,
        *,
        clip_id: str | int,
        client_request_id: str,
        knowledge_base_id: str,
        ragflow_dataset_id: str,
        ragflow_document_id: str,
        route_decision_id: int | None,
        enrichment_id: int | None,
        operation: str,
        status: str,
        dry_run: bool,
        reason: str,
        plan: dict[str, object],
        remote_document_changed: bool,
        attempt_key: str = "",
        phase: str = "",
        error_code: str = "",
        error_message: str = "",
        started_at: str = "",
        finished_at: str = "",
    ) -> StoredRagflowSyncJob:
        if not isinstance(plan, dict):
            raise ValueError("plan_json must be a JSON object")
        now = datetime.now(timezone.utc).isoformat()
        normalized_request_id = normalize_client_request_id(client_request_id) or ""
        plan_json = json.dumps(plan, ensure_ascii=False, sort_keys=True)
        with self.connect() as db:
            cursor = db.execute(
                """
                insert into ragflow_sync_jobs (
                    clip_id, client_request_id, knowledge_base_id, ragflow_dataset_id,
                    ragflow_document_id, route_decision_id, enrichment_id,
                    operation, status, dry_run, reason, plan_json,
                    remote_document_changed, attempt_key, phase, error_code,
                    error_message, started_at, finished_at, created_at, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(clip_id),
                    normalized_request_id,
                    knowledge_base_id.strip(),
                    ragflow_dataset_id.strip(),
                    ragflow_document_id.strip(),
                    route_decision_id,
                    enrichment_id,
                    operation,
                    status,
                    1 if dry_run else 0,
                    reason,
                    plan_json,
                    1 if remote_document_changed else 0,
                    attempt_key.strip(),
                    phase.strip(),
                    error_code.strip(),
                    error_message.strip(),
                    started_at.strip(),
                    finished_at.strip(),
                    now,
                    now,
                ),
            )
            row = db.execute("select * from ragflow_sync_jobs where id = ?", (int(cursor.lastrowid),)).fetchone()
        return self._row_to_sync_job(row)

    def update_ragflow_sync_job(
        self,
        job_id: int,
        *,
        status: str,
        phase: str,
        reason: str,
        plan: dict[str, object],
        ragflow_document_id: str,
        remote_document_changed: bool,
        error_code: str = "",
        error_message: str = "",
        finished_at: str = "",
    ) -> StoredRagflowSyncJob:
        now = datetime.now(timezone.utc).isoformat()
        plan_json = json.dumps(plan, ensure_ascii=False, sort_keys=True)
        with self.connect() as db:
            db.execute(
                """
                update ragflow_sync_jobs
                set status = ?, phase = ?, reason = ?, plan_json = ?, ragflow_document_id = ?,
                    remote_document_changed = ?, error_code = ?, error_message = ?,
                    finished_at = ?, updated_at = ?
                where id = ?
                """,
                (
                    status,
                    phase,
                    reason,
                    plan_json,
                    ragflow_document_id.strip(),
                    1 if remote_document_changed else 0,
                    error_code.strip(),
                    error_message.strip(),
                    finished_at.strip(),
                    now,
                    int(job_id),
                ),
            )
            row = db.execute("select * from ragflow_sync_jobs where id = ?", (int(job_id),)).fetchone()
        if row is None:
            raise ValueError("ragflow sync job not found")
        return self._row_to_sync_job(row)

    def find_completed_ragflow_sync_job_by_attempt_key(self, attempt_key: str) -> StoredRagflowSyncJob | None:
        with self.connect() as db:
            row = db.execute(
                """
                select * from ragflow_sync_jobs
                where attempt_key = ? and status = 'completed'
                order by id desc
                limit 1
                """,
                (attempt_key,),
            ).fetchone()
        return self._row_to_sync_job(row) if row else None

    def acquire_ragflow_sync_lock(self, clip_id: str | int, *, now_epoch: int, stale_after_seconds: int = 15 * 60) -> bool:
        normalized_clip_id = str(clip_id)
        with self.connect() as db:
            db.execute(
                "delete from ragflow_sync_locks where created_at_epoch <= ?",
                (int(now_epoch) - int(stale_after_seconds),),
            )
            try:
                db.execute(
                    "insert into ragflow_sync_locks (clip_id, created_at_epoch) values (?, ?)",
                    (normalized_clip_id, int(now_epoch)),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def release_ragflow_sync_lock(self, clip_id: str | int) -> None:
        with self.connect() as db:
            db.execute("delete from ragflow_sync_locks where clip_id = ?", (str(clip_id),))

    def find_latest_ragflow_sync_job_by_clip_id(self, clip_id: str | int) -> StoredRagflowSyncJob | None:
        with self.connect() as db:
            row = db.execute(
                """
                select * from ragflow_sync_jobs
                where clip_id = ?
                order by id desc
                limit 1
                """,
                (str(clip_id),),
            ).fetchone()
        return self._row_to_sync_job(row) if row else None

    def find_latest_ragflow_sync_job_by_request_id(self, client_request_id: str) -> StoredRagflowSyncJob | None:
        normalized_request_id = normalize_client_request_id(client_request_id)
        if normalized_request_id is None:
            return None
        with self.connect() as db:
            row = db.execute(
                """
                select * from ragflow_sync_jobs
                where client_request_id = ?
                order by id desc
                limit 1
                """,
                (normalized_request_id,),
            ).fetchone()
        return self._row_to_sync_job(row) if row else None

    def list_clips_pending_ragflow_sync(self, *, limit: int) -> list[StoredClipRawFields]:
        return self.list_raw_fields_after_clip_id(after_id=0, limit=limit)

    def list_raw_fields_after_clip_id(self, *, after_id: int, limit: int) -> list[StoredClipRawFields]:
        with self.connect() as db:
            rows = db.execute(
                """
                select c.* from clips c
                where c.id > ?
                order by c.id asc
                limit ?
                """,
                (int(after_id), int(limit)),
            ).fetchall()
        return [self._row_to_raw_fields(row) for row in rows]

    def list_recall_raw_rows_for_window(
        self,
        start: str,
        end: str,
        *,
        end_exclusive: bool = False,
        knowledge_base_id: str = "",
    ) -> list[tuple[StoredClipRawFields, str]]:
        """Return Recall inputs, optionally scoped to one active Knowledge Base."""
        end_operator = "<" if end_exclusive else "<="
        normalized_knowledge_base_id = knowledge_base_id.strip()
        name_expression = "kb.name"
        scope_clause = ""
        parameters: list[object] = [start, end, start, end]
        if normalized_knowledge_base_id:
            # A clip may be associated with more than one Knowledge Base. The
            # scope uses the association table rather than the latest route
            # decision so each selected library gets its own planet.
            name_expression = "(select scoped_kb.name from knowledge_bases scoped_kb where scoped_kb.id = ?)"
            scope_clause = """
                  and (
                      exists (
                          select 1 from clip_knowledge_bases scoped_ckb
                          where scoped_ckb.clip_id = c.id
                            and scoped_ckb.knowledge_base_id = ?
                      )
                      or exists (
                          select 1 from clip_enrichments scoped_e
                          where scoped_e.clip_id = cast(c.id as text)
                            and scoped_e.knowledge_base_id = ?
                            and scoped_e.status = 'completed'
                      )
                  )
            """
            parameters = [normalized_knowledge_base_id, *parameters, normalized_knowledge_base_id, normalized_knowledge_base_id]
        with self.connect() as db:
            rows = db.execute(
                f"""
                select c.*, {name_expression} as knowledge_base_name
                from clips c
                left join clip_route_decisions rd on rd.id = (
                    select inner_rd.id from clip_route_decisions inner_rd
                    where inner_rd.clip_id = cast(c.id as text)
                    order by inner_rd.id desc limit 1
                )
                left join knowledge_bases kb on kb.id = rd.knowledge_base_id
                where ((c.created_at >= ? and c.created_at {end_operator} ?)
                   or (c.captured_at >= ? and c.captured_at {end_operator} ?))
                  {scope_clause}
                order by c.id asc
                """,
                parameters,
            ).fetchall()
        return [
            (self._row_to_raw_fields(row), str(row["knowledge_base_name"] or ""))
            for row in rows
        ]

    def find_recall_raw_row_by_clip_id(
        self, clip_id: str | int
    ) -> tuple[StoredClipRawFields, str] | None:
        """Return a single Recall input; the shared domain resolver selects content."""
        with self.connect() as db:
            row = db.execute(
                """
                select c.*, kb.name as knowledge_base_name
                from clips c
                left join clip_route_decisions rd on rd.id = (
                    select inner_rd.id from clip_route_decisions inner_rd
                    where inner_rd.clip_id = cast(c.id as text)
                    order by inner_rd.id desc limit 1
                )
                left join knowledge_bases kb on kb.id = rd.knowledge_base_id
                where c.id = ?
                """,
                (str(clip_id),),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_raw_fields(row), str(row["knowledge_base_name"] or "")

    def list_recall_source_rows_for_window(self, start: str, end: str, *, end_exclusive: bool = False) -> list[tuple[StoredClipRawFields, StoredClipEnrichment | None, str]]:
        """Return plausible rows using the active enrichment, or legacy latest-completed fallback."""
        end_operator = "<" if end_exclusive else "<="
        with self.connect() as db:
            rows = db.execute(
                f"""
                select c.*, kb.name as knowledge_base_name,
                    coalesce(json_extract(cm.metadata_json, '$.clip.url'), '') as active_url,
                    case
                        when json_extract(cm.metadata_json, '$.processing.active_enrichment_id') is not null
                         and not exists (
                            select 1 from clip_enrichments active_e
                            where active_e.id = cast(json_extract(cm.metadata_json, '$.processing.active_enrichment_id') as integer)
                              and active_e.clip_id = cast(c.id as text)
                         )
                        then 1 else 0
                    end as active_enrichment_invalid,
                    e.id as enrichment_id, e.clip_id as enrichment_clip_id,
                    e.client_request_id as enrichment_client_request_id,
                    e.knowledge_base_id as enrichment_knowledge_base_id,
                    e.route_decision_id as enrichment_route_decision_id,
                    e.engine as enrichment_engine, e.status as enrichment_status,
                    e.title as enrichment_title, e.summary as enrichment_summary,
                    e.tags_json as enrichment_tags_json, e.key_points_json as enrichment_key_points_json,
                    e.language as enrichment_language,
                    e.extracted_text as enrichment_extracted_text,
                    e.error_code as enrichment_error_code, e.error_message as enrichment_error_message,
                    e.created_at as enrichment_created_at, e.updated_at as enrichment_updated_at
                from clips c
                left join clip_metadata cm on cm.clip_id = c.id
                left join clip_route_decisions rd on rd.id = (
                    select inner_rd.id from clip_route_decisions inner_rd
                    where inner_rd.clip_id = cast(c.id as text) order by inner_rd.id desc limit 1
                )
                left join knowledge_bases kb on kb.id = rd.knowledge_base_id
                left join clip_enrichments e
                  on e.clip_id = cast(c.id as text)
                 and e.id = case
                    when json_extract(cm.metadata_json, '$.processing.active_enrichment_id') is not null
                    then cast(json_extract(cm.metadata_json, '$.processing.active_enrichment_id') as integer)
                    else (
                        select inner_e.id from clip_enrichments inner_e
                        where inner_e.clip_id = cast(c.id as text) and inner_e.status = 'completed'
                        order by inner_e.id desc limit 1
                    )
                 end
                where (c.created_at >= ? and c.created_at {end_operator} ?)
                   or (c.captured_at >= ? and c.captured_at {end_operator} ?)
                order by c.id asc
                """
            , (start, end, start, end)).fetchall()
        result: list[tuple[StoredClipRawFields, StoredClipEnrichment | None, str]] = []
        for row in rows:
            raw = self._row_to_raw_fields(row)
            result.append((raw, self._row_to_joined_recall_enrichment(row), str(row["knowledge_base_name"] or "")))
        return result

    def find_recall_source_row_by_clip_id(self, clip_id: str | int) -> tuple[StoredClipRawFields, StoredClipEnrichment | None, str] | None:
        with self.connect() as db:
            row = db.execute(
                """select c.*, kb.name as knowledge_base_name,
                    coalesce(json_extract(cm.metadata_json, '$.clip.url'), '') as active_url,
                    case
                        when json_extract(cm.metadata_json, '$.processing.active_enrichment_id') is not null
                         and not exists (select 1 from clip_enrichments active_e where active_e.id = cast(json_extract(cm.metadata_json, '$.processing.active_enrichment_id') as integer) and active_e.clip_id = cast(c.id as text))
                        then 1 else 0
                    end as active_enrichment_invalid,
                    e.id as enrichment_id, e.clip_id as enrichment_clip_id, e.client_request_id as enrichment_client_request_id,
                    e.knowledge_base_id as enrichment_knowledge_base_id, e.route_decision_id as enrichment_route_decision_id,
                    e.engine as enrichment_engine, e.status as enrichment_status, e.title as enrichment_title,
                    e.summary as enrichment_summary, e.tags_json as enrichment_tags_json,
                    e.key_points_json as enrichment_key_points_json, e.language as enrichment_language,
                    e.extracted_text as enrichment_extracted_text, e.error_code as enrichment_error_code,
                    e.error_message as enrichment_error_message, e.created_at as enrichment_created_at, e.updated_at as enrichment_updated_at
                    from clips c
                    left join clip_metadata cm on cm.clip_id = c.id
                    left join clip_route_decisions rd on rd.id = (select inner_rd.id from clip_route_decisions inner_rd where inner_rd.clip_id = cast(c.id as text) order by inner_rd.id desc limit 1)
                    left join knowledge_bases kb on kb.id = rd.knowledge_base_id
                    left join clip_enrichments e
                      on e.clip_id = cast(c.id as text)
                     and e.id = case
                        when json_extract(cm.metadata_json, '$.processing.active_enrichment_id') is not null
                        then cast(json_extract(cm.metadata_json, '$.processing.active_enrichment_id') as integer)
                        else (select inner_e.id from clip_enrichments inner_e where inner_e.clip_id = cast(c.id as text) and inner_e.status = 'completed' order by inner_e.id desc limit 1)
                     end
                    where c.id = ?""",
                (str(clip_id),),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_raw_fields(row), self._row_to_joined_recall_enrichment(row), str(row["knowledge_base_name"] or "")

    def recall_enrichment_resolution(self, clip_id: str | int) -> dict[str, object]:
        """Expose active-vs-legacy Recall selection without silently healing a broken pointer."""
        with self.connect() as db:
            row = db.execute(
                """
                select
                    json_extract(cm.metadata_json, '$.processing.active_enrichment_id') as active_enrichment_id,
                    case
                        when json_extract(cm.metadata_json, '$.processing.active_enrichment_id') is not null
                        then (
                            select e.id from clip_enrichments e
                            where e.id = cast(json_extract(cm.metadata_json, '$.processing.active_enrichment_id') as integer)
                              and e.clip_id = cast(c.id as text)
                        )
                        else (
                            select e.id from clip_enrichments e
                            where e.clip_id = cast(c.id as text) and e.status = 'completed'
                            order by e.id desc limit 1
                        )
                    end as selected_enrichment_id
                from clips c
                left join clip_metadata cm on cm.clip_id = c.id
                where c.id = ?
                """,
                (str(clip_id),),
            ).fetchone()
        if row is None:
            return {
                "status": "clip_not_found",
                "active_enrichment_id": None,
                "selected_enrichment_id": None,
            }
        active_id = row["active_enrichment_id"]
        selected_id = row["selected_enrichment_id"]
        if active_id is not None:
            status = "active" if selected_id is not None else "missing_active_enrichment"
        else:
            status = "legacy_latest_completed" if selected_id is not None else "no_enrichment"
        return {
            "status": status,
            "active_enrichment_id": int(active_id) if active_id is not None else None,
            "selected_enrichment_id": int(selected_id) if selected_id is not None else None,
        }

    def create_recall_session(self, *, session_id: str, days: int, topic_id: str, items: list[dict[str, object]], window_start: str, window_end: str, snapshot_key: str) -> StoredRecallSession:
        now = datetime.now(timezone.utc).isoformat(); kind = "topic" if topic_id else "general"
        with self.connect() as db:
            db.execute("insert into recall_sessions (id, days, kind, topic_id, window_start, window_end, snapshot_key, status, total_items, current_position, created_at, updated_at, completed_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (session_id, int(days), kind, topic_id, window_start, window_end, snapshot_key, "completed" if not items else "active", len(items), 0 if not items else 1, now, now, now if not items else ""))
            for position, item in enumerate(items, start=1):
                db.execute("insert into recall_session_items (id, session_id, clip_id, client_request_id, topic_id, position, status, score, title, cue, reveal_text, summary, tags_json, source_type, source_label, knowledge_base_name, captured_at, recall_count_before, created_at, updated_at) values (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (str(item["id"]), session_id, str(item["clip_id"]), str(item.get("client_request_id", "")), str(item.get("topic_id", "")), position, float(item.get("score", 0)), str(item.get("title", "")), str(item.get("cue", "")), str(item.get("reveal_text", "")), str(item.get("summary", "")), json.dumps(item.get("tags", []), ensure_ascii=False), str(item.get("source_type", "")), str(item.get("source_label", "")), str(item.get("knowledge_base_name", "")), str(item.get("captured_at", "")), int(item.get("recall_count_before", 0)), now, now))
            row = db.execute("select * from recall_sessions where id = ?", (session_id,)).fetchone()
        return self._row_to_recall_session(row)

    def find_active_recall_session(self, *, snapshot_key: str, topic_id: str) -> StoredRecallSession | None:
        with self.connect() as db: row = db.execute("select * from recall_sessions where snapshot_key = ? and topic_id = ? and status = 'active' order by created_at desc limit 1", (snapshot_key, topic_id)).fetchone()
        return self._row_to_recall_session(row) if row else None

    def find_recall_session(self, session_id: str) -> StoredRecallSession | None:
        with self.connect() as db:
            row = db.execute("select * from recall_sessions where id = ?", (session_id,)).fetchone()
        return self._row_to_recall_session(row) if row else None

    def list_recall_items(self, session_id: str) -> list[StoredRecallItem]:
        with self.connect() as db:
            rows = db.execute("select * from recall_session_items where session_id = ? order by position asc", (session_id,)).fetchall()
        return [self._row_to_recall_item(row) for row in rows]

    def record_recall_action(self, *, session_id: str, item_id: str, action: str, client_action_id: str) -> tuple[StoredRecallItem, bool]:
        if action not in {"reveal", "remembered", "later", "open_original"}:
            raise ValueError("invalid recall action")
        if not client_action_id or len(client_action_id) > 128: raise ValueError("invalid client action id")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            replay = db.execute("select * from recall_events where client_action_id = ?", (client_action_id,)).fetchone()
            if replay:
                if str(replay["session_id"]) != session_id or str(replay["item_id"]) != item_id or str(replay["action"]) != action:
                    raise RecallActionCollisionError("client_action_id already used for another recall action")
                row = db.execute("select * from recall_session_items where id = ?", (str(replay["item_id"]),)).fetchone()
                if row is None: raise RecallItemNotFoundError("recall item not found")
                return self._row_to_recall_item(row), True
            row = db.execute("select * from recall_session_items where session_id = ? and id = ?", (session_id, str(item_id))).fetchone()
            if row is None:
                raise RecallItemNotFoundError("recall item not found")
            if action in {"remembered", "later"} and str(row["status"]) != "pending":
                return self._row_to_recall_item(row), True
            try:
                db.execute("insert into recall_events (client_action_id, session_id, item_id, clip_id, action, created_at) values (?, ?, ?, ?, ?, ?)", (client_action_id, session_id, item_id, str(row["clip_id"]), action, now))
            except sqlite3.IntegrityError:
                replay = db.execute("select * from recall_events where client_action_id = ?", (client_action_id,)).fetchone()
                if replay is None:
                    raise
                if str(replay["session_id"]) != session_id or str(replay["item_id"]) != item_id or str(replay["action"]) != action:
                    raise RecallActionCollisionError("client_action_id already used for another recall action")
                return self._row_to_recall_item(row), True
            if action in {"remembered", "later"} and row["status"] == "pending": db.execute("update recall_session_items set status = ?, updated_at = ?, acted_at = ? where id = ?", (action, now, now, item_id))
            remaining = db.execute("select count(*) from recall_session_items where session_id = ? and status = 'pending'", (session_id,)).fetchone()[0]
            next_row = db.execute("select position from recall_session_items where session_id = ? and status = 'pending' order by position limit 1", (session_id,)).fetchone()
            db.execute("update recall_sessions set status = ?, current_position = ?, updated_at = ?, completed_at = ? where id = ?", ("completed" if remaining == 0 else "active", 0 if not next_row else int(next_row["position"]), now, now if remaining == 0 else "", session_id))
            updated = db.execute("select * from recall_session_items where id = ?", (item_id,)).fetchone()
        return self._row_to_recall_item(updated), False

    def recalled_clip_ids_since(self, since: str) -> set[str]:
        with self.connect() as db:
            rows = db.execute("select distinct clip_id from recall_events where action in ('remembered', 'later') and created_at >= ?", (since,)).fetchall()
        return {str(row["clip_id"]) for row in rows}

    def recall_metrics_since(self, since: str) -> dict[str, int]:
        with self.connect() as db:
            events = int(db.execute("select count(*) from recall_events where action = 'remembered' and created_at >= ?", (since,)).fetchone()[0])
            recalled = int(db.execute("select count(distinct clip_id) from recall_events where action in ('remembered', 'later') and created_at >= ?", (since,)).fetchone()[0])
        return {"recall_count": events, "recalled_clip_count": recalled}

    def recall_counts_by_clip(self) -> dict[str, int]:
        with self.connect() as db: rows = db.execute("select clip_id, count(*) as count from recall_events where action = 'remembered' group by clip_id").fetchall()
        return {str(row["clip_id"]): int(row["count"]) for row in rows}

    def recall_history_stats(self, clip_ids: list[str]) -> dict[str, dict[str, object]]:
        if not clip_ids: return {}
        marks = ",".join("?" for _ in clip_ids)
        with self.connect() as db:
            rows = db.execute(f"select clip_id, count(*) as recall_count, max(created_at) as last_recalled_at from recall_events where action='remembered' and clip_id in ({marks}) group by clip_id", clip_ids).fetchall()
        return {str(row["clip_id"]): {"recall_count": int(row["recall_count"]), "last_recalled_at": str(row["last_recalled_at"] or "")} for row in rows}

    def recall_counts_by_clip_since(self, since: str) -> dict[str, int]:
        with self.connect() as db:
            rows = db.execute("select clip_id, count(*) as count from recall_events where action = 'remembered' and created_at >= ? group by clip_id", (since,)).fetchall()
        return {str(row["clip_id"]): int(row["count"]) for row in rows}

    def recall_preferences(self) -> dict[str, object]:
        with self.connect() as db:
            row = db.execute("select * from recall_preferences where user_id = 'default'").fetchone()
        return {"visible_label_count": int(row["visible_label_count"]), "label_rotation_seconds": int(row["label_rotation_seconds"]), "default_days": int(row["default_days"]), "preferred_topic_ids": json.loads(str(row["preferred_topic_ids_json"])), "muted_topic_ids": json.loads(str(row["muted_topic_ids_json"])), "include_memory_labels": bool(row["include_memory_labels"]), "updated_at": str(row["updated_at"])}

    def update_recall_preferences(self, values: dict[str, object]) -> dict[str, object]:
        current = self.recall_preferences(); current.update(values); current["preferred_topic_ids"] = [item for item in current["preferred_topic_ids"] if item not in set(current["muted_topic_ids"])]; now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute("update recall_preferences set visible_label_count=?, label_rotation_seconds=?, default_days=?, preferred_topic_ids_json=?, muted_topic_ids_json=?, include_memory_labels=?, updated_at=? where user_id='default'", (current["visible_label_count"], current["label_rotation_seconds"], current["default_days"], json.dumps(current["preferred_topic_ids"], ensure_ascii=False), json.dumps(current["muted_topic_ids"], ensure_ascii=False), int(bool(current["include_memory_labels"])), now))
        return self.recall_preferences()

    def record_recall_surface_event(
        self,
        *,
        client_event_id: str,
        surface: str,
        action: str,
        node_id: str,
        topic_id: str,
        clip_id: str,
        session_id: str,
        metadata: dict[str, object],
        occurred_at: str,
        suppressed: bool | None = None,
        fault_after_event_insert: Callable[[], None] | None = None,
    ) -> tuple[dict[str, object], bool]:
        """Persist an interaction and its suppression effect atomically.

        Replays return before touching suppression state, so an old suppress
        replay cannot overwrite a later restore (or vice versa). The optional
        hook exists solely for transaction fault-injection tests.
        """
        now = datetime.now(timezone.utc).isoformat(); incoming = {"surface": surface, "action": action, "node_id": node_id, "topic_id": topic_id, "clip_id": clip_id, "session_id": session_id, "metadata": metadata, "occurred_at": occurred_at}
        with self.connect() as db:
            row = db.execute("select * from recall_surface_events where client_event_id=?", (client_event_id,)).fetchone()
            if row:
                existing = {"surface": str(row["surface"]), "action": str(row["action"]), "node_id": str(row["node_id"]), "topic_id": str(row["topic_id"]), "clip_id": str(row["clip_id"]), "session_id": str(row["session_id"]), "metadata": json.loads(str(row["metadata_json"])), "occurred_at": str(row["occurred_at"])}
                if existing != incoming: raise RecallActionCollisionError("client_event_id already used for another interaction")
                return {"id": int(row["id"]), "client_event_id": client_event_id}, True
            db.execute("insert into recall_surface_events (client_event_id,surface,action,node_id,topic_id,clip_id,session_id,metadata_json,occurred_at,created_at) values (?,?,?,?,?,?,?,?,?,?)", (client_event_id, surface, action, node_id, topic_id, clip_id, session_id, json.dumps(metadata, ensure_ascii=False, sort_keys=True), occurred_at, now))
            identifier = int(db.execute("select last_insert_rowid()").fetchone()[0])
            if fault_after_event_insert is not None:
                fault_after_event_insert()
            if suppressed is not None:
                db.execute(
                    """insert into recall_suppressions (clip_id, suppressed, updated_at)
                       values (?, ?, ?)
                       on conflict(clip_id) do update set
                         suppressed=excluded.suppressed,
                         updated_at=excluded.updated_at""",
                    (clip_id, int(suppressed), now),
                )
        return {"id": identifier, "client_event_id": client_event_id}, False

    def set_recall_suppressed(self, clip_id: str, suppressed: bool) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute(
                """insert into recall_suppressions (clip_id, suppressed, updated_at)
                   values (?, ?, ?)
                   on conflict(clip_id) do update set
                     suppressed=excluded.suppressed,
                     updated_at=excluded.updated_at""",
                (clip_id, int(suppressed), now),
            )

    def suppressed_recall_clip_ids(self, clip_ids: list[str] | None = None) -> set[str]:
        with self.connect() as db:
            if clip_ids is None:
                rows = db.execute(
                    "select clip_id from recall_suppressions where suppressed=1 order by updated_at desc, clip_id"
                ).fetchall()
            elif not clip_ids:
                return set()
            else:
                marks = ",".join("?" for _ in clip_ids)
                rows = db.execute(
                    f"select clip_id from recall_suppressions where suppressed=1 and clip_id in ({marks})",
                    clip_ids,
                ).fetchall()
        return {str(row["clip_id"]) for row in rows}

    def recall_suppressions(
        self,
        *,
        limit: int = 50,
        after_updated_at: str = "",
        after_clip_id: str = "",
        direction: str = "next",
    ) -> list[dict[str, str]]:
        where = "where suppressed=1"
        values: list[object] = []
        if after_updated_at:
            if direction == "previous":
                where += " and (updated_at > ? or (updated_at = ? and clip_id < ?))"
            else:
                where += " and (updated_at < ? or (updated_at = ? and clip_id > ?))"
            values.extend((after_updated_at, after_updated_at, after_clip_id))
        values.append(limit)
        ordering = (
            "updated_at asc, clip_id desc"
            if direction == "previous"
            else "updated_at desc, clip_id"
        )
        with self.connect() as db:
            rows = db.execute(
                f"""select clip_id, updated_at from recall_suppressions
                    {where}
                    order by {ordering}
                    limit ?""",
                values,
            ).fetchall()
        return [
            {"clip_id": str(row["clip_id"]), "suppressed_at": str(row["updated_at"])}
            for row in rows
        ]

    def recall_surface_stats(self, clip_ids: list[str]) -> dict[str, dict[str, object]]:
        if not clip_ids: return {}
        marks = ",".join("?" for _ in clip_ids)
        with self.connect() as db:
            rows = db.execute(f"select clip_id, max(case when action='viewed' then coalesce(nullif(occurred_at,''),created_at) end) as last_viewed_at, max(case when action='defer' then coalesce(nullif(occurred_at,''),created_at) end) as last_deferred_at, sum(case when action='viewed' then 1 else 0 end) as view_count, sum(case when action='defer' then 1 else 0 end) as defer_count, sum(case when action='open_original' then 1 else 0 end) as opened_original_count, sum(case when action in ('impression','label_impression') then 1 else 0 end) as impression_count from recall_surface_events where clip_id in ({marks}) group by clip_id", clip_ids).fetchall()
        suppressed = self.suppressed_recall_clip_ids(clip_ids)
        result = {str(row["clip_id"]): {"last_viewed_at": str(row["last_viewed_at"] or ""), "last_deferred_at": str(row["last_deferred_at"] or ""), "view_count": int(row["view_count"] or 0), "defer_count": int(row["defer_count"] or 0), "opened_original_count":int(row["opened_original_count"] or 0), "impression_count":int(row["impression_count"] or 0), "suppressed": str(row["clip_id"]) in suppressed} for row in rows}
        for clip_id in suppressed:
            result.setdefault(clip_id, {"last_viewed_at": "", "last_deferred_at": "", "view_count": 0, "defer_count": 0, "opened_original_count": 0, "impression_count": 0, "suppressed": True})
        return result

    @staticmethod
    def _row_to_clip(row: sqlite3.Row, duplicate: bool) -> StoredClip:
        return StoredClip(
            id=int(row["id"]),
            duplicate=duplicate,
            title=str(row["title_hint"]),
            platform="android_share",
            original_path=str(row["original_path"]),
            content_hash=str(row["content_hash"]),
            filename=str(row["filename"]),
            size_bytes=int(row["size_bytes"]),
            ragflow_document_id=str(row["ragflow_document_id"]),
            archive_status=str(row["archive_status"]),
            capture_client_batch_id=str(row["capture_client_batch_id"] or ""),
            capture_parent_client_request_id=str(row["capture_parent_client_request_id"] or ""),
            capture_part_index=int(row["capture_part_index"]),
            capture_part_count=int(row["capture_part_count"]),
            capture_part_role=str(row["capture_part_role"] or "single"),
            client_request_id=str(row["client_request_id"] or ""),
        )

    @staticmethod
    def _row_to_metadata(row: sqlite3.Row) -> StoredClipMetadata:
        metadata = loads_normalized_metadata(str(row["metadata_json"]))
        return StoredClipMetadata(
            clip_id=int(row["clip_id"]),
            client_request_id=str(row["client_request_id"]),
            contract_version=str(row["contract_version"]),
            metadata=metadata,
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _row_to_raw_fields(row: sqlite3.Row) -> StoredClipRawFields:
        return StoredClipRawFields(
            id=int(row["id"]),
            client_request_id=str(row["client_request_id"] or ""),
            source_type=str(row["source_type"]),
            title_hint=str(row["title_hint"]),
            note=str(row["note"]),
            text=str(row["text"]),
            url=str(row["url"]),
            mime_type=str(row["mime_type"]),
            device_name=str(row["device_name"]),
            source_app=str(row["source_app"]),
            captured_at=str(row["captured_at"]),
            filename=str(row["filename"]),
            size_bytes=int(row["size_bytes"]),
            original_path=str(row["original_path"]),
            content_hash=str(row["content_hash"]),
            ragflow_document_id=str(row["ragflow_document_id"]),
            archive_status=str(row["archive_status"]),
            created_at=str(row["created_at"]),
            capture_client_batch_id=str(row["capture_client_batch_id"] or ""),
            capture_parent_client_request_id=str(row["capture_parent_client_request_id"] or ""),
            capture_part_index=int(row["capture_part_index"]),
            capture_part_count=int(row["capture_part_count"]),
            capture_part_role=str(row["capture_part_role"] or "single"),
            active_url=str(row["active_url"] or "") if "active_url" in row.keys() else "",
            active_enrichment_invalid=bool(row["active_enrichment_invalid"]) if "active_enrichment_invalid" in row.keys() else False,
        )

    @staticmethod
    def _row_to_capture_part_attempt(row: sqlite3.Row) -> StoredCapturePartAttempt:
        return StoredCapturePartAttempt(
            client_batch_id=str(row["client_batch_id"]),
            parent_client_request_id=str(row["parent_client_request_id"]),
            client_request_id=str(row["client_request_id"]),
            part_index=int(row["part_index"]),
            part_count=int(row["part_count"]),
            part_role=str(row["part_role"]),
            status=str(row["status"]),
            error_code=str(row["error_code"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _row_to_ingest_receipt(row: sqlite3.Row) -> StoredIngestReceipt:
        return StoredIngestReceipt(
            receipt_id=row["receipt_id"], client_request_id=row["client_request_id"],
            clip_id=row["clip_id"], contract_version=row["contract_version"],
            source_adapter=row["source_adapter"], request_signature=row["request_signature"],
            status=row["status"], archive_status=row["archive_status"],
            metadata_status=row["metadata_status"],
            error_code=row["error_code"],
            capture_client_batch_id=row["capture_client_batch_id"],
            capture_parent_client_request_id=row["capture_parent_client_request_id"],
            capture_part_index=row["capture_part_index"], capture_part_count=row["capture_part_count"],
            capture_part_role=row["capture_part_role"],
            target_knowledge_base_id=row["target_knowledge_base_id"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_enrichment(row: sqlite3.Row) -> StoredClipEnrichment:
        tags = json.loads(str(row["tags_json"]))
        key_points = json.loads(str(row["key_points_json"]))
        if not isinstance(tags, list):
            tags = []
        return StoredClipEnrichment(
            id=int(row["id"]),
            clip_id=str(row["clip_id"]),
            client_request_id=str(row["client_request_id"]),
            knowledge_base_id=str(row["knowledge_base_id"]),
            route_decision_id=int(row["route_decision_id"]) if row["route_decision_id"] is not None else None,
            engine=str(row["engine"]),
            status=str(row["status"]),
            title=str(row["title"]),
            summary=str(row["summary"]),
            tags=[str(tag) for tag in tags],
            key_points=[str(point) for point in key_points] if isinstance(key_points, list) else [],
            language=str(row["language"]),
            extracted_text=str(row["extracted_text"]),
            error_code=str(row["error_code"]),
            error_message=str(row["error_message"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _row_to_joined_recall_enrichment(row: sqlite3.Row) -> StoredClipEnrichment | None:
        if row["enrichment_id"] is None:
            return None
        tags = json.loads(str(row["enrichment_tags_json"]))
        key_points = json.loads(str(row["enrichment_key_points_json"]))
        return StoredClipEnrichment(id=int(row["enrichment_id"]), clip_id=str(row["enrichment_clip_id"]), client_request_id=str(row["enrichment_client_request_id"]), knowledge_base_id=str(row["enrichment_knowledge_base_id"]), route_decision_id=int(row["enrichment_route_decision_id"]) if row["enrichment_route_decision_id"] is not None else None, engine=str(row["enrichment_engine"]), status=str(row["enrichment_status"]), title=str(row["enrichment_title"]), summary=str(row["enrichment_summary"]), tags=[str(tag) for tag in tags] if isinstance(tags, list) else [], key_points=[str(point) for point in key_points] if isinstance(key_points, list) else [], language=str(row["enrichment_language"]), extracted_text=str(row["enrichment_extracted_text"]), error_code=str(row["enrichment_error_code"]), error_message=str(row["enrichment_error_message"]), created_at=str(row["enrichment_created_at"]), updated_at=str(row["enrichment_updated_at"]))

    @staticmethod
    def _row_to_sync_job(row: sqlite3.Row) -> StoredRagflowSyncJob:
        plan = json.loads(str(row["plan_json"]))
        if not isinstance(plan, dict):
            plan = {}
        return StoredRagflowSyncJob(
            id=int(row["id"]),
            clip_id=str(row["clip_id"]),
            client_request_id=str(row["client_request_id"]),
            knowledge_base_id=str(row["knowledge_base_id"]),
            ragflow_dataset_id=str(row["ragflow_dataset_id"]),
            ragflow_document_id=str(row["ragflow_document_id"]),
            route_decision_id=int(row["route_decision_id"]) if row["route_decision_id"] is not None else None,
            enrichment_id=int(row["enrichment_id"]) if row["enrichment_id"] is not None else None,
            operation=str(row["operation"]),
            status=str(row["status"]),
            dry_run=bool(row["dry_run"]),
            reason=str(row["reason"]),
            plan=plan,
            remote_document_changed=bool(row["remote_document_changed"]),
            attempt_key=str(row["attempt_key"]),
            phase=str(row["phase"]),
            error_code=str(row["error_code"]),
            error_message=str(row["error_message"]),
            started_at=str(row["started_at"]),
            finished_at=str(row["finished_at"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _row_to_recall_session(row: sqlite3.Row) -> StoredRecallSession:
        return StoredRecallSession(id=str(row["id"]), days=int(row["days"]), kind=str(row["kind"]), topic_id=str(row["topic_id"]), window_start=str(row["window_start"]), window_end=str(row["window_end"]), snapshot_key=str(row["snapshot_key"]), status=str(row["status"]), total_items=int(row["total_items"]), current_position=int(row["current_position"]), created_at=str(row["created_at"]), updated_at=str(row["updated_at"]), completed_at=str(row["completed_at"]))

    @staticmethod
    def _row_to_recall_item(row: sqlite3.Row) -> StoredRecallItem:
        tags = json.loads(str(row["tags_json"]))
        return StoredRecallItem(id=str(row["id"]), session_id=str(row["session_id"]), clip_id=str(row["clip_id"]), client_request_id=str(row["client_request_id"]), topic_id=str(row["topic_id"]), position=int(row["position"]), state=str(row["status"]), score=float(row["score"]), title=str(row["title"]), cue=str(row["cue"]), reveal_text=str(row["reveal_text"]), summary=str(row["summary"]), tags=[str(tag) for tag in tags] if isinstance(tags, list) else [], source_type=str(row["source_type"]), source_label=str(row["source_label"]), knowledge_base_name=str(row["knowledge_base_name"]), captured_at=str(row["captured_at"]), recall_count_before=int(row["recall_count_before"]), created_at=str(row["created_at"]), updated_at=str(row["updated_at"]), acted_at=str(row["acted_at"]))

    @staticmethod
    def _ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in db.execute(f"pragma table_info({table})")}
        if column not in columns:
            db.execute(f"alter table {table} add column {column} {definition}")


def sanitize_filename(name: str) -> str:
    safe = SAFE_NAME_RE.sub("_", Path(name).name).strip("._ ")
    return safe[:120] or "perclip_upload"


def normalize_client_request_id(client_request_id: str) -> str | None:
    value = client_request_id.strip()
    return value or None


def unique_path(folder: Path, safe_name: str, content_hash: str) -> Path:
    candidate = folder / safe_name
    if not candidate.exists():
        return candidate

    suffix = candidate.suffix
    stem = candidate.name[: -len(suffix)] if suffix else candidate.name
    digest = content_hash[:10]

    for index in range(2, 1000):
        unique_name = f"{stem}-{digest}" if index == 2 else f"{stem}-{digest}-{index}"
        unique_candidate = folder / f"{unique_name}{suffix}"
        if not unique_candidate.exists():
            return unique_candidate

    raise RuntimeError(f"Unable to allocate unique upload path for {safe_name}")
