from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from integrations.wechat_bridge.errors import LeaseLostError
from integrations.wechat_bridge.outbox import WechatOutbox


NOW = datetime(2026, 7, 12, tzinfo=timezone.utc)


def test_migration_unique_and_no_content_columns(tmp_path):
    box = WechatOutbox(tmp_path / "outbox.sqlite3"); box.migrate()
    a = box.enqueue(event_key="event", event_type="text", client_request_id="wechat:d:event", now=NOW)
    b = box.enqueue(event_key="event", event_type="text", client_request_id="wechat:d:event", now=NOW)
    assert a == b
    with box.connect() as db:
        columns = {row[1] for row in db.execute("pragma table_info(wechat_outbox)")}
    assert {"routing_target_knowledge_base_id", "lease_token"} <= columns
    assert not columns & {"text", "content", "payload", "cookie", "headers", "path", "url", "binary"}
    with pytest.raises(ValueError): box.enqueue(event_key="event", event_type="file", client_request_id="other", now=NOW)
    with pytest.raises(ValueError):
        box.enqueue(event_key="event", event_type="text", client_request_id="wechat:d:event",
                    routing_target_knowledge_base_id="kb-changed", now=NOW)


def test_stale_recovery_backoff_and_terminal_attempt_limit(tmp_path):
    box = WechatOutbox(tmp_path / "o.db", stale_seconds=30, max_attempts=2, base_backoff_seconds=10)
    box.enqueue(event_key="e", event_type="text", client_request_id="r", now=NOW)
    first = box.claim(now=NOW)[0]
    assert first.attempt_count == 1 and first.lease_token
    assert box.recover_stale(now=NOW + timedelta(seconds=31)) == 1
    assert box.get("e").attempt_count == 1 and box.get("e").lease_token == ""
    second = box.claim(now=NOW + timedelta(seconds=31))[0]
    assert second.attempt_count == 2 and second.lease_token != first.lease_token
    box.retry("e", lease_token=second.lease_token, error_code="upstream_retryable", now=NOW + timedelta(seconds=31))
    assert box.get("e").status == "failed"


def test_concurrent_workers_claim_once(tmp_path):
    path = tmp_path / "o.db"
    box = WechatOutbox(path)
    box.enqueue(event_key="e", event_type="text", client_request_id="r", now=NOW)
    boxes = [WechatOutbox(path) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda candidate: candidate.claim(limit=1, now=NOW), boxes))
    assert sum(len(result) for result in results) == 1


def test_conflict_keeps_request_id(tmp_path):
    box = WechatOutbox(tmp_path / "o.db")
    box.enqueue(event_key="e", event_type="text", client_request_id="wechat:d:e", now=NOW)
    record = box.claim(now=NOW)[0]
    box.finish("e", lease_token=record.lease_token, status="conflict", error_code="content_conflict", now=NOW)
    assert box.get("e").client_request_id == "wechat:d:e"
    assert box.get("e").status == "conflict"


def test_stale_worker_cannot_finish_or_retry_newer_lease(tmp_path):
    box = WechatOutbox(tmp_path / "o.db", stale_seconds=30)
    box.enqueue(event_key="e", event_type="text", client_request_id="r", now=NOW)
    worker_a = box.claim(now=NOW)[0]
    box.recover_stale(now=NOW + timedelta(seconds=31))
    worker_b = box.claim(now=NOW + timedelta(seconds=31))[0]
    with pytest.raises(LeaseLostError):
        box.finish("e", lease_token=worker_a.lease_token, status="sent", now=NOW + timedelta(seconds=31))
    with pytest.raises(LeaseLostError):
        box.retry("e", lease_token=worker_a.lease_token, error_code="late", now=NOW + timedelta(seconds=31))
    assert box.finish("e", lease_token=worker_b.lease_token, status="sent", now=NOW + timedelta(seconds=31))
    assert box.get("e").status == "sent"


def test_migration_adds_columns_idempotently(tmp_path):
    path = tmp_path / "legacy.db"
    import sqlite3
    with sqlite3.connect(path) as db:
        db.execute("""create table wechat_outbox (event_key text primary key,event_type text not null,
            client_request_id text not null,status text not null,attempt_count integer not null,
            next_attempt_at text not null,receipt_id text not null,last_error_code text not null,
            created_at text not null,updated_at text not null)""")
    box = WechatOutbox(path); box.migrate()
    with box.connect() as db:
        columns = {row[1] for row in db.execute("pragma table_info(wechat_outbox)")}
    assert {"routing_target_knowledge_base_id", "lease_token"} <= columns
