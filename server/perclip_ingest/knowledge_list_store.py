from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "perclip.knowledge-list.v2"
BOOTSTRAP_VERSION = 1


@dataclass(frozen=True)
class KnowledgeListCursor:
    scope: tuple[str, ...]
    query: str
    source: str
    source_type: str
    attachment: str
    captured_after: str
    captured_before: str
    captured_at: str
    public_clip_id: str


@dataclass(frozen=True)
class KnowledgeListSnapshot:
    rows: tuple[dict[str, Any], ...]
    total_count: int
    matching_count: int
    revision: int
    generated_at: str


@dataclass(frozen=True)
class KnowledgeSummarySnapshot:
    total_count: int
    matching_count: int
    revision: int
    generated_at: str


def _cursor_payload(cursor: KnowledgeListCursor) -> bytes:
    return json.dumps(
        {
            "v": 2,
            "scope": list(cursor.scope),
            "query": cursor.query,
            "source": cursor.source,
            "source_type": cursor.source_type,
            "attachment": cursor.attachment,
            "captured_after": cursor.captured_after,
            "captured_before": cursor.captured_before,
            "captured_at": cursor.captured_at,
            "public_clip_id": cursor.public_clip_id,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def encode_cursor(cursor: KnowledgeListCursor, secret: bytes) -> str:
    raw = _cursor_payload(cursor)
    signature = hmac.new(secret, raw, hashlib.sha256).digest()
    return "kl_" + base64.urlsafe_b64encode(signature + raw).decode().rstrip("=")


def decode_cursor(value: str, secret: bytes) -> KnowledgeListCursor:
    if not value.startswith("kl_"):
        raise ValueError("invalid knowledge list cursor")
    try:
        encoded = value[3:] + "=" * (-len(value[3:]) % 4)
        packed = base64.urlsafe_b64decode(encoded.encode())
        signature, raw = packed[:32], packed[32:]
        if len(signature) != 32 or not hmac.compare_digest(
            signature, hmac.new(secret, raw, hashlib.sha256).digest()
        ):
            raise ValueError
        payload = json.loads(raw.decode())
        if payload.get("v") != 2:
            raise ValueError
        cursor = KnowledgeListCursor(
            scope=tuple(str(item) for item in payload.get("scope", [])),
            query=str(payload.get("query", "")),
            source=str(payload.get("source", "")),
            source_type=str(payload.get("source_type", "")),
            attachment=str(payload.get("attachment", "")),
            captured_after=str(payload.get("captured_after", "")),
            captured_before=str(payload.get("captured_before", "")),
            captured_at=str(payload.get("captured_at", "")),
            public_clip_id=str(payload.get("public_clip_id", "")),
        )
        if not cursor.captured_at or not cursor.public_clip_id.startswith("pc_"):
            raise ValueError
        return cursor
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("invalid knowledge list cursor") from None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _literal_like(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class KnowledgeListStore:
    """Read model and transactional SQLite change outbox for Knowledge List v2."""

    def __init__(self, data_dir: Path) -> None:
        self.db_path = data_dir / "perclip.sqlite3"

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("pragma foreign_keys=on")
        db.execute("pragma journal_mode=wal")
        return db

    @staticmethod
    def _tables(db: sqlite3.Connection) -> set[str]:
        return {
            str(row[0])
            for row in db.execute("select name from sqlite_master where type='table'").fetchall()
        }

    def init(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                create table if not exists knowledge_change_events (
                    revision integer primary key autoincrement,
                    public_clip_id text not null,
                    knowledge_base_id text not null,
                    operation text not null check(operation in ('upsert', 'remove')),
                    changed_at text not null,
                    reason text not null default '',
                    membership_ids_json text not null default '[]'
                );
                create index if not exists idx_knowledge_changes_revision
                    on knowledge_change_events(revision);
                create index if not exists idx_knowledge_changes_scope_revision
                    on knowledge_change_events(knowledge_base_id, revision);
                create index if not exists idx_knowledge_changes_item_revision
                    on knowledge_change_events(public_clip_id, revision desc);

                create table if not exists knowledge_list_bootstrap_state (
                    version integer primary key,
                    status text not null,
                    started_at text not null,
                    completed_at text not null default '',
                    rows_recorded integer not null default 0
                );
                create table if not exists knowledge_list_cursor_key (
                    singleton integer primary key check(singleton=1),
                    secret_hex text not null,
                    created_at text not null
                );
                create table if not exists knowledge_list_projection (
                    clip_id integer primary key,
                    public_clip_id text unique not null,
                    captured_at text not null,
                    updated_at text not null
                );
                create index if not exists idx_knowledge_list_keyset
                    on knowledge_list_projection(captured_at desc, public_clip_id desc);
                create table if not exists knowledge_list_membership_projection (
                    knowledge_base_id text not null,
                    clip_id integer not null,
                    public_clip_id text not null,
                    captured_at text not null,
                    updated_at text not null,
                    primary key(knowledge_base_id, clip_id)
                );
                create index if not exists idx_knowledge_membership_keyset
                    on knowledge_list_membership_projection(
                        knowledge_base_id, captured_at desc, public_clip_id desc
                    );
                """
            )
            columns = {str(row[1]) for row in db.execute("pragma table_info(knowledge_change_events)")}
            if "reason" not in columns:
                db.execute("alter table knowledge_change_events add column reason text not null default ''")
            if "membership_ids_json" not in columns:
                db.execute("alter table knowledge_change_events add column membership_ids_json text not null default '[]'")
            db.execute(
                "insert or ignore into knowledge_list_cursor_key values (1, ?, ?)",
                (secrets.token_hex(32), _utc_now()),
            )
            tables = self._tables(db)
            if {"clips", "clip_identities"} <= tables:
                db.execute(
                    """
                    insert into knowledge_list_projection(clip_id, public_clip_id, captured_at, updated_at)
                    select c.id, ci.public_id, c.captured_at, coalesce(c.created_at, c.captured_at)
                    from clips c join clip_identities ci on ci.clip_id=c.id
                    on conflict(clip_id) do update set
                        public_clip_id=excluded.public_clip_id,
                        captured_at=excluded.captured_at
                    """
                )
            if {"clips", "clip_identities", "clip_knowledge_bases", "knowledge_bases"} <= tables:
                db.execute("create index if not exists idx_knowledge_list_association_scope on clip_knowledge_bases(knowledge_base_id, clip_id)")
                db.execute("create index if not exists idx_knowledge_list_association_clip on clip_knowledge_bases(clip_id, knowledge_base_id)")
                db.execute(
                    """
                    insert into knowledge_list_membership_projection(
                        knowledge_base_id,clip_id,public_clip_id,captured_at,updated_at)
                    select ckb.knowledge_base_id,c.id,ci.public_id,c.captured_at,
                           coalesce(c.created_at,c.captured_at)
                    from clip_knowledge_bases ckb
                    join clips c on c.id=ckb.clip_id
                    join clip_identities ci on ci.clip_id=c.id
                    join knowledge_bases kb on kb.id=ckb.knowledge_base_id
                    where kb.deleted_at='' and kb.is_archived=0
                    on conflict(knowledge_base_id,clip_id) do update set
                        public_clip_id=excluded.public_clip_id,
                        captured_at=excluded.captured_at
                    """
                )
                self._install_triggers(db, tables)

    def _install_triggers(self, db: sqlite3.Connection, tables: set[str]) -> None:
        membership = """coalesce((select json_group_array(knowledge_base_id) from
            (select ckb2.knowledge_base_id from clip_knowledge_bases ckb2
             join knowledge_bases kb2 on kb2.id=ckb2.knowledge_base_id
             where ckb2.clip_id=CI_CLIP and kb2.deleted_at='' and kb2.is_archived=0
             order by ckb2.knowledge_base_id)), '[]')"""
        event_for_clip = """insert into knowledge_change_events(
                public_clip_id, knowledge_base_id, operation, changed_at, reason, membership_ids_json)
            select ci.public_id, ckb.knowledge_base_id, 'upsert', strftime('%Y-%m-%dT%H:%M:%fZ','now'), REASON,
                   MEMBERSHIP
            from clip_identities ci join clip_knowledge_bases ckb on ckb.clip_id=ci.clip_id
            where ci.clip_id=EVENT_CLIP"""

        def add(name: str, sql: str) -> None:
            db.execute(f"drop trigger if exists {name}")
            db.execute(sql)

        add("knowledge_projection_identity_insert", """
            create trigger knowledge_projection_identity_insert after insert on clip_identities begin
              insert into knowledge_list_projection(clip_id,public_clip_id,captured_at,updated_at)
              select new.clip_id,new.public_id,c.captured_at,strftime('%Y-%m-%dT%H:%M:%fZ','now') from clips c where c.id=new.clip_id
              on conflict(clip_id) do update set public_clip_id=excluded.public_clip_id,captured_at=excluded.captured_at,updated_at=excluded.updated_at;
              insert into knowledge_list_membership_projection(knowledge_base_id,clip_id,public_clip_id,captured_at,updated_at)
              select ckb.knowledge_base_id,new.clip_id,new.public_id,c.captured_at,strftime('%Y-%m-%dT%H:%M:%fZ','now')
              from clip_knowledge_bases ckb join knowledge_bases kb on kb.id=ckb.knowledge_base_id
              join clips c on c.id=new.clip_id
              where ckb.clip_id=new.clip_id and kb.deleted_at='' and kb.is_archived=0
              on conflict(knowledge_base_id,clip_id) do update set public_clip_id=excluded.public_clip_id,captured_at=excluded.captured_at,updated_at=excluded.updated_at;
            end""")
        add("knowledge_projection_clip_update", """
            create trigger knowledge_projection_clip_update after update of captured_at on clips begin
              update knowledge_list_projection set captured_at=new.captured_at,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') where clip_id=new.id;
              update knowledge_list_membership_projection set captured_at=new.captured_at,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') where clip_id=new.id;
            end""")
        statement = event_for_clip.replace("EVENT_CLIP", "new.id").replace("REASON", "'clip_projection_update'")
        statement = statement.replace("MEMBERSHIP", membership.replace("CI_CLIP", "new.id"))
        add(
            "knowledge_event_clip_projection_update",
            f"create trigger knowledge_event_clip_projection_update after update of title_hint,note,text,url,source_app,source_type,filename,mime_type,captured_at on clips begin {statement}; end",
        )
        membership_new = membership.replace("CI_CLIP", "new.clip_id")
        membership_old = membership.replace("CI_CLIP", "old.clip_id")
        add("knowledge_event_association_insert", f"""
            create trigger knowledge_event_association_insert after insert on clip_knowledge_bases begin
              insert into knowledge_list_membership_projection(knowledge_base_id,clip_id,public_clip_id,captured_at,updated_at)
              select new.knowledge_base_id,new.clip_id,ci.public_id,c.captured_at,strftime('%Y-%m-%dT%H:%M:%fZ','now')
              from clip_identities ci join clips c on c.id=new.clip_id
              join knowledge_bases kb on kb.id=new.knowledge_base_id
              where ci.clip_id=new.clip_id and kb.deleted_at='' and kb.is_archived=0
              on conflict(knowledge_base_id,clip_id) do update set public_clip_id=excluded.public_clip_id,captured_at=excluded.captured_at,updated_at=excluded.updated_at;
              insert into knowledge_change_events(public_clip_id,knowledge_base_id,operation,changed_at,reason,membership_ids_json)
              select ci.public_id,new.knowledge_base_id,'upsert',strftime('%Y-%m-%dT%H:%M:%fZ','now'),'association_upsert',{membership_new}
              from clip_identities ci where ci.clip_id=new.clip_id;
            end""")
        add("knowledge_event_association_delete", f"""
            create trigger knowledge_event_association_delete after delete on clip_knowledge_bases begin
              delete from knowledge_list_membership_projection where knowledge_base_id=old.knowledge_base_id and clip_id=old.clip_id;
              insert into knowledge_change_events(public_clip_id,knowledge_base_id,operation,changed_at,reason,membership_ids_json)
              select ci.public_id,old.knowledge_base_id,'remove',strftime('%Y-%m-%dT%H:%M:%fZ','now'),'association_remove',{membership_old}
              from clip_identities ci where ci.clip_id=old.clip_id;
            end""")

        for table, clip_expr, operations, reason in (
            ("clip_enrichments", "cast(new.clip_id as integer)", ("insert", "update"), "enrichment_update"),
            ("clip_metadata", "new.clip_id", ("insert", "update"), "active_projection_update"),
            ("clip_topic_assignments", "new.clip_id", ("insert", "update"), "topic_update"),
        ):
            if table not in tables:
                continue
            for operation in operations:
                statement = event_for_clip.replace("EVENT_CLIP", clip_expr).replace("REASON", f"'{reason}'")
                statement = statement.replace("MEMBERSHIP", membership.replace("CI_CLIP", clip_expr))
                add(f"knowledge_event_{table}_{operation}", f"create trigger knowledge_event_{table}_{operation} after {operation} on {table} begin {statement}; end")
        if "clip_topic_assignments" in tables:
            statement = event_for_clip.replace("EVENT_CLIP", "old.clip_id").replace("REASON", "'topic_update'")
            statement = statement.replace("MEMBERSHIP", membership.replace("CI_CLIP", "old.clip_id"))
            add("knowledge_event_clip_topic_assignments_delete", f"create trigger knowledge_event_clip_topic_assignments_delete after delete on clip_topic_assignments begin {statement}; end")

        add("knowledge_event_kb_visibility", f"""
            create trigger knowledge_event_kb_visibility after update of is_archived,deleted_at,name on knowledge_bases begin
              delete from knowledge_list_membership_projection
              where knowledge_base_id=new.id and (new.deleted_at<>'' or new.is_archived=1);
              insert into knowledge_list_membership_projection(knowledge_base_id,clip_id,public_clip_id,captured_at,updated_at)
              select new.id,ckb.clip_id,ci.public_id,c.captured_at,strftime('%Y-%m-%dT%H:%M:%fZ','now')
              from clip_knowledge_bases ckb join clip_identities ci on ci.clip_id=ckb.clip_id
              join clips c on c.id=ckb.clip_id
              where ckb.knowledge_base_id=new.id and new.deleted_at='' and new.is_archived=0
              on conflict(knowledge_base_id,clip_id) do update set public_clip_id=excluded.public_clip_id,captured_at=excluded.captured_at,updated_at=excluded.updated_at;
              insert into knowledge_change_events(public_clip_id,knowledge_base_id,operation,changed_at,reason,membership_ids_json)
              select ci.public_id,new.id,
                     case when new.deleted_at<>'' or new.is_archived=1 then 'remove' else 'upsert' end,
                     strftime('%Y-%m-%dT%H:%M:%fZ','now'),'knowledge_base_visibility',
                     {membership.replace('CI_CLIP', 'ckb.clip_id')}
              from clip_knowledge_bases ckb join clip_identities ci on ci.clip_id=ckb.clip_id
              where ckb.knowledge_base_id=new.id and
                    (old.is_archived<>new.is_archived or old.deleted_at<>new.deleted_at or old.name<>new.name);
            end""")
        add("knowledge_event_clip_delete", """
            create trigger knowledge_event_clip_delete before delete on clips begin
              insert into knowledge_change_events(public_clip_id,knowledge_base_id,operation,changed_at,reason,membership_ids_json)
              select ci.public_id,ckb.knowledge_base_id,'remove',strftime('%Y-%m-%dT%H:%M:%fZ','now'),'clip_delete','[]'
              from clip_identities ci join clip_knowledge_bases ckb on ckb.clip_id=ci.clip_id where ci.clip_id=old.id;
              delete from knowledge_list_projection where clip_id=old.id;
              delete from knowledge_list_membership_projection where clip_id=old.id;
            end""")

    def cursor_secret(self) -> bytes:
        with self.connect() as db:
            row = db.execute("select secret_hex from knowledge_list_cursor_key where singleton=1").fetchone()
        if row is None:
            raise RuntimeError("knowledge cursor key unavailable")
        return bytes.fromhex(str(row["secret_hex"]))

    def bootstrap_status(self) -> dict[str, object]:
        with self.connect() as db:
            row = db.execute("select * from knowledge_list_bootstrap_state where version=?", (BOOTSTRAP_VERSION,)).fetchone()
        return dict(row) if row else {"version": BOOTSTRAP_VERSION, "status": "pending", "started_at": "", "completed_at": "", "rows_recorded": 0}

    def bootstrap(self) -> dict[str, object]:
        now = _utc_now()
        with self.connect() as db:
            db.execute("begin immediate")
            status_row = db.execute(
                "select * from knowledge_list_bootstrap_state where version=?",
                (BOOTSTRAP_VERSION,),
            ).fetchone()
            if status_row is not None and str(status_row["status"]) == "completed":
                return {**dict(status_row), "already_completed": True}
            db.execute(
                "insert into knowledge_list_bootstrap_state(version,status,started_at) values (?, 'running', ?) on conflict(version) do update set status='running',started_at=excluded.started_at",
                (BOOTSTRAP_VERSION, now),
            )
            before = int(db.execute("select count(*) from knowledge_change_events").fetchone()[0])
            db.execute(
                """
                insert into knowledge_change_events(public_clip_id,knowledge_base_id,operation,changed_at,reason,membership_ids_json)
                select ci.public_id,ckb.knowledge_base_id,'upsert',?,'legacy_bootstrap',
                       coalesce((select json_group_array(knowledge_base_id) from
                         (select c2.knowledge_base_id from clip_knowledge_bases c2
                          join knowledge_bases k2 on k2.id=c2.knowledge_base_id
                          where c2.clip_id=ckb.clip_id and k2.deleted_at='' and k2.is_archived=0
                          order by c2.knowledge_base_id)), '[]')
                from clip_knowledge_bases ckb
                join clip_identities ci on ci.clip_id=ckb.clip_id
                join knowledge_bases kb on kb.id=ckb.knowledge_base_id
                where kb.deleted_at='' and kb.is_archived=0
                  and not exists (
                    select 1 from knowledge_change_events e
                    where e.public_clip_id=ci.public_id and e.knowledge_base_id=ckb.knowledge_base_id
                  )
                """,
                (now,),
            )
            after = int(db.execute("select count(*) from knowledge_change_events").fetchone()[0])
            recorded = after - before
            completed = _utc_now()
            db.execute(
                "update knowledge_list_bootstrap_state set status='completed',completed_at=?,rows_recorded=? where version=?",
                (completed, recorded, BOOTSTRAP_VERSION),
            )
        return {"version": BOOTSTRAP_VERSION, "status": "completed", "started_at": now, "completed_at": completed, "rows_recorded": recorded, "already_completed": False}

    def latest_revision(self) -> int:
        with self.connect() as db:
            return self._latest_revision_in(db)

    @staticmethod
    def _latest_revision_in(db: sqlite3.Connection) -> int:
        row = db.execute("select coalesce(max(revision),0) from knowledge_change_events").fetchone()
        return int(row[0])

    def _where(self, *, scope: tuple[str, ...], query: str, source: str, source_type: str, attachment: str, captured_after: str, captured_before: str, public_ids: tuple[str, ...] = (), membership_driver: bool = False) -> tuple[str, list[Any]]:
        args: list[Any] = []
        if membership_driver:
            clauses = ["p.knowledge_base_id=?"]
            args.append(scope[0])
        else:
            clauses = ["exists (select 1 from clip_knowledge_bases sx join knowledge_bases sk on sk.id=sx.knowledge_base_id where sx.clip_id=p.clip_id and sk.deleted_at='' and sk.is_archived=0"]
            if scope:
                clauses[0] += " and sx.knowledge_base_id in (" + ",".join("?" for _ in scope) + ")"
                args.extend(scope)
            clauses[0] += ")"
        if public_ids:
            clauses.append("p.public_clip_id in (" + ",".join("?" for _ in public_ids) + ")")
            args.extend(public_ids)
        if query:
            pattern = _literal_like(query)
            clauses.append("(c.title_hint like ? escape '\\' collate nocase or c.note like ? escape '\\' collate nocase or c.text like ? escape '\\' collate nocase or c.url like ? escape '\\' collate nocase or c.source_app like ? escape '\\' collate nocase or c.filename like ? escape '\\' collate nocase or coalesce(en.summary,'') like ? escape '\\' collate nocase or coalesce(en.title,'') like ? escape '\\' collate nocase)")
            args.extend([pattern] * 8)
        if source:
            clauses.append("(c.source_app=? or c.source_type=?)")
            args.extend([source, source])
        if source_type:
            clauses.append("c.source_type=?")
            args.append(source_type)
        attachment_sql = "(c.source_type in ('file','image','audio') or (c.source_type='screen_clip' and (c.filename<>'' or c.mime_type not in ('','text/plain'))))"
        if attachment == "with":
            clauses.append(attachment_sql)
        elif attachment == "without":
            clauses.append("not " + attachment_sql)
        if captured_after:
            clauses.append("p.captured_at>=?")
            args.append(captured_after)
        if captured_before:
            clauses.append("p.captured_at<=?")
            args.append(captured_before)
        return " and ".join(clauses), args

    @staticmethod
    def _active_enrichment_join() -> str:
        return """left join clip_metadata cm on cm.clip_id=c.id
            left join clip_enrichments en on en.id=coalesce(
              cast(json_extract(cm.metadata_json,'$.processing.active_enrichment_id') as integer),
              (select max(e2.id) from clip_enrichments e2 where e2.clip_id=cast(c.id as text) and e2.status='completed')
            )"""

    @staticmethod
    def _projection_source(membership_driver: bool) -> str:
        if membership_driver:
            return "knowledge_list_membership_projection p indexed by idx_knowledge_membership_keyset"
        return "knowledge_list_projection p indexed by idx_knowledge_list_keyset"

    def _select(self, where: str, *, membership_driver: bool) -> str:
        return f"""
            select p.clip_id,p.public_clip_id,p.captured_at,c.source_type,c.source_app,c.url,c.filename,c.mime_type,
                   c.title_hint,c.note,c.text,c.client_request_id,
                   coalesce(en.title,'') enrichment_title,coalesce(en.summary,'') enrichment_summary,
                   coalesce(json_extract(cm.metadata_json,'$.processing.active_projection.structured_metadata.author.value'),'') extraction_author,
                   coalesce(json_extract(cm.metadata_json,'$.processing.active_projection.structured_metadata.author.resolution_state'),'') extraction_author_resolution_state,
                   coalesce(json_extract(cm.metadata_json,'$.processing.active_projection.structured_metadata.core_content.value'),'') extraction_core_content,
                   coalesce(json_extract(cm.metadata_json,'$.processing.active_projection.structured_metadata.core_content.resolution_state'),'') extraction_core_content_resolution_state,
                   coalesce(en.updated_at,c.created_at,p.updated_at) content_updated_at,
                   coalesce((select json_group_array(knowledge_base_id) from
                     (select a.knowledge_base_id from clip_knowledge_bases a join knowledge_bases k on k.id=a.knowledge_base_id
                      where a.clip_id=p.clip_id and k.deleted_at='' and k.is_archived=0 order by a.knowledge_base_id)), '[]') knowledge_base_ids_json,
                   coalesce((select json_group_array(name) from
                     (select k.name from clip_knowledge_bases a join knowledge_bases k on k.id=a.knowledge_base_id
                      where a.clip_id=p.clip_id and k.deleted_at='' and k.is_archived=0 order by a.knowledge_base_id)), '[]') knowledge_base_names_json,
                   coalesce((select max(e.revision) from knowledge_change_events e where e.public_clip_id=p.public_clip_id),0) item_revision,
                   coalesce((select max(e.changed_at) from knowledge_change_events e where e.public_clip_id=p.public_clip_id),coalesce(en.updated_at,c.created_at)) item_updated_at
            from {self._projection_source(membership_driver)} join clips c on c.id=p.clip_id
            {self._active_enrichment_join()}
            where {where}
        """

    def _page_in(self, db: sqlite3.Connection, *, scope: tuple[str, ...], query: str = "", source: str = "", source_type: str = "", attachment: str = "", captured_after: str = "", captured_before: str = "", after_captured_at: str = "", after_public_clip_id: str = "", limit: int = 50, public_ids: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        membership_driver = len(scope) == 1
        where, args = self._where(scope=scope, query=query, source=source, source_type=source_type, attachment=attachment, captured_after=captured_after, captured_before=captured_before, public_ids=public_ids, membership_driver=membership_driver)
        if after_captured_at or after_public_clip_id:
            where += " and (p.captured_at<? or (p.captured_at=? and p.public_clip_id<?))"
            args.extend([after_captured_at, after_captured_at, after_public_clip_id])
        sql = self._select(where, membership_driver=membership_driver) + " order by p.captured_at desc,p.public_clip_id desc limit ?"
        rows = [dict(row) for row in db.execute(sql, [*args, int(limit)]).fetchall()]
        self._attach_topic_assignments(db, rows)
        return rows

    @staticmethod
    def _attach_topic_assignments(db: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        clip_ids = [int(row["clip_id"]) for row in rows]
        placeholders = ",".join("?" for _ in clip_ids)
        assignment_rows = db.execute(
            f"""select a.clip_id,a.id,a.topic_id,a.role,a.source,a.manual_override,
                       a.created_at,d.display_name,d.enabled,d.sort_order
                from clip_topic_assignments a join topic_definitions d on d.topic_id=a.topic_id
                where a.active=1 and a.clip_id in ({placeholders})
                order by a.clip_id,case a.role when 'primary' then 0 else 1 end,
                         d.sort_order,a.created_at,a.id""",
            clip_ids,
        ).fetchall()
        entity_rows = db.execute(
            f"""select clip_id,entity from clip_entities
                where active=1 and clip_id in ({placeholders}) order by clip_id,id""",
            clip_ids,
        ).fetchall()
        keyword_rows = db.execute(
            f"""select clip_id,keyword from clip_keywords
                where active=1 and clip_id in ({placeholders}) order by clip_id,id""",
            clip_ids,
        ).fetchall()
        assignments: dict[int, list[sqlite3.Row]] = {}
        entities: dict[int, list[str]] = {}
        keywords: dict[int, list[str]] = {}
        for item in assignment_rows:
            assignments.setdefault(int(item["clip_id"]), []).append(item)
        for item in entity_rows:
            values = entities.setdefault(int(item["clip_id"]), [])
            value = str(item["entity"])
            if value not in values and len(values) < 8:
                values.append(value)
        for item in keyword_rows:
            values = keywords.setdefault(int(item["clip_id"]), [])
            value = str(item["keyword"])
            if value not in values and len(values) < 12:
                values.append(value)
        for row in rows:
            clip_id = int(row["clip_id"])
            candidates = assignments.get(clip_id, [])
            primary = next((item for item in candidates if str(item["role"]) == "primary"), None)
            seen = {str(primary["topic_id"])} if primary is not None else set()
            secondary: list[dict[str, str]] = []
            for item in candidates:
                topic_id = str(item["topic_id"])
                if str(item["role"]) != "secondary" or topic_id in seen:
                    continue
                seen.add(topic_id)
                secondary.append({"topic_id": topic_id, "display_name": str(item["display_name"])})
                if len(secondary) == 2:
                    break
            topic_id = str(primary["topic_id"]) if primary is not None else "unclassified"
            row["topic_assignment_json"] = json.dumps(
                {
                    "contract_version": "perclip.topic-assignment.v1",
                    "primary": {
                        "topic_id": topic_id,
                        "display_name": str(primary["display_name"]) if primary is not None else "待归类",
                        "source": str(primary["source"]) if primary is not None else "unclassified",
                    },
                    "secondary": secondary,
                    "entities": entities.get(clip_id, []),
                    "keywords": keywords.get(clip_id, []),
                    "unclassified": primary is None or topic_id == "unclassified",
                    "manual_override": bool(primary and primary["manual_override"]),
                    "topic_disabled": bool(primary and not bool(primary["enabled"])),
                },
                ensure_ascii=False,
            )

    def page(self, *, scope: tuple[str, ...], query: str = "", source: str = "", source_type: str = "", attachment: str = "", captured_after: str = "", captured_before: str = "", after_captured_at: str = "", after_public_clip_id: str = "", limit: int = 50, public_ids: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as db:
            db.execute("begin")
            rows = self._page_in(db, scope=scope, query=query, source=source, source_type=source_type, attachment=attachment, captured_after=captured_after, captured_before=captured_before, after_captured_at=after_captured_at, after_public_clip_id=after_public_clip_id, limit=limit, public_ids=public_ids)
            db.commit()
            return rows

    def _count_in(self, db: sqlite3.Connection, *, scope: tuple[str, ...], query: str = "", source: str = "", source_type: str = "", attachment: str = "", captured_after: str = "", captured_before: str = "") -> int:
        membership_driver = len(scope) == 1
        where, args = self._where(scope=scope, query=query, source=source, source_type=source_type, attachment=attachment, captured_after=captured_after, captured_before=captured_before, membership_driver=membership_driver)
        enrichment_join = self._active_enrichment_join() if query else ""
        source_sql = self._projection_source(membership_driver)
        row = db.execute(f"select count(*) from {source_sql} join clips c on c.id=p.clip_id {enrichment_join} where {where}", args).fetchone()
        return int(row[0])

    def count(self, *, scope: tuple[str, ...], query: str = "", source: str = "", source_type: str = "", attachment: str = "", captured_after: str = "", captured_before: str = "") -> int:
        with self.connect() as db:
            return self._count_in(db, scope=scope, query=query, source=source, source_type=source_type, attachment=attachment, captured_after=captured_after, captured_before=captured_before)

    def read_list_snapshot(self, *, scope: tuple[str, ...], query: str = "", source: str = "", source_type: str = "", attachment: str = "", captured_after: str = "", captured_before: str = "", after_captured_at: str = "", after_public_clip_id: str = "", limit: int = 50) -> KnowledgeListSnapshot:
        with self.connect() as db:
            db.execute("begin")
            revision = self._latest_revision_in(db)
            rows = self._page_in(db, scope=scope, query=query, source=source, source_type=source_type, attachment=attachment, captured_after=captured_after, captured_before=captured_before, after_captured_at=after_captured_at, after_public_clip_id=after_public_clip_id, limit=limit)
            total_count = self._count_in(db, scope=scope)
            matching_count = self._count_in(db, scope=scope, query=query, source=source, source_type=source_type, attachment=attachment, captured_after=captured_after, captured_before=captured_before)
            generated_at = _utc_now()
            db.commit()
        return KnowledgeListSnapshot(tuple(rows), total_count, matching_count, revision, generated_at)

    def read_summary_snapshot(self, *, scope: tuple[str, ...], query: str = "", source: str = "", source_type: str = "", attachment: str = "", captured_after: str = "", captured_before: str = "") -> KnowledgeSummarySnapshot:
        with self.connect() as db:
            db.execute("begin")
            revision = self._latest_revision_in(db)
            total_count = self._count_in(db, scope=scope)
            matching_count = self._count_in(db, scope=scope, query=query, source=source, source_type=source_type, attachment=attachment, captured_after=captured_after, captured_before=captured_before)
            generated_at = _utc_now()
            db.commit()
        return KnowledgeSummarySnapshot(total_count, matching_count, revision, generated_at)

    def changes(self, *, after_revision: int, scope: tuple[str, ...], limit: int = 100) -> list[sqlite3.Row]:
        args: list[Any] = [int(after_revision)]
        scope_clause = ""
        if scope:
            scope_clause = " and knowledge_base_id in (" + ",".join("?" for _ in scope) + ")"
            args.extend(scope)
        with self.connect() as db:
            return db.execute(
                f"select revision,public_clip_id,knowledge_base_id,operation,changed_at,reason,membership_ids_json from knowledge_change_events where revision>?{scope_clause} order by revision limit ?",
                [*args, int(limit) + 1],
            ).fetchall()

    def query_plan(self, *, scope: tuple[str, ...], after_captured_at: str = "", after_public_clip_id: str = "") -> list[str]:
        membership_driver = len(scope) == 1
        where, args = self._where(scope=scope, query="", source="", source_type="", attachment="", captured_after="", captured_before="", membership_driver=membership_driver)
        if after_captured_at:
            where += " and (p.captured_at<? or (p.captured_at=? and p.public_clip_id<?))"
            args.extend([after_captured_at, after_captured_at, after_public_clip_id])
        sql = self._select(where, membership_driver=membership_driver) + " order by p.captured_at desc,p.public_clip_id desc limit 51"
        with self.connect() as db:
            return [str(row[3]) for row in db.execute("explain query plan " + sql, args).fetchall()]


def make_cursor(*, secret: bytes, scope: tuple[str, ...], query: str, source: str, source_type: str, attachment: str, captured_after: str, captured_before: str, row: sqlite3.Row) -> str:
    return encode_cursor(KnowledgeListCursor(scope, query, source, source_type, attachment, captured_after, captured_before, str(row["captured_at"]), str(row["public_clip_id"])), secret)
