from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from typing import Any

from .knowledge_base_store import KnowledgeBaseStore
from .mobile_projection_safety import safe_mobile_text, safe_mobile_url
from .mobile_safety import contains_private_path
from .pipeline_store import PipelineStore
from .recall import displayable_title_hint, safe_text
from .secret_redaction import redact_structured_secret_values
from .storage import ClipStore, StoredClipEnrichment, StoredClipRawFields
from .topics import TopicStore


QUALITY_READ_CONTRACT_VERSION = "perclip.quality-read.v1"
USER_STATUSES = {"saved", "processing", "ready", "needs_attention"}
ACTIVE_JOB_STATUSES = {"pending", "running", "retry"}
FORBIDDEN_SERIALIZED_KEYS = {
    "storage_uri",
    "original_path",
    "original_url",
    "captured_url",
    "normalized_request_url",
    "ragflow_dataset_id",
    "dataset_id",
    "ragflow_document_id",
    "document_id",
    "ragflow_token",
    "connector_credential",
    "credential",
    "api_key",
    "stack_trace",
    "traceback",
    "active_enrichment_id",
    "latest_attempted_enrichment_id",
    "enrichment_id",
    "internal_clip_id",
    "source_asset_id",
    "projection_id",
    "active_projection_id",
    "index_pending_projection_id",
    "last_indexed_projection_id",
}
URL_CREDENTIAL_RE = re.compile(r"(?i)https?://[^/\s:@]+:[^/\s@]+@")
CONTENT_STAGES = {"archive_original", "extract", "clean", "enrich", "classify_topic", "route"}
CONTENT_STAGE_ORDER = {stage: index for index, stage in enumerate(
    ("archive_original", "extract", "clean", "enrich", "classify_topic", "route")
)}


@dataclass(frozen=True)
class ActiveContentResolution:
    raw: StoredClipRawFields
    enrichment: StoredClipEnrichment | None
    metadata: dict[str, object]
    processing: dict[str, object]
    active_projection: dict[str, object]
    resolution_mode: str
    active_enrichment_id: int | None

    @property
    def valid(self) -> bool:
        return self.resolution_mode in {"active", "legacy_latest_completed"}


def _dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _safe_url(value: object) -> str:
    return safe_mobile_url(value)


def _safe_mobile_text(value: object, *, limit: int) -> str:
    return safe_mobile_text(value, limit=limit)


def _generation_for_reference(public_id: str, reference: str) -> str:
    material = "\0".join((public_id, reference, "quality-read-generation-v1"))
    return "gen_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _generation_token(
    public_id: str,
    enrichment: StoredClipEnrichment | None,
    projection: object,
) -> str:
    projection_reference = str(_dict(projection).get("source_asset_id") or "")
    if projection_reference:
        return _generation_for_reference(public_id, projection_reference)
    if enrichment is None:
        return ""
    fallback_reference = "\0".join(
        (str(enrichment.id), enrichment.created_at, enrichment.engine)
    )
    return _generation_for_reference(public_id, fallback_reference)


def _safe_projection(value: object, *, generation: str) -> dict[str, object]:
    projection = _dict(value)
    return {
        "generation": generation,
        "state": str(projection.get("extraction_status") or ""),
        "quality_reason": safe_text(str(projection.get("quality_reason") or ""), limit=160),
        "safe_error": safe_text(str(projection.get("safe_error_code") or ""), limit=64),
        "recall_eligible": bool(projection.get("recall_eligible", False)),
        "index_eligible": bool(projection.get("index_eligible", False)),
        "raw_fallback_used": bool(projection.get("raw_fallback_used", False)),
    }


def _safe_index_state(
    value: object, *, time_key: str, public_id: str
) -> dict[str, object]:
    state = _dict(value)
    projection_reference = str(state.get("projection_id") or "")
    return {
        "status": safe_text(str(state.get("status") or "not_started"), limit=64),
        "generation": _generation_for_reference(public_id, projection_reference) if projection_reference else "",
        "reason": safe_text(str(state.get("reason") or ""), limit=160),
        time_key: safe_text(str(state.get(time_key) or ""), limit=64),
    }


def _field_provenance(projection: dict[str, object], name: str) -> dict[str, object]:
    structured = _dict(projection.get("structured_metadata"))
    field = _dict(structured.get(name))
    return {
        "source": safe_text(str(field.get("source") or ""), limit=96),
        "extractor": safe_text(str(field.get("engine") or ""), limit=96),
        "version": safe_text(str(field.get("engine_version") or ""), limit=64),
    }


class ActiveContentResolver:
    """The sole domain resolver for active-vs-latest content semantics."""

    def __init__(
        self,
        store: ClipStore,
        pipeline_store: PipelineStore,
        knowledge_store: KnowledgeBaseStore,
        topic_store: TopicStore | None = None,
    ) -> None:
        self.store = store
        self.pipeline_store = pipeline_store
        self.knowledge_store = knowledge_store
        self.topic_store = topic_store

    def resolve(self, raw: StoredClipRawFields) -> ActiveContentResolution:
        stored = self.store.find_normalized_metadata_by_clip_id(raw.id)
        metadata = dict(stored.metadata) if stored is not None else {}
        processing = _dict(metadata.get("processing"))
        active_projection = _dict(processing.get("active_projection"))
        pointer_present = "active_enrichment_id" in processing and processing.get("active_enrichment_id") is not None
        if pointer_present:
            try:
                active_id = int(processing["active_enrichment_id"])
            except (TypeError, ValueError):
                return ActiveContentResolution(
                    raw, None, metadata, processing, active_projection,
                    "invalid_active_pointer", None,
                )
            enrichment = self.store.find_enrichment_by_id(active_id)
            if enrichment is None or enrichment.clip_id != str(raw.id):
                return ActiveContentResolution(
                    raw, None, metadata, processing, active_projection,
                    "invalid_active_pointer", active_id,
                )
            return ActiveContentResolution(
                raw, enrichment, metadata, processing, active_projection,
                "active", active_id,
            )

        legacy = self.store.find_latest_completed_enrichment_by_clip_id(raw.id)
        if legacy is not None:
            legacy_projection = active_projection or _dict(metadata.get("projection"))
            return ActiveContentResolution(
                raw, legacy, metadata, processing, legacy_projection,
                "legacy_latest_completed", legacy.id,
            )
        return ActiveContentResolution(
            raw, None, metadata, processing, active_projection,
            "no_active_enrichment", None,
        )

    def recall_source(
        self, raw: StoredClipRawFields, knowledge_base_name: str
    ) -> tuple[StoredClipRawFields, StoredClipEnrichment | None, str]:
        resolved = self.resolve(raw)
        active_url = ""
        if resolved.valid:
            active_url = _safe_url(
                resolved.active_projection.get("canonical_url")
                or resolved.active_projection.get("resolved_url")
                or _dict(resolved.metadata.get("clip")).get("url")
            )
        recall_raw = replace(
            raw,
            active_url=active_url,
            active_enrichment_invalid=resolved.resolution_mode == "invalid_active_pointer",
        )
        return recall_raw, resolved.enrichment, knowledge_base_name

    def build(self, raw: StoredClipRawFields) -> dict[str, object]:
        resolved = self.resolve(raw)
        processing_summary = self.pipeline_store.processing_summary(clip_id=raw.id)
        jobs = list(processing_summary.get("jobs", []))
        active_content_jobs = [
            job for job in jobs
            if str(job.get("stage") or "") in CONTENT_STAGES
            and str(job.get("status") or "") in ACTIVE_JOB_STATUSES
        ]
        active_content_jobs.sort(
            key=lambda job: CONTENT_STAGE_ORDER.get(str(job.get("stage") or ""), 999)
        )
        latest_projection = _dict(resolved.processing.get("latest_attempted_projection"))
        latest_enrichment_id = resolved.processing.get("latest_attempted_enrichment_id")
        latest_enrichment = None
        if latest_enrichment_id is not None:
            try:
                latest_enrichment = self.store.find_enrichment_by_id(int(latest_enrichment_id))
            except (TypeError, ValueError):
                latest_enrichment = None
        if latest_enrichment is None:
            latest_enrichment = self.store.find_latest_enrichment_by_clip_id(raw.id)

        quality_state = str(resolved.active_projection.get("extraction_status") or "")
        if not quality_state and resolved.enrichment is not None:
            quality_state = "completed" if resolved.enrichment.status == "completed" else resolved.enrichment.status
        recall_eligible = bool(resolved.active_projection.get("recall_eligible", quality_state == "completed"))
        index_eligible = bool(resolved.active_projection.get("index_eligible", quality_state == "completed"))
        active_usable = bool(
            resolved.valid
            and resolved.enrichment is not None
            and quality_state in {"completed", "partial"}
            and (quality_state != "partial" or recall_eligible)
        )
        latest_state = str(latest_projection.get("extraction_status") or "")
        latest_unusable = bool(
            latest_state == "failed"
            or (
                latest_state == "partial"
                and not bool(latest_projection.get("recall_eligible", False))
            )
        )
        public_id = self.pipeline_store.public_id_for(raw.id)
        active_generation = _generation_token(public_id, resolved.enrichment, resolved.active_projection)
        latest_generation = _generation_token(public_id, latest_enrichment, latest_projection)
        latest_index = _safe_index_state(
            resolved.processing.get("latest_index_attempt"),
            time_key="attempted_at",
            public_id=public_id,
        )
        index_failed = latest_index["status"] == "failed"
        needs_attention = bool(
            resolved.resolution_mode == "invalid_active_pointer"
            or latest_unusable
            or index_failed
            or (
                resolved.enrichment is not None
                and not active_usable
                and quality_state in {"failed", "partial"}
            )
        )
        if resolved.resolution_mode == "invalid_active_pointer":
            user_status = "needs_attention"
        elif active_content_jobs:
            user_status = "processing"
        elif active_usable:
            user_status = "ready"
        elif resolved.enrichment is not None or latest_unusable:
            user_status = "needs_attention"
        else:
            user_status = "saved"

        enrichment = resolved.enrichment
        active_url = ""
        if resolved.valid:
            active_url = _safe_url(
                resolved.active_projection.get("canonical_url")
                or resolved.active_projection.get("resolved_url")
                or _dict(resolved.metadata.get("clip")).get("url")
            )
        explicit_title = displayable_title_hint(raw.title_hint)
        if (
            raw.source_type in {"file", "image", "audio"}
            and raw.filename
            and explicit_title == displayable_title_hint(raw.filename)
        ):
            # Legacy ingest copies an asset filename into title_hint. Treat that
            # compatibility value as filename provenance, not a user title.
            explicit_title = ""
        filename_title = (
            _safe_mobile_text(raw.filename, limit=160)
            if raw.source_type in {"file", "image", "audio"}
            else ""
        )
        content_title = ""
        if explicit_title:
            content_title = enrichment.title if enrichment and resolved.valid else explicit_title
        elif filename_title:
            content_title = enrichment.title if enrichment and resolved.valid else filename_title
        elif active_usable and enrichment is not None:
            content_title = enrichment.title
        structured = _dict(resolved.active_projection.get("structured_metadata"))
        author_field = _dict(structured.get("author"))
        author_state = str(author_field.get("resolution_state") or "")
        author_value = str(author_field.get("value") or "")
        if author_state == "explicit_unknown":
            source_label = "未明确来源"
        elif author_state == "resolved" and author_value.strip():
            source_label = author_value
        else:
            source_label = raw.source_app or raw.source_type

        content_field = _dict(structured.get("core_content"))
        content_state = str(content_field.get("resolution_state") or "")
        summary = enrichment.summary if enrichment and resolved.valid else ""
        if content_state == "explicit_unavailable":
            summary = "内容暂不可用"

        active_content = {
            "title": _safe_mobile_text(content_title, limit=160),
            "summary": _safe_mobile_text(summary, limit=320),
            "original_text": _safe_mobile_text(raw.text, limit=4_000),
            "text_preview": _safe_mobile_text(
                enrichment.extracted_text if enrichment and resolved.valid else "", limit=600
            ),
            "source": _safe_mobile_text(source_label, limit=80),
            "safe_display_url": active_url,
            "captured_at": safe_mobile_text(raw.captured_at or raw.created_at, limit=64),
            "tags": [
                _safe_mobile_text(tag, limit=64)
                for tag in (enrichment.tags if enrichment and resolved.valid else [])
            ],
            "key_points": [
                _safe_mobile_text(point, limit=240)
                for point in (enrichment.key_points if enrichment and resolved.valid else [])
            ],
        }

        route = self.knowledge_store.find_latest_route_decision_by_clip_id(raw.id)
        knowledge_base = (
            self.knowledge_store.get_knowledge_base(route.knowledge_base_id, include_deleted=True)
            if route is not None
            else None
        )
        active_title_provenance = _field_provenance(resolved.active_projection, "title")
        canonical_provenance = _field_provenance(resolved.active_projection, "canonical_url")
        if explicit_title:
            active_title_provenance["source"] = "user.title_hint"
        elif filename_title:
            active_title_provenance["source"] = "file.filename"
        elif not active_usable:
            active_title_provenance = {"source": "", "extractor": "", "version": ""}
        latest_safe = _safe_projection(latest_projection, generation=latest_generation)
        latest_safe.update(
            {
                "engine": safe_text(latest_enrichment.engine if latest_enrichment else "", limit=96),
                "version": safe_text(
                    str(_field_provenance(latest_projection, "title").get("version") or ""), limit=64
                ),
            }
        )

        payload: dict[str, object] = {
            "contract_version": QUALITY_READ_CONTRACT_VERSION,
            "clip_id": public_id,
            "user_status": user_status,
            "active_content": active_content,
            "topic_assignment": (
                self.topic_store.assignment_payload(raw.id, current_generation=active_generation)
                if self.topic_store is not None
                else {}
            ),
            "quality": {
                "state": quality_state or "not_started",
                "quality_reason": safe_text(
                    str(resolved.active_projection.get("quality_reason") or ""), limit=160
                ),
                "recall_eligible": recall_eligible and resolved.valid,
                "index_eligible": index_eligible and resolved.valid,
                "raw_fallback_used": bool(
                    resolved.active_projection.get("raw_fallback_used", False)
                ),
            },
            "processing": {
                "active_generation": active_generation,
                "latest_attempt_generation": latest_generation,
                "in_progress": bool(active_content_jobs),
                "current_stage": str(active_content_jobs[0].get("stage") or "") if active_content_jobs else "",
                "resolution_mode": resolved.resolution_mode,
                "latest_attempt": latest_safe,
                "safe_error": safe_text(
                    str(latest_projection.get("safe_error_code") or resolved.processing.get("safe_error_code") or ""),
                    limit=64,
                ),
                "engine": safe_text(enrichment.engine if enrichment else "", limit=96),
                "version": safe_text(str(active_title_provenance.get("version") or ""), limit=64),
            },
            "routing": {
                "knowledge_base_id": route.knowledge_base_id if route else "",
                "knowledge_base_name": safe_text(knowledge_base.name if knowledge_base else "", limit=96),
                "decision_type": safe_text(route.decision_type if route else "", limit=64),
                "reason": safe_text(route.reason if route else "", limit=200),
                "manual_override": bool(route.manual_override) if route else False,
            },
            "index": {
                "active_index": _safe_index_state(
                    resolved.processing.get("active_index"),
                    time_key="updated_at",
                    public_id=public_id,
                ),
                "latest_index_attempt": latest_index,
            },
            "provenance": {
                "title_source": active_title_provenance["source"],
                "canonical_source": canonical_provenance["source"],
                "extractor": active_title_provenance["extractor"] or canonical_provenance["extractor"],
                "version": active_title_provenance["version"] or canonical_provenance["version"],
            },
            "actions": {
                "can_retry_processing": bool(latest_unusable or resolved.resolution_mode == "invalid_active_pointer"),
                "can_reprocess": True,
                "can_retry_index": bool(index_eligible and index_failed),
                "needs_attention": needs_attention,
            },
        }
        audit_quality_payload(payload)
        return payload

    def compact(self, raw: StoredClipRawFields) -> dict[str, object]:
        payload = self.build(raw)
        active = _dict(payload["active_content"])
        quality = _dict(payload["quality"])
        processing = _dict(payload["processing"])
        routing = _dict(payload["routing"])
        actions = _dict(payload["actions"])
        topic_assignment = _dict(payload.get("topic_assignment"))
        compact = {
            "clip_id": payload["clip_id"],
            "title": active["title"],
            "summary": active["summary"],
            "source": active["source"],
            "captured_at": active["captured_at"],
            "knowledge_base": {
                "id": routing["knowledge_base_id"],
                "name": routing["knowledge_base_name"],
            },
            "user_status": payload["user_status"],
            "quality_state": quality["state"],
            "has_safe_error": bool(processing["safe_error"]),
            "recall_eligible": quality["recall_eligible"],
            "needs_attention": actions["needs_attention"],
            "active_generation": processing["active_generation"],
            "active_version": processing["version"],
            "topic_assignment": topic_assignment,
        }
        audit_quality_payload(compact)
        return compact


def audit_quality_payload(payload: object) -> None:
    """Fail closed if a mobile read payload crosses a server/private boundary."""

    def visit(value: object, path: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = str(key).strip().lower()
                if normalized in FORBIDDEN_SERIALIZED_KEYS:
                    raise ValueError(f"forbidden quality field: {path}{key}")
                if normalized == "clip_id" and isinstance(nested, str) and nested and not re.fullmatch(r"pc_[0-9a-f]{32}", nested):
                    raise ValueError(f"non-public clip identity: {path}{key}")
                if normalized in {"active_generation", "latest_attempt_generation", "generation"} and isinstance(nested, str) and nested and not re.fullmatch(r"gen_[0-9a-f]{24}", nested):
                    raise ValueError(f"non-public content generation: {path}{key}")
                if normalized in {"cursor", "next_cursor"} and isinstance(nested, str) and nested and not nested.startswith("kc_"):
                    raise ValueError(f"non-public cursor identity: {path}{key}")
                if normalized in {"id", "event_id"} and isinstance(nested, int):
                    raise ValueError(f"numeric internal identity: {path}{key}")
                if normalized in {"id", "event_id"} and isinstance(nested, str) and nested.isdecimal():
                    raise ValueError(f"numeric internal identity: {path}{key}")
                if normalized in {"id", "node_id", "source", "target"} and isinstance(nested, str) and nested.startswith("clip:") and not nested.startswith("clip:pc_"):
                    raise ValueError(f"non-public clip node identity: {path}{key}")
                visit(nested, f"{path}{key}.")
            return
        if isinstance(value, list):
            for index, nested in enumerate(value):
                visit(nested, f"{path}{index}.")
            return
        if isinstance(value, str):
            if redact_structured_secret_values(value) != value:
                raise ValueError(f"unredacted secret-like value: {path[:-1]}")
            if URL_CREDENTIAL_RE.search(value) or contains_private_path(value):
                raise ValueError(f"private location or credential URL: {path[:-1]}")

    visit(payload, "")
