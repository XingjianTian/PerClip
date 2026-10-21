from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


INGEST_CONTRACT_VERSION = "perclip.ingest.v1"
IngestAdapter = Literal["android", "api", "wechat_bot", "webhook", "import"]
ReplayPolicy = Literal["legacy_mobile", "strict_v1"]


@dataclass(frozen=True)
class IngestSource:
    adapter: IngestAdapter
    client_id: str = ""
    event_id: str = ""
    source_app: str = ""
    account_hint: str = ""


@dataclass(frozen=True)
class IngestClip:
    source_type: str
    title_hint: str = ""
    note: str = ""
    text: str = ""
    url: str = ""
    mime_type: str = ""
    captured_at: str = ""
    captured_timezone: str = ""
    device_name: str = ""


@dataclass(frozen=True)
class IngestCapture:
    client_batch_id: str = ""
    parent_client_request_id: str = ""
    part_index: int = 0
    part_count: int = 1
    part_role: str = "single"
    source_intent: str = "unknown"
    content_fingerprint: str = ""


@dataclass(frozen=True)
class IngestAsset:
    filename: str = ""
    mime_type: str = ""
    payload: bytes = b""


@dataclass(frozen=True)
class IngestRouting:
    target_knowledge_base_id: str = ""
    mode: str = ""


@dataclass(frozen=True)
class IngestCommand:
    contract_version: str
    client_request_id: str
    source: IngestSource
    clip: IngestClip
    capture: IngestCapture = field(default_factory=IngestCapture)
    routing: IngestRouting = field(default_factory=IngestRouting)
    asset: IngestAsset | None = None
    replay_policy: ReplayPolicy = "strict_v1"


@dataclass(frozen=True)
class IngestResult:
    receipt_id: str
    clip_id: str
    client_request_id: str
    duplicate: bool
    title: str
    platform: str
    content_hash: str
    filename: str
    size_bytes: int
    archive_status: str
    metadata_status: str
    capture: dict[str, object]
    routing: dict[str, object]

    def v1_response(self) -> dict[str, object]:
        return {
            "ok": True,
            "receipt_id": self.receipt_id,
            "clip_id": self.clip_id,
            "client_request_id": self.client_request_id,
            "duplicate": self.duplicate,
            "status": "accepted" if self.archive_status == "accepted" else "received",
            "archive_status": self.archive_status,
            "metadata_status": self.metadata_status,
            "capture": dict(self.capture),
            "routing": dict(self.routing),
        }
