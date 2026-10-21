from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from datetime import datetime, timezone as datetime_timezone
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .ingest_models import (
    INGEST_CONTRACT_VERSION, IngestAsset, IngestCapture, IngestClip, IngestCommand,
    IngestRouting, IngestSource,
)


ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
ADAPTERS = {"android", "api", "wechat_bot", "webhook", "import"}
SECRET_RE = re.compile(r"(?:bearer|authorization|token|secret|password|api[_-]?key)", re.I)
MAX_TEXT = 200_000


class AdapterValidationError(ValueError):
    pass


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AdapterValidationError(f"{name} must be an object")
    return value


def _only(value: Mapping[str, Any], model: type, name: str) -> None:
    unknown = set(value) - {item.name for item in fields(model)}
    if unknown:
        raise AdapterValidationError(f"unknown {name} field")


def _text(value: Any, name: str, limit: int = 512) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise AdapterValidationError(f"invalid {name}")
    return value.strip()


def _integer(value: Any, name: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdapterValidationError(f"invalid {name}")
    return value


def _reject_encoded_payload(*values: str) -> None:
    for value in values:
        lowered = value.lstrip().lower()
        if lowered.startswith("data:") or "base64," in lowered:
            raise AdapterValidationError("encoded payload is not supported")


def json_envelope_to_command(envelope: Mapping[str, Any]) -> IngestCommand:
    envelope = _mapping(envelope, "envelope")
    allowed = {"contract_version", "client_request_id", "source", "clip", "capture", "routing"}
    if set(envelope) - allowed:
        raise AdapterValidationError("unknown envelope field")
    contract = _text(envelope.get("contract_version"), "contract_version", 64)
    if contract != INGEST_CONTRACT_VERSION:
        raise AdapterValidationError("unsupported contract_version")
    request_id = _text(envelope.get("client_request_id"), "client_request_id", 128)
    if not request_id or not ID_RE.fullmatch(request_id):
        raise AdapterValidationError("invalid client_request_id")

    source_data = _mapping(envelope.get("source"), "source")
    clip_data = _mapping(envelope.get("clip"), "clip")
    capture_data = _mapping(envelope.get("capture", {}), "capture")
    routing_data = _mapping(envelope.get("routing", {}), "routing")
    _only(source_data, IngestSource, "source")
    _only(clip_data, IngestClip, "clip")
    _only(capture_data, IngestCapture, "capture")
    _only(routing_data, IngestRouting, "routing")

    adapter = _text(source_data.get("adapter"), "source.adapter", 32)
    if adapter not in ADAPTERS:
        raise AdapterValidationError("invalid source.adapter")
    client_id = _text(source_data.get("client_id"), "source.client_id", 128)
    event_id = _text(source_data.get("event_id"), "source.event_id", 128)
    if client_id and not ID_RE.fullmatch(client_id) or event_id and not ID_RE.fullmatch(event_id):
        raise AdapterValidationError("invalid source identifier")
    source_app = _text(source_data.get("source_app"), "source.source_app", 128)
    account_hint = _text(source_data.get("account_hint"), "source.account_hint", 128)
    if SECRET_RE.search(source_app) or SECRET_RE.search(account_hint):
        raise AdapterValidationError("secret-like source field is not allowed")

    source_type = _text(clip_data.get("source_type"), "clip.source_type", 32)
    if source_type not in {"text", "url", "image", "file", "screen_clip"}:
        raise AdapterValidationError("unsupported source_type")
    title = _text(clip_data.get("title_hint"), "clip.title_hint", 2_000)
    note = _text(clip_data.get("note"), "clip.note", MAX_TEXT)
    text = _text(clip_data.get("text"), "clip.text", MAX_TEXT)
    url = _text(clip_data.get("url"), "clip.url", 8_192)
    mime = _text(clip_data.get("mime_type"), "clip.mime_type", 256)
    captured_at = _text(clip_data.get("captured_at"), "clip.captured_at", 128)
    timezone = _text(clip_data.get("captured_timezone"), "clip.captured_timezone", 64)
    if not captured_at:
        raise AdapterValidationError("captured_at is required")
    if not timezone:
        raise AdapterValidationError("captured_timezone is required")
    if captured_at:
        try:
            parsed = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise AdapterValidationError("invalid captured_at") from error
        if parsed.tzinfo is None:
            raise AdapterValidationError("captured_at requires timezone")
        captured_at = parsed.astimezone(datetime_timezone.utc).isoformat().replace("+00:00", "Z")
    if timezone:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise AdapterValidationError("invalid captured_timezone") from error
    _reject_encoded_payload(text, url, note)

    batch_id = _text(capture_data.get("client_batch_id"), "capture.client_batch_id", 128)
    parent_id = _text(capture_data.get("parent_client_request_id"), "capture.parent_client_request_id", 128)
    part_index = _integer(capture_data.get("part_index"), "capture.part_index", 0)
    part_count = _integer(capture_data.get("part_count"), "capture.part_count", 1)
    part_role = _text(capture_data.get("part_role", "single"), "capture.part_role", 32) or "single"
    source_intent = _text(capture_data.get("source_intent", "unknown"), "capture.source_intent", 32) or "unknown"
    fingerprint = _text(capture_data.get("content_fingerprint"), "capture.content_fingerprint", 64).lower()
    target = _text(routing_data.get("target_knowledge_base_id"), "routing.target_knowledge_base_id", 128)
    routing_mode = _text(routing_data.get("mode"), "routing.mode", 32)

    return IngestCommand(
        contract_version=contract,
        client_request_id=request_id,
        source=IngestSource(adapter=adapter, client_id=client_id, event_id=event_id, source_app=source_app, account_hint=account_hint),  # type: ignore[arg-type]
        clip=IngestClip(source_type=source_type, title_hint=title, note=note, text=text, url=url, mime_type=mime,
                        captured_at=captured_at, captured_timezone=timezone,
                        device_name=_text(clip_data.get("device_name"), "clip.device_name", 256)),
        capture=IngestCapture(client_batch_id=batch_id, parent_client_request_id=parent_id,
                              part_index=part_index, part_count=part_count, part_role=part_role,
                              source_intent=source_intent, content_fingerprint=fingerprint),
        routing=IngestRouting(target_knowledge_base_id=target, mode=routing_mode),
        replay_policy="strict_v1",
    )


def multipart_envelope_to_command(envelope: Mapping[str, Any], *, filename: str, mime_type: str, payload: bytes) -> IngestCommand:
    command = json_envelope_to_command(envelope)
    if command.clip.source_type not in {"image", "file", "screen_clip"}:
        raise AdapterValidationError("multipart source_type must be binary")
    return IngestCommand(**{**command.__dict__, "asset": IngestAsset(filename=filename, mime_type=mime_type, payload=payload)})


def mobile_form_to_command(*, source_type: str, title_hint: str = "", note: str = "", text: str = "", url: str = "",
                           mime_type: str = "", device_name: str = "", source_app: str = "", captured_at: str = "",
                           client_request_id: str = "", target_knowledge_base_id: str = "", routing_mode: str = "",
                           client_batch_id: str = "",
                           parent_client_request_id: str = "", client_part_index: int = 0, client_part_count: int = 1,
                           part_role: str = "single", source_intent: str = "unknown", captured_timezone: str = "",
                           content_fingerprint: str = "", filename: str = "", file_mime_type: str = "", payload: bytes = b"") -> IngestCommand:
    return IngestCommand(
        contract_version=INGEST_CONTRACT_VERSION, client_request_id=client_request_id,
        source=IngestSource(adapter="android", source_app=source_app),
        clip=IngestClip(source_type=source_type, title_hint=title_hint, note=note, text=text, url=url,
                        mime_type=mime_type, captured_at=captured_at, captured_timezone=captured_timezone,
                        device_name=device_name),
        capture=IngestCapture(client_batch_id=client_batch_id, parent_client_request_id=parent_client_request_id,
                              part_index=client_part_index, part_count=client_part_count, part_role=part_role,
                              source_intent=source_intent, content_fingerprint=content_fingerprint),
        routing=IngestRouting(target_knowledge_base_id=target_knowledge_base_id, mode=routing_mode),
        asset=IngestAsset(filename=filename, mime_type=file_mime_type, payload=payload) if filename or payload else None,
        replay_policy="legacy_mobile",
    )
