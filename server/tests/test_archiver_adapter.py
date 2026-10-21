from __future__ import annotations

import sys
import textwrap

from perclip_ingest.archiver import ClipToRAGFlowAdapter
from perclip_ingest.config import Settings


def write_module(path, content: str) -> None:
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def test_clip_to_ragflow_adapter_imports_plugin_without_langbot_runtime(tmp_path):
    plugin_dir = tmp_path / "ClipToRAGFlow"
    package_dir = plugin_dir / "clip_to_ragflow"
    package_dir.mkdir(parents=True)

    write_module(
        package_dir / "__init__.py",
        """
        from .archiver import PersonalClipsArchiver
        from .settings import Settings
        """,
    )
    write_module(
        package_dir / "archiver.py",
        """
        from .ocr import run_ocr
        from .models import ArchiveResult

        LAST_CLIP = None

        class PersonalClipsArchiver:
            def __init__(self, settings):
                settings.validate()
                self.settings = settings

            async def archive(self, clip):
                global LAST_CLIP
                LAST_CLIP = clip
                return ArchiveResult(
                    ok=True,
                    action="archive",
                    title=clip.title_hint or clip.filename or "archived",
                    platform=clip.source_type,
                    markdown_path="/tmp/archive.md",
                    original_path="/tmp/original",
                    ragflow_document_id="doc-id",
                    summary=clip.text,
                    tags=[],
                )
        """,
    )
    write_module(
        package_dir / "ocr.py",
        """
        from langbot_plugin.api.entities.builtin.provider.message import ContentElement, Message

        def run_ocr():
            return ContentElement, Message
        """,
    )
    write_module(
        package_dir / "models.py",
        """
        from dataclasses import dataclass

        @dataclass
        class ClipInput:
            source_type: str = ""
            text: str = ""
            url: str = ""
            title_hint: str = ""
            description_hint: str = ""
            filename: str = ""
            payload: bytes | None = None
            mime_type: str = ""
            original_suffix: str = ""
            message_id: str = ""
            launcher_type: str = ""
            launcher_id: str = ""
            sender_id: str = ""

        @dataclass
        class ArchiveResult:
            ok: bool
            action: str
            title: str = ""
            platform: str = ""
            markdown_path: str = ""
            original_path: str = ""
            ragflow_document_id: str = ""
            summary: str = ""
            tags: list[str] | None = None
            error_message: str = ""
        """,
    )
    write_module(
        package_dir / "settings.py",
        """
        class Settings:
            @classmethod
            def from_plugin_config(cls, config, plugin_dir):
                return cls()

            def validate(self):
                return None
        """,
    )

    for name in list(sys.modules):
        if name == "clip_to_ragflow" or name.startswith("clip_to_ragflow."):
            del sys.modules[name]

    adapter = ClipToRAGFlowAdapter(
        Settings(
            data_dir=tmp_path / "data",
            ingest_token="secret",
            enable_clip_to_ragflow=True,
            clip_to_ragflow_dir=plugin_dir,
        ),
    )

    assert adapter.plugin_dir == plugin_dir
    assert "langbot_plugin.api.entities.builtin.provider.message" in sys.modules


def test_audio_payload_is_transcribed_before_archiving(tmp_path):
    import asyncio
    import importlib

    plugin_dir = tmp_path / "ClipToRAGFlow"
    package_dir = plugin_dir / "clip_to_ragflow"
    package_dir.mkdir(parents=True)

    write_module(package_dir / "__init__.py", "from .archiver import PersonalClipsArchiver\n")
    write_module(
        package_dir / "archiver.py",
        """
        from .models import ArchiveResult

        LAST_CLIP = None

        class PersonalClipsArchiver:
            def __init__(self, settings):
                self.settings = settings

            async def archive(self, clip):
                global LAST_CLIP
                LAST_CLIP = clip
                return ArchiveResult(
                    ok=True,
                    action="archive",
                    title=clip.title_hint,
                    platform=clip.source_type,
                    markdown_path="/tmp/archive.md",
                    original_path="/tmp/archive.md",
                    ragflow_document_id="doc-id",
                    summary=clip.text,
                    tags=[],
                )
        """,
    )
    write_module(
        package_dir / "models.py",
        """
        from dataclasses import dataclass

        @dataclass
        class ClipInput:
            source_type: str = ""
            text: str = ""
            url: str = ""
            title_hint: str = ""
            description_hint: str = ""
            filename: str = ""
            payload: bytes | None = None
            mime_type: str = ""
            original_suffix: str = ""
            message_id: str = ""
            launcher_type: str = ""
            launcher_id: str = ""
            sender_id: str = ""

        @dataclass
        class ArchiveResult:
            ok: bool
            action: str
            title: str = ""
            platform: str = ""
            markdown_path: str = ""
            original_path: str = ""
            ragflow_document_id: str = ""
            summary: str = ""
            tags: list[str] | None = None
            error_message: str = ""
        """,
    )
    write_module(package_dir / "settings.py", "class Settings:\n    @classmethod\n    def from_plugin_config(cls, config, plugin_dir):\n        return cls()\n")

    for name in list(sys.modules):
        if name == "clip_to_ragflow" or name.startswith("clip_to_ragflow."):
            del sys.modules[name]

    adapter = ClipToRAGFlowAdapter(
        Settings(
            data_dir=tmp_path / "data",
            ingest_token="secret",
            enable_clip_to_ragflow=True,
            clip_to_ragflow_dir=plugin_dir,
        ),
    )
    adapter._audio_asr = FakeAudioAsr()

    from perclip_ingest.archiver import MobileClipPayload

    outcome = asyncio.run(
        adapter.archive(
            MobileClipPayload(
                source_type="file",
                title_hint="录音测试",
                note="",
                text="",
                url="",
                mime_type="audio/mp4",
                device_name="device",
                source_app="PerClip",
                captured_at="2026-07-02T00:00:00Z",
                client_request_id="audio-1",
                filename="recording.m4a",
                payload=b"audio",
            )
        )
    )

    plugin_archiver = importlib.import_module("clip_to_ragflow.archiver")
    archived_clip = plugin_archiver.LAST_CLIP
    assert outcome.ok is True
    assert archived_clip.source_type == "text"
    assert archived_clip.payload is None
    assert archived_clip.filename == ""
    assert "语音转写" in archived_clip.text
    assert "这是语音转写结果。" in archived_clip.text


class FakeAudioAsr:
    def recognize(self, **kwargs):
        return type(
            "Result",
            (),
            {
                "ok": True,
                "text": "这是语音转写结果。",
                "engine": "fake_asr",
                "audio_format": "m4a",
            },
        )()
