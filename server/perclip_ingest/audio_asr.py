from __future__ import annotations

import base64
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BAIDU_TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
BAIDU_ASR_URL = "http://vop.baidu.com/server_api"
SUPPORTED_BAIDU_FORMATS = {"pcm", "wav", "amr", "m4a"}
BAIDU_AUDIO_TOO_LONG_ERRNO = 3308
SEGMENT_SECONDS = 55


@dataclass(frozen=True)
class AudioAsrSettings:
    enabled: bool
    baidu_api_key: str = ""
    baidu_secret_key: str = ""
    dev_pid: int = 1537
    rate: int = 16000
    channel: int = 1
    token_url: str = BAIDU_TOKEN_URL
    asr_url: str = BAIDU_ASR_URL
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class AudioAsrResult:
    ok: bool
    text: str = ""
    engine: str = "baidu_short_asr"
    status: str = ""
    message: str = ""
    audio_format: str = ""


class BaiduShortAudioRecognizer:
    def __init__(self, settings: AudioAsrSettings) -> None:
        self.settings = settings
        self._access_token = ""

    def recognize(
        self,
        *,
        audio: bytes,
        filename: str,
        mime_type: str,
        cuid: str,
    ) -> AudioAsrResult:
        if not self.settings.enabled:
            return AudioAsrResult(ok=False, status="disabled", message="audio ASR is disabled")
        audio_format = infer_baidu_audio_format(filename, mime_type)
        if audio_format not in SUPPORTED_BAIDU_FORMATS:
            return AudioAsrResult(
                ok=False,
                status="unsupported_format",
                message=f"unsupported audio format for Baidu ASR: {audio_format or mime_type or filename}",
                audio_format=audio_format,
            )
        if not audio:
            return AudioAsrResult(ok=False, status="empty_audio", message="audio payload is empty", audio_format=audio_format)

        token = self._access_token or self._fetch_access_token()
        self._access_token = token
        result = self._recognize_single(audio, audio_format, cuid, token)
        if result.status == f"baidu_error:{BAIDU_AUDIO_TOO_LONG_ERRNO}":
            return self._recognize_segments(audio, filename, cuid, token)
        return result

    def _recognize_single(self, audio: bytes, audio_format: str, cuid: str, token: str) -> AudioAsrResult:
        try:
            response = self._post_asr(audio, audio_format, cuid, token)
        except BaiduAsrError as first_error:
            if "token" not in first_error.message.lower():
                raise
            self._access_token = self._fetch_access_token()
            response = self._post_asr(audio, audio_format, cuid, self._access_token)

        err_no = int(response.get("err_no", -1))
        err_msg = str(response.get("err_msg", "")).strip()
        if err_no != 0:
            return AudioAsrResult(
                ok=False,
                status=f"baidu_error:{err_no}",
                message=err_msg or f"Baidu ASR failed with err_no={err_no}",
                audio_format=audio_format,
            )

        result = response.get("result") or []
        text = "\n".join(str(item).strip() for item in result if str(item).strip()).strip()
        if not text:
            return AudioAsrResult(
                ok=False,
                status="empty_result",
                message="Baidu ASR returned no transcription text",
                audio_format=audio_format,
            )
        return AudioAsrResult(ok=True, text=text, status="success", audio_format=audio_format)

    def _recognize_segments(self, audio: bytes, filename: str, cuid: str, token: str) -> AudioAsrResult:
        try:
            segments = self._split_audio(audio, filename)
        except BaiduAsrError as error:
            return AudioAsrResult(
                ok=False,
                status="segment_failed",
                message=error.message,
                audio_format="m4a",
            )
        if not segments:
            return AudioAsrResult(
                ok=False,
                status="segment_failed",
                message="ffmpeg produced no audio segments",
                audio_format="m4a",
            )

        texts: list[str] = []
        failures: list[str] = []
        for index, segment in enumerate(segments, start=1):
            segment_result = self._recognize_single(segment, "m4a", f"{cuid[:50]}-{index}", token)
            if segment_result.ok and segment_result.text.strip():
                texts.append(segment_result.text.strip())
            else:
                failures.append(f"第 {index} 段：{segment_result.message or segment_result.status}")

        if texts:
            text = "\n".join(texts)
            status = "success" if not failures else "partial_success"
            message = "\n".join(failures)
            return AudioAsrResult(ok=True, text=text, status=status, message=message, audio_format="m4a")
        return AudioAsrResult(
            ok=False,
            status="segment_asr_failed",
            message="; ".join(failures) or "all audio segments failed",
            audio_format="m4a",
        )

    def _split_audio(self, audio: bytes, filename: str) -> list[bytes]:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise BaiduAsrError("ffmpeg is required to split audio longer than 60 seconds")
        suffix = Path(filename or "").suffix or ".m4a"
        with tempfile.TemporaryDirectory(prefix="perclip-asr-") as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / f"input{suffix}"
            output_pattern = temp_path / "segment_%03d.m4a"
            input_path.write_bytes(audio)
            command = [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(input_path),
                "-ac",
                "1",
                "-ar",
                str(self.settings.rate),
                "-c:a",
                "aac",
                "-b:a",
                "48k",
                "-f",
                "segment",
                "-segment_time",
                str(SEGMENT_SECONDS),
                "-reset_timestamps",
                "1",
                str(output_pattern),
            ]
            completed = subprocess.run(command, capture_output=True, check=False)
            if completed.returncode != 0:
                stderr = completed.stderr.decode("utf-8", errors="replace").strip()
                raise BaiduAsrError(f"ffmpeg split failed: {stderr or completed.returncode}")
            return [path.read_bytes() for path in sorted(temp_path.glob("segment_*.m4a"))]

    def _fetch_access_token(self) -> str:
        query = urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self.settings.baidu_api_key,
                "client_secret": self.settings.baidu_secret_key,
            }
        )
        request = Request(
            f"{self.settings.token_url}?{query}",
            data=b"",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        payload = request_json(request, self.settings.timeout_seconds)
        token = str(payload.get("access_token", "")).strip()
        if not token:
            message = str(payload.get("error_description") or payload.get("error") or "missing access_token")
            raise BaiduAsrError(f"Baidu token request failed: {message}")
        return token

    def _post_asr(self, audio: bytes, audio_format: str, cuid: str, token: str) -> dict[str, Any]:
        payload = {
            "format": audio_format,
            "rate": self.settings.rate,
            "dev_pid": self.settings.dev_pid,
            "channel": self.settings.channel,
            "token": token,
            "cuid": cuid[:60] or "perclip",
            "len": len(audio),
            "speech": base64.b64encode(audio).decode("ascii"),
        }
        request = Request(
            self.settings.asr_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return request_json(request, self.settings.timeout_seconds)


class BaiduAsrError(RuntimeError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def request_json(request: Request, timeout: float) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise BaiduAsrError(f"HTTP {error.code}: {body}") from error
    except URLError as error:
        raise BaiduAsrError(str(error.reason)) from error
    except TimeoutError as error:
        raise BaiduAsrError("request timed out") from error

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise BaiduAsrError("Baidu ASR returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise BaiduAsrError("Baidu ASR returned non-object JSON")
    return payload


def infer_baidu_audio_format(filename: str, mime_type: str) -> str:
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    if suffix in SUPPORTED_BAIDU_FORMATS:
        return suffix
    normalized_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime in {"audio/mp4", "audio/m4a", "audio/x-m4a", "audio/aac"}:
        return "m4a"
    if normalized_mime in {"audio/wav", "audio/x-wav", "audio/wave"}:
        return "wav"
    if normalized_mime in {"audio/amr", "audio/3gpp"}:
        return "amr"
    if normalized_mime in {"audio/pcm", "audio/l16", "application/octet-stream"}:
        return "pcm"
    return suffix


def is_audio_payload(mime_type: str, filename: str) -> bool:
    normalized_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime.startswith("audio/"):
        return True
    return Path(filename or "").suffix.lower() in {".pcm", ".wav", ".amr", ".m4a", ".aac"}


def render_asr_text_note(
    *,
    transcription: str,
    filename: str,
    mime_type: str,
    size_bytes: int,
    engine: str,
    audio_format: str,
    captured_at: str,
) -> str:
    return (
        "语音转写\n\n"
        f"原始文件：{filename or '未命名录音'}\n"
        f"音频类型：{mime_type or 'unknown'}\n"
        f"音频大小：{size_bytes} bytes\n"
        f"ASR 引擎：{engine}\n"
        f"ASR 格式：{audio_format or 'unknown'}\n"
        f"采集时间：{captured_at}\n\n"
        "## 转写正文\n\n"
        f"{transcription.strip()}"
    )
