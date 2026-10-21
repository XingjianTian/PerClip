from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable

from .client import PerClipIngestClient
from .errors import (IngestConflictError, LeaseLostError, MappingError, MediaError,
                     RetryableIngestError, TerminalIngestError, UnsupportedEventError)
from .mapping import WechatIngestMapper
from .media import MediaProvider, SpoolManager
from .models import NormalizedWechatEvent
from .outbox import OutboxRecord, WechatOutbox

EventLoader = Callable[[OutboxRecord], Awaitable[NormalizedWechatEvent | None]]

REPLIES = {
    "sent": "已保存", "duplicate": "已存在", "unsupported": "格式不支持",
    "conflict": "内容冲突，需要检查", "retry": "暂时失败，将重试", "failed": "保存失败",
}


class WechatBridgeService:
    def __init__(self, *, mapper: WechatIngestMapper, client: PerClipIngestClient,
                 outbox: WechatOutbox, media_provider: MediaProvider | None = None,
                 event_loader: EventLoader | None = None, spool: SpoolManager | None = None,
                 cache_max_count: int = 256, cache_max_age_seconds: float = 3600) -> None:
        self.mapper = mapper
        self.client = client
        self.outbox = outbox
        self.media_provider = media_provider
        self.event_loader = event_loader
        self.spool = spool
        self.cache_max_count = max(1, cache_max_count)
        self.cache_max_age_seconds = max(1.0, cache_max_age_seconds)
        self._event_cache: OrderedDict[str, tuple[NormalizedWechatEvent, str, float]] = OrderedDict()

    async def handle_event(self, event: NormalizedWechatEvent, routing_target: str = "") -> str:
        try:
            mapped = self.mapper.map(event, routing_target)
        except UnsupportedEventError:
            try:
                key = self._event_key(event)
                request_id = self.mapper.client_request_id(event)
            except MappingError:
                return REPLIES["failed"]
            self.outbox.enqueue(event_key=key, event_type=type(event).__name__, client_request_id=request_id,
                                routing_target_knowledge_base_id="")
            self.outbox.mark_unsupported(key)
            return REPLIES["unsupported"]
        except MappingError:
            return REPLIES["failed"]
        key = self._event_key(event)
        try:
            record = self.outbox.enqueue(
                event_key=key, event_type=type(event).__name__, client_request_id=mapped.client_request_id,
                routing_target_knowledge_base_id=str(mapped.envelope["routing"]["target_knowledge_base_id"]),
            )
        except ValueError:
            return REPLIES["conflict"]
        if record.status == "sent":
            return REPLIES["duplicate"]
        if record.status == "conflict":
            return REPLIES["conflict"]
        if record.status in {"failed", "unsupported"}:
            return REPLIES[record.status]
        self._cache_put(key, event, record.routing_target_knowledge_base_id)
        results = await self.process_pending(limit=1)
        return results.get(key, REPLIES["retry"])

    async def process_pending(self, limit: int = 20) -> dict[str, str]:
        self.outbox.recover_stale()
        results: dict[str, str] = {}
        for record in self.outbox.claim(limit=limit):
            media = None
            cached = self._cache_get(record.event_key)
            event = cached[0] if cached else None
            routing_target = record.routing_target_knowledge_base_id
            if event is None and self.event_loader is not None:
                event = await self.event_loader(record)
            if event is None:
                try:
                    if self.event_loader is None:
                        persisted = self._finish_record(record, status="failed", error_code="event_unavailable")
                        results[record.event_key] = REPLIES["failed" if persisted else "retry"]
                    else:
                        persisted = self._retry_record(record, error_code="event_unavailable")
                        current = self.outbox.get(record.event_key)
                        results[record.event_key] = (REPLIES["failed"] if persisted and current and current.status == "failed"
                                                     else REPLIES["retry"])
                except LeaseLostError:
                    results[record.event_key] = REPLIES["retry"]
                continue
            try:
                mapped = self.mapper.map(event, routing_target)
                if mapped.client_request_id != record.client_request_id:
                    raise IngestConflictError("stable event identity changed")
                if mapped.multipart:
                    if self.media_provider is None:
                        raise RetryableIngestError("media provider unavailable")
                    media = await self.media_provider.fetch(event)
                    receipt = await self.client.send_multipart(mapped.envelope, media)
                else:
                    receipt = await self.client.send_json(mapped.envelope)
                if not self._finish_record(record, status="sent", receipt_id=receipt.receipt_id):
                    results[record.event_key] = REPLIES["retry"]
                    continue
                if self.spool and media is not None:
                    self.spool.remove(media.spool_token)
                self._cache_remove(record.event_key)
                results[record.event_key] = REPLIES["duplicate" if receipt.duplicate else "sent"]
            except UnsupportedEventError:
                if not self._finish_record(record, status="unsupported", error_code="unsupported"):
                    results[record.event_key] = REPLIES["retry"]
                    continue
                self._cache_remove(record.event_key)
                results[record.event_key] = REPLIES["unsupported"]
            except IngestConflictError:
                if not self._finish_record(record, status="conflict", error_code="content_conflict"):
                    results[record.event_key] = REPLIES["retry"]
                    continue
                if self.spool and media is not None: self.spool.remove(media.spool_token)
                self._cache_remove(record.event_key)
                results[record.event_key] = REPLIES["conflict"]
            except TerminalIngestError as error:
                if not self._finish_record(record, status="failed", error_code=error.code):
                    results[record.event_key] = REPLIES["retry"]
                    continue
                if self.spool and media is not None: self.spool.remove(media.spool_token)
                self._cache_remove(record.event_key)
                results[record.event_key] = REPLIES["failed"]
            except (RetryableIngestError, MediaError) as error:
                if not self._retry_record(record, error_code=error.code):
                    results[record.event_key] = REPLIES["retry"]
                    continue
                results[record.event_key] = (REPLIES["failed"] if self.outbox.get(record.event_key).status == "failed"
                                             else REPLIES["retry"])
            except MappingError as error:
                if not self._finish_record(record, status="failed", error_code=error.code):
                    results[record.event_key] = REPLIES["retry"]
                    continue
                if self.spool and media is not None: self.spool.remove(media.spool_token)
                self._cache_remove(record.event_key)
                results[record.event_key] = REPLIES["failed"]
            except LeaseLostError:
                results[record.event_key] = REPLIES["retry"]
        return results

    def _event_key(self, event: NormalizedWechatEvent) -> str:
        return self.mapper.client_request_id(event)

    def _finish_record(self, record: OutboxRecord, *, status: str, receipt_id: str = "",
                       error_code: str = "") -> bool:
        try:
            return self.outbox.finish(record.event_key, lease_token=record.lease_token, status=status,
                                      receipt_id=receipt_id, error_code=error_code)
        except LeaseLostError:
            return False

    def _retry_record(self, record: OutboxRecord, *, error_code: str) -> bool:
        try:
            return self.outbox.retry(record.event_key, lease_token=record.lease_token, error_code=error_code)
        except LeaseLostError:
            return False

    def _cache_put(self, key: str, event: NormalizedWechatEvent, routing_target: str) -> None:
        self._prune_cache()
        self._event_cache[key] = (event, routing_target, time.monotonic())
        self._event_cache.move_to_end(key)
        while len(self._event_cache) > self.cache_max_count:
            self._event_cache.popitem(last=False)

    def _cache_get(self, key: str) -> tuple[NormalizedWechatEvent, str, float] | None:
        self._prune_cache()
        value = self._event_cache.get(key)
        if value is not None:
            self._event_cache.move_to_end(key)
        return value

    def _cache_remove(self, key: str) -> None:
        self._event_cache.pop(key, None)

    def _prune_cache(self) -> None:
        cutoff = time.monotonic() - self.cache_max_age_seconds
        expired = [key for key, (_event, _routing, stored_at) in self._event_cache.items() if stored_at < cutoff]
        for key in expired:
            self._event_cache.pop(key, None)
