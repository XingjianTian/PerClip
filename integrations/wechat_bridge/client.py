from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
import re

from .errors import ConfigurationError, IngestConflictError, RetryableIngestError, TerminalIngestError
from .models import IngestReceipt, MediaPayload


@dataclass(frozen=True)
class ClientTimeouts:
    connect: float = 5.0
    read: float = 20.0
    write: float = 20.0
    total: float = 30.0


class PerClipIngestClient:
    """Small v1 HTTP client. It never logs credentials or upstream bodies."""

    def __init__(self, api_url: str | None = None, token: str | None = None, *, timeouts: ClientTimeouts | None = None) -> None:
        supplied_url = (api_url if api_url is not None else os.getenv("PERCLIP_API_URL", "")).strip()
        self._token = token if token is not None else os.getenv("PERCLIP_WECHAT_INGEST_TOKEN", "")
        self.timeouts = timeouts or ClientTimeouts()
        parsed = urlsplit(supplied_url)
        localhost = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment):
            raise ConfigurationError("PERCLIP_API_URL is invalid")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and localhost):
            raise ConfigurationError("PERCLIP_API_URL must use HTTPS except on localhost")
        try:
            parsed.port
        except ValueError as error:
            raise ConfigurationError("PERCLIP_API_URL has an invalid port") from error
        prefix = parsed.path.rstrip("/")
        if any(segment in {".", ".."} for segment in prefix.split("/")) or "//" in prefix:
            raise ConfigurationError("PERCLIP_API_URL has an invalid path prefix")
        self._base_url = urlunsplit((parsed.scheme, parsed.netloc, prefix, "", ""))
        if not self._token:
            raise ConfigurationError("PERCLIP_WECHAT_INGEST_TOKEN is required")

    async def send_json(self, envelope: dict[str, object]) -> IngestReceipt:
        payload = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode()
        request_id = envelope.get("client_request_id")
        if not isinstance(request_id, str) or not request_id:
            raise TerminalIngestError("invalid submitted client request identifier")
        return await self._request("POST", "/api/ingest/v1/clips", payload, "application/json",
                                   expected_request_id=request_id)

    async def send_multipart(self, envelope: dict[str, object], media: MediaPayload) -> IngestReceipt:
        boundary = "perclip-" + secrets.token_hex(12)
        body = self._multipart_body(boundary, envelope, media)
        request_id = envelope.get("client_request_id")
        if not isinstance(request_id, str) or not request_id:
            raise TerminalIngestError("invalid submitted client request identifier")
        return await self._request("POST", "/api/ingest/v1/clips/multipart", body,
                                   f"multipart/form-data; boundary={boundary}", expected_request_id=request_id)

    async def get_receipt(self, receipt_id: str) -> IngestReceipt:
        if not receipt_id.startswith("ir_") or len(receipt_id) != 35:
            raise TerminalIngestError("invalid receipt identifier")
        return await self._request("GET", f"/api/ingest/v1/receipts/{receipt_id}", b"", "application/json")

    def _multipart_body(self, boundary: str, envelope: dict[str, object], media: MediaPayload) -> bytes:
        safe_name = media.filename.replace('"', "").replace("\r", "").replace("\n", "")
        head = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"envelope_json\"\r\n\r\n"
            + json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
            + f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{safe_name}\"\r\n"
            + f"Content-Type: {media.mime_type}\r\n\r\n"
        ).encode()
        return head + media.data + f"\r\n--{boundary}--\r\n".encode()

    async def _request(self, method: str, path: str, body: bytes, content_type: str,
                       expected_request_id: str | None = None) -> IngestReceipt:
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        if method != "GET":
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self._base_url + path, data=body if method != "GET" else None,
                                         headers=headers, method=method)
        try:
            status, raw = await asyncio.wait_for(asyncio.to_thread(self._open, request), timeout=self.timeouts.total)
        except (TimeoutError, socket.timeout, urllib.error.URLError, OSError) as error:
            raise RetryableIngestError("PerClip ingest temporarily unavailable") from error
        if status == 409:
            raise IngestConflictError("PerClip strict ingest conflict")
        if status in {408, 429} or status >= 500:
            raise RetryableIngestError(f"PerClip ingest temporarily unavailable ({status})")
        if status in {400, 401, 403, 404, 413, 415, 422} or status >= 300:
            raise TerminalIngestError(f"PerClip ingest rejected request ({status})")
        try:
            result = json.loads(raw)
            receipt_id = str(result["receipt_id"])
            request_id = str(result["client_request_id"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise RetryableIngestError("PerClip returned an invalid safe receipt") from error
        status_value = str(result.get("status", ""))
        if (not re.fullmatch(r"ir_[a-f0-9]{32}", receipt_id)
                or not request_id
                or (expected_request_id is not None and request_id != expected_request_id)
                or status_value not in {"accepted", "processing", "received", "failed"}
                or not isinstance(result.get("duplicate", False), bool)):
            raise RetryableIngestError("PerClip returned an invalid safe receipt")
        return IngestReceipt(receipt_id, request_id, bool(result.get("duplicate", False)), status_value)

    def _open(self, request: urllib.request.Request) -> tuple[int, bytes]:
        try:
            with urllib.request.urlopen(request, timeout=max(self.timeouts.connect, self.timeouts.read)) as response:
                return response.status, response.read(64 * 1024)
        except urllib.error.HTTPError as error:
            error.read(1024)  # drain a bounded amount; never expose it
            return error.code, b"{}"

    def __repr__(self) -> str:
        return "PerClipIngestClient(endpoint=<redacted>, token=<redacted>)"
