from __future__ import annotations

import os
import re
from datetime import timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigurationError, MappingError, UnsupportedEventError
from .models import (
    MappedIngest, NormalizedWechatEvent, WechatFileEvent, WechatImageEvent,
    WechatLinkEvent, WechatTextEvent, WechatUnsupportedEvent,
)

_SAFE_ID = re.compile(r"[^A-Za-z0-9._:-]+")
_SAFE_HINT = re.compile(r"[\x00-\x1f\x7f]")
_SECRET = re.compile(r"(?i)(?:(?:bearer|authorization|cookie|token|secret|password)\b|wxid_)")
_MIME = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$")


def safe_identifier(value: str, *, limit: int = 64) -> str:
    cleaned = _SAFE_ID.sub("-", str(value).strip()).strip("-.:_")[:limit]
    if not cleaned or _SECRET.search(cleaned):
        raise MappingError("invalid stable event identity")
    return cleaned


def safe_hint(value: str, *, limit: int = 40) -> str:
    cleaned = _SAFE_HINT.sub("", str(value)).strip()[:limit]
    return "" if _SECRET.search(cleaned) else cleaned


def safe_filename(value: str, *, fallback: str) -> str:
    if not value or value.lower().startswith(("data:", "http://", "https://")):
        return fallback
    normalized = value.replace("\\", "/").split("/")[-1]
    normalized = _SAFE_HINT.sub("", normalized).strip().lstrip(".")[:120]
    return normalized or fallback


class WechatIngestMapper:
    def __init__(self, deployment_id: str | None = None, default_kb_id: str | None = None) -> None:
        deployment = deployment_id if deployment_id is not None else os.getenv("PERCLIP_WECHAT_DEPLOYMENT_ID", "")
        if not deployment:
            raise ConfigurationError("PERCLIP_WECHAT_DEPLOYMENT_ID is required")
        self.deployment_id = safe_identifier(deployment, limit=40)
        self.default_kb_id = default_kb_id if default_kb_id is not None else os.getenv("PERCLIP_WECHAT_DEFAULT_KB_ID", "")

    def client_request_id(self, event: NormalizedWechatEvent) -> str:
        if event.part_count > 1:
            parent = safe_identifier(event.parent_event_id, limit=48)
            if not 0 <= event.part_index < event.part_count:
                raise MappingError("invalid zero-based capture part")
            return f"wechat:{self.deployment_id}:{parent}:part:{event.part_index}"
        return f"wechat:{self.deployment_id}:{safe_identifier(event.event_id, limit=64)}"

    def map(self, event: NormalizedWechatEvent, routing_target: str = "") -> MappedIngest:
        if isinstance(event, WechatUnsupportedEvent):
            raise UnsupportedEventError("unsupported WeChat event")
        try:
            ZoneInfo(event.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise MappingError("invalid captured timezone") from error
        if event.occurred_at.tzinfo is None or event.occurred_at.utcoffset() is None:
            raise MappingError("message occurrence time must include an offset")
        if event.part_count < 1 or not 0 <= event.part_index < event.part_count:
            raise MappingError("invalid zero-based capture part")
        if event.part_count > 1 and not event.parent_event_id.strip():
            raise MappingError("multipart event requires parent_event_id")

        request_id = self.client_request_id(event)
        source_type, text, url, mime, multipart = self._content(event)
        target = routing_target or self.default_kb_id
        if target and (len(target) > 128 or _SECRET.search(target) or not re.fullmatch(r"[A-Za-z0-9._:-]+", target)):
            raise MappingError("invalid routing target")
        parent = ""
        batch = ""
        if event.part_count > 1:
            parent_event = event.parent_event_id
            parent = f"wechat:{self.deployment_id}:{safe_identifier(parent_event, limit=64)}"
            batch = f"batch:{self.deployment_id}:{safe_identifier(parent_event, limit=56)}"
        envelope: dict[str, object] = {
            "contract_version": "perclip.ingest.v1",
            "client_request_id": request_id,
            "source": {
                "adapter": "wechat_bot", "client_id": self.deployment_id,
                "event_id": safe_identifier(event.event_id, limit=64), "source_app": "WeChat",
                "account_hint": safe_hint(event.sender_hint or event.conversation_hint),
            },
            "clip": {
                "source_type": source_type, "title_hint": "", "note": "", "text": text, "url": url,
                "mime_type": mime, "captured_at": event.occurred_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "captured_timezone": event.timezone, "device_name": "",
            },
            "capture": {
                "client_batch_id": batch, "parent_client_request_id": parent,
                "part_index": event.part_index, "part_count": event.part_count,
                "part_role": source_type, "source_intent": "share", "content_fingerprint": "",
            },
            "routing": {"target_knowledge_base_id": target},
        }
        return MappedIngest(request_id, envelope, multipart)

    def _content(self, event: NormalizedWechatEvent) -> tuple[str, str, str, str, bool]:
        if isinstance(event, WechatTextEvent):
            if not event.text or event.text.lower().startswith("data:"):
                raise MappingError("invalid text event")
            return "text", event.text, "", "text/plain", False
        if isinstance(event, WechatLinkEvent):
            parsed = urlsplit(event.url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
                raise MappingError("invalid http/https URL")
            return "url", "", event.url, "text/uri-list", False
        if isinstance(event, (WechatImageEvent, WechatFileEvent)):
            image = isinstance(event, WechatImageEvent)
            fallback_mime = "image/jpeg" if image else "application/octet-stream"
            mime = event.mime_type.lower().strip() or fallback_mime
            if not _MIME.fullmatch(mime) or mime.startswith("text/html"):
                raise MappingError("invalid media MIME type")
            if image and not mime.startswith("image/"):
                raise MappingError("image event requires image MIME type")
            return ("image" if image else "file"), "", "", mime, True
        raise UnsupportedEventError("unsupported WeChat event")

    @staticmethod
    def filename_for(event: NormalizedWechatEvent) -> str:
        fallback = "wechat-image.jpg" if isinstance(event, WechatImageEvent) else "wechat-file.bin"
        return safe_filename(event.filename, fallback=fallback)
