from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, kw_only=True)
class NormalizedWechatEvent:
    event_id: str
    message_id: str = ""
    conversation_hint: str = ""
    sender_hint: str = ""
    source_app: str = "WeChat"
    occurred_at: datetime
    timezone: str
    text: str = ""
    url: str = ""
    filename: str = ""
    mime_type: str = ""
    media_reference: Any = field(default=None, repr=False, compare=False)
    part_index: int = 0
    part_count: int = 1
    parent_event_id: str = ""


@dataclass(frozen=True, kw_only=True)
class WechatTextEvent(NormalizedWechatEvent):
    pass


@dataclass(frozen=True, kw_only=True)
class WechatLinkEvent(NormalizedWechatEvent):
    pass


@dataclass(frozen=True, kw_only=True)
class WechatImageEvent(NormalizedWechatEvent):
    pass


@dataclass(frozen=True, kw_only=True)
class WechatFileEvent(NormalizedWechatEvent):
    pass


@dataclass(frozen=True, kw_only=True)
class WechatUnsupportedEvent(NormalizedWechatEvent):
    unsupported_type: str = "unsupported"


@dataclass(frozen=True)
class MappedIngest:
    client_request_id: str
    envelope: dict[str, object]
    multipart: bool


@dataclass(frozen=True)
class MediaPayload:
    data: bytes
    filename: str
    mime_type: str
    spool_token: str = ""


@dataclass(frozen=True)
class IngestReceipt:
    receipt_id: str
    client_request_id: str
    duplicate: bool = False
    status: str = "received"
