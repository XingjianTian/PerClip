from __future__ import annotations

import sqlite3
import secrets
import stat
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .errors import LeaseLostError


STATUSES = {"pending", "sending", "sent", "conflict", "failed", "unsupported"}


@dataclass(frozen=True)
class OutboxRecord:
    event_key: str
    event_type: str
    client_request_id: str
    routing_target_knowledge_base_id: str
    status: str
    attempt_count: int
    next_attempt_at: str
    receipt_id: str
    last_error_code: str
    lease_token: str
    created_at: str
    updated_at: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WechatOutbox:
    """Metadata-only durable delivery state; never a clip source of truth."""

    def __init__(self, path: Path, *, stale_seconds: int = 300, max_attempts: int = 8,
                 base_backoff_seconds: int = 10, max_backoff_seconds: int = 3600) -> None:
        self.path = path
        self.stale_seconds = stale_seconds
        self.max_attempts = max_attempts
        self.base_backoff_seconds = base_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(stat.S_IRWXU)
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("pragma busy_timeout=10000")
        if self.path.exists():
            self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return db

    def migrate(self) -> None:
        with self.connect() as db:
            db.execute("""create table if not exists wechat_outbox (
                event_key text primary key, event_type text not null, client_request_id text not null,
                routing_target_knowledge_base_id text not null default '',
                status text not null, attempt_count integer not null default 0,
                next_attempt_at text not null, receipt_id text not null default '',
                last_error_code text not null default '', lease_token text not null default '',
                created_at text not null, updated_at text not null
            )""")
            columns = {str(row[1]) for row in db.execute("pragma table_info(wechat_outbox)")}
            if "routing_target_knowledge_base_id" not in columns:
                db.execute("alter table wechat_outbox add column routing_target_knowledge_base_id text not null default ''")
            if "lease_token" not in columns:
                db.execute("alter table wechat_outbox add column lease_token text not null default ''")
            db.execute("create index if not exists idx_wechat_outbox_due on wechat_outbox(status,next_attempt_at)")
        self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def enqueue(self, *, event_key: str, event_type: str, client_request_id: str,
                routing_target_knowledge_base_id: str = "", now: datetime | None = None) -> OutboxRecord:
        stamp = (now or utc_now()).isoformat()
        with self.connect() as db:
            db.execute("""insert or ignore into wechat_outbox
                (event_key,event_type,client_request_id,routing_target_knowledge_base_id,status,attempt_count,
                 next_attempt_at,created_at,updated_at)
                values (?,?,?,?,'pending',0,?,?,?)""",
                (event_key, event_type, client_request_id, routing_target_knowledge_base_id, stamp, stamp, stamp))
            row = db.execute("select * from wechat_outbox where event_key=?", (event_key,)).fetchone()
        assert row is not None
        if (row["client_request_id"] != client_request_id or row["event_type"] != event_type
                or row["routing_target_knowledge_base_id"] != routing_target_knowledge_base_id):
            raise ValueError("event_key belongs to a different stable event")
        return self._record(row)

    def recover_stale(self, *, now: datetime | None = None) -> int:
        current = now or utc_now()
        cutoff = (current - timedelta(seconds=self.stale_seconds)).isoformat()
        with self.connect() as db:
            cursor = db.execute("""update wechat_outbox set status='pending',next_attempt_at=?,lease_token='',updated_at=?
                where status='sending' and updated_at<=?""", (current.isoformat(), current.isoformat(), cutoff))
            return cursor.rowcount

    def claim(self, *, limit: int = 20, now: datetime | None = None) -> list[OutboxRecord]:
        current = (now or utc_now()).isoformat()
        claimed: list[OutboxRecord] = []
        with self._lock, self.connect() as db:
            db.execute("begin immediate")
            rows = db.execute("""select * from wechat_outbox where status='pending' and next_attempt_at<=?
                order by created_at,event_key limit ?""", (current, max(0, limit))).fetchall()
            for row in rows:
                lease_token = secrets.token_urlsafe(32)
                cursor = db.execute("""update wechat_outbox set status='sending',attempt_count=attempt_count+1,
                    lease_token=?,updated_at=?
                    where event_key=? and status='pending'""", (lease_token, current, row["event_key"]))
                if cursor.rowcount:
                    updated = db.execute("select * from wechat_outbox where event_key=?", (row["event_key"],)).fetchone()
                    claimed.append(self._record(updated))
            db.execute("commit")
        return claimed

    def finish(self, event_key: str, *, lease_token: str, status: str, receipt_id: str = "",
               error_code: str = "", now: datetime | None = None) -> bool:
        if status not in STATUSES - {"pending", "sending"}:
            raise ValueError("invalid terminal outbox status")
        stamp = (now or utc_now()).isoformat()
        with self.connect() as db:
            cursor = db.execute("""update wechat_outbox set status=?,receipt_id=?,last_error_code=?,lease_token='',updated_at=?
                where event_key=? and status='sending' and lease_token=?""",
                (status, receipt_id, error_code, stamp, event_key, lease_token))
        if cursor.rowcount != 1:
            raise LeaseLostError("outbox delivery lease was lost")
        return True

    def mark_unsupported(self, event_key: str, *, now: datetime | None = None) -> None:
        stamp = (now or utc_now()).isoformat()
        with self.connect() as db:
            db.execute("""update wechat_outbox set status='unsupported',last_error_code='unsupported',lease_token='',updated_at=?
                where event_key=? and status='pending'""", (stamp, event_key))

    def retry(self, event_key: str, *, lease_token: str, error_code: str, now: datetime | None = None) -> bool:
        current = now or utc_now()
        with self.connect() as db:
            row = db.execute("""select attempt_count from wechat_outbox
                where event_key=? and status='sending' and lease_token=?""", (event_key, lease_token)).fetchone()
            if row is None:
                raise LeaseLostError("outbox delivery lease was lost")
            attempts = int(row["attempt_count"])
            if attempts >= self.max_attempts:
                cursor = db.execute("""update wechat_outbox set status='failed',last_error_code=?,lease_token='',updated_at=?
                    where event_key=? and status='sending' and lease_token=?""",
                    (error_code, current.isoformat(), event_key, lease_token))
                if cursor.rowcount != 1:
                    raise LeaseLostError("outbox delivery lease was lost")
                return True
            delay = min(self.max_backoff_seconds, self.base_backoff_seconds * (2 ** max(0, attempts - 1)))
            due = (current + timedelta(seconds=delay)).isoformat()
            cursor = db.execute("""update wechat_outbox set status='pending',next_attempt_at=?,last_error_code=?,
                lease_token='',updated_at=? where event_key=? and status='sending' and lease_token=?""",
                (due, error_code, current.isoformat(), event_key, lease_token))
            if cursor.rowcount != 1:
                raise LeaseLostError("outbox delivery lease was lost")
        return True

    def get(self, event_key: str) -> OutboxRecord | None:
        with self.connect() as db:
            row = db.execute("select * from wechat_outbox where event_key=?", (event_key,)).fetchone()
        return self._record(row) if row else None

    @staticmethod
    def _record(row: sqlite3.Row) -> OutboxRecord:
        return OutboxRecord(**{key: row[key] for key in OutboxRecord.__dataclass_fields__})
