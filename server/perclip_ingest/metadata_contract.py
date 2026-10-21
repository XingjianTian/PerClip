from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from .web_extraction import WebFetchError, canonicalize_url


CONTRACT_VERSION = "perclip.clip.v1"
CAPTURE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
CAPTURE_PART_ROLES = {"single", "file", "image", "text", "url", "mixed"}
CAPTURE_SOURCE_INTENTS = {"share", "manual", "retry", "unknown"}


@dataclass(frozen=True)
class NormalizedMetadataInput:
    source_type: str
    title_hint: str
    note: str
    text: str
    url: str
    mime_type: str
    device_name: str
    source_app: str
    captured_at: str
    client_request_id: str
    filename: str
    has_file: bool
    size_bytes: int
    content_hash: str
    storage_uri: str
    received_at: str
    archive_status: str
    ragflow_document_id: str
    source_adapter: str = "android"
    source_client_id: str = ""
    source_event_id: str = ""
    error_code: str = ""
    error_message: str = ""
    client_batch_id: str = ""
    parent_client_request_id: str = ""
    part_index: int = 0
    part_count: int = 1
    part_role: str = "single"
    source_intent: str = "unknown"
    captured_timezone: str = ""
    content_fingerprint: str = ""


def build_normalized_metadata(payload: NormalizedMetadataInput) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "clip": build_clip(payload),
        "provenance": build_provenance(payload),
        "assets": [build_asset(payload)],
        "capture": build_capture(payload),
        "processing": build_processing(payload),
        "security": build_security(payload),
    }


def dumps_normalized_metadata(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def loads_normalized_metadata(metadata_json: str) -> dict[str, Any]:
    payload = json.loads(metadata_json)
    if not isinstance(payload, dict):
        raise ValueError("normalized metadata must be a JSON object")
    capture = payload.get("capture")
    if capture is not None:
        validate_capture_section(capture)
    return payload


def build_capture(payload: NormalizedMetadataInput) -> dict[str, Any]:
    return {
        "client_batch_id": safe_capture_identifier(payload.client_batch_id),
        "parent_client_request_id": safe_capture_identifier(payload.parent_client_request_id),
        "part_index": payload.part_index,
        "part_count": payload.part_count,
        "part_role": payload.part_role if payload.part_role in CAPTURE_PART_ROLES else "single",
        "original_filename": safe_original_filename(payload.filename),
        "original_mime_type": safe_capture_text(payload.mime_type, 256),
        "source_intent": payload.source_intent if payload.source_intent in CAPTURE_SOURCE_INTENTS else "unknown",
        "captured_timezone": safe_timezone(payload.captured_timezone),
        "content_fingerprint": safe_fingerprint(payload.content_fingerprint),
    }


def validate_capture_section(capture: Any) -> None:
    if not isinstance(capture, dict):
        raise ValueError("capture must be a JSON object")
    allowed = {
        "client_batch_id", "parent_client_request_id", "part_index", "part_count", "part_role",
        "original_filename", "original_mime_type", "source_intent", "captured_timezone", "content_fingerprint",
    }
    if set(capture) - allowed:
        raise ValueError("capture contains unsupported fields")
    part_index = capture.get("part_index", 0)
    part_count = capture.get("part_count", 1)
    if not isinstance(part_index, int) or not isinstance(part_count, int) or not 1 <= part_count <= 100 or not 0 <= part_index < part_count:
        raise ValueError("capture part index/count is invalid")
    for field in ("client_batch_id", "parent_client_request_id", "part_role", "source_intent", "captured_timezone", "original_mime_type"):
        value = capture.get(field, "")
        if not isinstance(value, str) or len(value) > 256:
            raise ValueError(f"capture {field} is invalid")
    for field in ("client_batch_id", "parent_client_request_id"):
        value = capture.get(field, "")
        if value and value != safe_capture_identifier(value):
            raise ValueError(f"capture {field} is invalid")
    if capture.get("part_role", "single") not in CAPTURE_PART_ROLES:
        raise ValueError("capture part_role is invalid")
    if capture.get("source_intent", "unknown") not in CAPTURE_SOURCE_INTENTS:
        raise ValueError("capture source_intent is invalid")
    if capture.get("captured_timezone", "") != safe_timezone(str(capture.get("captured_timezone", ""))):
        raise ValueError("capture captured_timezone is invalid")
    if capture.get("original_mime_type", "") != safe_capture_text(str(capture.get("original_mime_type", "")), 256):
        raise ValueError("capture original_mime_type is invalid")
    original_filename = capture.get("original_filename", "")
    if not isinstance(original_filename, str) or len(original_filename) > 255 or original_filename != safe_original_filename(original_filename):
        raise ValueError("capture original_filename is invalid")
    fingerprint = capture.get("content_fingerprint", "")
    if not isinstance(fingerprint, str) or fingerprint != safe_fingerprint(fingerprint):
        raise ValueError("capture content_fingerprint is invalid")


def safe_capture_identifier(value: str) -> str:
    candidate = value.strip()
    return candidate if not candidate or CAPTURE_ID_RE.fullmatch(candidate) else ""


def safe_original_filename(value: str) -> str:
    return PurePath(value.replace("\\", "/")).name.strip()[:255]


def safe_fingerprint(value: str) -> str:
    candidate = value.strip().lower()
    return candidate if re.fullmatch(r"[a-f0-9]{64}", candidate) else ""


def safe_capture_text(value: str, limit: int) -> str:
    return "".join(character for character in value.strip() if character >= " " and character != "\x7f")[:limit]


def safe_timezone(value: str) -> str:
    candidate = safe_capture_text(value, 64)
    if candidate.startswith(("/", "\\")) or ".." in candidate:
        return ""
    return candidate if re.fullmatch(r"[A-Za-z0-9_+./:-]*", candidate) else ""


def build_clip(payload: NormalizedMetadataInput) -> dict[str, Any]:
    return {
        "clip_id": clip_id_for(payload),
        "client_request_id": payload.client_request_id.strip(),
        "source_type": payload.source_type,
        "title_hint": payload.title_hint,
        "note": payload.note,
        "text": payload.text,
        "url": safe_normalized_url(payload.url),
        "captured_at": payload.captured_at,
        "language_hint": "",
        "tags_hint": [],
    }


def build_provenance(payload: NormalizedMetadataInput) -> dict[str, Any]:
    adapter = payload.source_adapter if payload.source_adapter in {
        "android", "api", "wechat_bot", "webhook", "import"
    } else "api"
    return {
        "launcher_type": adapter,
        "launcher_id": payload.source_client_id or payload.device_name or adapter,
        "source_app": payload.source_app,
        "source_account_hint": "",
        "source_message_id": payload.source_event_id,
        "source_url": safe_normalized_url(payload.url),
        "original_url_hash": hashlib.sha256(payload.url.encode("utf-8")).hexdigest() if payload.url else "",
        "capture_method": capture_method_for(payload.source_type),
    }


def build_asset(payload: NormalizedMetadataInput) -> dict[str, Any]:
    return {
        "asset_id": "original-1",
        "role": asset_role_for(payload.source_type),
        "filename": payload.filename,
        "mime_type": payload.mime_type,
        "size_bytes": payload.size_bytes,
        "content_hash": payload.content_hash,
        "storage_uri": payload.storage_uri,
        "text": asset_text_for(payload),
        "source_part_index": 0,
    }


def build_processing(payload: NormalizedMetadataInput) -> dict[str, Any]:
    return {
        "received_at": payload.received_at,
        "archive_status": payload.archive_status,
        "original_path": payload.storage_uri,
        "ragflow_document_id": payload.ragflow_document_id,
        "extraction_status": "not_started",
        "graph_status": "not_started",
        "publish_status": "not_started",
        "error_code": payload.error_code,
        "error_message": payload.error_message,
    }


def build_security(payload: NormalizedMetadataInput) -> dict[str, Any]:
    return {
        "auth_context": {
            "method": "connector_ingest_token" if payload.source_adapter != "android" else "mobile_ingest_token",
            "verified": True,
        },
        "token_id": "",
        "redaction_level": "metadata_only",
        "credential_scope": credential_scope_for(payload),
    }


def clip_id_for(payload: NormalizedMetadataInput) -> str:
    request_id = payload.client_request_id.strip()
    if request_id:
        return request_id.split(":", 1)[0] or request_id
    digest = payload.content_hash[:16] if payload.content_hash else "unidentified"
    return f"{payload.source_type}-{digest}"


def capture_method_for(source_type: str) -> str:
    if source_type == "screen_clip":
        return "accessibility"
    return "share_sheet"


def asset_role_for(source_type: str) -> str:
    if source_type == "screen_clip":
        return "screenshot"
    return "original"


def asset_text_for(payload: NormalizedMetadataInput) -> str:
    if payload.has_file:
        return ""
    return payload.text or safe_normalized_url(payload.url) or payload.note


def safe_normalized_url(value: str) -> str:
    if not value.strip():
        return ""
    try:
        return canonicalize_url(value)
    except WebFetchError:
        return ""


def credential_scope_for(payload: NormalizedMetadataInput) -> list[str]:
    if payload.archive_status == "clip_to_ragflow" or payload.ragflow_document_id:
        return ["ragflow:personalclips"]
    return []
