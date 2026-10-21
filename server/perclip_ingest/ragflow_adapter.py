from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from .config import RagflowSettings
from .ragflow_index import (
    RagflowChunkSummary,
    RagflowDocumentMatch,
    RagflowDocumentStatus,
    RagflowVectorEvidence,
)


CAPABILITY_KEYS = (
    "dataset_list",
    "dataset_create",
    "dataset_update",
    "dataset_delete",
    "document_upload",
    "document_operation_lookup",
    "document_meta_fields",
    "document_parse",
    "document_status",
    "document_chunk_summary",
    "document_vector_evidence",
    "document_disable",
    "document_delete",
    "document_delete_verification",
    "cross_dataset_move",
)
STAGE14A_MUTATION_DISABLED_MESSAGE = "remote RAGFlow mutation is disabled by the Stage 14B safety gate"


class RagflowAdapterError(ValueError):
    pass


class RagflowUnsupportedError(RagflowAdapterError):
    pass


@dataclass(frozen=True)
class RagflowDataset:
    id: str
    name: str
    description: str = ""
    template_key: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "template_key": self.template_key,
        }


@dataclass(frozen=True)
class RagflowDocumentRef:
    dataset_id: str
    document_id: str
    name: str
    meta_fields: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "document_id": self.document_id,
            "name": self.name,
            "meta_fields": self.meta_fields,
            "dry_run": self.dry_run,
        }


@dataclass(frozen=True)
class RagflowCapabilityReport:
    adapter_status: str
    configured: bool
    capabilities: dict[str, str]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_status": self.adapter_status,
            "configured": self.configured,
            "capabilities": self.capabilities,
            "notes": self.notes,
        }


class RagflowAdapter(Protocol):
    def list_datasets(self) -> list[RagflowDataset]:
        ...

    def create_dataset(self, name: str, description: str, template_key: str, dry_run: bool = True) -> dict[str, Any]:
        ...

    def update_dataset(
        self,
        dataset_id: str,
        name: str | None = None,
        description: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        ...

    def delete_dataset(self, dataset_id: str, dry_run: bool = True, confirm_name: str | None = None) -> dict[str, Any]:
        ...

    def upload_document(
        self,
        dataset_id: str,
        name: str,
        content_or_path: str,
        meta_fields: dict[str, Any] | None = None,
        dry_run: bool = True,
    ) -> RagflowDocumentRef:
        ...

    def find_document_by_operation_key(
        self, dataset_id: str, operation_key: str
    ) -> list[RagflowDocumentMatch]:
        ...

    def request_parse(self, dataset_id: str, document_id: str) -> None:
        ...

    def get_document_status(
        self, dataset_id: str, document_id: str
    ) -> RagflowDocumentStatus:
        ...

    def get_chunk_summary(
        self, dataset_id: str, document_id: str
    ) -> RagflowChunkSummary:
        ...

    def get_vector_evidence(
        self, dataset_id: str, document_id: str
    ) -> RagflowVectorEvidence:
        ...

    def request_delete(self, dataset_id: str, document_id: str) -> None:
        ...

    def verify_deleted(
        self, dataset_id: str, document_id: str
    ) -> tuple[RagflowDocumentStatus, RagflowChunkSummary, RagflowVectorEvidence]:
        ...

    def update_document_meta(
        self,
        dataset_id: str,
        document_id: str,
        meta_fields: dict[str, Any],
        dry_run: bool = True,
    ) -> dict[str, Any]:
        ...

    def disable_or_delete_document(
        self,
        dataset_id: str,
        document_id: str,
        mode: str,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        ...

    def capability_report(self) -> RagflowCapabilityReport:
        ...


class RagflowHttpClient(Protocol):
    def upload_document(self, base_url: str, api_key: str, dataset_id: str, name: str, content: bytes) -> object:
        ...

    def update_document_meta(self, base_url: str, api_key: str, dataset_id: str, document_id: str, meta_fields: dict[str, Any]) -> object:
        ...

    def find_documents(
        self, base_url: str, api_key: str, dataset_id: str, operation_key: str
    ) -> object:
        ...

    def request_parse(
        self, base_url: str, api_key: str, dataset_id: str, document_id: str
    ) -> object:
        ...

    def get_document(
        self, base_url: str, api_key: str, dataset_id: str, document_id: str
    ) -> object:
        ...

    def get_chunks(
        self, base_url: str, api_key: str, dataset_id: str, document_id: str,
        page: int, page_size: int,
    ) -> object:
        ...

    def delete_document(
        self, base_url: str, api_key: str, dataset_id: str, document_id: str
    ) -> object:
        ...


class UrlLibRagflowHttpClient:
    timeout_seconds = 30.0

    def upload_document(self, base_url: str, api_key: str, dataset_id: str, name: str, content: bytes) -> object:
        boundary = f"perclip-{uuid.uuid4().hex}"
        return self._request(base_url, api_key, f"/api/v1/datasets/{dataset_id}/documents", multipart_file_body(boundary, name, content), f"multipart/form-data; boundary={boundary}")

    def update_document_meta(self, base_url: str, api_key: str, dataset_id: str, document_id: str, meta_fields: dict[str, Any]) -> object:
        return self._request(base_url, api_key, f"/api/v1/datasets/{dataset_id}/documents/{document_id}", json.dumps({"meta_fields": meta_fields}, ensure_ascii=False).encode("utf-8"), "application/json", method="PUT")

    def find_documents(
        self, base_url: str, api_key: str, dataset_id: str, operation_key: str
    ) -> object:
        query = urlencode({"keywords": operation_key, "page_size": 100})
        return self._request(
            base_url, api_key, f"/api/v1/datasets/{dataset_id}/documents?{query}",
            None, "application/json", method="GET",
        )

    def request_parse(
        self, base_url: str, api_key: str, dataset_id: str, document_id: str
    ) -> object:
        return self._request(
            base_url, api_key, f"/api/v1/datasets/{dataset_id}/chunks",
            json.dumps({"document_ids": [document_id]}).encode(), "application/json",
        )

    def get_document(
        self, base_url: str, api_key: str, dataset_id: str, document_id: str
    ) -> object:
        query = urlencode({"id": document_id})
        return self._request(
            base_url, api_key, f"/api/v1/datasets/{dataset_id}/documents?{query}",
            None, "application/json", method="GET", accept_document_missing=True,
        )

    def get_chunks(
        self, base_url: str, api_key: str, dataset_id: str, document_id: str,
        page: int, page_size: int,
    ) -> object:
        query = urlencode({"page": page, "page_size": page_size})
        return self._request(
            base_url,
            api_key,
            f"/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks?{query}",
            None, "application/json", method="GET",
        )

    def delete_document(
        self, base_url: str, api_key: str, dataset_id: str, document_id: str
    ) -> object:
        return self._request(
            base_url, api_key, f"/api/v1/datasets/{dataset_id}/documents",
            json.dumps({"ids": [document_id]}).encode(), "application/json",
            method="DELETE", accept_document_delete_missing=True,
        )

    def _request(
        self,
        base_url: str,
        api_key: str,
        path: str,
        body: bytes | None,
        content_type: str,
        *,
        method: str = "POST",
        accept_document_missing: bool = False,
        accept_document_delete_missing: bool = False,
    ) -> object:
        request = Request(urljoin(base_url.rstrip("/") + "/", path.lstrip("/")), data=body, headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json", "Content-Type": content_type}, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RagflowAdapterError("RAGFlow document request failed") from error
        if (
            isinstance(payload, dict)
            and "code" in payload
            and payload["code"] not in (0, "0")
        ):
            if (
                accept_document_missing
                and payload.get("code") in (102, "102")
                and str(payload.get("message") or "").startswith(
                    "You don't own the document "
                )
            ):
                return {"data": {"docs": [], "total": 0}}
            if (
                accept_document_delete_missing
                and payload.get("code") in (102, "102")
                and "Document not found:" in str(payload.get("message") or "")
            ):
                return {"code": 0, "data": None}
            raise RagflowAdapterError("RAGFlow document request was rejected")
        return payload


class DisabledRagflowAdapter:
    def list_datasets(self) -> list[RagflowDataset]:
        return []

    def create_dataset(self, name: str, description: str, template_key: str, dry_run: bool = True) -> dict[str, Any]:
        return planned_dataset_operation(
            operation="create_dataset",
            dry_run=True,
            configured=False,
            dataset_id="",
            name=name,
            description=description,
            template_key=template_key,
            note="RAGFlow is not configured; this is a local plan only.",
        )

    def update_dataset(
        self,
        dataset_id: str,
        name: str | None = None,
        description: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        return planned_dataset_operation(
            operation="update_dataset",
            dry_run=True,
            configured=False,
            dataset_id=dataset_id,
            name=name,
            description=description,
            note="RAGFlow is not configured; this is a local plan only.",
        )

    def delete_dataset(self, dataset_id: str, dry_run: bool = True, confirm_name: str | None = None) -> dict[str, Any]:
        return planned_delete_operation(
            dataset_id=dataset_id,
            dry_run=True,
            configured=False,
            confirm_name=confirm_name,
            note="RAGFlow is not configured; no remote dataset can be deleted.",
        )

    def upload_document(
        self,
        dataset_id: str,
        name: str,
        content_or_path: str,
        meta_fields: dict[str, Any] | None = None,
        dry_run: bool = True,
    ) -> RagflowDocumentRef:
        return RagflowDocumentRef(
            dataset_id=dataset_id,
            document_id=f"dry-run:{stable_ref(dataset_id, name)}",
            name=name,
            meta_fields=meta_fields or {},
            dry_run=True,
        )

    def update_document_meta(
        self,
        dataset_id: str,
        document_id: str,
        meta_fields: dict[str, Any],
        dry_run: bool = True,
    ) -> dict[str, Any]:
        return {
            "operation": "update_document_meta",
            "dry_run": True,
            "configured": False,
            "dataset_id": dataset_id,
            "document_id": document_id,
            "planned_meta_fields": meta_fields,
        }

    def _unsupported_read(self) -> None:
        raise RagflowUnsupportedError("RAGFlow index verification is unavailable")

    def find_document_by_operation_key(
        self, dataset_id: str, operation_key: str
    ) -> list[RagflowDocumentMatch]:
        self._unsupported_read()

    def request_parse(self, dataset_id: str, document_id: str) -> None:
        self._unsupported_read()

    def get_document_status(
        self, dataset_id: str, document_id: str
    ) -> RagflowDocumentStatus:
        self._unsupported_read()

    def get_chunk_summary(
        self, dataset_id: str, document_id: str
    ) -> RagflowChunkSummary:
        self._unsupported_read()

    def get_vector_evidence(
        self, dataset_id: str, document_id: str
    ) -> RagflowVectorEvidence:
        self._unsupported_read()

    def request_delete(self, dataset_id: str, document_id: str) -> None:
        self._unsupported_read()

    def verify_deleted(
        self, dataset_id: str, document_id: str
    ) -> tuple[RagflowDocumentStatus, RagflowChunkSummary, RagflowVectorEvidence]:
        self._unsupported_read()

    def disable_or_delete_document(
        self,
        dataset_id: str,
        document_id: str,
        mode: str,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        validate_document_mode(mode)
        return {
            "operation": "disable_or_delete_document",
            "mode": mode,
            "dry_run": True,
            "configured": False,
            "dataset_id": dataset_id,
            "document_id": document_id,
            "remote_document_changed": False,
        }

    def capability_report(self) -> RagflowCapabilityReport:
        return RagflowCapabilityReport(
            adapter_status="disabled",
            configured=False,
            capabilities={key: "not_configured" for key in CAPABILITY_KEYS},
            notes=["RAGFlow base URL or API key is not configured."],
        )


class DryRunRagflowAdapter(DisabledRagflowAdapter):
    def __init__(self, configured: bool = False) -> None:
        self.configured = configured

    def list_datasets(self) -> list[RagflowDataset]:
        return []

    def create_dataset(self, name: str, description: str, template_key: str, dry_run: bool = True) -> dict[str, Any]:
        require_dry_run(dry_run, "create_dataset")
        return planned_dataset_operation(
            operation="create_dataset",
            dry_run=True,
            configured=self.configured,
            dataset_id=f"dry-run-dataset:{stable_ref(name, template_key)}",
            name=name,
            description=description,
            template_key=template_key,
        )

    def update_dataset(
        self,
        dataset_id: str,
        name: str | None = None,
        description: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        require_dry_run(dry_run, "update_dataset")
        return planned_dataset_operation(
            operation="update_dataset",
            dry_run=True,
            configured=self.configured,
            dataset_id=dataset_id,
            name=name,
            description=description,
        )

    def delete_dataset(self, dataset_id: str, dry_run: bool = True, confirm_name: str | None = None) -> dict[str, Any]:
        if not dry_run:
            raise RagflowAdapterError(STAGE14A_MUTATION_DISABLED_MESSAGE)
        return planned_delete_operation(
            dataset_id=dataset_id,
            dry_run=True,
            configured=self.configured,
            confirm_name=confirm_name,
            note="Dry-run only; no remote RAGFlow dataset will be deleted.",
        )

    def upload_document(
        self,
        dataset_id: str,
        name: str,
        content_or_path: str,
        meta_fields: dict[str, Any] | None = None,
        dry_run: bool = True,
    ) -> RagflowDocumentRef:
        require_dry_run(dry_run, "upload_document")
        return RagflowDocumentRef(
            dataset_id=dataset_id,
            document_id=f"dry-run:{stable_ref(dataset_id, name, content_or_path)}",
            name=name,
            meta_fields=meta_fields or {},
            dry_run=True,
        )

    def update_document_meta(
        self,
        dataset_id: str,
        document_id: str,
        meta_fields: dict[str, Any],
        dry_run: bool = True,
    ) -> dict[str, Any]:
        require_dry_run(dry_run, "update_document_meta")
        return {
            "operation": "update_document_meta",
            "dry_run": True,
            "configured": self.configured,
            "dataset_id": dataset_id,
            "document_id": document_id,
            "planned_meta_fields": meta_fields,
        }

    def disable_or_delete_document(
        self,
        dataset_id: str,
        document_id: str,
        mode: str,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        require_dry_run(dry_run, "disable_or_delete_document")
        validate_document_mode(mode)
        return {
            "operation": "disable_or_delete_document",
            "mode": mode,
            "dry_run": True,
            "configured": self.configured,
            "dataset_id": dataset_id,
            "document_id": document_id,
            "remote_document_changed": False,
        }

    def capability_report(self) -> RagflowCapabilityReport:
        return RagflowCapabilityReport(
            adapter_status="dry_run",
            configured=self.configured,
            capabilities={key: "not_verified" for key in CAPABILITY_KEYS},
            notes=[
                "Dry-run adapter does not call RAGFlow.",
                "Real dataset/document endpoint details remain unverified.",
            ],
        )


class HttpRagflowAdapter(DryRunRagflowAdapter):
    """Allowlisted HTTP boundary for one-document index lifecycle operations."""

    def __init__(self, settings: RagflowSettings, client: RagflowHttpClient | None = None) -> None:
        super().__init__(configured=settings.configured)
        self.base_url = settings.base_url
        self.api_key = settings.api_key
        self.real_sync_enabled = settings.real_sync_enabled
        self.allowed_dataset_ids = settings.sync_allow_dataset_ids
        self.client = client or UrlLibRagflowHttpClient()

    def upload_document(self, dataset_id: str, name: str, content_or_path: str, meta_fields: dict[str, Any] | None = None, dry_run: bool = True) -> RagflowDocumentRef:
        if dry_run:
            return super().upload_document(dataset_id, name, content_or_path, meta_fields, dry_run=True)
        self.require_allowed_dataset(dataset_id)
        candidate = Path(content_or_path)
        content = candidate.read_bytes() if candidate.is_file() else content_or_path.encode("utf-8")
        response = self.client.upload_document(self.base_url, self.api_key, dataset_id, name, content)
        return RagflowDocumentRef(dataset_id=dataset_id, document_id=document_id_from_response(response), name=name, meta_fields=meta_fields or {}, dry_run=False)

    def update_document_meta(self, dataset_id: str, document_id: str, meta_fields: dict[str, Any], dry_run: bool = True) -> dict[str, Any]:
        if dry_run:
            return super().update_document_meta(dataset_id, document_id, meta_fields, dry_run=True)
        self.require_allowed_dataset(dataset_id)
        self.client.update_document_meta(self.base_url, self.api_key, dataset_id, document_id, meta_fields)
        return {"operation": "update_document_meta", "dry_run": False, "configured": True, "dataset_id": dataset_id, "document_id": document_id, "meta_fields": meta_fields, "remote_document_changed": True}

    def find_document_by_operation_key(
        self, dataset_id: str, operation_key: str
    ) -> list[RagflowDocumentMatch]:
        self.require_allowed_dataset(dataset_id)
        rows = response_rows(
            self.client.find_documents(
                self.base_url, self.api_key, dataset_id, operation_key
            )
        )
        matches: list[RagflowDocumentMatch] = []
        for row in rows:
            metadata = row.get("meta_fields")
            metadata = dict(metadata) if isinstance(metadata, dict) else {}
            deterministic_suffix = f"-{operation_key}.md"
            if (
                metadata.get("operation_key") == operation_key
                or str(row.get("name") or "").endswith(deterministic_suffix)
            ) and row.get("id"):
                matches.append(
                    RagflowDocumentMatch(str(row["id"]), operation_key, metadata)
                )
        return matches

    def request_parse(self, dataset_id: str, document_id: str) -> None:
        self.require_allowed_dataset(dataset_id)
        self.client.request_parse(
            self.base_url, self.api_key, dataset_id, document_id
        )

    def get_document_status(
        self, dataset_id: str, document_id: str
    ) -> RagflowDocumentStatus:
        self.require_allowed_dataset(dataset_id)
        rows = response_rows(
            self.client.get_document(
                self.base_url, self.api_key, dataset_id, document_id
            )
        )
        matching = [row for row in rows if str(row.get("id") or "") == document_id]
        if not matching:
            return RagflowDocumentStatus(document_id, "missing", {})
        row = matching[0]
        metadata = row.get("meta_fields")
        raw_status = row["run"] if "run" in row else row.get("status")
        return RagflowDocumentStatus(
            document_id,
            normalize_remote_status(raw_status),
            dict(metadata) if isinstance(metadata, dict) else {},
        )

    def get_chunk_summary(
        self, dataset_id: str, document_id: str
    ) -> RagflowChunkSummary:
        self.require_allowed_dataset(dataset_id)
        rows, total = self._all_chunk_rows(dataset_id, document_id)
        if len(rows) != total:
            raise RagflowUnsupportedError("RAGFlow chunk pagination is incomplete")
        return RagflowChunkSummary(document_id, total)

    def get_vector_evidence(
        self, dataset_id: str, document_id: str
    ) -> RagflowVectorEvidence:
        self.require_allowed_dataset(dataset_id)
        rows, total = self._all_chunk_rows(dataset_id, document_id)
        if len(rows) != total:
            raise RagflowUnsupportedError("RAGFlow vector coverage is incomplete")
        if any(not isinstance(row.get("has_vector"), bool) for row in rows):
            raise RagflowUnsupportedError(
                "RAGFlow public chunk API does not expose explicit vector evidence"
            )
        return RagflowVectorEvidence(
            document_id,
            sum(1 for row in rows if row["has_vector"] is True),
            covered_chunk_count=len(rows),
            evidence_type="explicit_chunk_vector_flag",
        )

    def _all_chunk_rows(
        self, dataset_id: str, document_id: str
    ) -> tuple[list[dict[str, Any]], int]:
        page_size = 100
        page = 1
        expected_total: int | None = None
        rows: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        while True:
            response = self.client.get_chunks(
                self.base_url,
                self.api_key,
                dataset_id,
                document_id,
                page,
                page_size,
            )
            total = response_total(response)
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise RagflowUnsupportedError(
                    "RAGFlow chunk total changed during pagination"
                )
            page_rows = response_rows(response)
            if total > 0 and not page_rows:
                raise RagflowUnsupportedError("RAGFlow chunk pagination is incomplete")
            for row in page_rows:
                chunk_id = str(row.get("id") or "")
                if not chunk_id or chunk_id in seen_ids:
                    raise RagflowUnsupportedError(
                        "RAGFlow chunk pagination lacks unique complete coverage"
                    )
                seen_ids.add(chunk_id)
                rows.append(row)
            if len(rows) >= total:
                break
            if len(page_rows) < page_size:
                raise RagflowUnsupportedError("RAGFlow chunk pagination is incomplete")
            page += 1
        if len(rows) != (expected_total or 0):
            raise RagflowUnsupportedError("RAGFlow chunk pagination is incomplete")
        return rows, expected_total or 0

    def request_delete(self, dataset_id: str, document_id: str) -> None:
        self.require_allowed_dataset(dataset_id)
        self.client.delete_document(
            self.base_url, self.api_key, dataset_id, document_id
        )

    def verify_deleted(
        self, dataset_id: str, document_id: str
    ) -> tuple[RagflowDocumentStatus, RagflowChunkSummary, RagflowVectorEvidence]:
        return (
            self.get_document_status(dataset_id, document_id),
            self.get_chunk_summary(dataset_id, document_id),
            self.get_vector_evidence(dataset_id, document_id),
        )

    def require_allowed_dataset(self, dataset_id: str) -> None:
        if not self.real_sync_enabled:
            raise RagflowAdapterError("real RAGFlow sync is disabled; set PERCLIP_ENABLE_REAL_RAGFLOW_SYNC and PERCLIP_RAGFLOW_SYNC_ALLOW_DATASET_IDS")
        if dataset_id not in self.allowed_dataset_ids:
            raise RagflowAdapterError("RAGFlow dataset is not allowlisted for real sync")

    def capability_report(self) -> RagflowCapabilityReport:
        if not self.configured:
            return DisabledRagflowAdapter().capability_report()
        capabilities = {key: "disabled" for key in CAPABILITY_KEYS}
        capabilities["dataset_list"] = "unknown"
        capabilities["document_upload"] = "enabled" if self.real_sync_enabled else "disabled"
        capabilities["document_meta_fields"] = "enabled" if self.real_sync_enabled else "disabled"
        for key in (
            "document_operation_lookup",
            "document_parse",
            "document_status",
            "document_chunk_summary",
            "document_delete",
            "document_delete_verification",
        ):
            capabilities[key] = "enabled" if self.real_sync_enabled else "disabled"
        capabilities["document_vector_evidence"] = (
            "unsupported_public_api" if self.real_sync_enabled else "disabled"
        )
        return RagflowCapabilityReport(
            adapter_status="real_sync_enabled" if self.real_sync_enabled else "http_skeleton",
            configured=True,
            capabilities=capabilities,
            notes=[
                "RAGFlow credentials are present in server settings only.",
                "RAGFlow v0.26.1 public chunks omit vector fields; complete vector evidence requires an explicit operator verifier.",
                "Only exact-allowlisted single-document lifecycle operations can use the real sync gate.",
            ],
        )


def build_ragflow_adapter(settings: RagflowSettings) -> RagflowAdapter:
    if not settings.configured:
        return DisabledRagflowAdapter()
    return HttpRagflowAdapter(settings)


def planned_dataset_operation(
    *,
    operation: str,
    dry_run: bool,
    configured: bool,
    dataset_id: str,
    name: str | None = None,
    description: str | None = None,
    template_key: str = "",
    note: str = "",
) -> dict[str, Any]:
    return {
        "operation": operation,
        "dry_run": dry_run,
        "configured": configured,
        "dataset_id": dataset_id,
        "name": name or "",
        "description": description or "",
        "template_key": template_key,
        "remote_dataset_changed": False,
        "note": note,
    }


def planned_delete_operation(
    *,
    dataset_id: str,
    dry_run: bool,
    configured: bool,
    confirm_name: str | None,
    note: str,
) -> dict[str, Any]:
    return {
        "operation": "delete_dataset",
        "dry_run": dry_run,
        "configured": configured,
        "dataset_id": dataset_id,
        "danger_level": "high",
        "requires_confirmation": True,
        "confirm_name": confirm_name or "",
        "remote_dataset_deleted": False,
        "note": note,
    }


def require_dry_run(dry_run: bool, operation: str) -> None:
    if not dry_run:
        raise RagflowAdapterError(STAGE14A_MUTATION_DISABLED_MESSAGE)


def validate_document_mode(mode: str) -> None:
    if mode not in {"disable", "delete"}:
        raise RagflowAdapterError("document mode must be disable or delete")


def stable_ref(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]


def multipart_file_body(boundary: str, name: str, content: bytes) -> bytes:
    safe_name = name.replace('"', "_").replace("\r", "_").replace("\n", "_") or "perclip.md"
    return b"".join((f"--{boundary}\r\n".encode(), f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'.encode(), b"Content-Type: text/markdown; charset=utf-8\r\n\r\n", content, f"\r\n--{boundary}--\r\n".encode()))


def document_id_from_response(response: object) -> str:
    payload = response.get("data") if isinstance(response, dict) else None
    candidate = payload[0] if isinstance(payload, list) and payload else payload
    if isinstance(candidate, dict) and candidate.get("id"):
        return str(candidate["id"])
    raise RagflowAdapterError("RAGFlow upload response did not include a document id")


def response_rows(response: object) -> list[dict[str, Any]]:
    payload = response.get("data") if isinstance(response, dict) else None
    if isinstance(payload, dict):
        for key in ("docs", "documents", "chunks"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [dict(payload)]
    return []


def response_total(response: object) -> int:
    payload = response.get("data") if isinstance(response, dict) else None
    for container in (payload, response):
        if isinstance(container, dict):
            for key in ("total", "total_count", "count"):
                if key not in container:
                    continue
                value = container[key]
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    return value
                if isinstance(value, str) and value.isdigit():
                    return int(value)
                raise RagflowAdapterError("RAGFlow evidence count is invalid")
    return len(response_rows(response))


def normalize_remote_status(value: object) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        aliases = {
            "0": "unstart",
            "1": "running",
            "2": "cancelled",
            "3": "done",
            "4": "failed",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized in {
            "unstart", "running", "scheduled", "done", "failed", "cancelled",
            "missing", "unknown",
        }:
            return normalized
    if isinstance(value, int) and not isinstance(value, bool):
        return {0: "unstart", 1: "running", 2: "cancelled", 3: "done", 4: "failed"}.get(
            value, "unknown"
        )
    return "unknown"
