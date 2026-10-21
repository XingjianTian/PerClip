from __future__ import annotations

import os
import stat
import time
import secrets
from pathlib import Path
from typing import Protocol

from .errors import MediaError
from .models import MediaPayload, NormalizedWechatEvent


class MediaProvider(Protocol):
    async def fetch(self, event: NormalizedWechatEvent) -> MediaPayload: ...


class BytesMediaProvider:
    """Adapter helper for already-authenticated platform bytes; no WeChat protocol lives here."""

    def __init__(self, *, max_bytes: int = 25 * 1024 * 1024) -> None:
        self.max_bytes = max_bytes

    async def fetch(self, event: NormalizedWechatEvent) -> MediaPayload:
        value = event.media_reference
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise MediaError("adapter did not provide bounded media bytes")
        data = bytes(value)
        if not data or len(data) > self.max_bytes:
            raise MediaError("media payload is empty or exceeds the bridge limit")
        from .mapping import WechatIngestMapper
        return MediaPayload(data, WechatIngestMapper.filename_for(event), event.mime_type or "application/octet-stream")


class SpoolManager:
    def __init__(self, directory: Path, *, retention_seconds: int = 3600) -> None:
        self.directory = directory
        self.retention_seconds = retention_seconds
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, stat.S_IRWXU)

    def write(self, data: bytes) -> str:
        token = secrets.token_hex(24) + ".spool"
        path = self.directory / token
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return token

    def remove(self, token: str) -> None:
        if token:
            try:
                (self.directory / Path(token).name).unlink(missing_ok=True)
            except OSError:
                pass

    def cleanup_expired(self, *, now: float | None = None) -> int:
        cutoff = (now if now is not None else time.time()) - self.retention_seconds
        removed = 0
        for item in self.directory.iterdir():
            try:
                if item.is_file() and item.stat().st_mtime < cutoff:
                    item.unlink(); removed += 1
            except OSError:
                continue
        return removed
