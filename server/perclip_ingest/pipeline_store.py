from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .ragflow_index import LOCAL_INDEX_STATUSES, REMOTE_DOCUMENT_STATUSES


PIPELINE_STAGES = (
    "archive_original",
    "extract",
    "clean",
    "enrich",
    "classify_topic",
    "route",
    "index",
)
KNOWLEDGE_CURSOR_TTL = timedelta(hours=24)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


@dataclass(frozen=True)
class StoredPipelineJob:
    id: int
    job_key: str
    clip_id: str
    stage: str
    engine: str
    engine_version: str
    input_hash: str
    payload: dict[str, object]
    status: str
    attempt_count: int
    max_attempts: int
    available_at: str
    lease_token: str
    lease_expires_at: str
    safe_error_code: str
    output_asset_id: str
    created_at: str
    updated_at: str


class PipelineStore:
    """Durable unified pipeline state stored beside the canonical clip tables."""

    def __init__(
        self,
        data_dir: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.db_path = data_dir / "perclip.sqlite3"
        self._clock = clock or utc_now

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("pipeline clock must return a timezone-aware datetime")
        return value

    def connect(self) -> sqlite3.Connection:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("pragma foreign_keys=on")
        db.execute("pragma journal_mode=wal")
        return db

    def init(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                create table if not exists clip_identities (
                    clip_id integer primary key,
                    public_id text unique not null,
                    created_at text not null,
                    foreign key (clip_id) references clips(id)
                );

                create table if not exists source_events (
                    id text primary key,
                    event_key text unique not null,
                    clip_id integer not null,
                    adapter text not null,
                    client_id text not null default '',
                    event_id text not null default '',
                    source_app text not null default '',
                    occurred_at text not null default '',
                    deployment_environment text not null,
                    created_at text not null,
                    foreign key (clip_id) references clips(id)
                );
                create index if not exists idx_source_events_clip on source_events(clip_id, created_at);

                create table if not exists assets (
                    id text primary key,
                    clip_id integer not null,
                    role text not null,
                    filename text not null default '',
                    mime_type text not null default '',
                    size_bytes integer not null default 0,
                    content_hash text not null,
                    storage_uri text not null,
                    engine text not null default '',
                    engine_version text not null default '',
                    metadata_json text not null default '{}',
                    created_at text not null,
                    foreign key (clip_id) references clips(id),
                    unique (clip_id, role, content_hash, engine_version)
                );
                create index if not exists idx_assets_clip_role on assets(clip_id, role, created_at);

                create table if not exists clip_knowledge_bases (
                    clip_id integer not null,
                    knowledge_base_id text not null,
                    association_type text not null,
                    route_decision_id integer,
                    association_intent_id text not null default '',
                    created_at text not null,
                    primary key (clip_id, knowledge_base_id),
                    foreign key (clip_id) references clips(id),
                    foreign key (knowledge_base_id) references knowledge_bases(id)
                );

                create table if not exists knowledge_read_cursors (
                    token text primary key,
                    knowledge_base_id text not null,
                    after_clip_id integer not null,
                    created_at text not null,
                    foreign key (knowledge_base_id) references knowledge_bases(id),
                    foreign key (after_clip_id) references clips(id)
                );
                create index if not exists idx_knowledge_read_cursors_scope
                    on knowledge_read_cursors(knowledge_base_id, created_at);

                create table if not exists processing_runs (
                    id integer primary key autoincrement,
                    clip_id integer not null,
                    stage text not null,
                    engine text not null,
                    engine_version text not null,
                    input_hash text not null,
                    status text not null,
                    attempt_count integer not null,
                    started_at text not null,
                    finished_at text not null default '',
                    safe_error_code text not null default '',
                    output_asset_id text not null default '',
                    created_at text not null,
                    updated_at text not null,
                    foreign key (clip_id) references clips(id),
                    unique (clip_id, stage, engine_version, input_hash)
                );
                create index if not exists idx_processing_runs_clip on processing_runs(clip_id, id);

                create table if not exists index_documents (
                    clip_id integer not null,
                    knowledge_base_id text not null,
                    index_provider text not null,
                    dataset_id text not null,
                    document_id text not null,
                    content_hash text not null default '',
                    status text not null,
                    created_at text not null,
                    updated_at text not null,
                    primary key (clip_id, knowledge_base_id, index_provider, dataset_id),
                    foreign key (clip_id) references clips(id)
                );

                create table if not exists index_attempts (
                    operation_key text primary key,
                    clip_id integer not null,
                    knowledge_base_id text not null,
                    index_provider text not null,
                    dataset_id text not null,
                    association_intent_id text not null default '',
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
                    foreign key (clip_id) references clips(id),
                    unique (
                        clip_id, knowledge_base_id, index_provider, dataset_id,
                        association_intent_id, generation_id, content_hash
                    )
                );
                create index if not exists idx_index_attempts_scope
                    on index_attempts(
                        clip_id, knowledge_base_id, index_provider, dataset_id, updated_at
                    );

                create table if not exists active_indexes (
                    clip_id integer not null,
                    knowledge_base_id text not null,
                    index_provider text not null,
                    dataset_id text not null,
                    operation_key text not null,
                    document_id text not null,
                    generation_id text not null,
                    content_hash text not null,
                    activated_at text not null,
                    primary key (clip_id, knowledge_base_id, index_provider, dataset_id),
                    foreign key (clip_id) references clips(id),
                    foreign key (operation_key) references index_attempts(operation_key)
                );

                create table if not exists outbox_jobs (
                    id integer primary key autoincrement,
                    job_key text unique not null,
                    clip_id integer not null,
                    stage text not null,
                    engine text not null,
                    engine_version text not null,
                    input_hash text not null,
                    payload_json text not null default '{}',
                    status text not null,
                    attempt_count integer not null default 0,
                    max_attempts integer not null default 5,
                    available_at text not null,
                    lease_token text not null default '',
                    lease_expires_at text not null default '',
                    safe_error_code text not null default '',
                    output_asset_id text not null default '',
                    created_at text not null,
                    updated_at text not null,
                    foreign key (clip_id) references clips(id)
                );
                create index if not exists idx_outbox_jobs_ready
                    on outbox_jobs(status, available_at, id);

                create table if not exists pipeline_control_events (
                    id integer primary key autoincrement,
                    request_id text unique not null,
                    action text not null,
                    clip_id integer not null,
                    job_id integer,
                    result_job_id integer,
                    previous_status text not null default '',
                    previous_attempt_count integer not null default 0,
                    previous_safe_error_code text not null default '',
                    details_json text not null default '{}',
                    created_at text not null,
                    foreign key (clip_id) references clips(id),
                    foreign key (job_id) references outbox_jobs(id),
                    foreign key (result_job_id) references outbox_jobs(id)
                );
                create index if not exists idx_pipeline_control_events_clip
                    on pipeline_control_events(clip_id, id);

                create table if not exists legacy_import_map (
                    legacy_system text not null,
                    legacy_item_id text not null,
                    clip_id integer,
                    source_url text not null default '',
                    source_path_hash text not null default '',
                    content_hash text not null default '',
                    index_provider text not null default '',
                    dataset_id text not null default '',
                    document_id text not null default '',
                    import_status text not null,
                    evidence_json text not null default '{}',
                    created_at text not null,
                    updated_at text not null,
                    primary key (legacy_system, legacy_item_id),
                    foreign key (clip_id) references clips(id)
                );
                """
            )
            attempt_columns = {
                str(row[1])
                for row in db.execute("pragma table_info(index_attempts)").fetchall()
            }
            if "association_intent_id" not in attempt_columns:
                db.executescript(
                    """
                    create table index_attempts_v2 (
                        operation_key text primary key,
                        clip_id integer not null,
                        knowledge_base_id text not null,
                        index_provider text not null,
                        dataset_id text not null,
                        association_intent_id text not null default '',
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
                        foreign key (clip_id) references clips(id),
                        unique (
                            clip_id, knowledge_base_id, index_provider, dataset_id,
                            association_intent_id, generation_id, content_hash
                        )
                    );
                    insert into index_attempts_v2(
                        operation_key, clip_id, knowledge_base_id, index_provider,
                        dataset_id, association_intent_id, generation_id, document_id,
                        content_hash, status, remote_status, chunk_count, vector_count,
                        metadata_json, safe_error_code, created_at, updated_at
                    )
                    select operation_key, clip_id, knowledge_base_id, index_provider,
                           dataset_id, '', generation_id, document_id, content_hash,
                           status, remote_status, chunk_count, vector_count,
                           metadata_json, safe_error_code, created_at, updated_at
                    from index_attempts;
                    create table active_indexes_v2 (
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
                        ),
                        foreign key (clip_id) references clips(id),
                        foreign key (operation_key)
                            references index_attempts_v2(operation_key)
                    );
                    insert into active_indexes_v2 select * from active_indexes;
                    drop table active_indexes;
                    drop table index_attempts;
                    alter table index_attempts_v2 rename to index_attempts;
                    alter table active_indexes_v2 rename to active_indexes;
                    create index if not exists idx_index_attempts_scope
                        on index_attempts(
                            clip_id, knowledge_base_id, index_provider, dataset_id,
                            updated_at
                        );
                    """
                )
            columns = {
                str(row[1]) for row in db.execute("pragma table_info(index_documents)").fetchall()
            }
            if "content_hash" not in columns:
                db.execute(
                    "alter table index_documents add column content_hash text not null default ''"
                )
            asset_columns = {
                str(row[1]) for row in db.execute("pragma table_info(assets)").fetchall()
            }
            if "metadata_json" not in asset_columns:
                db.execute(
                    "alter table assets add column metadata_json text not null default '{}'"
                )
            association_columns = {
                str(row[1])
                for row in db.execute("pragma table_info(clip_knowledge_bases)").fetchall()
            }
            if "association_intent_id" not in association_columns:
                db.execute(
                    "alter table clip_knowledge_bases "
                    "add column association_intent_id text not null default ''"
                )
            for association in db.execute(
                """
                select clip_id, knowledge_base_id from clip_knowledge_bases
                where association_intent_id=''
                """
            ).fetchall():
                db.execute(
                    """
                    update clip_knowledge_bases set association_intent_id=?
                    where clip_id=? and knowledge_base_id=? and association_intent_id=''
                    """,
                    (
                        "assoc_" + uuid.uuid4().hex,
                        int(association["clip_id"]),
                        str(association["knowledge_base_id"]),
                    ),
                )

    def register_acceptance(
        self,
        *,
        clip_id: int,
        client_request_id: str,
        adapter: str,
        client_id: str,
        event_id: str,
        source_app: str,
        occurred_at: str,
        deployment_environment: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        content_hash: str,
        storage_uri: str,
        knowledge_base_id: str,
        route_decision_id: int | None,
        association_type: str,
    ) -> str:
        now = utc_text()
        event_key = self.source_event_key(
            adapter=adapter,
            client_id=client_id,
            event_id=event_id,
            client_request_id=client_request_id,
            fallback_clip_id=clip_id,
        )
        event_digest = hashlib.sha256(event_key.encode()).hexdigest()
        source_event_id = f"se_{event_digest[:24]}"
        asset_id = f"asset_{hashlib.sha256(f'{clip_id}:staged_original:{content_hash}'.encode()).hexdigest()[:24]}"
        with self.connect() as db:
            db.execute("begin immediate")
            existing_event = db.execute(
                "select clip_id from source_events where event_key=?", (event_key,)
            ).fetchone()
            if existing_event is not None and int(existing_event["clip_id"]) != int(clip_id):
                raise ValueError("source_event_conflict")
            identity = db.execute(
                "select public_id from clip_identities where clip_id=?", (clip_id,)
            ).fetchone()
            public_id = str(identity["public_id"]) if identity else f"pc_{uuid.uuid4().hex}"
            db.execute(
                "insert or ignore into clip_identities(clip_id, public_id, created_at) values (?, ?, ?)",
                (clip_id, public_id, now),
            )
            db.execute(
                """
                insert into source_events(
                    id, event_key, clip_id, adapter, client_id, event_id, source_app,
                    occurred_at, deployment_environment, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(event_key) do update set
                    source_app=excluded.source_app,
                    occurred_at=excluded.occurred_at
                """,
                (
                    source_event_id,
                    event_key,
                    clip_id,
                    adapter,
                    client_id,
                    event_id,
                    source_app,
                    occurred_at,
                    deployment_environment,
                    now,
                ),
            )
            db.execute(
                """
                insert or ignore into assets(
                    id, clip_id, role, filename, mime_type, size_bytes, content_hash,
                    storage_uri, engine, engine_version, created_at
                ) values (?, ?, 'staged_original', ?, ?, ?, ?, ?, 'perclip-api', 'v1', ?)
                """,
                (asset_id, clip_id, filename, mime_type, size_bytes, content_hash, storage_uri, now),
            )
            if knowledge_base_id:
                db.execute(
                    """
                    insert into clip_knowledge_bases(
                        clip_id, knowledge_base_id, association_type, route_decision_id,
                        association_intent_id, created_at
                    ) values (?, ?, ?, ?, ?, ?)
                    on conflict(clip_id, knowledge_base_id) do update set
                        association_type=excluded.association_type,
                        route_decision_id=excluded.route_decision_id
                    """,
                    (
                        clip_id,
                        knowledge_base_id,
                        association_type if association_type in {"manual", "automatic", "imported"} else "automatic",
                        route_decision_id,
                        "assoc_" + uuid.uuid4().hex,
                        now,
                    ),
                )
            self._enqueue_in_db(
                db,
                clip_id=clip_id,
                stage=PIPELINE_STAGES[0],
                engine="filesystem",
                engine_version="v1",
                input_hash=content_hash,
                payload={"staged_asset_id": asset_id},
                now=now,
            )
        return public_id

    @staticmethod
    def source_event_key(
        *,
        adapter: str,
        client_id: str,
        event_id: str,
        client_request_id: str,
        fallback_clip_id: int | None = None,
    ) -> str:
        event_key = ":".join(
            part for part in (adapter, client_id, event_id or client_request_id) if part
        )
        if event_key:
            return event_key
        return f"clip:{fallback_clip_id}" if fallback_clip_id is not None else ""

    def source_event_is_available(
        self,
        *,
        adapter: str,
        client_id: str,
        event_id: str,
        client_request_id: str,
    ) -> bool:
        event_key = self.source_event_key(
            adapter=adapter,
            client_id=client_id,
            event_id=event_id,
            client_request_id=client_request_id,
        )
        if not event_key:
            return True
        with self.connect() as db:
            row = db.execute(
                "select 1 from source_events where event_key=?", (event_key,)
            ).fetchone()
        return row is None

    def reconcile_acceptances(self, *, deployment_environment: str) -> int:
        """Restore durable pipeline registration after an interrupted API acceptance.

        ClipStore owns the compatibility tables and commits before this store can
        register the source event/outbox.  This scan makes that boundary
        recoverable without fabricating a successful processing result.
        """
        with self.connect() as db:
            rows = db.execute(
                """
                select c.*, r.source_adapter, r.target_knowledge_base_id,
                       m.metadata_json,
                       d.id as route_decision_id,
                       d.knowledge_base_id as routed_knowledge_base_id,
                       d.decision_type
                from clips c
                left join ingest_receipts r on r.clip_id=cast(c.id as text)
                left join clip_metadata m on m.clip_id=c.id
                left join clip_route_decisions d on d.id=(
                    select max(d2.id) from clip_route_decisions d2
                    where d2.clip_id=cast(c.id as text)
                )
                left join clip_identities i on i.clip_id=c.id
                where c.archive_status='accepted' and i.clip_id is null
                order by c.id
                """
            ).fetchall()
        recovered = 0
        for row in rows:
            metadata: dict[str, object] = {}
            try:
                metadata = json.loads(str(row["metadata_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            provenance = metadata.get("provenance")
            provenance = provenance if isinstance(provenance, dict) else {}
            adapter = str(row["source_adapter"] or provenance.get("launcher_type") or "api")
            self.register_acceptance(
                clip_id=int(row["id"]),
                client_request_id=str(row["client_request_id"] or ""),
                adapter=adapter,
                client_id=str(provenance.get("launcher_id") or ""),
                event_id=str(provenance.get("source_message_id") or ""),
                source_app=str(row["source_app"] or ""),
                occurred_at=str(row["captured_at"] or ""),
                deployment_environment=deployment_environment,
                filename=str(row["filename"] or ""),
                mime_type=str(row["mime_type"] or ""),
                size_bytes=int(row["size_bytes"] or 0),
                content_hash=str(row["content_hash"] or ""),
                storage_uri=str(row["original_path"] or ""),
                knowledge_base_id=str(
                    row["routed_knowledge_base_id"] or row["target_knowledge_base_id"] or ""
                ),
                route_decision_id=(
                    int(row["route_decision_id"]) if row["route_decision_id"] is not None else None
                ),
                association_type=(
                    "manual"
                    if str(row["decision_type"] or "") == "manual"
                    or bool(str(row["target_knowledge_base_id"] or ""))
                    else "automatic"
                ),
            )
            recovered += 1
        return recovered

    def enqueue(
        self,
        *,
        clip_id: int,
        stage: str,
        engine: str,
        engine_version: str,
        input_hash: str,
        payload: dict[str, object] | None = None,
    ) -> StoredPipelineJob:
        if stage not in PIPELINE_STAGES:
            raise ValueError("unsupported pipeline stage")
        now = utc_text()
        with self.connect() as db:
            job_id = self._enqueue_in_db(
                db,
                clip_id=clip_id,
                stage=stage,
                engine=engine,
                engine_version=engine_version,
                input_hash=input_hash,
                payload=payload or {},
                now=now,
            )
            row = db.execute("select * from outbox_jobs where id=?", (job_id,)).fetchone()
        return self._row_to_job(row)

    def _enqueue_in_db(
        self,
        db: sqlite3.Connection,
        *,
        clip_id: int,
        stage: str,
        engine: str,
        engine_version: str,
        input_hash: str,
        payload: dict[str, object],
        now: str,
    ) -> int:
        if stage not in PIPELINE_STAGES:
            raise ValueError("unsupported pipeline stage")
        job_key = hashlib.sha256(
            f"{clip_id}\0{stage}\0{engine_version}\0{input_hash}".encode()
        ).hexdigest()
        db.execute(
            """
            insert or ignore into outbox_jobs(
                job_key, clip_id, stage, engine, engine_version, input_hash,
                payload_json, status, available_at, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                job_key,
                clip_id,
                stage,
                engine,
                engine_version,
                input_hash,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                now,
                now,
                now,
            ),
        )
        row = db.execute("select id from outbox_jobs where job_key=?", (job_key,)).fetchone()
        return int(row["id"])

    def claim(self, *, limit: int = 1, lease_seconds: float = 300) -> list[StoredPipelineJob]:
        now = self._now()
        now_text = utc_text(now)
        expires = utc_text(now + timedelta(seconds=lease_seconds))
        claimed: list[StoredPipelineJob] = []
        with self.connect() as db:
            db.execute("begin immediate")
            db.execute(
                """
                update outbox_jobs
                set status='retry', lease_token='', lease_expires_at='',
                    safe_error_code='lease_expired', available_at=?, updated_at=?
                where status='running' and lease_expires_at != '' and lease_expires_at <= ?
                """,
                (now_text, now_text, now_text),
            )
            rows = db.execute(
                """
                select * from outbox_jobs
                where status in ('pending', 'retry') and available_at <= ?
                  and attempt_count < max_attempts
                order by id asc limit ?
                """,
                (now_text, max(1, int(limit))),
            ).fetchall()
            for row in rows:
                token = uuid.uuid4().hex
                db.execute(
                    """
                    update outbox_jobs
                    set status='running', attempt_count=attempt_count+1,
                        lease_token=?, lease_expires_at=?, safe_error_code='', updated_at=?
                    where id=? and status in ('pending', 'retry')
                    """,
                    (token, expires, now_text, int(row["id"])),
                )
                claimed_row = db.execute(
                    "select * from outbox_jobs where id=?", (int(row["id"]),)
                ).fetchone()
                claimed.append(self._row_to_job(claimed_row))
        return claimed

    def renew_lease(self, job: StoredPipelineJob, *, lease_seconds: float = 300) -> bool:
        """Extend only the lease currently owned by ``job``.

        A stale token can never revive or extend a job that another Worker has
        already reclaimed.
        """
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = self._now().astimezone(timezone.utc)
        with self.connect() as db:
            changed = db.execute(
                """
                update outbox_jobs
                set lease_expires_at=?, updated_at=?
                where id=? and status='running' and lease_token=?
                """,
                (
                    utc_text(now + timedelta(seconds=lease_seconds)),
                    utc_text(now),
                    job.id,
                    job.lease_token,
                ),
            ).rowcount
        return bool(changed)

    def complete(
        self,
        job: StoredPipelineJob,
        *,
        output_asset_id: str = "",
        next_stage: str = "",
        next_engine: str = "perclip",
        next_engine_version: str = "v1",
        next_input_hash: str = "",
        next_payload: dict[str, object] | None = None,
    ) -> bool:
        now = utc_text()
        with self.connect() as db:
            db.execute("begin immediate")
            changed = db.execute(
                """
                update outbox_jobs
                set status='completed', lease_token='', lease_expires_at='',
                    output_asset_id=?, updated_at=?
                where id=? and status='running' and lease_token=?
                """,
                (output_asset_id, now, job.id, job.lease_token),
            ).rowcount
            if not changed:
                return False
            db.execute(
                """
                insert into processing_runs(
                    clip_id, stage, engine, engine_version, input_hash, status,
                    attempt_count, started_at, finished_at, safe_error_code,
                    output_asset_id, created_at, updated_at
                ) values (?, ?, ?, ?, ?, 'completed', ?, ?, ?, '', ?, ?, ?)
                on conflict(clip_id, stage, engine_version, input_hash) do update set
                    status='completed', attempt_count=excluded.attempt_count,
                    finished_at=excluded.finished_at, safe_error_code='',
                    output_asset_id=excluded.output_asset_id, updated_at=excluded.updated_at
                """,
                (
                    int(job.clip_id), job.stage, job.engine, job.engine_version,
                    job.input_hash, job.attempt_count, job.updated_at, now,
                    output_asset_id, job.created_at, now,
                ),
            )
            if next_stage:
                self._enqueue_in_db(
                    db,
                    clip_id=int(job.clip_id),
                    stage=next_stage,
                    engine=next_engine,
                    engine_version=next_engine_version,
                    input_hash=next_input_hash or job.input_hash,
                    payload=next_payload or {},
                    now=now,
                )
        return True

    def register_asset(
        self,
        *,
        clip_id: int,
        role: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        content_hash: str,
        storage_uri: str,
        engine: str,
        engine_version: str,
        metadata: dict[str, object] | None = None,
    ) -> str:
        identity = hashlib.sha256(
            f"{clip_id}\0{role}\0{content_hash}\0{engine_version}".encode()
        ).hexdigest()
        asset_id = f"asset_{identity[:24]}"
        now = utc_text()
        with self.connect() as db:
            db.execute(
                """
                insert into assets(
                    id, clip_id, role, filename, mime_type, size_bytes, content_hash,
                    storage_uri, engine, engine_version, metadata_json, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(clip_id, role, content_hash, engine_version) do update set
                    filename=excluded.filename, mime_type=excluded.mime_type,
                    size_bytes=excluded.size_bytes, storage_uri=excluded.storage_uri,
                    metadata_json=excluded.metadata_json
                """,
                (
                    asset_id, clip_id, role, filename, mime_type, int(size_bytes),
                    content_hash, storage_uri, engine, engine_version,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True), now,
                ),
            )
        return asset_id

    @staticmethod
    def asset_metadata(asset: dict[str, object] | None) -> dict[str, object]:
        if not asset:
            return {}
        try:
            payload = json.loads(str(asset.get("metadata_json") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def update_clip_archive(self, *, clip_id: int, storage_uri: str, archive_status: str) -> None:
        with self.connect() as db:
            db.execute(
                "update clips set original_path=?, archive_status=? where id=?",
                (storage_uri, archive_status, int(clip_id)),
            )

    def public_id_for(self, clip_id: int) -> str:
        with self.connect() as db:
            row = db.execute(
                "select public_id from clip_identities where clip_id=?", (int(clip_id),)
            ).fetchone()
            if row is None:
                db.execute(
                    "insert or ignore into clip_identities(clip_id, public_id, created_at) values (?, ?, ?)",
                    (int(clip_id), f"pc_{uuid.uuid4().hex}", utc_text()),
                )
                row = db.execute(
                    "select public_id from clip_identities where clip_id=?", (int(clip_id),)
                ).fetchone()
        if row is None:
            raise ValueError("clip identity unavailable")
        return str(row["public_id"])

    def clip_id_for_public_id(self, public_id: str) -> int | None:
        with self.connect() as db:
            row = db.execute(
                "select clip_id from clip_identities where public_id=?", (public_id.strip(),)
            ).fetchone()
        return int(row["clip_id"]) if row is not None else None

    def find_source_event_by_clip_id(self, *, clip_id: int) -> dict[str, object] | None:
        with self.connect() as db:
            row = db.execute(
                """
                select * from source_events where clip_id=?
                order by created_at desc limit 1
                """,
                (int(clip_id),),
            ).fetchone()
        return dict(row) if row else None

    def latest_asset(self, *, clip_id: int, role: str) -> dict[str, object] | None:
        with self.connect() as db:
            row = db.execute(
                """
                select * from assets where clip_id=? and role=?
                order by created_at desc limit 1
                """,
                (int(clip_id), role),
            ).fetchone()
        return dict(row) if row else None

    def find_asset(self, asset_id: str) -> dict[str, object] | None:
        with self.connect() as db:
            row = db.execute("select * from assets where id=?", (asset_id,)).fetchone()
        return dict(row) if row else None

    def asset_hash(self, asset_id: str) -> str:
        if not asset_id:
            return ""
        with self.connect() as db:
            row = db.execute("select content_hash from assets where id=?", (asset_id,)).fetchone()
        return str(row["content_hash"]) if row else ""

    def upsert_index_document(
        self,
        *,
        clip_id: int,
        knowledge_base_id: str,
        index_provider: str,
        dataset_id: str,
        document_id: str,
        content_hash: str,
        status: str,
    ) -> None:
        now = utc_text()
        with self.connect() as db:
            db.execute(
                """
                insert into index_documents(
                    clip_id, knowledge_base_id, index_provider, dataset_id,
                    document_id, content_hash, status, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(clip_id, knowledge_base_id, index_provider, dataset_id) do update set
                    document_id=excluded.document_id, content_hash=excluded.content_hash,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    int(clip_id), knowledge_base_id, index_provider, dataset_id,
                    document_id, content_hash, status, now, now,
                ),
            )

    def ensure_index_attempt(
        self,
        *,
        operation_key: str,
        clip_id: int,
        knowledge_base_id: str,
        index_provider: str,
        dataset_id: str,
        association_intent_id: str = "",
        generation_id: str,
        content_hash: str,
        metadata_json: str,
        status: str,
    ) -> dict[str, object]:
        if status not in LOCAL_INDEX_STATUSES:
            raise ValueError("invalid local index status")
        if len(operation_key) != 64 or any(
            char not in "0123456789abcdef" for char in operation_key
        ):
            raise ValueError("invalid index operation key")
        now = utc_text()
        with self.connect() as db:
            db.execute(
                """
                insert into index_attempts(
                    operation_key, clip_id, knowledge_base_id, index_provider,
                    dataset_id, association_intent_id, generation_id, content_hash, status,
                    metadata_json, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(operation_key) do nothing
                """,
                (
                    operation_key,
                    int(clip_id),
                    knowledge_base_id,
                    index_provider,
                    dataset_id,
                    association_intent_id,
                    generation_id,
                    content_hash,
                    status,
                    metadata_json,
                    now,
                    now,
                ),
            )
            row = db.execute(
                "select * from index_attempts where operation_key=?", (operation_key,)
            ).fetchone()
        if row is None:
            raise RuntimeError("index attempt persistence failed")
        return dict(row)

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
        if status not in LOCAL_INDEX_STATUSES:
            raise ValueError("invalid local index status")
        if remote_status is not None and remote_status not in REMOTE_DOCUMENT_STATUSES:
            raise ValueError("invalid remote document status")
        for value in (chunk_count, vector_count):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError("invalid index evidence count")
        assignments = ["status=?", "updated_at=?"]
        values: list[object] = [status, utc_text()]
        for column, value in (
            ("document_id", document_id),
            ("remote_status", remote_status),
            ("chunk_count", chunk_count),
            ("vector_count", vector_count),
            ("safe_error_code", safe_error_code),
        ):
            if value is not None:
                assignments.append(f"{column}=?")
                values.append(value)
        values.append(operation_key)
        with self.connect() as db:
            changed = db.execute(
                f"update index_attempts set {', '.join(assignments)} where operation_key=?",
                tuple(values),
            ).rowcount
            row = db.execute(
                "select * from index_attempts where operation_key=?", (operation_key,)
            ).fetchone()
        if not changed or row is None:
            raise ValueError("index attempt not found")
        return dict(row)

    def find_index_attempt(self, *, operation_key: str) -> dict[str, object] | None:
        with self.connect() as db:
            row = db.execute(
                "select * from index_attempts where operation_key=?", (operation_key,)
            ).fetchone()
        return dict(row) if row else None

    def activate_verified_index(self, *, operation_key: str) -> None:
        now = utc_text()
        with self.connect() as db:
            db.execute("begin immediate")
            row = db.execute(
                "select * from index_attempts where operation_key=?", (operation_key,)
            ).fetchone()
            if (
                row is None
                or str(row["status"]) != "indexed_verified"
                or str(row["remote_status"]) != "done"
                or not str(row["document_id"])
                or int(row["chunk_count"]) <= 0
                or int(row["vector_count"]) != int(row["chunk_count"])
            ):
                raise ValueError("only a verified index attempt can become active")
            db.execute(
                """
                insert into active_indexes(
                    clip_id, knowledge_base_id, index_provider, dataset_id,
                    operation_key, document_id, generation_id, content_hash, activated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(clip_id, knowledge_base_id, index_provider, dataset_id)
                do update set
                    operation_key=excluded.operation_key,
                    document_id=excluded.document_id,
                    generation_id=excluded.generation_id,
                    content_hash=excluded.content_hash,
                    activated_at=excluded.activated_at
                """,
                (
                    int(row["clip_id"]),
                    str(row["knowledge_base_id"]),
                    str(row["index_provider"]),
                    str(row["dataset_id"]),
                    operation_key,
                    str(row["document_id"]),
                    str(row["generation_id"]),
                    str(row["content_hash"]),
                    now,
                ),
            )
            db.execute(
                """
                insert into index_documents(
                    clip_id, knowledge_base_id, index_provider, dataset_id,
                    document_id, content_hash, status, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, 'indexed_verified', ?, ?)
                on conflict(clip_id, knowledge_base_id, index_provider, dataset_id)
                do update set document_id=excluded.document_id,
                    content_hash=excluded.content_hash,
                    status='indexed_verified', updated_at=excluded.updated_at
                """,
                (
                    int(row["clip_id"]),
                    str(row["knowledge_base_id"]),
                    str(row["index_provider"]),
                    str(row["dataset_id"]),
                    str(row["document_id"]),
                    str(row["content_hash"]),
                    now,
                    now,
                ),
            )

    def find_active_index(
        self,
        *,
        clip_id: int,
        knowledge_base_id: str,
        index_provider: str,
        dataset_id: str,
    ) -> dict[str, object] | None:
        with self.connect() as db:
            row = db.execute(
                """
                select * from active_indexes
                where clip_id=? and knowledge_base_id=? and index_provider=? and dataset_id=?
                """,
                (int(clip_id), knowledge_base_id, index_provider, dataset_id),
            ).fetchone()
        return dict(row) if row else None

    def mark_ready(self, *, clip_id: int) -> None:
        now = utc_text()
        with self.connect() as db:
            db.execute(
                """
                update ingest_receipts
                set archive_status='ready', metadata_status='available', updated_at=?
                where clip_id=? and status='received'
                """,
                (now, str(clip_id)),
            )

    def associate_knowledge_base(
        self,
        *,
        clip_id: int,
        knowledge_base_id: str,
        association_type: str = "manual",
        route_decision_id: int | None = None,
    ) -> None:
        if association_type not in {"manual", "automatic", "imported"}:
            raise ValueError("invalid knowledge base association type")
        with self.connect() as db:
            db.execute(
                """
                insert into clip_knowledge_bases(
                    clip_id, knowledge_base_id, association_type, route_decision_id,
                    association_intent_id, created_at
                ) values (?, ?, ?, ?, ?, ?)
                on conflict(clip_id, knowledge_base_id) do update set
                    association_type=excluded.association_type,
                    route_decision_id=coalesce(excluded.route_decision_id, clip_knowledge_bases.route_decision_id)
                """,
                (
                    int(clip_id),
                    knowledge_base_id,
                    association_type,
                    route_decision_id,
                    "assoc_" + uuid.uuid4().hex,
                    utc_text(),
                ),
            )

    @staticmethod
    def _detach_knowledge_base_association_in_transaction(
        db: sqlite3.Connection,
        *,
        clip_id: int,
        knowledge_base_id: str,
        now: str,
    ) -> bool:
        """Detach membership and every local index record on one connection."""
        changed = db.execute(
            "delete from clip_knowledge_bases where clip_id=? and knowledge_base_id=?",
            (int(clip_id), knowledge_base_id),
        ).rowcount
        if not changed:
            return False
        db.execute(
            """
            update index_attempts
            set status='detached_pending_cleanup', updated_at=?
            where operation_key in (
                select operation_key from active_indexes
                where clip_id=? and knowledge_base_id=?
            ) and status='indexed_verified'
            """,
            (now, int(clip_id), knowledge_base_id),
        )
        db.execute(
            """
            delete from active_indexes
            where clip_id=? and knowledge_base_id=?
            """,
            (int(clip_id), knowledge_base_id),
        )
        db.execute(
            """
            update index_documents set status='detached_pending_cleanup', updated_at=?
            where clip_id=? and knowledge_base_id=?
            """,
            (now, int(clip_id), knowledge_base_id),
        )
        db.execute(
            """
            update index_attempts
            set status='detached_pending_cleanup', updated_at=?
            where clip_id=? and knowledge_base_id=? and status='indexed_verified'
            """,
            (now, int(clip_id), knowledge_base_id),
        )
        return True

    def remove_knowledge_base_association(self, *, clip_id: int, knowledge_base_id: str) -> bool:
        now = utc_text()
        with self.connect() as db:
            db.execute("begin immediate")
            changed = self._detach_knowledge_base_association_in_transaction(
                db,
                clip_id=int(clip_id),
                knowledge_base_id=knowledge_base_id,
                now=now,
            )
        return changed

    def move_knowledge_base_association(
        self,
        *,
        clip_id: int,
        previous_knowledge_base_id: str,
        knowledge_base_id: str,
        route_decision_id: int,
    ) -> None:
        """Atomically switch membership and its SQLite change-outbox events."""
        now = utc_text()
        with self.connect() as db:
            db.execute("begin immediate")
            if previous_knowledge_base_id and previous_knowledge_base_id != knowledge_base_id:
                self._detach_knowledge_base_association_in_transaction(
                    db,
                    clip_id=int(clip_id),
                    knowledge_base_id=previous_knowledge_base_id,
                    now=now,
                )
            association_intent_id = "assoc_" + uuid.uuid4().hex
            db.execute(
                """insert into clip_knowledge_bases(
                    clip_id,knowledge_base_id,association_type,route_decision_id,
                    association_intent_id,created_at
                ) values(?,?,'manual',?,?,?)
                on conflict(clip_id,knowledge_base_id) do update set
                    association_type='manual',route_decision_id=excluded.route_decision_id,
                    association_intent_id=case
                        when clip_knowledge_bases.association_intent_id=''
                        then excluded.association_intent_id
                        else clip_knowledge_bases.association_intent_id
                    end""",
                (
                    int(clip_id),
                    knowledge_base_id,
                    int(route_decision_id),
                    association_intent_id,
                    now,
                ),
            )

    def finalize_index_deletion(self, *, operation_key: str) -> None:
        now = utc_text()
        with self.connect() as db:
            db.execute("begin immediate")
            row = db.execute(
                "select * from index_attempts where operation_key=?", (operation_key,)
            ).fetchone()
            if row is None:
                raise ValueError("index attempt not found")
            if str(row["status"]) not in {
                "detached_pending_cleanup",
                "deleted_verified",
            }:
                raise ValueError("index cleanup target is not detached")
            db.execute(
                """
                update index_attempts
                set status='deleted_verified', remote_status='missing',
                    chunk_count=0, vector_count=0, safe_error_code='', updated_at=?
                where operation_key=?
                """,
                (now, operation_key),
            )
            db.execute(
                """
                delete from active_indexes
                where operation_key=?
                """,
                (operation_key,),
            )
            db.execute(
                """
                update index_documents
                set status='deleted_verified', updated_at=?
                where clip_id=? and knowledge_base_id=?
                  and index_provider=? and dataset_id=?
                  and document_id=? and status='detached_pending_cleanup'
                """,
                (
                    now,
                    int(row["clip_id"]),
                    str(row["knowledge_base_id"]),
                    str(row["index_provider"]),
                    str(row["dataset_id"]),
                    str(row["document_id"]),
                ),
            )

    def list_knowledge_base_associations(self, *, clip_id: int) -> list[dict[str, object]]:
        with self.connect() as db:
            rows = db.execute(
                """
                select knowledge_base_id, association_type, route_decision_id,
                       association_intent_id, created_at
                from clip_knowledge_bases where clip_id=? order by created_at, knowledge_base_id
                """,
                (int(clip_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_clip_ids_for_knowledge_base(
        self, *, knowledge_base_id: str, after_internal_id: int = 0, limit: int = 100
    ) -> list[int]:
        with self.connect() as db:
            rows = db.execute(
                """
                select clip_id from clip_knowledge_bases
                where knowledge_base_id = ? and clip_id > ?
                order by clip_id asc
                limit ?
                """,
                (knowledge_base_id.strip(), int(after_internal_id), int(limit)),
            ).fetchall()
        return [int(row["clip_id"]) for row in rows]

    def create_knowledge_read_cursor(
        self, *, knowledge_base_id: str, after_internal_id: int
    ) -> str:
        token = "kc_" + uuid.uuid4().hex
        now = self._now()
        with self.connect() as db:
            db.execute(
                "delete from knowledge_read_cursors where created_at < ?",
                (utc_text(now - KNOWLEDGE_CURSOR_TTL),),
            )
            db.execute(
                """
                insert into knowledge_read_cursors(
                    token, knowledge_base_id, after_clip_id, created_at
                ) values (?, ?, ?, ?)
                """,
                (token, knowledge_base_id.strip(), int(after_internal_id), utc_text(now)),
            )
        return token

    def resolve_knowledge_read_cursor(
        self, *, knowledge_base_id: str, token: str
    ) -> int | None:
        cutoff = utc_text(self._now().astimezone(timezone.utc) - KNOWLEDGE_CURSOR_TTL)
        with self.connect() as db:
            db.execute("delete from knowledge_read_cursors where created_at < ?", (cutoff,))
            row = db.execute(
                """
                select after_clip_id from knowledge_read_cursors
                where token=? and knowledge_base_id=?
                """,
                (token.strip(), knowledge_base_id.strip()),
            ).fetchone()
        return int(row["after_clip_id"]) if row is not None else None

    def association_fingerprint(self, *, clip_id: int, content_hash: str) -> str:
        with self.connect() as db:
            associations = db.execute(
                """
                select a.knowledge_base_id, coalesce(k.ragflow_dataset_id, '') as dataset_id
                from clip_knowledge_bases a
                left join knowledge_bases k on k.id = a.knowledge_base_id
                where a.clip_id = ?
                order by a.knowledge_base_id
                """,
                (int(clip_id),),
            ).fetchall()
        material = json.dumps(
            [
                {
                    "knowledge_base_id": str(item["knowledge_base_id"]),
                    "dataset_id": str(item["dataset_id"]),
                }
                for item in associations
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(f"{content_hash}\0{material}".encode()).hexdigest()

    def find_index_document(
        self,
        *,
        clip_id: int,
        knowledge_base_id: str,
        index_provider: str,
        dataset_id: str,
    ) -> dict[str, object] | None:
        with self.connect() as db:
            row = db.execute(
                """
                select * from index_documents
                where clip_id=? and knowledge_base_id=? and index_provider=? and dataset_id=?
                """,
                (int(clip_id), knowledge_base_id, index_provider, dataset_id),
            ).fetchone()
        return dict(row) if row else None

    def retry_failed_job(
        self,
        *,
        job_id: int,
        request_id: str,
        authorized: bool = False,
        additional_attempts: int = 5,
    ) -> tuple[StoredPipelineJob, bool]:
        """Requeue one terminal job while preserving immutable retry evidence."""
        if not authorized:
            raise ValueError("pipeline retry authorization required")
        control_id = self._control_request_id(request_id)
        if additional_attempts <= 0 or additional_attempts > 20:
            raise ValueError("additional_attempts must be between 1 and 20")
        now = utc_text()
        with self.connect() as db:
            db.execute("begin immediate")
            existing_event = db.execute(
                "select result_job_id from pipeline_control_events where request_id=?",
                (control_id,),
            ).fetchone()
            if existing_event is not None:
                row = db.execute(
                    "select * from outbox_jobs where id=?",
                    (int(existing_event["result_job_id"]),),
                ).fetchone()
                if row is None:
                    raise ValueError("pipeline control result missing")
                return self._row_to_job(row), False
            row = db.execute(
                "select * from outbox_jobs where id=?", (int(job_id),)
            ).fetchone()
            if row is None:
                raise ValueError("pipeline job not found")
            if str(row["status"]) != "failed":
                raise ValueError("only terminal failed jobs can be retried")
            db.execute(
                """
                insert into pipeline_control_events(
                    request_id, action, clip_id, job_id, result_job_id,
                    previous_status, previous_attempt_count,
                    previous_safe_error_code, details_json, created_at
                ) values (?, 'retry_failed_job', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    control_id, int(row["clip_id"]), int(row["id"]), int(row["id"]),
                    str(row["status"]), int(row["attempt_count"]),
                    str(row["safe_error_code"]),
                    json.dumps({"additional_attempts": additional_attempts}, sort_keys=True),
                    now,
                ),
            )
            db.execute(
                """
                update outbox_jobs
                set status='retry', available_at=?, lease_token='', lease_expires_at='',
                    max_attempts=max(max_attempts, attempt_count + ?), updated_at=?
                where id=? and status='failed'
                """,
                (now, additional_attempts, now, int(row["id"])),
            )
            reopened = db.execute(
                "select * from outbox_jobs where id=?", (int(row["id"]),)
            ).fetchone()
        return self._row_to_job(reopened), True

    def promote_planned_index(
        self,
        *,
        clip_id: int,
        request_id: str,
        authorized: bool = False,
    ) -> tuple[StoredPipelineJob, bool]:
        """Schedule an auditable dry-run -> real-sync promotion.

        The caller must additionally enforce the runtime RAGFlow safety gates.
        This method only mutates local control-plane state.
        """
        if not authorized:
            raise ValueError("real-sync promotion authorization required")
        control_id = self._control_request_id(request_id)
        now = utc_text()
        with self.connect() as db:
            db.execute("begin immediate")
            existing_event = db.execute(
                "select result_job_id from pipeline_control_events where request_id=?",
                (control_id,),
            ).fetchone()
            if existing_event is not None:
                row = db.execute(
                    "select * from outbox_jobs where id=?",
                    (int(existing_event["result_job_id"]),),
                ).fetchone()
                if row is None:
                    raise ValueError("pipeline control result missing")
                return self._row_to_job(row), False
            running = db.execute(
                "select 1 from outbox_jobs where clip_id=? and stage='index' and status='running'",
                (int(clip_id),),
            ).fetchone()
            if running is not None:
                raise ValueError("index job is currently leased")
            planned = db.execute(
                """
                select count(*) as count from index_documents
                where clip_id=? and index_provider='ragflow' and status='planned'
                """,
                (int(clip_id),),
            ).fetchone()
            if planned is None or int(planned["count"]) == 0:
                raise ValueError("clip has no planned RAGFlow index")
            clean = db.execute(
                """
                select content_hash from assets
                where clip_id=? and role='clean_markdown'
                order by created_at desc limit 1
                """,
                (int(clip_id),),
            ).fetchone()
            if clean is None:
                raise ValueError("clean asset missing")
            associations = db.execute(
                """
                select knowledge_base_id from clip_knowledge_bases
                where clip_id=? order by knowledge_base_id
                """,
                (int(clip_id),),
            ).fetchall()
            material = json.dumps(
                [str(item["knowledge_base_id"]) for item in associations],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            base_fingerprint = hashlib.sha256(
                f'{clean["content_hash"]}\0{material}'.encode()
            ).hexdigest()
            promotion_hash = hashlib.sha256(
                f"{base_fingerprint}\0real-sync\0{control_id}".encode()
            ).hexdigest()
            result_job_id = self._enqueue_in_db(
                db,
                clip_id=int(clip_id),
                stage="index",
                engine="ragflow",
                engine_version="v1",
                input_hash=promotion_hash,
                payload={"sync_mode": "real", "control_request_id": control_id},
                now=now,
            )
            db.execute(
                """
                insert into pipeline_control_events(
                    request_id, action, clip_id, result_job_id,
                    previous_status, details_json, created_at
                ) values (?, 'promote_real_sync', ?, ?, 'planned', ?, ?)
                """,
                (
                    control_id, int(clip_id), result_job_id,
                    json.dumps(
                        {"planned_index_count": int(planned["count"])}, sort_keys=True
                    ),
                    now,
                ),
            )
            result = db.execute(
                "select * from outbox_jobs where id=?", (result_job_id,)
            ).fetchone()
        return self._row_to_job(result), True

    def list_control_events(self, *, clip_id: int) -> list[dict[str, object]]:
        with self.connect() as db:
            rows = db.execute(
                """
                select request_id, action, job_id, result_job_id, previous_status,
                       previous_attempt_count, previous_safe_error_code,
                       details_json, created_at
                from pipeline_control_events where clip_id=? order by id
                """,
                (int(clip_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _control_request_id(value: str) -> str:
        candidate = value.strip()
        if (
            not candidate
            or len(candidate) > 128
            or any(not (character.isalnum() or character in "._:-") for character in candidate)
        ):
            raise ValueError("invalid pipeline control request_id")
        return candidate

    def processing_summary(self, *, clip_id: int) -> dict[str, object]:
        with self.connect() as db:
            jobs = db.execute(
                """
                select stage, status, attempt_count, max_attempts, safe_error_code, updated_at
                from outbox_jobs where clip_id=? order by id
                """,
                (int(clip_id),),
            ).fetchall()
            runs = db.execute(
                """
                select stage, engine, engine_version, status, attempt_count,
                       safe_error_code, started_at, finished_at
                from processing_runs where clip_id=? order by id
                """,
                (int(clip_id),),
            ).fetchall()
            asset_roles = db.execute(
                "select distinct role from assets where clip_id=? order by role",
                (int(clip_id),),
            ).fetchall()
            indexes = db.execute(
                """
                select knowledge_base_id, index_provider, status, updated_at
                from index_documents where clip_id=?
                order by knowledge_base_id, index_provider
                """,
                (int(clip_id),),
            ).fetchall()
            controls = db.execute(
                """
                select request_id, action, job_id, result_job_id, previous_status,
                       previous_attempt_count, previous_safe_error_code, created_at
                from pipeline_control_events where clip_id=? order by id
                """,
                (int(clip_id),),
            ).fetchall()
        return {
            "jobs": [dict(row) for row in jobs],
            "runs": [dict(row) for row in runs],
            "asset_roles": [str(row["role"]) for row in asset_roles],
            "indexes": [dict(row) for row in indexes],
            "control_events": [dict(row) for row in controls],
        }

    def fail(
        self,
        job: StoredPipelineJob,
        *,
        safe_error_code: str,
        retryable: bool,
        retry_delay_seconds: int = 30,
    ) -> bool:
        code = "".join(c for c in safe_error_code.lower() if c.isalnum() or c in "_-")[:64] or "pipeline_failed"
        now = self._now()
        terminal = not retryable or job.attempt_count >= job.max_attempts
        status = "failed" if terminal else "retry"
        available = utc_text(now + timedelta(seconds=max(0, retry_delay_seconds)))
        now_text = utc_text(now)
        with self.connect() as db:
            changed = db.execute(
                """
                update outbox_jobs
                set status=?, available_at=?, lease_token='', lease_expires_at='',
                    safe_error_code=?, updated_at=?
                where id=? and status='running' and lease_token=?
                """,
                (status, available, code, now_text, job.id, job.lease_token),
            ).rowcount
            if terminal and changed:
                db.execute(
                    """
                    insert into processing_runs(
                        clip_id, stage, engine, engine_version, input_hash, status,
                        attempt_count, started_at, finished_at, safe_error_code,
                        output_asset_id, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, 'failed', ?, ?, ?, ?, '', ?, ?)
                    on conflict(clip_id, stage, engine_version, input_hash) do update set
                        status='failed', attempt_count=excluded.attempt_count,
                        finished_at=excluded.finished_at,
                        safe_error_code=excluded.safe_error_code, updated_at=excluded.updated_at
                    """,
                    (
                        int(job.clip_id), job.stage, job.engine, job.engine_version,
                        job.input_hash, job.attempt_count, job.updated_at, now_text,
                        code, job.created_at, now_text,
                    ),
                )
        return bool(changed)

    def get_job(self, job_id: int) -> StoredPipelineJob | None:
        with self.connect() as db:
            row = db.execute("select * from outbox_jobs where id=?", (int(job_id),)).fetchone()
        return self._row_to_job(row) if row else None

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> StoredPipelineJob:
        return StoredPipelineJob(
            id=int(row["id"]),
            job_key=str(row["job_key"]),
            clip_id=str(row["clip_id"]),
            stage=str(row["stage"]),
            engine=str(row["engine"]),
            engine_version=str(row["engine_version"]),
            input_hash=str(row["input_hash"]),
            payload=json.loads(str(row["payload_json"])),
            status=str(row["status"]),
            attempt_count=int(row["attempt_count"]),
            max_attempts=int(row["max_attempts"]),
            available_at=str(row["available_at"]),
            lease_token=str(row["lease_token"]),
            lease_expires_at=str(row["lease_expires_at"]),
            safe_error_code=str(row["safe_error_code"]),
            output_asset_id=str(row["output_asset_id"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
