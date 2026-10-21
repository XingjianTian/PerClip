"""The only LangBot-version-sensitive boundary.

No LangBot package is imported because the audited workspace contains no real,
versioned SDK contract. A future wiring module implements these ports and only
normalizes callback data plus delegates to WechatBridgeService.
"""
from __future__ import annotations

from typing import Any, Protocol

from .models import NormalizedWechatEvent


class LangBotEventPort(Protocol):
    def normalize(self, raw_event: Any) -> NormalizedWechatEvent: ...


class LangBotReplyPort(Protocol):
    async def reply(self, raw_event: Any, message: str) -> None: ...


async def handle_langbot_callback(raw_event: Any, *, event_port: LangBotEventPort,
                                  reply_port: LangBotReplyPort, service: Any) -> None:
    """Thin conversion/delegation only: no HTTP, retry, media download, or outbox logic."""
    event = event_port.normalize(raw_event)
    message = await service.handle_event(event)
    await reply_port.reply(raw_event, message)
