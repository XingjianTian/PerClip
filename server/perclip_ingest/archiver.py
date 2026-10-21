from __future__ import annotations

import sys
import types
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audio_asr import BaiduShortAudioRecognizer, is_audio_payload, render_asr_text_note
from .config import Settings


@dataclass(frozen=True)
class MobileClipPayload:
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
    payload: bytes


@dataclass(frozen=True)
class ArchiveOutcome:
    ok: bool
    title: str = ""
    platform: str = ""
    original_path: str = ""
    ragflow_document_id: str = ""
    message: str = ""


class ClipToRAGFlowAdapter:
    def __init__(self, settings: Settings) -> None:
        if not settings.clip_to_ragflow_dir:
            raise ValueError("PERCLIP_CLIP_TO_RAGFLOW_DIR is not configured")
        self.plugin_dir = settings.clip_to_ragflow_dir
        if not (self.plugin_dir / "clip_to_ragflow").exists():
            raise ValueError(f"ClipToRAGFlow package not found under {self.plugin_dir}")

        plugin_path = str(self.plugin_dir)
        if plugin_path not in sys.path:
            sys.path.insert(0, plugin_path)

        install_langbot_message_shim()

        from clip_to_ragflow import PersonalClipsArchiver  # type: ignore
        from clip_to_ragflow.models import ClipInput  # type: ignore
        from clip_to_ragflow.settings import Settings as ClipSettings  # type: ignore

        self._clip_input = ClipInput
        clip_settings = ClipSettings.from_plugin_config({}, self.plugin_dir)
        self._archiver = PersonalClipsArchiver(clip_settings)
        self._audio_asr = BaiduShortAudioRecognizer(settings.audio_asr)

    async def archive(self, payload: MobileClipPayload) -> ArchiveOutcome:
        text = payload.text
        if payload.note:
            text = f"{text}\n\n备注：{payload.note}".strip()

        source_type = normalize_source_type(payload)
        filename = payload.filename
        clip_payload = payload.payload or None
        mime_type = payload.mime_type
        original_suffix = Path(payload.filename).suffix

        if is_audio_payload(payload.mime_type, payload.filename) and payload.payload:
            try:
                asr_result = await asyncio.to_thread(
                    self._audio_asr.recognize,
                    audio=payload.payload,
                    filename=payload.filename,
                    mime_type=payload.mime_type,
                    cuid=payload.device_name or payload.source_app or "perclip",
                )
            except Exception:
                asr_result = None
            if asr_result and asr_result.ok:
                source_type = "text"
                text = render_asr_text_note(
                    transcription=asr_result.text,
                    filename=payload.filename,
                    mime_type=payload.mime_type,
                    size_bytes=len(payload.payload),
                    engine=asr_result.engine,
                    audio_format=asr_result.audio_format,
                    captured_at=payload.captured_at,
                )
                if payload.note:
                    text = f"{text}\n\n## 补充备注\n\n{payload.note}".strip()
                filename = ""
                clip_payload = None
                mime_type = "text/plain"
                original_suffix = ""

        clip = self._clip_input(
            source_type=source_type,
            text=text,
            url=payload.url,
            title_hint=payload.title_hint,
            description_hint=payload.note,
            filename=filename,
            payload=clip_payload,
            mime_type=mime_type,
            original_suffix=original_suffix,
            message_id=payload.client_request_id,
            launcher_type="android",
            launcher_id=payload.device_name or "android",
            sender_id=payload.source_app or "android_share",
        )
        result: Any = await self._archiver.archive(clip)
        display_path = result.original_path or result.markdown_path
        return ArchiveOutcome(
            ok=bool(result.ok),
            title=str(result.title or payload.title_hint or payload.filename or "未命名收藏"),
            platform=str(result.platform or "android_share"),
            original_path=str(display_path or ""),
            ragflow_document_id=str(result.ragflow_document_id or ""),
            message=str(result.error_message or result.summary or ""),
        )


def normalize_source_type(payload: MobileClipPayload) -> str:
    if payload.source_type == "screen_clip":
        return "image" if payload.payload else "text"
    if payload.source_type in {"url", "text", "image", "file"}:
        return payload.source_type
    return "file" if payload.payload else "text"


def build_archiver(settings: Settings) -> ClipToRAGFlowAdapter | None:
    if not settings.enable_clip_to_ragflow:
        return None
    return ClipToRAGFlowAdapter(settings)


def install_langbot_message_shim() -> None:
    """Allow ClipToRAGFlow OCR imports outside the LangBot runtime.

    The mobile ingest API uses ClipToRAGFlow as a library, but that plugin imports
    LangBot message types at module import time for optional vision OCR. PerClip
    does not pass a LangBot LLM invoker, so a tiny compatible surface is enough
    for standalone NAS startup while leaving real LangBot installs untouched.
    """
    target = "langbot_plugin.api.entities.builtin.provider.message"
    if target in sys.modules:
        return

    class ContentElement:
        @staticmethod
        def from_text(text: str) -> dict[str, str]:
            return {"type": "text", "text": text}

        @staticmethod
        def from_image_base64(encoded: str) -> dict[str, str]:
            return {"type": "image_base64", "data": encoded}

    class Message:
        def __init__(self, role: str = "", content: Any = "") -> None:
            self.role = role
            self.content = content

    module_names = [
        "langbot_plugin",
        "langbot_plugin.api",
        "langbot_plugin.api.entities",
        "langbot_plugin.api.entities.builtin",
        "langbot_plugin.api.entities.builtin.provider",
        target,
    ]
    for name in module_names:
        sys.modules.setdefault(name, types.ModuleType(name))
    message_module = sys.modules[target]
    message_module.ContentElement = ContentElement
    message_module.Message = Message
