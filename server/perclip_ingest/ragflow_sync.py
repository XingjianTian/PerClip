from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .knowledge_base_store import ClipRouteDecision
from .storage import StoredClipEnrichment, StoredClipRawFields


SYNC_OPERATIONS = {
    "upload_document",
    "update_meta_fields",
    "reindex_after_move",
    "skip_no_dataset",
    "skip_no_enrichment",
}
SYNC_STATUSES = {"planned", "skipped", "blocked", "failed"}
SECRET_KEY_RE = re.compile(r"(token|api[_-]?key|password|passwd|secret|cookie|authorization)", re.IGNORECASE)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?:token|api[_-]?key|password|passwd|secret|cookie|authorization)\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RagflowSyncPlan:
    knowledge_base_id: str
    ragflow_dataset_id: str
    ragflow_document_id: str
    route_decision_id: int | None
    enrichment_id: int | None
    operation: str
    status: str
    reason: str
    plan: dict[str, object]
    dry_run: bool = True
    remote_document_changed: bool = False


def plan_ragflow_sync_dry_run(
    raw: StoredClipRawFields,
    route_decision: ClipRouteDecision | None,
    enrichment: StoredClipEnrichment | None,
    metadata: dict[str, object],
) -> RagflowSyncPlan:
    del metadata
    if route_decision is None:
        return RagflowSyncPlan(
            knowledge_base_id="",
            ragflow_dataset_id="",
            ragflow_document_id=raw.ragflow_document_id,
            route_decision_id=None,
            enrichment_id=enrichment.id if enrichment is not None else None,
            operation="skip_no_dataset",
            status="blocked",
            reason="missing route decision",
            plan={"dry_run": True},
        )

    if not route_decision.ragflow_dataset_id:
        return RagflowSyncPlan(
            knowledge_base_id=route_decision.knowledge_base_id,
            ragflow_dataset_id="",
            ragflow_document_id=raw.ragflow_document_id,
            route_decision_id=route_decision.id,
            enrichment_id=enrichment.id if enrichment is not None else None,
            operation="skip_no_dataset",
            status="blocked",
            reason="target knowledge base has no ragflow dataset mapping",
            plan={"dry_run": True},
        )

    if enrichment is None:
        return RagflowSyncPlan(
            knowledge_base_id=route_decision.knowledge_base_id,
            ragflow_dataset_id=route_decision.ragflow_dataset_id,
            ragflow_document_id=raw.ragflow_document_id,
            route_decision_id=route_decision.id,
            enrichment_id=None,
            operation="skip_no_enrichment",
            status="blocked",
            reason="missing enrichment",
            plan={
                "target_dataset_id": route_decision.ragflow_dataset_id,
                "dry_run": True,
            },
        )

    if not raw.ragflow_document_id:
        return planned_sync(
            raw=raw,
            route_decision=route_decision,
            enrichment=enrichment,
            operation="upload_document",
            reason="document would be uploaded to target dataset",
            extra_plan={},
        )

    if route_decision.reindex_status == "required":
        return planned_sync(
            raw=raw,
            route_decision=route_decision,
            enrichment=enrichment,
            operation="reindex_after_move",
            reason="document move requires reindex in target dataset",
            extra_plan={
                "existing_document_id": raw.ragflow_document_id,
                "reindex_status": route_decision.reindex_status,
            },
        )

    return planned_sync(
        raw=raw,
        route_decision=route_decision,
        enrichment=enrichment,
        operation="update_meta_fields",
        reason="document meta_fields would be updated from enrichment",
        extra_plan={"existing_document_id": raw.ragflow_document_id},
    )


def planned_sync(
    *,
    raw: StoredClipRawFields,
    route_decision: ClipRouteDecision,
    enrichment: StoredClipEnrichment,
    operation: str,
    reason: str,
    extra_plan: dict[str, object],
) -> RagflowSyncPlan:
    meta_fields = {
        "summary": enrichment.summary,
        "tags": enrichment.tags,
        "language": enrichment.language,
    }
    plan: dict[str, object] = {
        "target_dataset_id": route_decision.ragflow_dataset_id,
        "title": enrichment.title or raw.title_hint or raw.filename or "未命名收藏",
        "summary": enrichment.summary,
        "tags": enrichment.tags,
        "language": enrichment.language,
        "dry_run": True,
    }
    if operation in {"update_meta_fields", "reindex_after_move"}:
        plan["meta_fields"] = meta_fields
    plan.update(extra_plan)
    return RagflowSyncPlan(
        knowledge_base_id=route_decision.knowledge_base_id,
        ragflow_dataset_id=route_decision.ragflow_dataset_id,
        ragflow_document_id=raw.ragflow_document_id,
        route_decision_id=route_decision.id,
        enrichment_id=enrichment.id,
        operation=operation,
        status="planned",
        reason=reason,
        plan=sanitize_plan(plan),
    )


def sanitize_plan(value: dict[str, object]) -> dict[str, object]:
    sanitized = sanitize_value(value)
    return sanitized if isinstance(sanitized, dict) else {}


def sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): sanitize_value(item)
            for key, item in value.items()
            if not SECRET_KEY_RE.search(str(key))
        }
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        return SECRET_KEY_RE.sub("[redacted]", SECRET_ASSIGNMENT_RE.sub("[redacted]", value))
    return value
