import asyncio
import json
import urllib.error
from datetime import datetime
import stat

import pytest

from integrations.wechat_bridge.client import ClientTimeouts, PerClipIngestClient
from integrations.wechat_bridge.errors import IngestConflictError, LeaseLostError, RetryableIngestError, TerminalIngestError
from integrations.wechat_bridge.mapping import WechatIngestMapper
from integrations.wechat_bridge.media import BytesMediaProvider, SpoolManager
from integrations.wechat_bridge.models import IngestReceipt, WechatImageEvent, WechatTextEvent, WechatUnsupportedEvent
from integrations.wechat_bridge.outbox import WechatOutbox
from integrations.wechat_bridge.service import WechatBridgeService

NOW = datetime.fromisoformat("2026-07-12T10:00:00+08:00")

class Response:
    def __init__(self, body, status=200): self.body = body; self.status = status
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, _limit): return self.body

def client(monkeypatch, status=200, result=None, api_url="http://localhost:8000"):
    seen = {}
    body = json.dumps(result or {"receipt_id": "ir_" + "a" * 32, "client_request_id": "wechat:d:e", "duplicate": False, "status": "received"}).encode()
    def open_(request, timeout):
        seen.update(url=request.full_url, headers=dict(request.headers), data=request.data, timeout=timeout)
        if status >= 400: raise urllib.error.HTTPError(request.full_url, status, "safe", {}, None)
        return Response(body, status)
    monkeypatch.setattr("urllib.request.urlopen", open_)
    return PerClipIngestClient(api_url, "super-secret", timeouts=ClientTimeouts(total=1)), seen

def test_request_shape_auth_redaction_duplicate_and_receipt(monkeypatch):
    c, seen = client(monkeypatch, result={"receipt_id": "ir_" + "a" * 32, "client_request_id": "wechat:d:e", "duplicate": True, "status": "received"})
    receipt = asyncio.run(c.send_json({"client_request_id": "wechat:d:e"}))
    assert receipt.duplicate is True
    assert seen["url"].endswith("/api/ingest/v1/clips")
    assert seen["headers"]["Authorization"] == "Bearer super-secret"
    assert "super-secret" not in repr(c)
    assert "localhost" not in repr(c) and "/api" not in repr(c)
    assert asyncio.run(c.get_receipt("ir_" + "a" * 32)).receipt_id.startswith("ir_")

@pytest.mark.parametrize("status,error", [(409, IngestConflictError), (422, TerminalIngestError), (404, TerminalIngestError), (429, RetryableIngestError), (500, RetryableIngestError)])
def test_status_classification(monkeypatch, status, error):
    c, _ = client(monkeypatch, status=status)
    with pytest.raises(error): asyncio.run(c.send_json({"client_request_id": "wechat:d:e"}))

def test_network_failure_is_retryable_without_body_leak(monkeypatch):
    c, _ = client(monkeypatch)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("private upstream body")))
    with pytest.raises(RetryableIngestError) as caught:
        asyncio.run(c.send_json({"client_request_id": "wechat:d:e", "text": "private"}))
    assert "private" not in str(caught.value)

@pytest.mark.parametrize("url", [
    "", "ftp://example.com", "https:///missing", "http://example.com", "https://user@example.com",
    "https://user:pass@example.com", "https://example.com?x=1", "https://example.com/#fragment",
])
def test_client_rejects_unsafe_api_urls(url):
    from integrations.wechat_bridge.errors import ConfigurationError
    with pytest.raises(ConfigurationError): PerClipIngestClient(url, "token")

def test_client_supports_safe_reverse_proxy_prefix(monkeypatch):
    c, seen = client(monkeypatch, api_url="https://example.com/perclip")
    asyncio.run(c.send_json({"client_request_id": "wechat:d:e"}))
    assert seen["url"] == "https://example.com/perclip/api/ingest/v1/clips"

@pytest.mark.parametrize("result", [
    {"receipt_id": "bad", "client_request_id": "wechat:d:e", "status": "received"},
    {"receipt_id": "ir_" + "a" * 32, "client_request_id": "other", "status": "received"},
    {"receipt_id": "ir_" + "a" * 32, "client_request_id": "wechat:d:e", "status": "unknown"},
    {"receipt_id": "ir_" + "a" * 32, "client_request_id": "wechat:d:e", "status": "received", "duplicate": "true"},
])
def test_malformed_or_mismatched_receipt_is_retryable(monkeypatch, result):
    c, _ = client(monkeypatch, result=result)
    with pytest.raises(RetryableIngestError):
        asyncio.run(c.send_json({"client_request_id": "wechat:d:e"}))

class FakeClient:
    def __init__(self, failures=0, conflict=False): self.failures=failures; self.conflict=conflict; self.ids=[]; self.targets=[]
    async def send_json(self, envelope):
        self.ids.append(envelope["client_request_id"])
        self.targets.append(envelope["routing"]["target_knowledge_base_id"])
        if self.conflict: raise IngestConflictError("conflict")
        if self.failures: self.failures -= 1; raise RetryableIngestError("later")
        return IngestReceipt("ir_" + "b" * 32, envelope["client_request_id"])
    async def send_multipart(self, envelope, media): return await self.send_json(envelope)

def service(tmp_path, fake, media=None, loader=None):
    return WechatBridgeService(mapper=WechatIngestMapper("d", ""), client=fake,
                               outbox=WechatOutbox(tmp_path / "state" / "o.db", base_backoff_seconds=0,
                                                   max_attempts=2), media_provider=media, event_loader=loader)

def test_temporary_failure_then_success_and_same_identity(tmp_path):
    fake = FakeClient(failures=1); svc = service(tmp_path, fake)
    event = WechatTextEvent(event_id="e", occurred_at=NOW, timezone="Asia/Shanghai", text="private text")
    assert asyncio.run(svc.handle_event(event)) == "暂时失败，将重试"
    assert asyncio.run(svc.process_pending())["wechat:d:e"] == "已保存"
    assert fake.ids == ["wechat:d:e", "wechat:d:e"]
    database_bytes = svc.outbox.path.read_bytes()
    assert b"private text" not in database_bytes and b"Authorization" not in database_bytes

def test_service_never_reports_success_after_losing_lease(tmp_path, monkeypatch):
    svc = service(tmp_path, FakeClient())
    monkeypatch.setattr(svc.outbox, "finish", lambda *_args, **_kwargs: (_ for _ in ()).throw(LeaseLostError("lost")))
    event = WechatTextEvent(event_id="e", occurred_at=NOW, timezone="Asia/Shanghai", text="x")
    assert asyncio.run(svc.handle_event(event)) == "暂时失败，将重试"

def test_restart_with_loader_preserves_explicit_routing(tmp_path):
    event = WechatTextEvent(event_id="e", occurred_at=NOW, timezone="Asia/Shanghai", text="private text")
    first = service(tmp_path, FakeClient(failures=1))
    assert asyncio.run(first.handle_event(event, "kb-explicit")) == "暂时失败，将重试"
    seen_records = []
    async def loader(record):
        seen_records.append(record)
        return event
    replacement_client = FakeClient()
    replacement = service(tmp_path, replacement_client, loader=loader)
    assert asyncio.run(replacement.process_pending())["wechat:d:e"] == "已保存"
    assert seen_records[0].routing_target_knowledge_base_id == "kb-explicit"
    assert replacement_client.targets == ["kb-explicit"]

def test_restart_without_loader_converges_to_terminal_event_unavailable(tmp_path):
    event = WechatTextEvent(event_id="e", occurred_at=NOW, timezone="Asia/Shanghai", text="private text")
    first = service(tmp_path, FakeClient(failures=1))
    assert asyncio.run(first.handle_event(event)) == "暂时失败，将重试"
    replacement = service(tmp_path, FakeClient())
    assert asyncio.run(replacement.process_pending())["wechat:d:e"] == "保存失败"
    record = replacement.outbox.get("wechat:d:e")
    assert record.status == "failed" and record.last_error_code == "event_unavailable"

def test_loader_none_retries_only_to_attempt_limit(tmp_path):
    event = WechatTextEvent(event_id="e", occurred_at=NOW, timezone="Asia/Shanghai", text="x")
    first = service(tmp_path, FakeClient(failures=1))
    asyncio.run(first.handle_event(event))
    async def unavailable(_record): return None
    replacement = service(tmp_path, FakeClient(), loader=unavailable)
    assert asyncio.run(replacement.process_pending())["wechat:d:e"] == "保存失败"
    assert replacement.outbox.get("wechat:d:e").status == "failed"

def test_changed_routing_target_conflicts(tmp_path):
    event = WechatTextEvent(event_id="e", occurred_at=NOW, timezone="Asia/Shanghai", text="x")
    svc = service(tmp_path, FakeClient(failures=1))
    assert asyncio.run(svc.handle_event(event, "kb-a")) == "暂时失败，将重试"
    assert asyncio.run(svc.handle_event(event, "kb-b")) == "内容冲突，需要检查"
    assert svc.outbox.get("wechat:d:e").routing_target_knowledge_base_id == "kb-a"

def test_conflict_is_terminal_and_does_not_change_id(tmp_path):
    fake = FakeClient(conflict=True); svc = service(tmp_path, fake)
    event = WechatTextEvent(event_id="e", occurred_at=NOW, timezone="Asia/Shanghai", text="x")
    assert asyncio.run(svc.handle_event(event)) == "内容冲突，需要检查"
    assert svc.outbox.get("wechat:d:e").status == "conflict"
    assert fake.ids == ["wechat:d:e"]

def test_unsupported_is_marked_even_with_older_pending_record(tmp_path):
    svc = service(tmp_path, FakeClient())
    svc.outbox.enqueue(event_key="wechat:d:older", event_type="text", client_request_id="wechat:d:older")
    event = WechatUnsupportedEvent(event_id="voice", occurred_at=NOW, timezone="Asia/Shanghai", unsupported_type="voice")
    assert asyncio.run(svc.handle_event(event)) == "格式不支持"
    assert svc.outbox.get("wechat:d:voice").status == "unsupported"

def test_invalid_event_returns_only_safe_failure_reply(tmp_path):
    svc = service(tmp_path, FakeClient())
    event = WechatTextEvent(event_id="e", occurred_at=NOW.replace(tzinfo=None), timezone="UTC", text="private")
    assert asyncio.run(svc.handle_event(event)) == "保存失败"

def test_malformed_unsupported_event_has_no_partial_outbox_row(tmp_path):
    svc = service(tmp_path, FakeClient())
    event = WechatUnsupportedEvent(event_id="wxid_private", occurred_at=NOW, timezone="Asia/Shanghai", unsupported_type="voice")
    assert asyncio.run(svc.handle_event(event)) == "保存失败"
    with svc.outbox.connect() as db:
        assert db.execute("select count(*) from wechat_outbox").fetchone()[0] == 0

def test_media_bytes_are_bounded_and_not_stored(tmp_path):
    svc = service(tmp_path, FakeClient(), BytesMediaProvider(max_bytes=10))
    event = WechatImageEvent(event_id="image", occurred_at=NOW, timezone="Asia/Shanghai", filename="photo.jpg", mime_type="image/jpeg", media_reference=b"jpeg")
    assert asyncio.run(svc.handle_event(event)) == "已保存"
    with svc.outbox.connect() as db: row = dict(db.execute("select * from wechat_outbox").fetchone())
    assert b"jpeg" not in repr(row).encode()

def test_spool_retention_cleanup(tmp_path):
    spool = SpoolManager(tmp_path / "spool", retention_seconds=0)
    item = spool.directory / "retry.bin"; item.write_bytes(b"x")
    assert spool.cleanup_expired(now=item.stat().st_mtime + 1) == 1

def test_outbox_and_spool_permissions(tmp_path):
    state = tmp_path / "state"
    box = WechatOutbox(state / "outbox.sqlite3")
    spool = SpoolManager(tmp_path / "spool")
    token = spool.write(b"safe-test-bytes")
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert stat.S_IMODE(box.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(spool.directory.stat().st_mode) == 0o700
    assert stat.S_IMODE((spool.directory / token).stat().st_mode) == 0o600

def test_langbot_sdk_is_not_imported():
    import integrations.wechat_bridge.langbot_adapter as adapter
    assert hasattr(adapter, "LangBotEventPort")
