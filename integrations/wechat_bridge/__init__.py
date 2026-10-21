"""Framework-neutral WeChat to PerClip ingest bridge."""

from .mapping import WechatIngestMapper
from .models import (
    WechatFileEvent,
    WechatImageEvent,
    WechatLinkEvent,
    WechatTextEvent,
    WechatUnsupportedEvent,
)
from .service import WechatBridgeService

__all__ = [
    "WechatBridgeService", "WechatIngestMapper", "WechatTextEvent", "WechatLinkEvent",
    "WechatImageEvent", "WechatFileEvent", "WechatUnsupportedEvent",
]
