from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .config import RagflowSettings


READ_ONLY_DATASET_PATHS = (
    "/api/v1/datasets",
    "/v1/datasets",
    "/api/datasets",
    "/datasets",
)
MUTATION_CAPABILITIES = (
    "dataset_create",
    "document_upload",
    "document_meta_fields",
    "document_delete",
    "cross_dataset_move",
)
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_BYTES = 256 * 1024


class RagflowProbeClient(Protocol):
    def get_json(self, base_url: str, api_key: str, path: str) -> "ProbeHttpResult":
        ...


@dataclass(frozen=True)
class ProbeHttpResult:
    status_code: int
    json_body: Any
    response_shape: str


@dataclass(frozen=True)
class RagflowProbeResult:
    ok: bool
    configured: bool
    status: str
    base_url: str
    capabilities: dict[str, bool | str]
    warnings: list[str] = field(default_factory=list)
    checked_at: str = ""
    latency_ms: int = 0
    http_status: int | None = None
    response_shape: str = "none"

    def to_dict(self) -> dict[str, Any]:
        ragflow: dict[str, Any] = {
            "configured": self.configured,
            "status": self.status,
            "base_url": self.base_url,
            "capabilities": self.capabilities,
            "warnings": self.warnings,
            "checked_at": self.checked_at,
            "latency_ms": self.latency_ms,
            "response_shape": self.response_shape,
        }
        if self.http_status is not None:
            ragflow["http_status"] = self.http_status
        return {"ok": self.ok, "ragflow": ragflow}


class UrlLibRagflowProbeClient:
    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = timeout_seconds

    def get_json(self, base_url: str, api_key: str, path: str) -> ProbeHttpResult:
        url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="GET",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            raw_body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw_body) > MAX_RESPONSE_BYTES:
                return ProbeHttpResult(
                    status_code=response.status,
                    json_body=None,
                    response_shape="too_large",
                )
            body = json.loads(raw_body.decode("utf-8")) if raw_body else None
            return ProbeHttpResult(
                status_code=response.status,
                json_body=body,
                response_shape=response_shape(body),
            )


def probe_ragflow(
    settings: RagflowSettings,
    *,
    client: RagflowProbeClient | None = None,
    checked_at: str | None = None,
) -> RagflowProbeResult:
    started = time.perf_counter()
    checked_at = checked_at or datetime.now(timezone.utc).isoformat()
    base_url = sanitize_base_url(settings.base_url)
    capabilities = disabled_capabilities()

    if not settings.configured:
        return RagflowProbeResult(
            ok=True,
            configured=False,
            status="disabled",
            base_url=base_url,
            capabilities=capabilities,
            warnings=["RAGFlow probe is disabled because server settings are incomplete."],
            checked_at=checked_at,
            latency_ms=elapsed_ms(started),
        )

    probe_client = client or UrlLibRagflowProbeClient()
    warnings: list[str] = []
    last_status: int | None = None
    last_shape = "none"

    for path in READ_ONLY_DATASET_PATHS:
        try:
            result = probe_client.get_json(settings.base_url, settings.api_key, path)
        except HTTPError as error:
            last_status = error.code
            last_shape = "http_error"
            if error.code == 404:
                warnings.append("Read-only dataset endpoint was not found.")
                continue
            warnings.append("Read-only probe received an HTTP error.")
            return RagflowProbeResult(
                ok=True,
                configured=True,
                status="unknown_api",
                base_url=base_url,
                capabilities=capabilities_with_dataset_list("unknown"),
                warnings=dedupe(warnings),
                checked_at=checked_at,
                latency_ms=elapsed_ms(started),
                http_status=last_status,
                response_shape=last_shape,
            )
        except (TimeoutError, URLError, OSError):
            warnings.append("RAGFlow read-only probe could not reach the configured service.")
            return RagflowProbeResult(
                ok=True,
                configured=True,
                status="unreachable",
                base_url=base_url,
                capabilities=capabilities_with_dataset_list("unknown"),
                warnings=dedupe(warnings),
                checked_at=checked_at,
                latency_ms=elapsed_ms(started),
                response_shape="network_error",
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            warnings.append("Read-only probe returned a non-JSON response.")
            return RagflowProbeResult(
                ok=True,
                configured=True,
                status="unknown_api",
                base_url=base_url,
                capabilities=capabilities_with_dataset_list("unknown"),
                warnings=dedupe(warnings),
                checked_at=checked_at,
                latency_ms=elapsed_ms(started),
                http_status=last_status,
                response_shape="non_json",
            )

        last_status = result.status_code
        last_shape = result.response_shape
        if 200 <= result.status_code < 300:
            dataset_list = result.response_shape in {"list", "dict", "dict_with_data", "dict_with_items"}
            if not dataset_list:
                warnings.append("Read-only probe response shape is not recognized as a dataset list.")
            return RagflowProbeResult(
                ok=True,
                configured=True,
                status="reachable" if dataset_list else "unknown_api",
                base_url=base_url,
                capabilities=capabilities_with_dataset_list(dataset_list),
                warnings=dedupe(warnings),
                checked_at=checked_at,
                latency_ms=elapsed_ms(started),
                http_status=result.status_code,
                response_shape=result.response_shape,
            )
        warnings.append("Read-only probe received an unexpected HTTP status.")

    return RagflowProbeResult(
        ok=True,
        configured=True,
        status="unknown_api",
        base_url=base_url,
        capabilities=capabilities_with_dataset_list("unknown"),
        warnings=dedupe(warnings),
        checked_at=checked_at,
        latency_ms=elapsed_ms(started),
        http_status=last_status,
        response_shape=last_shape,
    )


def disabled_capabilities() -> dict[str, bool | str]:
    capabilities: dict[str, bool | str] = {"dataset_list": False}
    for key in MUTATION_CAPABILITIES:
        capabilities[key] = False
    return capabilities


def capabilities_with_dataset_list(dataset_list: bool | str) -> dict[str, bool | str]:
    capabilities = disabled_capabilities()
    capabilities["dataset_list"] = dataset_list
    return capabilities


def sanitize_base_url(base_url: str) -> str:
    if not base_url:
        return ""
    split = urlsplit(base_url)
    hostname = split.hostname or ""
    netloc = hostname
    if split.port is not None:
        netloc = f"{hostname}:{split.port}"
    return urlunsplit((split.scheme, netloc, split.path.rstrip("/"), "", ""))


def response_shape(body: Any) -> str:
    if isinstance(body, list):
        return "list"
    if isinstance(body, dict):
        if isinstance(body.get("data"), list):
            return "dict_with_data"
        if isinstance(body.get("items"), list):
            return "dict_with_items"
        return "dict"
    if body is None:
        return "empty"
    return type(body).__name__


def elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result
