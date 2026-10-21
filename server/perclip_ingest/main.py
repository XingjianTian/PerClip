from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import base64
import binascii
import re
from secrets import compare_digest
from typing import Annotated, Literal
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from .archiver import ArchiveOutcome, MobileClipPayload, build_archiver
from .config import Settings
from .enrichment import deterministic_enrich
from .knowledge_base_store import (
    ClipRouteDecision,
    KnowledgeBaseConflictError,
    KnowledgeBaseError,
    KnowledgeBaseNotFoundError,
    KnowledgeBaseStore,
)
from .knowledge_list_store import CONTRACT_VERSION as KNOWLEDGE_LIST_CONTRACT_VERSION, KnowledgeListStore, decode_cursor, make_cursor
from .mobile_projection_safety import safe_correlation_identity, safe_mobile_text, safe_mobile_url
from .metadata_contract import NormalizedMetadataInput, build_normalized_metadata
from .memory_planet import build_memory_planet
from .mime_policy import is_allowed_mime_type, normalize_mime_type
from .ragflow_adapter import RagflowAdapterError, build_ragflow_adapter
from .ragflow_probe import probe_ragflow
from .ragflow_sync import plan_ragflow_sync_dry_run, sanitize_plan, sanitize_value
from .routing import RoutingPreviewError, RoutingPreviewInput, preview_route
from .storage import ClipStore, StoredClip, StoredClipRawFields, StoredRagflowSyncJob
from .recall import balanced_select, candidate_from_row, candidate_payload, graph_for, recent_candidates, utc_now, parse_utc
from .recall_domain import build_recall_domain, domain_payload, resurface_query_key, score_resurface_memory
from .recall_service import RecallContext
from .storage import RecallActionCollisionError, RecallItemNotFoundError
from .ingest_adapters import AdapterValidationError, json_envelope_to_command, mobile_form_to_command, multipart_envelope_to_command
from .ingest_service import (
    IngestArchiveError, IngestConflictError, IngestNotFoundError, IngestPayloadTooLargeError,
    IngestInternalError, IngestService, IngestUnsupportedMediaError, IngestValidationError,
)
from .pipeline_store import PipelineStore
from .quality_read_model import ActiveContentResolver, QUALITY_READ_CONTRACT_VERSION, audit_quality_payload
from .topics import TopicStore


ContentLengthStatus = Literal["ok", "invalid", "too_large"]
UPLOAD_READ_CHUNK_BYTES = 1024 * 1024
RAGFLOW_SYNC_ERROR_DATASET_NOT_ALLOWLISTED = "ragflow_dataset_not_allowlisted"
RAGFLOW_SYNC_ERROR_REINDEX_REQUIRED = "ragflow_reindex_required"
RAGFLOW_SYNC_ERROR_PLAN_BLOCKED = "ragflow_sync_plan_blocked"
CAPTURE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


def classify_content_length(content_length: str | None, max_request_bytes: int) -> ContentLengthStatus:
    if content_length is None or content_length == "":
        return "ok"
    try:
        request_bytes = int(content_length)
    except ValueError:
        return "invalid"
    if request_bytes < 0:
        return "invalid"
    if request_bytes > max_request_bytes:
        return "too_large"
    return "ok"


async def read_upload_file_limited(file: UploadFile, max_file_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total_bytes = 0

    while True:
        read_limit = min(UPLOAD_READ_CHUNK_BYTES, max_file_bytes + 1 - total_bytes)
        chunk = await file.read(read_limit)
        if not chunk:
            return b"".join(chunks)

        total_bytes += len(chunk)
        if total_bytes > max_file_bytes:
            raise HTTPException(status_code=413, detail="file too large")
        chunks.append(chunk)


async def read_json_body_limited(request: Request, max_request_bytes: int) -> object:
    chunks: list[bytes] = []
    total_bytes = 0
    async for chunk in request.stream():
        total_bytes += len(chunk)
        if total_bytes > max_request_bytes:
            raise HTTPException(status_code=413, detail="request too large")
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=422, detail="invalid JSON envelope") from error


def create_app(
    settings: Settings | None = None,
    archiver_override=None,
    ragflow_probe_override=None,
    ragflow_adapter_override=None,
    recall_fault_after_event_insert=None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    store = ClipStore(resolved_settings.data_dir)
    store.init()
    knowledge_store = KnowledgeBaseStore(resolved_settings.data_dir)
    knowledge_store.init()
    knowledge_list_store = KnowledgeListStore(resolved_settings.data_dir)
    pipeline_store = PipelineStore(resolved_settings.data_dir)
    pipeline_store.init()
    topic_store = TopicStore(resolved_settings.data_dir)
    topic_store.init()
    knowledge_list_store.init()
    quality_resolver = ActiveContentResolver(store, pipeline_store, knowledge_store, topic_store)
    ragflow_adapter = ragflow_adapter_override or build_ragflow_adapter(resolved_settings.ragflow)
    archiver = archiver_override if archiver_override is not None else (
        build_archiver(resolved_settings) if resolved_settings.processing_mode == "inline" else None
    )
    ingest_service = IngestService(
        store=store,
        knowledge_store=knowledge_store,
        archiver=archiver,
        max_file_bytes=resolved_settings.max_file_bytes,
        pipeline_store=pipeline_store,
        processing_mode=resolved_settings.processing_mode,
        deployment_environment=resolved_settings.deployment_environment,
    )

    app = FastAPI(title="PerClip Ingestion API", version="0.3.0")

    @app.middleware("http")
    async def limit_mobile_clip_request_size(request: Request, call_next):
        if request.url.path in {"/api/mobile-clips", "/api/ingest/v1/clips", "/api/ingest/v1/clips/multipart"}:
            content_length = request.headers.get("content-length")
            content_length_status = classify_content_length(
                content_length,
                resolved_settings.max_request_bytes,
            )
            if content_length_status == "invalid":
                return JSONResponse(status_code=400, content={"detail": "invalid content-length"})
            if content_length_status == "too_large":
                return JSONResponse(status_code=413, content={"detail": "request too large"})
            if request.url.path.startswith("/api/ingest/v1/clips"):
                chunks: list[bytes] = []
                total = 0
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > resolved_settings.max_request_bytes:
                        return JSONResponse(status_code=413, content={"detail": "request too large"})
                    chunks.append(chunk)
                body = b"".join(chunks)
                request._body = body
        return await call_next(request)

    def legacy_ingest_response(result) -> dict[str, object]:
        raw = store.find_raw_fields_by_clip_id(int(result.clip_id))
        return {
            "ok": True, "clip_id": result.clip_id, "client_request_id": result.client_request_id,
            "duplicate": result.duplicate, "title": result.title, "platform": result.platform,
            "content_hash": result.content_hash, "filename": result.filename, "size_bytes": result.size_bytes,
            "ragflow_document_id": "",
            "archive_status": result.archive_status, "capture": dict(result.capture),
        }

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        prefix = "Bearer "
        supplied_token = authorization[len(prefix):] if authorization and authorization.startswith(prefix) else ""
        if not compare_digest(supplied_token, resolved_settings.ingest_token):
            raise HTTPException(status_code=401, detail="invalid mobile ingest token")

    def require_ingest_token(authorization: Annotated[str | None, Header()] = None) -> str:
        prefix = "Bearer "
        supplied = authorization[len(prefix):] if authorization and authorization.startswith(prefix) else ""
        candidates = [resolved_settings.ingest_token, *resolved_settings.connector_tokens.values()]
        if not supplied or not any(compare_digest(supplied, candidate) for candidate in candidates):
            raise HTTPException(status_code=401, detail="invalid ingest token")
        return supplied

    def enforce_adapter_scope(adapter: str, supplied_token: str) -> None:
        if compare_digest(supplied_token, resolved_settings.ingest_token):
            if resolved_settings.connector_tokens and adapter != "android":
                raise HTTPException(status_code=403, detail="source adapter requires a dedicated ingest token")
            return
        authorized_adapter = next(
            (
                candidate
                for candidate, token in resolved_settings.connector_tokens.items()
                if compare_digest(supplied_token, token)
            ),
            "",
        )
        if authorized_adapter != adapter:
            raise HTTPException(status_code=403, detail="ingest token is not authorized for source adapter")

    def build_metadata_from_raw_fields(raw: StoredClipRawFields) -> dict[str, object]:
        source_event = pipeline_store.find_source_event_by_clip_id(clip_id=raw.id)
        has_file = raw.source_type in {"file", "image"} or (
            raw.source_type == "screen_clip" and not (raw.text or raw.url or raw.note)
        )
        return build_normalized_metadata(
            NormalizedMetadataInput(
                source_type=raw.source_type,
                title_hint=raw.title_hint,
                note=raw.note,
                text=raw.text,
                url=raw.url,
                mime_type=raw.mime_type,
                device_name=raw.device_name,
                source_app=raw.source_app,
                captured_at=raw.captured_at,
                client_request_id=raw.client_request_id,
                filename=raw.filename,
                has_file=has_file,
                size_bytes=raw.size_bytes,
                content_hash=raw.content_hash,
                storage_uri=raw.original_path,
                received_at=raw.created_at,
                archive_status=raw.archive_status,
                ragflow_document_id=raw.ragflow_document_id,
                client_batch_id=raw.capture_client_batch_id,
                parent_client_request_id=raw.capture_parent_client_request_id,
                part_index=raw.capture_part_index,
                part_count=raw.capture_part_count,
                part_role=raw.capture_part_role,
                content_fingerprint=raw.content_hash,
                source_adapter=str(source_event["adapter"]) if source_event else "android",
                source_client_id=str(source_event["client_id"]) if source_event else "",
                source_event_id=str(source_event["event_id"]) if source_event else "",
            )
        )

    def routing_input_from_raw_fields(
        raw: StoredClipRawFields,
        *,
        target_knowledge_base_id: str,
    ) -> RoutingPreviewInput:
        return RoutingPreviewInput(
            source_type=raw.source_type,
            title_hint=raw.title_hint,
            note=raw.note,
            text=raw.text,
            url=raw.url,
            mime_type=raw.mime_type,
            filename=raw.filename,
            device_name=raw.device_name,
            source_app=raw.source_app,
            client_request_id=raw.client_request_id,
            target_knowledge_base_id=target_knowledge_base_id,
        )

    def ensure_route_decision_for_raw_fields(
        raw: StoredClipRawFields,
        *,
        target_knowledge_base_id: str,
    ) -> ClipRouteDecision | None:
        existing = knowledge_store.find_latest_route_decision_by_clip_id(raw.id)
        if existing is not None:
            return existing
        if raw.client_request_id:
            existing = knowledge_store.find_route_decision_by_request_id(raw.client_request_id)
            if existing is not None:
                return existing
        preview = preview_route(
            knowledge_store,
            routing_input_from_raw_fields(raw, target_knowledge_base_id=target_knowledge_base_id),
        )
        return knowledge_store.save_route_decision(
            clip_id=raw.id,
            client_request_id=raw.client_request_id,
            knowledge_base_id=preview.knowledge_base_id,
            ragflow_dataset_id=preview.ragflow_dataset_id,
            decision_type=preview.decision_type,
            matched_rule_id=preview.matched_rule_id,
            matched_rule_ids=preview.matched_rule_ids,
            confidence=preview.confidence,
            manual_override=preview.manual_override,
            reason=preview.reason,
        )

    def with_routing_metadata(
        metadata: dict[str, object],
        route_decision: ClipRouteDecision,
    ) -> dict[str, object]:
        next_metadata = dict(metadata)
        knowledge_base = knowledge_store.get_knowledge_base(
            route_decision.knowledge_base_id,
            include_deleted=True,
        )
        routing = {
            "knowledge_base_id": route_decision.knowledge_base_id,
            "knowledge_base_name": knowledge_base.name if knowledge_base else "",
            "ragflow_dataset_id": route_decision.ragflow_dataset_id,
            "decision_type": route_decision.decision_type,
            "matched_rule_ids": route_decision.matched_rule_ids,
            "reason": route_decision.reason,
            "manual_override": route_decision.manual_override,
            "routed_at": route_decision.created_at,
        }
        if route_decision.previous_knowledge_base_id:
            routing["previous_knowledge_base_id"] = route_decision.previous_knowledge_base_id
        if route_decision.reindex_status and route_decision.reindex_status != "not_required":
            routing["reindex_status"] = route_decision.reindex_status
        if route_decision.lineage_id:
            routing["lineage_id"] = route_decision.lineage_id
        next_metadata["routing"] = routing
        return next_metadata

    def with_enrichment_metadata(
        metadata: dict[str, object],
        enrichment: dict[str, object],
    ) -> dict[str, object]:
        next_metadata = dict(metadata)
        next_metadata["enrichment"] = enrichment
        processing = dict(next_metadata.get("processing", {})) if isinstance(next_metadata.get("processing"), dict) else {}
        status = enrichment.get("status")
        processing["extraction_status"] = {
            "completed": "completed",
            "failed": "failed",
            "skipped": "not_started",
            "running": "partial",
            "pending": "not_started",
        }.get(str(status), "not_started")
        next_metadata["processing"] = processing
        return next_metadata

    def with_ragflow_sync_metadata(
        metadata: dict[str, object],
        sync_job: StoredRagflowSyncJob,
    ) -> dict[str, object]:
        next_metadata = dict(metadata)
        next_metadata["ragflow_sync"] = ragflow_sync_metadata_for(sync_job)
        return next_metadata

    def find_raw_clip_for_path(clip_id: str, *, ambiguous_detail: str) -> StoredClipRawFields:
        raw = None
        try:
            numeric_clip_id = int(clip_id)
        except ValueError:
            numeric_clip_id = None
        if numeric_clip_id is not None:
            raw = store.find_raw_fields_by_clip_id(numeric_clip_id)
        if raw is None and clip_id.startswith("pc_"):
            public_clip_id = pipeline_store.clip_id_for_public_id(clip_id)
            raw = (
                store.find_raw_fields_by_clip_id(public_clip_id)
                if public_clip_id is not None
                else None
            )
        if raw is None:
            raw = store.find_raw_fields_by_client_request_id(clip_id)
        if raw is None:
            prefix_matches = store.find_raw_fields_by_client_request_prefix(clip_id)
            if len(prefix_matches) > 1:
                raise HTTPException(status_code=409, detail=ambiguous_detail)
            raw = prefix_matches[0] if prefix_matches else None
        if raw is None:
            raise HTTPException(status_code=404, detail="clip not found")
        return raw

    def validate_limit(body: dict[str, object] | None, *, default: int) -> int:
        payload = body or {}
        limit = body_int(payload, "limit", default)
        if limit < 1:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        if limit > 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        return limit

    def validate_recall_days(days: int) -> int:
        if days < 1 or days > 30:
            raise HTTPException(status_code=422, detail="days must be between 1 and 30")
        return days

    def validate_domain_days(days: int) -> int:
        if days < 1 or days > 90:
            raise HTTPException(status_code=422, detail="days must be between 1 and 90")
        return days

    def recall_window_bounds(days: int, *, now: datetime | None = None) -> tuple[datetime, datetime]:
        current = (now or utc_now()).astimezone(timezone.utc)
        checked_days = validate_recall_days(days)
        start = datetime.combine(current.date() - timedelta(days=checked_days - 1), datetime.min.time(), tzinfo=timezone.utc)
        return start, current

    def previous_recall_window_bounds(days: int, *, now: datetime | None = None) -> tuple[datetime, datetime]:
        current_start, _current_end = recall_window_bounds(days, now=now)
        return current_start - timedelta(days=validate_recall_days(days)), current_start

    def recall_candidates_for_window(
        days: int,
        *,
        start: datetime,
        end: datetime,
        end_exclusive: bool = False,
        recall_counts: dict[str, int] | None = None,
        knowledge_base_id: str = "",
    ):
        comparison_now = end - timedelta(microseconds=1) if end_exclusive else end
        raw_rows = store.list_recall_raw_rows_for_window(
            start.isoformat(),
            end.isoformat(),
            end_exclusive=end_exclusive,
            knowledge_base_id=knowledge_base_id,
        )
        rows = [
            quality_resolver.recall_source(raw, knowledge_base_name)
            for raw, knowledge_base_name in raw_rows
        ]
        candidates = recent_candidates(rows, days=validate_recall_days(days), now=comparison_now, recall_counts=store.recall_counts_by_clip() if recall_counts is None else recall_counts, public_id_for=pipeline_store.public_id_for)
        return [
            replace(
                candidate,
                topics=(
                    topic_store.active_topic_pairs(int(candidate.internal_clip_id))
                    or [topic_store.unclassified_pair()]
                ),
            )
            for candidate in candidates
        ]

    def recall_candidates_for(days: int, *, now: datetime | None = None, recall_counts: dict[str, int] | None = None):
        start, end = recall_window_bounds(days, now=now)
        return recall_candidates_for_window(days, start=start, end=end, recall_counts=recall_counts)

    def recall_context_for_range(
        days: int,
        *,
        start: datetime,
        end: datetime,
        knowledge_base_id: str = "",
    ) -> RecallContext:
        days = validate_domain_days(days)
        query_end = min(end, utc_now())
        raw_rows = store.list_recall_raw_rows_for_window(
            start.isoformat(),
            query_end.isoformat(),
            end_exclusive=True,
            knowledge_base_id=knowledge_base_id,
        )
        rows = [
            quality_resolver.recall_source(raw, knowledge_base_name)
            for raw, knowledge_base_name in raw_rows
        ]
        candidates = recent_candidates(
            rows,
            days=days,
            now=query_end - timedelta(microseconds=1),
            recall_counts=store.recall_counts_by_clip(),
            public_id_for=pipeline_store.public_id_for,
        )
        candidates = [
            replace(
                candidate,
                topics=(
                    topic_store.active_topic_pairs(int(candidate.internal_clip_id))
                    or [topic_store.unclassified_pair()]
                ),
            )
            for candidate in candidates
        ]
        previous_start = start - timedelta(days=days)
        previous_raw_rows = store.list_recall_raw_rows_for_window(
            previous_start.isoformat(),
            start.isoformat(),
            end_exclusive=True,
            knowledge_base_id=knowledge_base_id,
        )
        previous_rows = [
            quality_resolver.recall_source(raw, knowledge_base_name)
            for raw, knowledge_base_name in previous_raw_rows
        ]
        previous = recent_candidates(previous_rows, days=days, now=start - timedelta(microseconds=1), recall_counts={}, public_id_for=pipeline_store.public_id_for)
        previous = [
            replace(
                candidate,
                topics=(
                    topic_store.active_topic_pairs(int(candidate.internal_clip_id))
                    or [topic_store.unclassified_pair()]
                ),
            )
            for candidate in previous
        ]
        internal_ids = [c.internal_clip_id for c in candidates]
        raw_interactions = store.recall_surface_stats(internal_ids)
        raw_history = store.recall_history_stats(internal_ids)
        interaction_stats = {c.clip_id: raw_interactions.get(c.internal_clip_id, {}) for c in candidates}
        recall_history = {c.clip_id: raw_history.get(c.internal_clip_id, {}) for c in candidates}
        domain = build_recall_domain(candidates, days=days, window_start=start.isoformat(), window_end=end.isoformat(), previous_window_topic_ids={identifier for c in previous for identifier, _ in c.topics}, recall_stats=recall_history, interaction_stats=interaction_stats)
        return RecallContext(days, start.isoformat(), end.isoformat(), candidates, {identifier for c in previous for identifier, _ in c.topics}, recall_history, interaction_stats, domain)

    def recall_context_for(days: int, *, knowledge_base_id: str = "") -> RecallContext:
        days = validate_domain_days(days)
        now = utc_now()
        start = datetime.combine(
            now.date() - timedelta(days=days - 1),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        stable_end = datetime.combine(
            now.date() + timedelta(days=1),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        return recall_context_for_range(
            days,
            start=start,
            end=stable_end,
            knowledge_base_id=knowledge_base_id,
        )

    def recall_domain_for(days: int):
        return recall_context_for(days).domain

    def recall_since(days: int) -> str:
        now = utc_now()
        start = now.date() - timedelta(days=validate_recall_days(days) - 1)
        return datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).isoformat()

    def recall_range_end() -> str:
        return utc_now().isoformat()

    def recall_snapshot_window(days: int) -> tuple[str, str]:
        start, current = recall_window_bounds(days)
        end = datetime.combine(current.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        return start.isoformat(), end.isoformat()

    def recall_snapshot_key(*, days: int, topic_id: str, window_start: str, window_end: str, candidates) -> str:
        # Deliberately excludes dynamic recall scores/history, session status and positions.
        source = []
        for candidate in sorted(candidates, key=lambda item: item.clip_id):
            safe_content = "\u001f".join([candidate.title, candidate.summary, "\u001e".join(sorted(candidate.tags))])
            source.append({"clip_id": candidate.clip_id, "captured_at": candidate.captured_at, "safe_content_hash": hashlib.sha256(safe_content.encode("utf-8")).hexdigest()})
        encoded = json.dumps({"days": days, "topic_id": topic_id, "window_start": window_start, "window_end": window_end, "sources": source}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]

    def build_metadata_for_raw_with_routing(
        raw: StoredClipRawFields,
        route_decision: ClipRouteDecision | None,
    ) -> dict[str, object]:
        existing_metadata = store.find_normalized_metadata_by_clip_id(raw.id)
        metadata = existing_metadata.metadata if existing_metadata is not None else build_metadata_from_raw_fields(raw)
        if route_decision is not None and "routing" not in metadata:
            metadata = with_routing_metadata(metadata, route_decision)
        return metadata

    def run_deterministic_enrichment_for_raw(raw: StoredClipRawFields):
        route_decision = knowledge_store.find_latest_route_decision_by_clip_id(raw.id)
        if route_decision is None:
            route_decision = ensure_route_decision_for_raw_fields(raw, target_knowledge_base_id="")
        metadata = build_metadata_for_raw_with_routing(raw, route_decision)

        result = deterministic_enrich(raw, route_decision, metadata)
        saved = store.save_enrichment(
            clip_id=raw.id,
            client_request_id=raw.client_request_id,
            knowledge_base_id=route_decision.knowledge_base_id if route_decision is not None else "",
            route_decision_id=route_decision.id if route_decision is not None else None,
            engine=result.engine,
            status=result.status,
            title=result.title,
            summary=result.summary,
            tags=result.tags,
            key_points=result.key_points,
            language=result.language,
            extracted_text=result.extracted_text,
            error_code=result.error_code,
            error_message=result.error_message,
        )
        store.save_normalized_metadata(
            clip_id=raw.id,
            client_request_id=raw.client_request_id,
            metadata=with_enrichment_metadata(metadata, enrichment_metadata_for(saved)),
        )
        return saved

    def save_ragflow_sync_plan_for_raw(raw: StoredClipRawFields) -> StoredRagflowSyncJob:
        route_decision = knowledge_store.find_latest_route_decision_by_clip_id(raw.id)
        enrichment = store.find_latest_enrichment_by_clip_id(raw.id)
        metadata = build_metadata_for_raw_with_routing(raw, route_decision)
        plan = plan_ragflow_sync_dry_run(raw, route_decision, enrichment, metadata)
        saved = store.save_ragflow_sync_job(
            clip_id=raw.id,
            client_request_id=raw.client_request_id,
            knowledge_base_id=plan.knowledge_base_id,
            ragflow_dataset_id=plan.ragflow_dataset_id,
            ragflow_document_id=plan.ragflow_document_id,
            route_decision_id=plan.route_decision_id,
            enrichment_id=plan.enrichment_id,
            operation=plan.operation,
            status=plan.status,
            dry_run=plan.dry_run,
            reason=plan.reason,
            plan=plan.plan,
            remote_document_changed=plan.remote_document_changed,
        )
        store.save_normalized_metadata(
            clip_id=raw.id,
            client_request_id=raw.client_request_id,
            metadata=with_ragflow_sync_metadata(metadata, saved),
        )
        return saved

    def ragflow_attempt_key(raw: StoredClipRawFields, plan) -> str:
        snapshot = {
            "clip_id": str(raw.id),
            "route_decision_id": plan.route_decision_id,
            "enrichment_id": plan.enrichment_id,
            "ragflow_dataset_id": plan.ragflow_dataset_id,
        }
        return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode("utf-8")).hexdigest()

    def save_sync_job_for_plan(
        raw: StoredClipRawFields,
        plan,
        *,
        status: str,
        dry_run: bool,
        phase: str,
        reason: str | None = None,
        remote_document_changed: bool = False,
        attempt_key: str = "",
        error_code: str = "",
        error_message: str = "",
        plan_override: dict[str, object] | None = None,
        started_at: str = "",
        finished_at: str = "",
    ) -> StoredRagflowSyncJob:
        return store.save_ragflow_sync_job(
            clip_id=raw.id,
            client_request_id=raw.client_request_id,
            knowledge_base_id=plan.knowledge_base_id,
            ragflow_dataset_id=plan.ragflow_dataset_id,
            ragflow_document_id=plan.ragflow_document_id,
            route_decision_id=plan.route_decision_id,
            enrichment_id=plan.enrichment_id,
            operation=plan.operation,
            status=status,
            dry_run=dry_run,
            reason=reason if reason is not None else plan.reason,
            plan=sanitize_plan(plan_override if plan_override is not None else plan.plan),
            remote_document_changed=remote_document_changed,
            attempt_key=attempt_key,
            phase=phase,
            error_code=error_code,
            error_message=str(sanitize_value(error_message)),
            started_at=started_at,
            finished_at=finished_at,
        )

    def persist_sync_metadata(raw: StoredClipRawFields, route_decision: ClipRouteDecision | None, sync_job: StoredRagflowSyncJob) -> None:
        metadata = build_metadata_for_raw_with_routing(raw, route_decision)
        store.save_normalized_metadata(
            clip_id=raw.id,
            client_request_id=raw.client_request_id,
            metadata=with_ragflow_sync_metadata(metadata, sync_job),
        )

    def execute_ragflow_sync_for_raw(raw: StoredClipRawFields) -> tuple[StoredRagflowSyncJob, bool]:
        if not resolved_settings.ragflow.real_sync_enabled:
            raise HTTPException(
                status_code=422,
                detail="real RAGFlow sync is disabled; set PERCLIP_ENABLE_REAL_RAGFLOW_SYNC and PERCLIP_RAGFLOW_SYNC_ALLOW_DATASET_IDS",
            )
        route_decision = knowledge_store.find_latest_route_decision_by_clip_id(raw.id)
        enrichment = store.find_latest_enrichment_by_clip_id(raw.id)
        metadata = build_metadata_for_raw_with_routing(raw, route_decision)
        plan = plan_ragflow_sync_dry_run(raw, route_decision, enrichment, metadata)
        if plan.ragflow_dataset_id and plan.ragflow_dataset_id not in resolved_settings.ragflow.sync_allow_dataset_ids:
            blocked = save_sync_job_for_plan(
                raw,
                plan,
                status="blocked",
                dry_run=False,
                phase="blocked",
                reason="target dataset is not allowlisted for real RAGFlow sync",
                error_code=RAGFLOW_SYNC_ERROR_DATASET_NOT_ALLOWLISTED,
            )
            persist_sync_metadata(raw, route_decision, blocked)
            return blocked, False
        if plan.operation == "reindex_after_move" or (route_decision is not None and route_decision.reindex_status == "required"):
            blocked = save_sync_job_for_plan(
                raw,
                plan,
                status="blocked",
                dry_run=False,
                phase="blocked",
                reason="existing document requires a later reindex stage",
                error_code=RAGFLOW_SYNC_ERROR_REINDEX_REQUIRED,
            )
            persist_sync_metadata(raw, route_decision, blocked)
            raise HTTPException(status_code=409, detail="existing document requires a later reindex stage")
        if plan.status != "planned" or enrichment is None or plan.operation not in {"upload_document", "update_meta_fields"}:
            blocked = save_sync_job_for_plan(
                raw,
                plan,
                status="blocked",
                dry_run=False,
                phase="blocked",
                error_code=RAGFLOW_SYNC_ERROR_PLAN_BLOCKED,
            )
            persist_sync_metadata(raw, route_decision, blocked)
            return blocked, False

        attempt_key = ragflow_attempt_key(raw, plan)
        completed = store.find_completed_ragflow_sync_job_by_attempt_key(attempt_key)
        if completed is not None:
            return completed, True
        if not store.acquire_ragflow_sync_lock(raw.id, now_epoch=int(datetime.now(timezone.utc).timestamp())):
            raise HTTPException(status_code=409, detail="ragflow sync already running")

        started_at = datetime.now(timezone.utc).isoformat()
        running = save_sync_job_for_plan(
            raw,
            plan,
            status="running",
            dry_run=False,
            phase="preparing",
            attempt_key=attempt_key,
            started_at=started_at,
            plan_override={**plan.plan, "dry_run": False},
        )
        persist_sync_metadata(raw, route_decision, running)
        meta_fields = {"summary": enrichment.summary, "tags": enrichment.tags, "language": enrichment.language}
        uploaded_name = f"perclip-{raw.id}.md"
        try:
            document_id = raw.ragflow_document_id
            uploaded_this_attempt = False
            if plan.operation == "upload_document":
                running = store.update_ragflow_sync_job(
                    running.id, status="running", phase="uploading", reason=plan.reason,
                    plan={**plan.plan, "dry_run": False, "uploaded_name": uploaded_name},
                    ragflow_document_id="", remote_document_changed=False,
                )
                document = ragflow_adapter.upload_document(
                    plan.ragflow_dataset_id, uploaded_name, ragflow_document_content(raw, enrichment), meta_fields, dry_run=False,
                )
                document_id = document.document_id
                uploaded_this_attempt = True
                store.update_ragflow_document_id(raw.id, document_id)
                raw = replace(raw, ragflow_document_id=document_id)
            running = store.update_ragflow_sync_job(
                running.id, status="running", phase="updating_meta", reason=plan.reason,
                plan={**plan.plan, "dry_run": False, "uploaded_name": uploaded_name},
                ragflow_document_id=document_id, remote_document_changed=plan.operation == "upload_document",
            )
            ragflow_adapter.update_document_meta(plan.ragflow_dataset_id, document_id, meta_fields, dry_run=False)
            saved = store.update_ragflow_sync_job(
                running.id, status="completed", phase="completed",
                reason="document meta_fields updated in allowlisted RAGFlow dataset",
                plan={**plan.plan, "dry_run": False, "uploaded_name": uploaded_name, "meta_fields_written": True},
                ragflow_document_id=document_id, remote_document_changed=True,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            persist_sync_metadata(raw, route_decision, saved)
            return saved, False
        except RagflowAdapterError as error:
            document_id = raw.ragflow_document_id
            remote_changed = uploaded_this_attempt
            phase = "failed"
            detail = "RAGFlow document metadata update failed" if document_id else "RAGFlow document upload failed"
            failed = store.update_ragflow_sync_job(
                running.id, status="failed", phase=phase,
                reason="document uploaded but meta_fields update failed" if document_id else "document upload failed",
                plan={**plan.plan, "dry_run": False, "uploaded_name": uploaded_name, "meta_fields_written": False},
                ragflow_document_id=document_id, remote_document_changed=remote_changed,
                error_code="ragflow_request_failed", error_message=str(sanitize_value(str(error))),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            persist_sync_metadata(raw, route_decision, failed)
            raise HTTPException(status_code=502 if document_id else 422, detail=detail) from error
        finally:
            store.release_ragflow_sync_lock(raw.id)

    def current_ragflow_plan(raw: StoredClipRawFields):
        route_decision = knowledge_store.find_latest_route_decision_by_clip_id(raw.id)
        enrichment = store.find_latest_enrichment_by_clip_id(raw.id)
        metadata = build_metadata_for_raw_with_routing(raw, route_decision)
        return plan_ragflow_sync_dry_run(raw, route_decision, enrichment, metadata)

    def matching_sync_job(raw: StoredClipRawFields, plan) -> StoredRagflowSyncJob | None:
        latest = store.find_latest_ragflow_sync_job_by_clip_id(raw.id)
        if latest is None:
            return None
        if latest.status == "completed" and latest.attempt_key == ragflow_attempt_key(raw, plan):
            return latest
        if (
            latest.route_decision_id == plan.route_decision_id
            and latest.enrichment_id == plan.enrichment_id
            and latest.ragflow_dataset_id == plan.ragflow_dataset_id
            and latest.operation == plan.operation
        ):
            return latest
        return None

    def blocked_sync_job_is_still_terminal(
        latest: StoredRagflowSyncJob,
        plan,
        allowed_dataset_ids: frozenset[str],
    ) -> bool:
        if latest.status != "blocked":
            return False
        if latest.operation == "reindex_after_move" or latest.error_code == RAGFLOW_SYNC_ERROR_REINDEX_REQUIRED:
            return True
        if plan.status != "planned" or latest.error_code == RAGFLOW_SYNC_ERROR_PLAN_BLOCKED:
            return True
        return plan.ragflow_dataset_id not in allowed_dataset_ids

    def pending_ragflow_sync_candidates(*, limit: int, dry_run: bool) -> list[StoredClipRawFields]:
        candidates: list[StoredClipRawFields] = []
        after_id = 0
        page_size = 100
        while len(candidates) < limit:
            page = store.list_raw_fields_after_clip_id(after_id=after_id, limit=page_size)
            if not page:
                break
            for raw in page:
                after_id = raw.id
                plan = current_ragflow_plan(raw)
                latest = matching_sync_job(raw, plan)
                if latest is not None and latest.status == "completed":
                    continue
                if dry_run and latest is not None and latest.status in {"planned", "blocked"}:
                    continue
                if not dry_run and latest is not None and latest.status == "blocked":
                    if blocked_sync_job_is_still_terminal(
                        latest,
                        plan,
                        resolved_settings.ragflow.sync_allow_dataset_ids,
                    ):
                        continue
                candidates.append(raw)
                if len(candidates) >= limit:
                    break
            if len(page) < page_size:
                break
        return candidates

    def readable_manual_move_reason(target_name: str) -> str:
        return f'manual move: user moved clip to "{target_name}"'

    def move_clip_route_decision(
        *,
        raw: StoredClipRawFields,
        target_knowledge_base_id: str,
    ) -> ClipRouteDecision:
        target = knowledge_store.require_active_knowledge_base(target_knowledge_base_id)
        previous = knowledge_store.find_latest_route_decision_by_clip_id(raw.id)
        previous_knowledge_base_id = previous.knowledge_base_id if previous is not None else ""
        lineage_id = previous.lineage_id if previous is not None and previous.lineage_id else f"clip:{raw.id}"
        return knowledge_store.save_route_decision(
            clip_id=raw.id,
            client_request_id=raw.client_request_id,
            knowledge_base_id=target.id,
            ragflow_dataset_id=target.ragflow_dataset_id,
            decision_type="manual",
            matched_rule_id="",
            matched_rule_ids=[],
            confidence=1.0,
            manual_override=True,
            reason=readable_manual_move_reason(target.name),
            previous_knowledge_base_id=previous_knowledge_base_id,
            reindex_status="required",
            lineage_id=lineage_id,
        )

    def http_error_for_knowledge_base_error(error: KnowledgeBaseError) -> HTTPException:
        if isinstance(error, KnowledgeBaseNotFoundError):
            return HTTPException(status_code=404, detail=str(error))
        if isinstance(error, KnowledgeBaseConflictError):
            return HTTPException(status_code=409, detail=str(error))
        return HTTPException(status_code=422, detail=str(error))

    def body_str(body: dict[str, object], key: str, default: str = "") -> str:
        value = body.get(key, default)
        return str(value).strip() if value is not None else default

    def body_bool(body: dict[str, object], key: str, default: bool = False) -> bool:
        value = body.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return default

    def body_int(body: dict[str, object], key: str, default: int = 100) -> int:
        value = body.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=f"{key} must be an integer") from error

    def require_knowledge_base_for_api(knowledge_base_id: str):
        knowledge_base = knowledge_store.get_knowledge_base(knowledge_base_id)
        if knowledge_base is None:
            raise HTTPException(status_code=404, detail="knowledge base not found")
        return knowledge_base

    @app.get("/health")
    def health() -> dict[str, object]:
        archive_mode = "worker" if resolved_settings.processing_mode == "worker" else (
            "clip_to_ragflow" if archiver else "local"
        )
        return {
            "ok": True,
            "service": "perclip-ingest",
            "archive_mode": archive_mode,
            "processing_mode": resolved_settings.processing_mode,
        }

    @app.get("/api/mobile-clips/verify", dependencies=[Depends(require_token)])
    def verify_mobile_token() -> dict[str, object]:
        archive_mode = "worker" if resolved_settings.processing_mode == "worker" else (
            "clip_to_ragflow" if archiver else "local"
        )
        return {
            "ok": True,
            "service": "perclip-ingest",
            "archive_mode": archive_mode,
            "processing_mode": resolved_settings.processing_mode,
            "auth": "mobile_ingest_token",
        }

    @app.get("/api/app-capabilities", dependencies=[Depends(require_token)])
    def app_capabilities() -> dict[str, object]:
        return {
            "ok": True,
            "api_contract": "perclip.app.v1",
            "service": "perclip-ingest",
            "features": {
                "knowledge_bases": True,
                "routing": True,
                "recall": True,
                "recall_domain": True,
                "mobile_batch_status": True,
                "ingest_v1": True,
                "durable_processing": resolved_settings.processing_mode == "worker",
                "processing_status": True,
                "quality_read_model": True,
                "knowledge_list_v2": True,
                "memory_planet": True,
                "ragflow_capabilities": True,
            },
            "contracts": {
                "knowledge_list": KNOWLEDGE_LIST_CONTRACT_VERSION,
            },
            "knowledge_list_bootstrap": knowledge_list_store.bootstrap_status(),
        }

    @app.get("/api/knowledge-bases", dependencies=[Depends(require_token)])
    def list_knowledge_bases() -> dict[str, object]:
        topics_by_knowledge_base = knowledge_store.top_topics_by_knowledge_base(limit=3)
        return {
            "ok": True,
            "knowledge_bases": [
                {
                    **public_knowledge_base_payload(knowledge_base.to_dict()),
                    "top_topics": [
                        topic.to_dict()
                        for topic in topics_by_knowledge_base.get(knowledge_base.id, [])
                    ],
                }
                for knowledge_base in knowledge_store.list_knowledge_bases()
            ],
        }

    @app.post("/api/knowledge-bases", dependencies=[Depends(require_token)])
    def create_knowledge_base(body: Annotated[dict[str, object], Body()]) -> dict[str, object]:
        try:
            knowledge_base = knowledge_store.create_knowledge_base(
                name=body_str(body, "name"),
                description=body_str(body, "description"),
                icon=body_str(body, "icon"),
                color=body_str(body, "color"),
                is_default=body_bool(body, "is_default"),
                ragflow_dataset_id=body_str(body, "ragflow_dataset_id"),
                ragflow_dataset_name=body_str(body, "ragflow_dataset_name"),
                template_key=body_str(body, "template_key", "general"),
            )
        except KnowledgeBaseError as error:
            raise http_error_for_knowledge_base_error(error) from error

        return {
            "ok": True,
            "knowledge_base": public_knowledge_base_payload(knowledge_base.to_dict()),
        }

    @app.get("/api/knowledge-bases/{knowledge_base_id}", dependencies=[Depends(require_token)])
    def get_knowledge_base(knowledge_base_id: str) -> dict[str, object]:
        knowledge_base = knowledge_store.get_knowledge_base(knowledge_base_id)
        if knowledge_base is None:
            raise HTTPException(status_code=404, detail="knowledge base not found")
        return {
            "ok": True,
            "knowledge_base": public_knowledge_base_payload(knowledge_base.to_dict()),
        }

    @app.get("/api/knowledge-bases/{knowledge_base_id}/clips", dependencies=[Depends(require_token)])
    def list_knowledge_base_clips(
        request: Request, knowledge_base_id: str, cursor: str = "", limit: int = 100
    ) -> dict[str, object]:
        knowledge_base = knowledge_store.get_knowledge_base(knowledge_base_id)
        if knowledge_base is None:
            raise HTTPException(status_code=404, detail="knowledge base not found")
        if "after_id" in request.query_params or not 1 <= limit <= 100:
            raise HTTPException(status_code=422, detail="invalid Knowledge clip pagination")
        after_internal_id = 0
        if cursor:
            resolved_cursor = pipeline_store.resolve_knowledge_read_cursor(
                knowledge_base_id=knowledge_base_id, token=cursor
            )
            if resolved_cursor is None:
                raise HTTPException(status_code=422, detail="invalid Knowledge clip cursor")
            after_internal_id = resolved_cursor
        clip_ids = pipeline_store.list_clip_ids_for_knowledge_base(
            knowledge_base_id=knowledge_base_id,
            after_internal_id=after_internal_id,
            limit=limit + 1,
        )
        page_clip_ids = clip_ids[:limit]
        items = []
        for stored_clip_id in page_clip_ids:
            raw = store.find_raw_fields_by_clip_id(stored_clip_id)
            if raw is not None:
                items.append(quality_resolver.compact(raw))
        next_cursor = None
        if len(clip_ids) > limit and page_clip_ids:
            next_cursor = pipeline_store.create_knowledge_read_cursor(
                knowledge_base_id=knowledge_base_id,
                after_internal_id=page_clip_ids[-1],
            )
        return {
            "ok": True,
            "contract_version": QUALITY_READ_CONTRACT_VERSION,
            "knowledge_base": {"id": knowledge_base.id, "name": knowledge_base.name},
            "items": items,
            "next_cursor": next_cursor,
        }

    def knowledge_scope(ids: list[str]) -> tuple[str, ...]:
        requested = tuple(dict.fromkeys(item.strip() for item in ids if item.strip()))
        if requested:
            missing = [item for item in requested if knowledge_store.get_knowledge_base(item) is None]
            if missing:
                raise HTTPException(status_code=404, detail="knowledge base not found")
            return tuple(sorted(requested))
        return tuple(sorted(item.id for item in knowledge_store.list_knowledge_bases()))

    def knowledge_change_scope(ids: list[str]) -> tuple[str, ...]:
        requested = tuple(dict.fromkeys(item.strip() for item in ids if item.strip()))
        if requested:
            missing = [
                item for item in requested
                if knowledge_store.get_knowledge_base(item, include_deleted=True) is None
            ]
            if missing:
                raise HTTPException(status_code=404, detail="knowledge base not found")
            return tuple(sorted(requested))
        # Empty means the global event stream, including events for a KB that
        # has just been archived or deleted and is no longer in active scope.
        return ()

    def knowledge_v2_filters(
        query: str,
        source: str,
        source_type: str,
        attachment: str,
        captured_after: str,
        captured_before: str,
    ) -> dict[str, str]:
        if attachment not in {"", "with", "without"}:
            raise HTTPException(status_code=422, detail="attachment must be with or without")
        if source_type and source_type.strip() not in {"text", "url", "image", "file", "screen_clip", "audio"}:
            raise HTTPException(status_code=422, detail="unsupported source_type")
        parsed_times: dict[str, datetime] = {}
        normalized_times: dict[str, str] = {}
        for name, value in (("captured_after", captured_after), ("captured_before", captured_before)):
            if not value.strip():
                continue
            try:
                parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError
                parsed_times[name] = parsed.astimezone(timezone.utc)
                normalized_times[name] = (
                    parsed_times[name].isoformat().replace("+00:00", "Z")
                )
            except ValueError as error:
                raise HTTPException(status_code=422, detail=f"{name} must be an ISO-8601 timestamp with timezone") from error
        if parsed_times.get("captured_after") and parsed_times.get("captured_before") and parsed_times["captured_after"] > parsed_times["captured_before"]:
            raise HTTPException(status_code=422, detail="captured_after must not be later than captured_before")
        return {
            "query": query.strip(), "source": source.strip(), "source_type": source_type.strip(),
            "attachment": attachment,
            "captured_after": normalized_times.get("captured_after", ""),
            "captured_before": normalized_times.get("captured_before", ""),
        }

    def knowledge_v2_item(row) -> dict[str, object]:
        knowledge_base_ids = json.loads(str(row["knowledge_base_ids_json"] or "[]"))
        knowledge_base_names = json.loads(str(row["knowledge_base_names_json"] or "[]"))
        source_type_value = str(row["source_type"] or "")
        title = str(row["enrichment_title"] or row["title_hint"] or "")
        if not title and source_type_value in {"file", "image", "audio"}:
            title = str(row["filename"] or "")
        assignment = json.loads(str(row["topic_assignment_json"]))
        has_attachment = source_type_value in {"file", "image", "audio"} or (
            source_type_value == "screen_clip"
            and bool(str(row["filename"] or "") or str(row["mime_type"] or "") not in {"", "text/plain"})
        )
        author_state = str(row["extraction_author_resolution_state"] or "")
        extracted_author = str(row["extraction_author"] or "")
        if author_state == "explicit_unknown":
            source_label = "未明确来源"
        elif author_state == "resolved" and extracted_author.strip():
            source_label = extracted_author
        else:
            source_label = str(row["source_app"] or source_type_value)

        content_state = str(row["extraction_core_content_resolution_state"] or "")
        summary = str(row["enrichment_summary"] or "")
        if content_state == "explicit_unavailable":
            summary = "内容暂不可用"
        return {
            "public_clip_id": str(row["public_clip_id"]),
            "knowledge_base_ids": [str(item) for item in knowledge_base_ids],
            "knowledge_base_id": str(knowledge_base_ids[0]) if knowledge_base_ids else "",
            "knowledge_base_name": str(knowledge_base_names[0]) if knowledge_base_names else "",
            "title": safe_mobile_text(title, limit=160),
            "summary": safe_mobile_text(summary, limit=320),
            "source": safe_mobile_text(source_label, limit=80),
            "source_type": source_type_value,
            "captured_at": safe_mobile_text(row["captured_at"], limit=64),
            "safe_display_url": safe_mobile_url(row["url"]),
            "has_attachment": has_attachment,
            "topic_assignment": assignment,
            "item_revision": int(row["item_revision"] or 0),
            "updated_at": str(row["item_updated_at"] or row["content_updated_at"] or ""),
            "correlation_identity": safe_correlation_identity(row["client_request_id"]),
        }

    @app.get("/api/knowledge/clips", dependencies=[Depends(require_token)])
    def list_knowledge_v2(
        cursor: str = "",
        limit: int = 50,
        knowledge_base_ids: Annotated[list[str] | None, Query(alias="knowledge_base_id")] = None,
        query: str = "",
        source: str = "",
        source_type: str = "",
        attachment: str = "",
        captured_after: str = "",
        captured_before: str = "",
    ) -> dict[str, object]:
        if not 1 <= limit <= 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        scope = knowledge_scope(knowledge_base_ids or [])
        filters = knowledge_v2_filters(query, source, source_type, attachment, captured_after, captured_before)
        after_captured_at = after_public_clip_id = ""
        if cursor:
            try:
                decoded = decode_cursor(cursor, knowledge_list_store.cursor_secret())
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            expected = (scope, *[filters[key] for key in ("query", "source", "source_type", "attachment", "captured_after", "captured_before")])
            actual = (decoded.scope, decoded.query, decoded.source, decoded.source_type, decoded.attachment, decoded.captured_after, decoded.captured_before)
            if actual != expected:
                raise HTTPException(status_code=422, detail="cursor does not match current scope or filters")
            after_captured_at, after_public_clip_id = decoded.captured_at, decoded.public_clip_id
        snapshot = knowledge_list_store.read_list_snapshot(
            scope=scope, **filters, after_captured_at=after_captured_at,
            after_public_clip_id=after_public_clip_id, limit=limit + 1,
        )
        page_rows = snapshot.rows[:limit]
        items = [item for row in page_rows if (item := knowledge_v2_item(row))]
        next_cursor = make_cursor(secret=knowledge_list_store.cursor_secret(), scope=scope, **filters, row=page_rows[-1]) if len(snapshot.rows) > limit and page_rows else ""
        return {
            "ok": True, "contract_version": KNOWLEDGE_LIST_CONTRACT_VERSION,
            "scope": {"knowledge_base_ids": list(scope)},
            "summary": {"total_count": snapshot.total_count, "matching_count": snapshot.matching_count, "revision": snapshot.revision, "generated_at": snapshot.generated_at},
            "items": items, "next_cursor": next_cursor, "has_more": bool(next_cursor),
        }

    @app.get("/api/knowledge/summary", dependencies=[Depends(require_token)])
    def knowledge_summary(
        knowledge_base_ids: Annotated[list[str] | None, Query(alias="knowledge_base_id")] = None,
        query: str = "", source: str = "", source_type: str = "", attachment: str = "", captured_after: str = "", captured_before: str = "",
    ) -> dict[str, object]:
        scope = knowledge_scope(knowledge_base_ids or [])
        filters = knowledge_v2_filters(query, source, source_type, attachment, captured_after, captured_before)
        snapshot = knowledge_list_store.read_summary_snapshot(scope=scope, **filters)
        return {"ok": True, "contract_version": KNOWLEDGE_LIST_CONTRACT_VERSION, "scope": {"knowledge_base_ids": list(scope)}, "summary": {"total_count": snapshot.total_count, "matching_count": snapshot.matching_count, "revision": snapshot.revision, "generated_at": snapshot.generated_at}}

    @app.get("/api/knowledge/changes", dependencies=[Depends(require_token)])
    def knowledge_changes(after_revision: int = 0, limit: int = 100, knowledge_base_ids: Annotated[list[str] | None, Query(alias="knowledge_base_id")] = None) -> dict[str, object]:
        if after_revision < 0 or not 1 <= limit <= 100:
            raise HTTPException(status_code=422, detail="invalid change feed parameters")
        scope = knowledge_change_scope(knowledge_base_ids or [])
        rows = knowledge_list_store.changes(after_revision=after_revision, scope=scope, limit=limit)
        page_rows = rows[:limit]
        current_rows = knowledge_list_store.page(
            scope=scope,
            public_ids=tuple(dict.fromkeys(str(row["public_clip_id"]) for row in page_rows)),
            limit=max(1, len(page_rows)),
        ) if page_rows else []
        current_items = {
            str(row["public_clip_id"]): knowledge_v2_item(row) for row in current_rows
        }
        changes = []
        for row in page_rows:
            public_clip_id = str(row["public_clip_id"])
            item = current_items.get(public_clip_id)
            membership_ids = item["knowledge_base_ids"] if item else json.loads(str(row["membership_ids_json"] or "[]"))
            change = {
                "revision": int(row["revision"]), "public_clip_id": public_clip_id,
                "knowledge_base_id": str(row["knowledge_base_id"]),
                "knowledge_base_ids": membership_ids,
                "operation": "upsert" if item is not None else "remove",
                "source_operation": str(row["operation"]),
                "reason": str(row["reason"]), "changed_at": str(row["changed_at"]),
            }
            if item is not None:
                change["item"] = item
            changes.append(change)
        return {"ok": True, "contract_version": KNOWLEDGE_LIST_CONTRACT_VERSION, "changes": changes, "next_revision": int(page_rows[-1]["revision"]) if page_rows else after_revision, "has_more": len(rows) > limit, "current_revision": knowledge_list_store.latest_revision()}

    @app.post("/api/knowledge/bootstrap", dependencies=[Depends(require_token)])
    def bootstrap_knowledge_changes() -> dict[str, object]:
        return {"ok": True, "contract_version": KNOWLEDGE_LIST_CONTRACT_VERSION, "bootstrap": knowledge_list_store.bootstrap()}

    @app.patch("/api/knowledge-bases/{knowledge_base_id}", dependencies=[Depends(require_token)])
    def update_knowledge_base(
        knowledge_base_id: str,
        body: Annotated[dict[str, object], Body()],
    ) -> dict[str, object]:
        try:
            knowledge_base = knowledge_store.update_knowledge_base(
                knowledge_base_id,
                name=body_str(body, "name") if "name" in body else None,
                description=body_str(body, "description") if "description" in body else None,
                icon=body_str(body, "icon") if "icon" in body else None,
                color=body_str(body, "color") if "color" in body else None,
                ragflow_dataset_id=body_str(body, "ragflow_dataset_id") if "ragflow_dataset_id" in body else None,
                ragflow_dataset_name=body_str(body, "ragflow_dataset_name") if "ragflow_dataset_name" in body else None,
            )
        except KnowledgeBaseError as error:
            raise http_error_for_knowledge_base_error(error) from error
        return {
            "ok": True,
            "knowledge_base": public_knowledge_base_payload(knowledge_base.to_dict()),
        }

    @app.post("/api/knowledge-bases/{knowledge_base_id}/set-default", dependencies=[Depends(require_token)])
    def set_default_knowledge_base(knowledge_base_id: str) -> dict[str, object]:
        try:
            knowledge_base = knowledge_store.set_default_knowledge_base(knowledge_base_id)
        except KnowledgeBaseError as error:
            raise http_error_for_knowledge_base_error(error) from error
        return {
            "ok": True,
            "knowledge_base": public_knowledge_base_payload(knowledge_base.to_dict()),
        }

    @app.post("/api/knowledge-bases/{knowledge_base_id}/archive", dependencies=[Depends(require_token)])
    def archive_knowledge_base(knowledge_base_id: str) -> dict[str, object]:
        try:
            knowledge_base = knowledge_store.archive_knowledge_base(knowledge_base_id)
        except KnowledgeBaseError as error:
            raise http_error_for_knowledge_base_error(error) from error
        return {
            "ok": True,
            "knowledge_base": public_knowledge_base_payload(knowledge_base.to_dict()),
        }

    @app.delete("/api/knowledge-bases/{knowledge_base_id}", dependencies=[Depends(require_token)])
    def delete_knowledge_base(knowledge_base_id: str) -> dict[str, object]:
        try:
            knowledge_base = knowledge_store.delete_knowledge_base(knowledge_base_id)
        except KnowledgeBaseError as error:
            raise http_error_for_knowledge_base_error(error) from error
        return {
            "ok": True,
            "knowledge_base": public_knowledge_base_payload(knowledge_base.to_dict()),
            "ragflow_dataset_deleted": False,
        }

    @app.post("/api/knowledge-bases/{knowledge_base_id}/ragflow/dry-run-create", dependencies=[Depends(require_token)])
    def dry_run_create_ragflow_dataset(
        knowledge_base_id: str,
        body: Annotated[dict[str, object] | None, Body()] = None,
    ) -> dict[str, object]:
        knowledge_base = require_knowledge_base_for_api(knowledge_base_id)
        payload = body or {}
        try:
            plan = ragflow_adapter.create_dataset(
                name=body_str(payload, "name", knowledge_base.name) or knowledge_base.name,
                description=body_str(payload, "description", knowledge_base.description),
                template_key=body_str(payload, "template_key", knowledge_base.template_key) or knowledge_base.template_key,
                dry_run=True,
            )
        except RagflowAdapterError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "ok": True,
            "knowledge_base_id": knowledge_base.id,
            "ragflow": plan,
        }

    @app.post("/api/knowledge-bases/{knowledge_base_id}/ragflow/dry-run-update", dependencies=[Depends(require_token)])
    def dry_run_update_ragflow_dataset(
        knowledge_base_id: str,
        body: Annotated[dict[str, object] | None, Body()] = None,
    ) -> dict[str, object]:
        knowledge_base = require_knowledge_base_for_api(knowledge_base_id)
        payload = body or {}
        dataset_id = body_str(payload, "dataset_id", knowledge_base.ragflow_dataset_id)
        if not dataset_id:
            raise HTTPException(status_code=422, detail="RAGFlow dataset mapping is missing")
        try:
            plan = ragflow_adapter.update_dataset(
                dataset_id=dataset_id,
                name=body_str(payload, "name") if "name" in payload else knowledge_base.name,
                description=body_str(payload, "description") if "description" in payload else knowledge_base.description,
                dry_run=True,
            )
        except RagflowAdapterError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "ok": True,
            "knowledge_base_id": knowledge_base.id,
            "ragflow": plan,
        }

    @app.post("/api/knowledge-bases/{knowledge_base_id}/ragflow/dry-run-delete", dependencies=[Depends(require_token)])
    def dry_run_delete_ragflow_dataset(
        knowledge_base_id: str,
        body: Annotated[dict[str, object] | None, Body()] = None,
    ) -> dict[str, object]:
        knowledge_base = require_knowledge_base_for_api(knowledge_base_id)
        payload = body or {}
        dataset_id = body_str(payload, "dataset_id", knowledge_base.ragflow_dataset_id)
        try:
            plan = ragflow_adapter.delete_dataset(
                dataset_id=dataset_id,
                dry_run=True,
                confirm_name=body_str(payload, "confirm_name"),
            )
        except RagflowAdapterError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "ok": True,
            "knowledge_base_id": knowledge_base.id,
            "affected_mapping": {
                "ragflow_dataset_id": knowledge_base.ragflow_dataset_id,
                "ragflow_dataset_name": knowledge_base.ragflow_dataset_name,
            },
            "ragflow": plan,
        }

    @app.get("/api/ragflow/capabilities", dependencies=[Depends(require_token)])
    def ragflow_capabilities() -> dict[str, object]:
        return {
            "ok": True,
            "ragflow": ragflow_adapter.capability_report().to_dict(),
        }

    @app.get("/api/ragflow/probe", dependencies=[Depends(require_token)])
    def ragflow_probe() -> dict[str, object]:
        if ragflow_probe_override is not None:
            return ragflow_probe_override(resolved_settings.ragflow)
        return probe_ragflow(resolved_settings.ragflow).to_dict()

    @app.get("/api/routing-rules", dependencies=[Depends(require_token)])
    def list_routing_rules() -> dict[str, object]:
        return {"ok": True, "routing_rules": [rule.to_dict() for rule in knowledge_store.list_routing_rules()]}

    @app.post("/api/routing-rules", dependencies=[Depends(require_token)])
    def create_routing_rule(body: Annotated[dict[str, object], Body()]) -> dict[str, object]:
        try:
            rule = knowledge_store.create_routing_rule(
                name=body_str(body, "name"),
                enabled=body_bool(body, "enabled", True),
                rule_type=body_str(body, "rule_type"),
                pattern=body_str(body, "pattern"),
                target_knowledge_base_id=body_str(body, "target_knowledge_base_id"),
                priority=body_int(body, "priority", 100),
            )
        except KnowledgeBaseError as error:
            raise http_error_for_knowledge_base_error(error) from error
        return {"ok": True, "routing_rule": rule.to_dict()}

    @app.get("/api/routing-rules/{rule_id}", dependencies=[Depends(require_token)])
    def get_routing_rule(rule_id: str) -> dict[str, object]:
        rule = knowledge_store.get_routing_rule(rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="routing rule not found")
        return {"ok": True, "routing_rule": rule.to_dict()}

    @app.patch("/api/routing-rules/{rule_id}", dependencies=[Depends(require_token)])
    def update_routing_rule(
        rule_id: str,
        body: Annotated[dict[str, object], Body()],
    ) -> dict[str, object]:
        try:
            rule = knowledge_store.update_routing_rule(
                rule_id,
                name=body_str(body, "name") if "name" in body else None,
                enabled=body_bool(body, "enabled") if "enabled" in body else None,
                rule_type=body_str(body, "rule_type") if "rule_type" in body else None,
                pattern=body_str(body, "pattern") if "pattern" in body else None,
                target_knowledge_base_id=body_str(body, "target_knowledge_base_id")
                if "target_knowledge_base_id" in body
                else None,
                priority=body_int(body, "priority") if "priority" in body else None,
            )
        except KnowledgeBaseError as error:
            raise http_error_for_knowledge_base_error(error) from error
        return {"ok": True, "routing_rule": rule.to_dict()}

    @app.delete("/api/routing-rules/{rule_id}", dependencies=[Depends(require_token)])
    def delete_routing_rule(rule_id: str) -> dict[str, object]:
        try:
            rule = knowledge_store.delete_routing_rule(rule_id)
        except KnowledgeBaseError as error:
            raise http_error_for_knowledge_base_error(error) from error
        return {"ok": True, "routing_rule": rule.to_dict()}

    @app.post("/api/routing/preview", dependencies=[Depends(require_token)])
    def routing_preview(body: Annotated[dict[str, object], Body()]) -> dict[str, object]:
        try:
            preview = preview_route(
                knowledge_store,
                RoutingPreviewInput(
                    source_type=body_str(body, "source_type"),
                    title_hint=body_str(body, "title_hint"),
                    note=body_str(body, "note"),
                    text=body_str(body, "text"),
                    url=body_str(body, "url"),
                    mime_type=body_str(body, "mime_type"),
                    filename=body_str(body, "filename"),
                    device_name=body_str(body, "device_name"),
                    source_app=body_str(body, "source_app"),
                    client_request_id=body_str(body, "client_request_id"),
                    target_knowledge_base_id=body_str(body, "target_knowledge_base_id"),
                    routing_mode=body_str(body, "routing_mode"),
                ),
            )
        except KnowledgeBaseError as error:
            raise http_error_for_knowledge_base_error(error) from error
        except RoutingPreviewError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"ok": True, "route_preview": preview.to_dict()}

    @app.post("/api/clips/{clip_id}/move", dependencies=[Depends(require_token)])
    def move_clip(
        clip_id: str,
        body: Annotated[dict[str, object], Body()],
    ) -> dict[str, object]:
        raw = find_raw_clip_for_path(clip_id, ambiguous_detail="multiple clip parts require batch move")

        target_knowledge_base_id = body_str(body, "target_knowledge_base_id")
        try:
            route_decision = move_clip_route_decision(
                raw=raw,
                target_knowledge_base_id=target_knowledge_base_id,
            )
        except KnowledgeBaseError as error:
            raise http_error_for_knowledge_base_error(error) from error

        existing_metadata = store.find_normalized_metadata_by_clip_id(raw.id)
        metadata = existing_metadata.metadata if existing_metadata is not None else build_metadata_from_raw_fields(raw)
        try:
            store.save_normalized_metadata(
                clip_id=raw.id,
                client_request_id=raw.client_request_id,
                metadata=with_routing_metadata(metadata, route_decision),
            )
        except Exception as error:
            raise HTTPException(status_code=500, detail="failed to update clip metadata routing") from error

        pipeline_store.move_knowledge_base_association(
            clip_id=raw.id,
            previous_knowledge_base_id=route_decision.previous_knowledge_base_id,
            knowledge_base_id=route_decision.knowledge_base_id,
            route_decision_id=route_decision.id,
        )
        schedule_index_for_associations(raw)

        return {
            "ok": True,
            "route_decision": route_decision.to_dict(),
            "reindex_required": True,
            "remote_document_changed": False,
        }

    def clip_knowledge_base_payload(raw: StoredClipRawFields) -> list[dict[str, object]]:
        payload: list[dict[str, object]] = []
        for association in pipeline_store.list_knowledge_base_associations(clip_id=raw.id):
            knowledge_base = knowledge_store.get_knowledge_base(
                str(association["knowledge_base_id"]), include_deleted=True
            )
            payload.append(
                {
                    "knowledge_base_id": str(association["knowledge_base_id"]),
                    "name": knowledge_base.name if knowledge_base else "",
                    "association_type": str(association["association_type"]),
                    "available": bool(
                        knowledge_base and not knowledge_base.deleted_at and not knowledge_base.is_archived
                    ),
                    "created_at": str(association["created_at"]),
                }
            )
        return payload

    def schedule_index_for_associations(raw: StoredClipRawFields) -> None:
        clean_asset = pipeline_store.latest_asset(clip_id=raw.id, role="clean_markdown")
        if clean_asset is None:
            return
        saved_metadata = store.find_normalized_metadata_by_clip_id(raw.id)
        if saved_metadata is not None:
            next_metadata = dict(saved_metadata.metadata)
            processing = dict(next_metadata.get("processing", {})) if isinstance(next_metadata.get("processing"), dict) else {}
            active = processing.get("active_projection")
            if isinstance(active, dict) and bool(active.get("index_eligible", False)):
                processing["index_pending_projection_id"] = str(active.get("source_asset_id") or "")
                next_metadata["processing"] = processing
                store.save_normalized_metadata(
                    clip_id=raw.id,
                    client_request_id=raw.client_request_id,
                    metadata=next_metadata,
                )
        fingerprint = pipeline_store.association_fingerprint(
            clip_id=raw.id,
            content_hash=str(clean_asset["content_hash"]),
        )
        fingerprint = hashlib.sha256(
            (
                fingerprint
                + "\0"
                + json.dumps(
                    topic_store.active_index_provenance(raw.id),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ).encode("utf-8")
        ).hexdigest()
        pipeline_store.enqueue(
            clip_id=raw.id,
            stage="index",
            engine="ragflow",
            engine_version="v1",
            input_hash=fingerprint,
        )

    def schedule_topic_reclassification_all() -> int:
        scheduled = 0
        after_id = 0
        taxonomy_version = topic_store.taxonomy_version()
        while True:
            rows = store.list_raw_fields_after_clip_id(after_id=after_id, limit=500)
            if not rows:
                break
            for raw in rows:
                after_id = raw.id
                clean_asset = pipeline_store.latest_asset(
                    clip_id=raw.id, role="clean_markdown"
                )
                if clean_asset is None:
                    continue
                input_hash = hashlib.sha256(
                    "\0".join(
                        (
                            str(raw.id),
                            str(clean_asset["id"]),
                            taxonomy_version,
                            "topic-reclassification-v1",
                        )
                    ).encode("utf-8")
                ).hexdigest()
                pipeline_store.enqueue(
                    clip_id=raw.id,
                    stage="classify_topic",
                    engine="perclip-fixed-topics",
                    engine_version="v1",
                    input_hash=input_hash,
                )
                scheduled += 1
        return scheduled

    @app.get("/api/clips/{clip_id}/knowledge-bases", dependencies=[Depends(require_token)])
    def list_clip_knowledge_bases(clip_id: str) -> dict[str, object]:
        raw = find_raw_clip_for_path(clip_id, ambiguous_detail="multiple clip parts require an exact clip id")
        return {"ok": True, "clip_id": str(raw.id), "knowledge_bases": clip_knowledge_base_payload(raw)}

    @app.get("/api/clips/{clip_id}/processing", dependencies=[Depends(require_token)])
    def get_clip_processing(clip_id: str) -> dict[str, object]:
        raw = find_raw_clip_for_path(clip_id, ambiguous_detail="multiple clip parts require an exact clip id")
        summary = pipeline_store.processing_summary(clip_id=raw.id)
        metadata = store.find_normalized_metadata_by_clip_id(raw.id)
        processing = metadata.metadata.get("processing", {}) if metadata else {}
        if isinstance(processing, dict):
            summary["projection_state"] = {
                "active_projection": processing.get("active_projection", {}),
                "latest_successful_projection": processing.get("latest_successful_projection", {}),
                "latest_attempted_projection": processing.get("latest_attempted_projection", {}),
            }
            summary["index_state"] = {
                "active_index": processing.get("active_index", {}),
                "latest_index_attempt": processing.get("latest_index_attempt", {}),
            }
        summary["recall_enrichment_resolution"] = store.recall_enrichment_resolution(raw.id)
        return {"ok": True, "clip_id": str(raw.id), **summary}

    @app.get("/api/clips/{clip_id}/quality", dependencies=[Depends(require_token)])
    def get_clip_quality(clip_id: str) -> dict[str, object]:
        raw = find_raw_clip_for_path(
            clip_id, ambiguous_detail="multiple clip parts require an exact clip id"
        )
        return {"ok": True, "quality_read": quality_resolver.build(raw)}

    @app.get("/api/topics", dependencies=[Depends(require_token)])
    def get_topics() -> dict[str, object]:
        return {"ok": True, "registry": topic_store.registry_payload()}

    @app.patch("/api/topics/{topic_id}", dependencies=[Depends(require_token)])
    def patch_topic(
        topic_id: str,
        body: Annotated[dict[str, object], Body()],
    ) -> dict[str, object]:
        try:
            registry = topic_store.update_topic(topic_id, body)
        except ValueError as error:
            detail = str(error)
            status_code = 404 if detail == "unknown_topic_id" else 422
            raise HTTPException(status_code=status_code, detail=detail) from error
        classification_change = bool(set(body) - {"display_name"})
        disabling = body.get("enabled") is False
        # Disabling is prospective. Existing active assignments remain
        # visible with topic_disabled=true instead of being silently replaced.
        scheduled = (
            schedule_topic_reclassification_all()
            if classification_change and not disabling
            else 0
        )
        return {
            "ok": True,
            "registry": registry,
            "reclassification_scheduled": scheduled,
        }

    @app.post("/api/topics/{topic_id}/aliases", dependencies=[Depends(require_token)])
    def add_topic_alias(
        topic_id: str,
        body: Annotated[dict[str, object], Body()],
    ) -> dict[str, object]:
        if set(body) - {"alias", "alias_type"} or not isinstance(body.get("alias"), str):
            raise HTTPException(status_code=422, detail="alias is required")
        alias_type = str(body.get("alias_type") or "exact_alias")
        try:
            alias_id = topic_store.add_alias(
                topic_id=topic_id,
                alias=str(body["alias"]),
                alias_type=alias_type,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        scheduled = schedule_topic_reclassification_all()
        return {
            "ok": True,
            "alias_id": alias_id,
            "registry": topic_store.registry_payload(),
            "reclassification_scheduled": scheduled,
        }

    @app.delete(
        "/api/topics/{topic_id}/aliases/{alias_id}",
        dependencies=[Depends(require_token)],
    )
    def delete_topic_alias(topic_id: str, alias_id: int) -> dict[str, object]:
        if not topic_store.delete_alias(topic_id=topic_id, alias_id=alias_id):
            raise HTTPException(status_code=404, detail="topic alias not found")
        return {
            "ok": True,
            "registry": topic_store.registry_payload(),
            "reclassification_scheduled": schedule_topic_reclassification_all(),
        }

    @app.post("/api/topic-rules", dependencies=[Depends(require_token)])
    def add_topic_rule(
        body: Annotated[dict[str, object], Body()],
    ) -> dict[str, object]:
        if set(body) != {"rule", "topic_id"} or not all(
            isinstance(body.get(key), str) for key in ("rule", "topic_id")
        ):
            raise HTTPException(status_code=422, detail="rule and topic_id are required")
        try:
            rule_id = topic_store.add_user_rule(
                rule=str(body["rule"]), topic_id=str(body["topic_id"])
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "ok": True,
            "rule_id": rule_id,
            "taxonomy_version": topic_store.taxonomy_version(),
            "reclassification_scheduled": schedule_topic_reclassification_all(),
        }

    @app.delete("/api/topic-rules/{rule_id}", dependencies=[Depends(require_token)])
    def delete_topic_rule(rule_id: int) -> dict[str, object]:
        if not topic_store.delete_user_rule(rule_id):
            raise HTTPException(status_code=404, detail="topic rule not found")
        return {
            "ok": True,
            "taxonomy_version": topic_store.taxonomy_version(),
            "reclassification_scheduled": schedule_topic_reclassification_all(),
        }

    @app.put("/api/clips/{clip_id}/topic-assignment", dependencies=[Depends(require_token)])
    def set_clip_topic_assignment(
        clip_id: str,
        body: Annotated[dict[str, object], Body()],
    ) -> dict[str, object]:
        if set(body) != {"topic_id"} or not isinstance(body.get("topic_id"), str):
            raise HTTPException(status_code=422, detail="topic_id is required")
        topic_id = str(body["topic_id"])
        if not topic_store.topic_exists_and_enabled(topic_id):
            raise HTTPException(status_code=422, detail="unknown or disabled topic_id")
        raw = find_raw_clip_for_path(
            clip_id, ambiguous_detail="multiple clip parts require an exact clip id"
        )
        quality = quality_resolver.build(raw)
        generation = str(dict(quality.get("processing", {})).get("active_generation") or "")
        if not generation:
            raise HTTPException(status_code=409, detail="clip has no active content generation")
        assignment = topic_store.set_manual_override(
            clip_id=raw.id, generation=generation, topic_id=topic_id
        )
        schedule_index_for_associations(raw)
        return {"ok": True, "clip_id": pipeline_store.public_id_for(raw.id), "topic_assignment": assignment}

    @app.delete(
        "/api/clips/{clip_id}/topic-assignment",
        dependencies=[Depends(require_token)],
    )
    def clear_clip_topic_assignment(clip_id: str) -> dict[str, object]:
        raw = find_raw_clip_for_path(
            clip_id, ambiguous_detail="multiple clip parts require an exact clip id"
        )
        try:
            assignment = topic_store.clear_manual_override(raw.id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        schedule_index_for_associations(raw)
        return {
            "ok": True,
            "clip_id": pipeline_store.public_id_for(raw.id),
            "topic_assignment": assignment,
        }

    @app.post("/api/clips/{clip_id}/knowledge-bases/{knowledge_base_id}", dependencies=[Depends(require_token)])
    def associate_clip_knowledge_base(clip_id: str, knowledge_base_id: str) -> dict[str, object]:
        raw = find_raw_clip_for_path(clip_id, ambiguous_detail="multiple clip parts require an exact clip id")
        try:
            knowledge_store.require_active_knowledge_base(knowledge_base_id)
        except KnowledgeBaseError as error:
            raise http_error_for_knowledge_base_error(error) from error
        pipeline_store.associate_knowledge_base(
            clip_id=raw.id,
            knowledge_base_id=knowledge_base_id,
            association_type="manual",
        )
        schedule_index_for_associations(raw)
        return {"ok": True, "clip_id": str(raw.id), "knowledge_bases": clip_knowledge_base_payload(raw)}

    @app.delete("/api/clips/{clip_id}/knowledge-bases/{knowledge_base_id}", dependencies=[Depends(require_token)])
    def detach_clip_knowledge_base(clip_id: str, knowledge_base_id: str) -> dict[str, object]:
        raw = find_raw_clip_for_path(clip_id, ambiguous_detail="multiple clip parts require an exact clip id")
        associations = pipeline_store.list_knowledge_base_associations(clip_id=raw.id)
        if len(associations) <= 1:
            raise HTTPException(status_code=409, detail="a clip must retain at least one knowledge base")
        primary = knowledge_store.find_latest_route_decision_by_clip_id(raw.id)
        if primary is not None and primary.knowledge_base_id == knowledge_base_id:
            raise HTTPException(status_code=409, detail="move the primary knowledge base before detaching it")
        if not pipeline_store.remove_knowledge_base_association(
            clip_id=raw.id, knowledge_base_id=knowledge_base_id
        ):
            raise HTTPException(status_code=404, detail="clip knowledge base association not found")
        schedule_index_for_associations(raw)
        return {"ok": True, "clip_id": str(raw.id), "knowledge_bases": clip_knowledge_base_payload(raw)}

    @app.post("/api/clips/{clip_id}/enrich", dependencies=[Depends(require_token)])
    def enrich_clip(clip_id: str) -> dict[str, object]:
        raw = find_raw_clip_for_path(clip_id, ambiguous_detail="multiple clip parts require batch enrichment")
        saved = run_deterministic_enrichment_for_raw(raw)
        return {"ok": True, "enrichment": enrichment_response_for(saved)}

    @app.post("/api/enrichment/run-pending", dependencies=[Depends(require_token)])
    def run_pending_enrichment(body: Annotated[dict[str, object] | None, Body()] = None) -> dict[str, object]:
        limit = validate_limit(body, default=20)
        items: list[dict[str, object]] = []
        processed = 0
        failed = 0
        for raw in store.list_clips_without_enrichment(limit=limit):
            try:
                saved = run_deterministic_enrichment_for_raw(raw)
                processed += 1
                items.append(
                    {
                        "clip_id": str(raw.id),
                        "client_request_id": raw.client_request_id,
                        "status": saved.status,
                    }
                )
            except Exception as error:
                failed += 1
                items.append(
                    {
                        "clip_id": str(raw.id),
                        "client_request_id": raw.client_request_id,
                        "status": "failed",
                        "error": str(error),
                    }
                )
        return {
            "ok": failed == 0,
            "processed": processed,
            "skipped": 0,
            "failed": failed,
            "items": items,
        }

    @app.get("/api/clips/{clip_id}/enrichment", dependencies=[Depends(require_token)])
    def get_clip_enrichment(clip_id: str) -> dict[str, object]:
        raw = find_raw_clip_for_path(clip_id, ambiguous_detail="multiple clip parts require batch enrichment")
        resolved = quality_resolver.resolve(raw)
        processing = resolved.processing
        enrichment = resolved.enrichment
        if resolved.resolution_mode == "invalid_active_pointer":
            raise HTTPException(status_code=409, detail="active enrichment reference is missing")
        if enrichment is None:
            raise HTTPException(status_code=404, detail="enrichment not found")
        return {
            "ok": True,
            "enrichment": enrichment_response_for(enrichment),
            "processing": {
                "latest_attempted_projection": processing.get("latest_attempted_projection", {}),
                "latest_successful_projection": processing.get("latest_successful_projection", {}),
                "active_projection": processing.get("active_projection", {}),
                "active_index": processing.get("active_index", {}),
                "latest_index_attempt": processing.get("latest_index_attempt", {}),
                "recall_enrichment_resolution": {
                    "status": resolved.resolution_mode,
                    "active_enrichment_id": resolved.active_enrichment_id,
                    "selected_enrichment_id": enrichment.id,
                },
                "safe_error_code": processing.get("safe_error_code", ""),
            } if isinstance(processing, dict) else {},
        }

    @app.post("/api/clips/{clip_id}/ragflow-sync/dry-run", dependencies=[Depends(require_token)])
    def dry_run_clip_ragflow_sync(clip_id: str) -> dict[str, object]:
        raw = find_raw_clip_for_path(clip_id, ambiguous_detail="multiple clip parts require batch sync")
        sync_job = save_ragflow_sync_plan_for_raw(raw)
        return {"ok": True, "sync": ragflow_sync_response_for(sync_job)}

    @app.post("/api/clips/{clip_id}/ragflow-sync/execute", dependencies=[Depends(require_token)])
    def execute_clip_ragflow_sync(clip_id: str) -> dict[str, object]:
        raw = find_raw_clip_for_path(clip_id, ambiguous_detail="multiple clip parts require batch sync")
        sync_job, idempotent_replay = execute_ragflow_sync_for_raw(raw)
        return {"ok": True, "sync": ragflow_sync_response_for(sync_job), "idempotent_replay": idempotent_replay}

    @app.get("/api/clips/{clip_id}/ragflow-sync", dependencies=[Depends(require_token)])
    def get_clip_ragflow_sync(clip_id: str) -> dict[str, object]:
        raw = find_raw_clip_for_path(clip_id, ambiguous_detail="multiple clip parts require batch sync")
        sync_job = store.find_latest_ragflow_sync_job_by_clip_id(raw.id)
        if sync_job is None:
            raise HTTPException(status_code=404, detail="ragflow sync not found")
        return {"ok": True, "sync": ragflow_sync_response_for(sync_job)}

    @app.post("/api/ragflow-sync/run-pending-dry-run", dependencies=[Depends(require_token)])
    def run_pending_ragflow_sync_dry_run(
        body: Annotated[dict[str, object] | None, Body()] = None,
    ) -> dict[str, object]:
        limit = validate_limit(body, default=20)
        items: list[dict[str, object]] = []
        processed = 0
        planned = 0
        blocked = 0
        failed = 0
        for raw in pending_ragflow_sync_candidates(limit=limit, dry_run=True):
            try:
                sync_job = save_ragflow_sync_plan_for_raw(raw)
                processed += 1
                if sync_job.status == "planned":
                    planned += 1
                elif sync_job.status == "blocked":
                    blocked += 1
                items.append(ragflow_sync_response_for(sync_job))
            except Exception as error:
                failed += 1
                items.append(
                    {
                        "clip_id": str(raw.id),
                        "client_request_id": raw.client_request_id,
                        "operation": "failed",
                        "status": "failed",
                        "dry_run": True,
                        "remote_document_changed": False,
                        "reason": str(error),
                        "plan": {},
                    }
                )
        return {
            "ok": failed == 0,
            "processed": processed,
            "planned": planned,
            "blocked": blocked,
            "failed": failed,
            "items": items,
        }

    @app.post("/api/ragflow-sync/run-pending", dependencies=[Depends(require_token)])
    def run_pending_ragflow_sync(
        body: Annotated[dict[str, object] | None, Body()] = None,
    ) -> dict[str, object]:
        if not resolved_settings.ragflow.real_sync_enabled:
            raise HTTPException(
                status_code=422,
                detail="real RAGFlow sync is disabled; set PERCLIP_ENABLE_REAL_RAGFLOW_SYNC and PERCLIP_RAGFLOW_SYNC_ALLOW_DATASET_IDS",
            )
        payload = body or {}
        limit = body_int(payload, "limit", 10)
        if limit < 1 or limit > 50:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 50")
        counts = {"completed": 0, "failed": 0, "blocked": 0, "skipped": 0}
        items: list[dict[str, object]] = []
        for raw in pending_ragflow_sync_candidates(limit=limit, dry_run=False):
            try:
                sync_job, idempotent_replay = execute_ragflow_sync_for_raw(raw)
                if idempotent_replay:
                    counts["skipped"] += 1
                elif sync_job.status in counts:
                    counts[sync_job.status] += 1
                else:
                    counts["failed"] += 1
                item = ragflow_sync_response_for(sync_job)
                item["idempotent_replay"] = idempotent_replay
                items.append(item)
            except HTTPException as error:
                if error.status_code == 409:
                    counts["blocked"] += 1
                    items.append({"clip_id": str(raw.id), "client_request_id": raw.client_request_id, "status": "blocked", "reason": str(error.detail)})
                else:
                    counts["failed"] += 1
                    items.append({"clip_id": str(raw.id), "client_request_id": raw.client_request_id, "status": "failed", "reason": str(error.detail)})
            except Exception:
                counts["failed"] += 1
                items.append({"clip_id": str(raw.id), "client_request_id": raw.client_request_id, "status": "failed", "reason": "ragflow sync failed"})
        return {"ok": True, "processed": len(items), **counts, "items": items}

    def recall_window(days: int) -> dict[str, object]:
        start = recall_since(days); end = recall_range_end()
        return {"days": days, "start": start, "end": end}

    def resolve_recall_knowledge_base_id(value: str) -> str:
        knowledge_base_id = value.strip()
        if not knowledge_base_id:
            return ""
        knowledge_base = knowledge_store.get_knowledge_base(knowledge_base_id)
        if knowledge_base is None or knowledge_base.deleted_at:
            raise HTTPException(status_code=404, detail="knowledge base not found")
        if knowledge_base.is_archived:
            raise HTTPException(status_code=409, detail="knowledge base is archived")
        return knowledge_base_id

    def recall_context_for_query(
        days: int,
        *,
        start: str = "",
        end: str = "",
        timezone_name: str = "",
        knowledge_base_id: str = "",
    ) -> RecallContext:
        resolved_knowledge_base_id = resolve_recall_knowledge_base_id(knowledge_base_id)
        if not start and not end and not timezone_name:
            return recall_context_for(days, knowledge_base_id=resolved_knowledge_base_id)
        if not start or not end or not timezone_name:
            raise HTTPException(status_code=422, detail="start, end, and timezone must be provided together")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
            raise HTTPException(status_code=422, detail="start and end must use YYYY-MM-DD")
        try:
            start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
            zone = ZoneInfo(timezone_name)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise HTTPException(status_code=422, detail="invalid custom date range or timezone") from error
        if end_date < start_date:
            raise HTTPException(status_code=422, detail="end must not be before start")
        effective_days = validate_domain_days((end_date - start_date).days + 1)
        if days != effective_days:
            raise HTTPException(status_code=422, detail="days must match the custom date range")
        start_at = datetime.combine(start_date, datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
        end_at = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
        return recall_context_for_range(
            effective_days,
            start=start_at,
            end=end_at,
            knowledge_base_id=resolved_knowledge_base_id,
        )

    def session_item_payload(item) -> dict[str, object]:
        return {"id": item.id, "item_id": item.id, "clip_id": pipeline_store.public_id_for(int(item.clip_id)), "client_request_id": item.client_request_id, "topic_id": item.topic_id, "topic_ids": [item.topic_id] if item.topic_id else [], "position": item.position, "state": item.state, "status": item.state, "title": item.title, "cue": item.cue, "prompt": item.cue, "reveal_text": item.reveal_text, "summary": item.summary, "tags": item.tags, "source_type": item.source_type, "source_label": item.source_label, "knowledge_base_name": item.knowledge_base_name, "captured_at": item.captured_at, "score": item.score, "recall_count_before": item.recall_count_before}

    def topic_item_payload(candidate, recalled_in_window: bool) -> dict[str, object]:
        return {**candidate_payload(candidate), "recall_count": candidate.recall_count, "recalled_in_window": recalled_in_window, "score": candidate.score}

    def mobile_recall_response(payload: dict[str, object]) -> dict[str, object]:
        audit_quality_payload(payload)
        return payload

    def session_payload(session) -> dict[str, object]:
        return {"id": session.id, "kind": session.kind, "topic_id": session.topic_id, "status": session.status, "days": session.days, "window": {"days": session.days, "start": session.window_start, "end": session.window_end}, "window_start": session.window_start, "window_end": session.window_end, "snapshot_key": session.snapshot_key, "total_items": session.total_items, "current_position": session.current_position, "created_at": session.created_at, "updated_at": session.updated_at, "completed_at": session.completed_at}

    def session_response(session) -> dict[str, object]:
        items = [session_item_payload(item) for item in store.list_recall_items(session.id)]
        current = next((item for item in items if item["state"] == "pending"), None)
        return mobile_recall_response({"ok": True, "session": session_payload(session), "items": items, "current_item": current, "progress": {"completed": sum(item["state"] != "pending" for item in items), "total": len(items), "current_position": session.current_position}})

    @app.get("/api/recall/domain", dependencies=[Depends(require_token)])
    def recall_domain(
        days: int | None = None,
        topic_limit: int = 12,
        memory_limit: int = 80,
        topic_id: str = "",
        include_memories: bool = True,
        start: str = "",
        end: str = "",
        timezone_name: Annotated[str, Query(alias="timezone")] = "",
        knowledge_base_id: str = "",
    ) -> dict[str, object]:
        if not 1 <= topic_limit <= 30: raise HTTPException(status_code=422, detail="topic_limit must be between 1 and 30")
        if not 1 <= memory_limit <= 200: raise HTTPException(status_code=422, detail="memory_limit must be between 1 and 200")
        prefs = store.recall_preferences()
        effective_days = days if days is not None else int(prefs["default_days"])
        resolved_knowledge_base_id = resolve_recall_knowledge_base_id(knowledge_base_id)
        context = recall_context_for_query(
            effective_days,
            start=start,
            end=end,
            timezone_name=timezone_name,
            knowledge_base_id=resolved_knowledge_base_id,
        )
        snapshot = context.domain
        if topic_id and topic_id not in {topic.id for topic in snapshot.topics}: raise HTTPException(status_code=404, detail="recall topic not found")
        return mobile_recall_response({
            **domain_payload(snapshot, topic_limit=topic_limit, memory_limit=memory_limit, topic_id=topic_id, include_memories=include_memories, preferences=prefs),
            "knowledge_base_id": resolved_knowledge_base_id,
        })

    @app.get("/api/memory-planet", dependencies=[Depends(require_token)])
    def memory_planet(
        window: str = "week",
        days: int | None = None,
        start: str = "",
        end: str = "",
        timezone_name: Annotated[str, Query(alias="timezone")] = "UTC",
        knowledge_base_id: str = "",
    ) -> dict[str, object]:
        resolved_knowledge_base_id = resolve_recall_knowledge_base_id(knowledge_base_id)
        if window not in {"week", "month", "custom"}:
            raise HTTPException(status_code=422, detail="window must be week, month, or custom")
        if window == "custom":
            if days is not None:
                raise HTTPException(status_code=422, detail="custom window requires start and end, not days")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
                raise HTTPException(status_code=422, detail="start and end must use YYYY-MM-DD")
            try:
                start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
                zone = ZoneInfo(timezone_name)
            except (ValueError, ZoneInfoNotFoundError) as error:
                raise HTTPException(status_code=422, detail="invalid custom date range or timezone") from error
            if end_date < start_date:
                raise HTTPException(status_code=422, detail="end must not be before start")
            effective_days = (end_date - start_date).days + 1
            validate_domain_days(effective_days)
            start_at = datetime.combine(start_date, datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
            end_at = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
            context = recall_context_for_range(
                effective_days,
                start=start_at,
                end=end_at,
                knowledge_base_id=resolved_knowledge_base_id,
            )
            response_window = {
                "kind": "custom",
                "days": effective_days,
                "start": start_at.isoformat(),
                "end": end_at.isoformat(),
                "start_date": start,
                "end_date": end,
                "timezone": timezone_name,
                "knowledge_base_id": resolved_knowledge_base_id,
            }
        else:
            if start or end or days is not None:
                raise HTTPException(status_code=422, detail="week and month do not accept custom range fields")
            effective_days = 7 if window == "week" else 30
            context = recall_context_for(
                effective_days,
                knowledge_base_id=resolved_knowledge_base_id,
            )
            response_window = {
                "kind": window,
                "days": effective_days,
                "start": context.window_start,
                "end": context.window_end,
                "timezone": "UTC",
                "knowledge_base_id": resolved_knowledge_base_id,
            }
        internal_stats = store.recall_surface_stats(
            [candidate.internal_clip_id for candidate in context.candidates]
        )
        prefs = store.recall_preferences()
        payload = build_memory_planet(
            context.candidates,
            window=response_window,
            stats=internal_stats,
            preferred_topic_ids=prefs["preferred_topic_ids"],
        )
        return mobile_recall_response({"ok": True, "planet": payload})

    @app.get("/api/recall/suppressions", dependencies=[Depends(require_token)])
    def recall_suppressions(limit: int = 50, cursor: str = "") -> dict[str, object]:
        if not 1 <= limit <= 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        after_updated_at = ""
        after_clip_id = ""
        direction = "next"
        if cursor:
            if not cursor.startswith("kc_"):
                raise HTTPException(status_code=422, detail="invalid suppression cursor")
            try:
                encoded = cursor[3:]
                decoded = json.loads(
                    base64.urlsafe_b64decode(
                        encoded + "=" * (-len(encoded) % 4)
                    ).decode()
                )
                if decoded.get("v") not in {1, 2}:
                    raise ValueError("unsupported cursor")
                direction = str(decoded.get("direction") or "next")
                if direction not in {"next", "previous"}:
                    raise ValueError("invalid cursor direction")
                after_updated_at = str(decoded["updated_at"])
                public_after_clip_id = str(decoded["public_clip_id"])
                if not re.fullmatch(r"pc_[0-9a-f]{32}", public_after_clip_id):
                    raise ValueError("invalid public clip identity")
                resolved_after_clip_id = pipeline_store.clip_id_for_public_id(
                    public_after_clip_id
                )
                if resolved_after_clip_id is None:
                    raise ValueError("unknown public clip identity")
                after_clip_id = str(resolved_after_clip_id)
            except (binascii.Error, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise HTTPException(status_code=422, detail="invalid suppression cursor") from error
        items: list[dict[str, object]] = []
        rows = store.recall_suppressions(
            limit=limit + 1,
            after_updated_at=after_updated_at,
            after_clip_id=after_clip_id,
            direction=direction,
        )
        selected_rows = rows[:limit]
        page_rows = (
            list(reversed(selected_rows))
            if direction == "previous"
            else selected_rows
        )
        for suppression in page_rows:
            internal_clip_id = suppression["clip_id"]
            try:
                public_clip_id = pipeline_store.public_id_for(int(internal_clip_id))
            except (TypeError, ValueError):
                continue
            raw = store.find_raw_fields_by_clip_id(int(internal_clip_id))
            compact = quality_resolver.compact(raw) if raw is not None else {}
            items.append(
                {
                    "clip_id": public_clip_id,
                    "title": compact.get("title", "未命名记忆"),
                    "summary": compact.get("summary", ""),
                    "suppressed_at": suppression["suppressed_at"],
                }
            )
        def suppression_cursor(
            row: dict[str, str],
            public_clip_id: str,
            cursor_direction: str,
        ) -> str:
            payload = json.dumps(
                {
                    "v": 2,
                    "direction": cursor_direction,
                    "updated_at": row["suppressed_at"],
                    "public_clip_id": public_clip_id,
                },
                separators=(",", ":"),
            ).encode()
            return "kc_" + base64.urlsafe_b64encode(payload).decode().rstrip("=")

        has_previous = bool(page_rows) and bool(
            store.recall_suppressions(
                limit=1,
                after_updated_at=page_rows[0]["suppressed_at"],
                after_clip_id=page_rows[0]["clip_id"],
                direction="previous",
            )
        )
        has_next = bool(page_rows) and bool(
            store.recall_suppressions(
                limit=1,
                after_updated_at=page_rows[-1]["suppressed_at"],
                after_clip_id=page_rows[-1]["clip_id"],
                direction="next",
            )
        )
        previous_cursor = (
            suppression_cursor(page_rows[0], str(items[0]["clip_id"]), "previous")
            if has_previous and page_rows and items
            else ""
        )
        next_cursor = (
            suppression_cursor(page_rows[-1], str(items[-1]["clip_id"]), "next")
            if has_next and page_rows and items
            else ""
        )
        return mobile_recall_response(
            {
                "ok": True,
                "items": items,
                "cursor": cursor,
                "previous_cursor": previous_cursor,
                "next_cursor": next_cursor,
                "limit": limit,
            }
        )

    @app.get("/api/recall/preferences", dependencies=[Depends(require_token)])
    def get_recall_preferences() -> dict[str, object]:
        return {"ok": True, "preferences": store.recall_preferences()}

    @app.patch("/api/recall/preferences", dependencies=[Depends(require_token)])
    def patch_recall_preferences(body: Annotated[dict[str, object], Body()]) -> dict[str, object]:
        allowed = {"visible_label_count", "label_rotation_seconds", "default_days", "preferred_topic_ids", "muted_topic_ids", "include_memory_labels"}
        if set(body) - allowed: raise HTTPException(status_code=422, detail="unknown preference field")
        values: dict[str, object] = {}
        for key, low, high in (("visible_label_count", 1, 5), ("label_rotation_seconds", 4, 30), ("default_days", 1, 90)):
            if key in body:
                if not isinstance(body[key], int) or isinstance(body[key], bool) or not low <= body[key] <= high: raise HTTPException(status_code=422, detail=f"invalid {key}")
                values[key] = body[key]
        for key, maximum in (("preferred_topic_ids", 20), ("muted_topic_ids", 50)):
            if key in body:
                ids = body[key]
                registry_topic_ids = set(topic_store.snapshot().by_id)
                if not isinstance(ids, list) or len(ids) > maximum or any(not isinstance(i, str) or (i not in registry_topic_ids and not re.fullmatch(r"topic:[0-9a-f]{16}", i)) for i in ids): raise HTTPException(status_code=422, detail=f"invalid {key}")
                values[key] = list(dict.fromkeys(ids))
        if "include_memory_labels" in body:
            if not isinstance(body["include_memory_labels"], bool): raise HTTPException(status_code=422, detail="invalid include_memory_labels")
            values["include_memory_labels"] = body["include_memory_labels"]
        return {"ok": True, "preferences": store.update_recall_preferences(values)}

    def _safe_interaction_value(value: str, *, limit: int = 128) -> bool:
        return bool(value) and len(value) <= limit and not re.search(r"(?i)(authorization|bearer|api[_-]?key|token|password|secret|cookie|https?://[^/\s:@]+:[^/\s@]+@)", value)

    def normalize_recall_interaction_target(action: str, node_id: str, topic_id: str, clip_id: str, session_id: str) -> tuple[str, str, str]:
        registry_topic_ids = set(topic_store.snapshot().by_id)
        topic_node = bool(re.fullmatch(r"topic:[0-9a-f]{16}", node_id) or node_id in registry_topic_ids)
        clip_node = re.fullmatch(r"clip:(pc_[0-9a-f]{32})", node_id)
        valid_topic = not topic_id or bool(re.fullmatch(r"topic:[0-9a-f]{16}", topic_id) or topic_id in registry_topic_ids)
        valid_clip = not clip_id or bool(re.fullmatch(r"pc_[0-9a-f]{32}", clip_id))
        if not valid_topic or not valid_clip: raise HTTPException(status_code=422, detail="invalid recall target")
        if action == "open_topic":
            if not topic_id or (node_id and (not topic_node or node_id != topic_id)): raise HTTPException(status_code=422, detail="invalid topic target")
            return topic_id, topic_id, ""
        if action in {"open_memory", "viewed", "defer", "suppress", "restore", "bookmark", "unbookmark", "open_original"}:
            if action == "open_original" and not clip_id: raise HTTPException(status_code=422, detail="clip_id required")
            derived = clip_node.group(1) if clip_node else ""
            if node_id and not clip_node: raise HTTPException(status_code=422, detail="invalid clip target")
            if not (clip_id or derived) or (clip_id and derived and clip_id != derived): raise HTTPException(status_code=422, detail="invalid clip target")
            actual = clip_id or derived
            return f"clip:{actual}", "", actual
        if action in {"impression", "label_impression"}:
            if not (topic_node or clip_node): raise HTTPException(status_code=422, detail="invalid impression target")
            if topic_node: return node_id, node_id, ""
            actual=clip_node.group(1)
            if clip_id and clip_id != actual: raise HTTPException(status_code=422, detail="inconsistent clip target")
            return node_id, "", actual
        return node_id, topic_id, clip_id

    @app.post("/api/recall/interactions", dependencies=[Depends(require_token)])
    def record_recall_interaction(body: Annotated[dict[str, object], Body()]) -> dict[str, object]:
        surfaces = {"overview", "graph", "topic", "resurface", "weekly", "library", "detail"}; actions = {"impression", "label_impression", "open_topic", "open_memory", "open_original", "viewed", "defer", "suppress", "restore", "bookmark", "unbookmark"}
        event_id = body_str(body, "client_event_id"); surface = body_str(body, "surface"); action = body_str(body, "action")
        if not _safe_interaction_value(event_id) or surface not in surfaces or action not in actions: raise HTTPException(status_code=422, detail="invalid recall interaction")
        node_id, topic_id, clip_id, session_id = (body_str(body, key) for key in ("node_id", "topic_id", "clip_id", "session_id"))
        if any(value and not _safe_interaction_value(value) for value in (node_id, topic_id, clip_id, session_id)): raise HTTPException(status_code=422, detail="unsafe recall interaction target")
        node_id, topic_id, clip_id = normalize_recall_interaction_target(action, node_id, topic_id, clip_id, session_id)
        metadata = body.get("metadata", {})
        if not isinstance(metadata, dict) or set(metadata) - {"visible_label_count", "rotation_index", "dwell_ms", "position", "source"} or len(json.dumps(metadata, ensure_ascii=False)) > 512: raise HTTPException(status_code=422, detail="invalid metadata")
        numeric = {"visible_label_count":(1,5),"rotation_index":(0,1000000),"dwell_ms":(0,3600000),"position":(0,10000)}
        if any(key in metadata and (not isinstance(metadata[key],int) or isinstance(metadata[key],bool) or not lo <= metadata[key] <= hi) for key,(lo,hi) in numeric.items()) or ("source" in metadata and (not isinstance(metadata["source"],str) or not 1 <= len(metadata["source"]) <= 40 or not re.fullmatch(r"[A-Za-z0-9._-]+",metadata["source"]) or not _safe_interaction_value(metadata["source"],limit=40))): raise HTTPException(status_code=422, detail="invalid metadata")
        occurred_at=body_str(body,"occurred_at")
        if len(occurred_at)>64 or (occurred_at and (not _safe_interaction_value(occurred_at,limit=64) or parse_utc(occurred_at) is None)): raise HTTPException(status_code=422, detail="invalid occurred_at")
        # An omitted client timestamp is represented consistently as an empty value
        # so a retry is truly byte-for-byte idempotent.
        internal_clip_id = ""
        if clip_id:
            resolved_clip_id = pipeline_store.clip_id_for_public_id(clip_id)
            if resolved_clip_id is None: raise HTTPException(status_code=422, detail="invalid recall target")
            internal_clip_id = str(resolved_clip_id)
        internal_node_id = f"clip:{internal_clip_id}" if internal_clip_id and node_id.startswith("clip:") else node_id
        try: result, replay = store.record_recall_surface_event(
            client_event_id=event_id,
            surface=surface,
            action=action,
            node_id=internal_node_id,
            topic_id=topic_id,
            clip_id=internal_clip_id,
            session_id=session_id,
            metadata=metadata,
            occurred_at=occurred_at,
            suppressed=(action == "suppress") if action in {"suppress", "restore"} else None,
            fault_after_event_insert=recall_fault_after_event_insert,
        )
        except RecallActionCollisionError as error: raise HTTPException(status_code=409, detail=str(error)) from error
        return mobile_recall_response({"ok": True, "event_id":event_id, "replayed": replay, "target":{"node_id":node_id,"topic_id":topic_id,"clip_id":clip_id}, "interaction": {"client_event_id": event_id}, "replay": replay})

    @app.get("/api/recall/resurface", dependencies=[Depends(require_token)])
    def recall_resurface(
        days: int | None = None,
        limit: int = 8,
        cursor: str = "",
        topic_id: str = "",
        exclude_clip_ids: str = "",
        start: str = "",
        end: str = "",
        timezone_name: Annotated[str, Query(alias="timezone")] = "",
        knowledge_base_id: str = "",
    ) -> dict[str, object]:
        if not 1 <= limit <= 20: raise HTTPException(status_code=422, detail="limit must be between 1 and 20")
        prefs = store.recall_preferences()
        effective_days = days if days is not None else int(prefs["default_days"])
        resolved_knowledge_base_id = resolve_recall_knowledge_base_id(knowledge_base_id)
        context = recall_context_for_query(
            effective_days,
            start=start,
            end=end,
            timezone_name=timezone_name,
            knowledge_base_id=resolved_knowledge_base_id,
        )
        snapshot = context.domain
        excluded = {x for x in exclude_clip_ids.split(",") if x}
        if len(excluded) > 50 or any(not re.fullmatch(r"pc_[0-9a-f]{32}", value) for value in excluded): raise HTTPException(status_code=422, detail="exclude_clip_ids must contain at most 50 public ids")
        offset=0
        query_key = resurface_query_key(snapshot.snapshot_key, topic_id=topic_id, exclude_clip_ids=excluded, preferred_topic_ids=prefs["preferred_topic_ids"], muted_topic_ids=prefs["muted_topic_ids"], effective_days=snapshot.days)
        if cursor:
            if not cursor.startswith("kc_"): raise HTTPException(status_code=422, detail="invalid cursor")
            encoded_cursor = cursor[3:]
            try: decoded=json.loads(base64.urlsafe_b64decode(encoded_cursor+"="*(-len(encoded_cursor)%4)).decode()); offset=int(decoded["offset"])
            except (binascii.Error, UnicodeDecodeError, ValueError,KeyError,TypeError,json.JSONDecodeError): raise HTTPException(status_code=422, detail="invalid cursor")
            if decoded.get("v") != 1 or decoded.get("query_key") != query_key or offset < 0: raise HTTPException(status_code=409, detail="resurface snapshot changed")
        internal_stats = store.recall_surface_stats([c.internal_clip_id for c in context.candidates]); stats = {c.clip_id: internal_stats.get(c.internal_clip_id, {}) for c in context.candidates}; muted = set(prefs["muted_topic_ids"]); preferred = set(prefs["preferred_topic_ids"])
        def scored(m):
            result=score_resurface_memory(m, stats, prefs, now=utc_now())
            if any(topic.new_in_window for topic in snapshot.topics if topic.id in m.topic_ids): result=type(result)(min(1,round(result.score+.05,6)), result.reason_codes+["new_in_window"])
            return result.score,result.reason_codes
        buckets={}
        for m in snapshot.memories:
            if m.clip_id not in excluded and not stats.get(m.clip_id, {}).get("suppressed", False) and (not topic_id or topic_id in m.topic_ids) and not any(i in muted for i in m.topic_ids): buckets.setdefault(topic_id or m.primary_topic_id,[]).append((m,*scored(m)))
        for values in buckets.values():values.sort(key=lambda x:(-x[1],x[0].clip_id))
        ordered=[]
        while buckets:
            for key in sorted(list(buckets)):
                if buckets[key]: ordered.append(buckets[key].pop(0))
                if not buckets[key]:del buckets[key]
        page=ordered[offset:offset+limit]; labels={t.id:t.label for t in snapshot.topics}
        has_diversity = not topic_id and len({m.primary_topic_id for m, _score, _reasons in page}) >= 2
        items=[{"clip_id":m.clip_id,"client_request_id":m.client_request_id,"topic_id":m.primary_topic_id,"topic_label":labels.get(m.primary_topic_id,""),"title":m.label,"summary":m.summary,"safe_excerpt":m.safe_excerpt,"source_type":m.source_type,"source_label":m.source_label,"knowledge_base_name":m.knowledge_base_name,"tags":m.tags,"captured_at":m.captured_at,"last_viewed_at":stats.get(m.clip_id,{}).get("last_viewed_at",""),"view_count":stats.get(m.clip_id,{}).get("view_count",0),"defer_count":stats.get(m.clip_id,{}).get("defer_count",0),"score":score,"reason_codes":list(dict.fromkeys(reasons+(["topic_diversity"] if has_diversity else [])))} for m,score,reasons in page]
        next_offset = offset + len(page)
        next_cursor="kc_"+base64.urlsafe_b64encode(json.dumps({"v":1,"query_key":query_key,"offset":next_offset},separators=(',',':')).encode()).decode().rstrip('=') if next_offset < len(ordered) else ""
        return mobile_recall_response({"ok": True, "knowledge_base_id": resolved_knowledge_base_id, "window":{"days":snapshot.days,"start":snapshot.window_start,"end":snapshot.window_end}, "snapshot_key": snapshot.snapshot_key, "cursor": cursor, "next_cursor": next_cursor, "items": items})

    @app.get("/api/recall/overview", dependencies=[Depends(require_token)])
    def recall_overview(days: int = 7) -> dict[str, object]:
        days = validate_recall_days(days); context = recall_context_for(days); candidates = context.candidates; since = recall_since(days); metrics = store.recall_metrics_since(since); recalled_ids = store.recalled_clip_ids_since(since)
        current_topics = {identifier for c in candidates for identifier, _ in c.topics}; previous_topics = context.previous_topic_ids
        return mobile_recall_response({"ok": True, "window": recall_window(days), "days": days, "range_start": since, "range_end": recall_range_end(), "metrics": {"eligible_clip_count": len(candidates), "recall_count": metrics["recall_count"], "new_topic_count": len(current_topics - previous_topics), "reviewed_ratio": len(recalled_ids & {c.internal_clip_id for c in candidates}) / len(candidates) if candidates else 0.0}, "graph": graph_for(candidates), "highlights": [{"type":"clip", "title":c.title, "subtitle":c.summary, "topic_id":c.topics[0][0] if c.topics else "", "clip_id":c.clip_id, "occurred_at":c.captured_at, **candidate_payload(c)} for c in candidates[:10]]})

    @app.get("/api/recall/topics/{requested_topic_id}", dependencies=[Depends(require_token)])
    def recall_topic(requested_topic_id: str, days: int = 7, filter: str = "all") -> dict[str, object]:
        if filter not in {"all", "frequent", "unrecalled", "recent"}: raise HTTPException(status_code=422, detail="filter must be all, frequent, or unrecalled")
        context = recall_context_for(validate_recall_days(days)); candidates = [candidate for candidate in context.candidates if requested_topic_id in {identifier for identifier, _ in candidate.topics}]
        if not candidates:
            raise HTTPException(status_code=404, detail="recall topic not found")
        since = recall_since(days)
        recalled_ids = store.recalled_clip_ids_since(since)
        window_counts = store.recall_counts_by_clip_since(since)
        candidates = [replace(candidate, recall_count=window_counts.get(candidate.internal_clip_id, 0)) for candidate in candidates]
        label = next(topic.label for topic in context.domain.topics if topic.id == requested_topic_id)
        if filter == "unrecalled":
            candidates = [candidate for candidate in candidates if candidate.internal_clip_id not in recalled_ids]
        elif filter == "frequent":
            candidates = sorted(candidates, key=lambda candidate: (-candidate.recall_count, -candidate.score, candidate.clip_id))
        return mobile_recall_response({"ok": True, "window": recall_window(days), "topic": {"id": requested_topic_id, "label": label}, "metrics": {"clip_count":len(candidates), "recall_count":sum(c.recall_count for c in candidates), "unrecalled_count":sum(c.internal_clip_id not in recalled_ids for c in candidates)}, "filter": "all" if filter == "recent" else filter, "graph": graph_for(candidates, topic_id_filter=requested_topic_id), "items": [topic_item_payload(c, c.internal_clip_id in recalled_ids) for c in candidates[:20]], "clips": [candidate_payload(c) for c in candidates[:20]]})

    @app.post("/api/recall/sessions", dependencies=[Depends(require_token)])
    def start_recall_session(body: Annotated[dict[str, object] | None, Body()] = None) -> dict[str, object]:
        payload = body or {}
        days = validate_recall_days(body_int(payload, "days", 7))
        limit = body_int(payload, "limit", 8)
        if limit < 1 or limit > 20: raise HTTPException(status_code=422, detail="limit must be between 1 and 20")
        requested_topic_id = body_str(payload, "topic_id")
        candidates = recall_context_for(days).candidates
        if requested_topic_id:
            candidates = [candidate for candidate in candidates if requested_topic_id in {identifier for identifier, _ in candidate.topics}]
        window_start, window_end = recall_snapshot_window(days)
        selected = balanced_select(candidates, limit=limit, recalled_clip_ids=set())
        snapshot_key = recall_snapshot_key(days=days, topic_id=requested_topic_id, window_start=window_start, window_end=window_end, candidates=candidates)
        existing = store.find_active_recall_session(snapshot_key=snapshot_key, topic_id=requested_topic_id)
        if existing: return session_response(existing)
        session_items = [{"id":"item_" + uuid.uuid4().hex, "clip_id":c.internal_clip_id, "client_request_id":c.client_request_id, "topic_id":requested_topic_id or (c.topics[0][0] if c.topics else ""), "score":c.score, "title":c.title, "cue":c.summary or c.title, "reveal_text":c.reveal_text, "summary":c.summary, "tags":c.tags, "source_type":c.source_type, "source_label":c.source_app or c.source_type, "knowledge_base_name":c.knowledge_base_name, "captured_at":c.captured_at, "recall_count_before":c.recall_count} for c in selected]
        session = store.create_recall_session(session_id="recall_" + uuid.uuid4().hex, days=days, topic_id=requested_topic_id, items=session_items, window_start=window_start, window_end=window_end, snapshot_key=snapshot_key)
        return session_response(session)

    @app.get("/api/recall/sessions/{session_id}", dependencies=[Depends(require_token)])
    @app.get("/api/recall/sessions/{session_id}/items", dependencies=[Depends(require_token)])
    def get_recall_session(session_id: str) -> dict[str, object]:
        session = store.find_recall_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="recall session not found")
        return session_response(session)

    @app.post("/api/recall/sessions/{session_id}/items/{item_id}/action", dependencies=[Depends(require_token)])
    @app.post("/api/recall/sessions/{session_id}/items/{item_id}/actions", dependencies=[Depends(require_token)])
    @app.post("/api/recall/sessions/{session_id}/items/{item_id}/events", dependencies=[Depends(require_token)])
    def record_recall_action(session_id: str, item_id: str, body: Annotated[dict[str, object], Body()], request: Request) -> dict[str, object]:
        if store.find_recall_session(session_id) is None:
            raise HTTPException(status_code=404, detail="recall session not found")
        try:
            requested = item_id
            if not requested.startswith("item_"):
                requested_internal = pipeline_store.clip_id_for_public_id(requested) if requested.startswith("pc_") else None
                lookup_clip_id = str(requested_internal) if requested_internal is not None else requested
                matched = next((item for item in store.list_recall_items(session_id) if item.clip_id == lookup_clip_id), None)
                if matched: requested = matched.id
            client_action_id = body_str(body, "client_action_id")
            if not client_action_id and request.url.path.endswith(("/actions", "/events")):
                client_action_id = "legacy_" + hashlib.sha256((session_id + requested + body_str(body, "action")).encode()).hexdigest()
            item, _replay = store.record_recall_action(session_id=session_id, item_id=requested, action=body_str(body, "action"), client_action_id=client_action_id)
        except RecallActionCollisionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except RecallItemNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        response = session_response(store.find_recall_session(session_id)); response["item"] = session_item_payload(item)
        if body_str(body, "action") == "reveal": response["reveal_text"] = item.reveal_text
        return mobile_recall_response(response)

    @app.get("/api/recall/weekly", dependencies=[Depends(require_token)])
    @app.get("/api/recall/weekly-review", dependencies=[Depends(require_token)])
    def recall_weekly(days: int = 7) -> dict[str, object]:
        candidates = recall_context_for(validate_recall_days(days)).candidates
        since = recall_since(days)
        metrics = store.recall_metrics_since(since)
        graph = graph_for(candidates)
        window_counts = store.recall_counts_by_clip_since(since)
        topic_counts: dict[str, int] = {}
        for candidate in candidates:
            for identifier, _label in candidate.topics:
                topic_counts[identifier] = topic_counts.get(identifier, 0) + window_counts.get(candidate.internal_clip_id, 0)
        topics = sorted((node for node in graph["nodes"] if node["type"] == "topic"), key=lambda node: (-topic_counts.get(str(node["id"]), 0), -int(node["weight"]), str(node["label"]), str(node["id"])))
        suggested = balanced_select(candidates, limit=5, recalled_clip_ids=store.recalled_clip_ids_since(since))
        item = lambda c: {"clip_id":c.clip_id, "title":c.title, "topic_id":c.topics[0][0] if c.topics else "", "topic_label":c.topics[0][1] if c.topics else "", "recall_count":window_counts.get(c.internal_clip_id, 0), "captured_at":c.captured_at}
        summary_text = f"本周保存了 {len(candidates)} 条闪记，完成 {metrics['recall_count']} 次回想，覆盖 {len(topics)} 个主题。"
        recalled_candidates = [candidate for candidate in candidates if window_counts.get(candidate.internal_clip_id, 0) > 0]
        return mobile_recall_response({"ok": True, "window": recall_window(days), "summary": {"saved_count":len(candidates), "recall_count":metrics["recall_count"], "topic_count":len(topics), "connection_count":len(graph["edges"]), "summary_text": summary_text}, "summary_text": summary_text, "top_topics":[{"topic_id":n["id"], "label":n["label"], "clip_count":n["weight"], "recall_count":topic_counts.get(str(n["id"]), 0), "weight":n["weight"]} for n in topics[:10]], "most_recalled":[item(c) for c in sorted(recalled_candidates, key=lambda c:(-window_counts[c.internal_clip_id], c.clip_id))[:10]], "suggested_items":[item(c) for c in suggested[:10]]})

    @app.get("/api/recall/clips/{clip_id}", dependencies=[Depends(require_token)])
    def recall_clip(clip_id: str) -> dict[str, object]:
        try:
            raw = find_raw_clip_for_path(
                clip_id, ambiguous_detail="multiple clip parts require an exact clip id"
            )
        except HTTPException as error:
            if error.status_code == 404:
                raise HTTPException(status_code=404, detail="recall clip not found") from error
            raise
        route = knowledge_store.find_latest_route_decision_by_clip_id(raw.id)
        knowledge_base = (
            knowledge_store.get_knowledge_base(route.knowledge_base_id, include_deleted=True)
            if route is not None
            else None
        )
        resolved_source = quality_resolver.recall_source(
            raw, knowledge_base.name if knowledge_base else ""
        )
        candidate = candidate_from_row(*resolved_source, public_clip_id=pipeline_store.public_id_for(raw.id)) if resolved_source else None
        if not candidate: raise HTTPException(status_code=404, detail="recall clip not found")
        return mobile_recall_response({"ok": True, "clip": candidate_payload(candidate)})

    def map_ingest_error(error: Exception) -> HTTPException:
        if isinstance(error, IngestValidationError):
            return HTTPException(status_code=422, detail=error.detail)
        if isinstance(error, IngestConflictError):
            return HTTPException(status_code=409, detail=error.detail)
        if isinstance(error, IngestNotFoundError):
            return HTTPException(status_code=404, detail=error.detail)
        if isinstance(error, IngestPayloadTooLargeError):
            return HTTPException(status_code=413, detail=error.detail)
        if isinstance(error, IngestUnsupportedMediaError):
            return HTTPException(status_code=415, detail=error.detail)
        if isinstance(error, IngestArchiveError):
            return HTTPException(status_code=502, detail=error.detail)
        if isinstance(error, IngestInternalError):
            return HTTPException(status_code=500, detail=error.detail)
        return HTTPException(status_code=500, detail="ingest failed")

    @app.post("/api/mobile-clips", dependencies=[Depends(require_token)])
    async def mobile_clips(
        source_type: Annotated[str, Form()],
        title_hint: Annotated[str, Form()] = "",
        note: Annotated[str, Form()] = "",
        text: Annotated[str, Form()] = "",
        url: Annotated[str, Form()] = "",
        mime_type: Annotated[str, Form()] = "",
        device_name: Annotated[str, Form()] = "",
        source_app: Annotated[str, Form()] = "",
        captured_at: Annotated[str, Form()] = "",
        client_request_id: Annotated[str, Form()] = "",
        target_knowledge_base_id: Annotated[str, Form()] = "",
        routing_mode: Annotated[str, Form()] = "",
        client_batch_id: Annotated[str, Form()] = "",
        parent_client_request_id: Annotated[str, Form()] = "",
        client_part_index: Annotated[int, Form()] = 0,
        client_part_count: Annotated[int, Form()] = 1,
        part_role: Annotated[str, Form()] = "single",
        source_intent: Annotated[str, Form()] = "unknown",
        captured_timezone: Annotated[str, Form()] = "",
        content_fingerprint: Annotated[str, Form()] = "",
        file: Annotated[UploadFile | None, File()] = None,
    ) -> dict[str, object]:
        try:
            payload = b""
            filename = ""
            file_mime = ""
            if file is not None:
                filename = file.filename or ""
                file_mime = file.content_type or mime_type
                payload = await read_upload_file_limited(file, resolved_settings.max_file_bytes)
            command = mobile_form_to_command(
                source_type=source_type, title_hint=title_hint, note=note, text=text, url=url,
                mime_type=mime_type, device_name=device_name, source_app=source_app,
                captured_at=captured_at, client_request_id=client_request_id,
                target_knowledge_base_id=target_knowledge_base_id, routing_mode=routing_mode,
                client_batch_id=client_batch_id,
                parent_client_request_id=parent_client_request_id, client_part_index=client_part_index,
                client_part_count=client_part_count, part_role=part_role, source_intent=source_intent,
                captured_timezone=captured_timezone, content_fingerprint=content_fingerprint,
                filename=filename, file_mime_type=file_mime, payload=payload,
            )
            return legacy_ingest_response(await ingest_service.ingest(command))
        except IngestValidationError as error:
            raise map_ingest_error(error) from error
        except IngestConflictError as error:
            raise map_ingest_error(error) from error
        except IngestNotFoundError as error:
            raise map_ingest_error(error) from error
        except IngestPayloadTooLargeError as error:
            raise map_ingest_error(error) from error
        except IngestUnsupportedMediaError as error:
            raise map_ingest_error(error) from error
        except (IngestArchiveError, IngestInternalError) as error:
            raise map_ingest_error(error) from error

    @app.post("/api/ingest/v1/clips")
    async def ingest_v1_json(
        request: Request,
        response: Response,
        authenticated_token: str = Depends(require_ingest_token),
    ) -> dict[str, object]:
        try:
            body = await read_json_body_limited(request, resolved_settings.max_request_bytes)
            command = json_envelope_to_command(body)
            enforce_adapter_scope(command.source.adapter, authenticated_token)
            if command.clip.source_type not in {"text", "url"}:
                raise IngestValidationError("JSON endpoint supports text and url only")
            if command.asset is not None:
                raise IngestValidationError("JSON endpoint does not accept assets")
            result = (await ingest_service.ingest(command)).v1_response()
            if resolved_settings.processing_mode == "worker":
                response.status_code = 202
            return result
        except (ValueError, json.JSONDecodeError, AdapterValidationError) as error:
            raise HTTPException(status_code=422, detail=str(error) or "invalid JSON envelope") from error
        except (IngestValidationError, IngestConflictError, IngestNotFoundError, IngestPayloadTooLargeError,
                IngestUnsupportedMediaError, IngestArchiveError, IngestInternalError) as error:
            raise map_ingest_error(error) from error

    @app.post("/api/ingest/v1/clips/multipart")
    async def ingest_v1_multipart(
        request: Request,
        response: Response,
        envelope_json: Annotated[str, Form()],
        file: Annotated[UploadFile, File()],
        authenticated_token: str = Depends(require_ingest_token),
    ) -> dict[str, object]:
        try:
            form = await request.form()
            if len(form.getlist("envelope_json")) != 1 or len(form.getlist("file")) != 1:
                raise IngestValidationError("exactly one envelope_json and file are required")
            envelope = json.loads(envelope_json)
            payload = await read_upload_file_limited(file, resolved_settings.max_file_bytes)
            command = multipart_envelope_to_command(
                envelope, filename=file.filename or "", mime_type=file.content_type or "", payload=payload,
            )
            enforce_adapter_scope(command.source.adapter, authenticated_token)
            result = (await ingest_service.ingest(command)).v1_response()
            if resolved_settings.processing_mode == "worker":
                response.status_code = 202
            return result
        except (ValueError, json.JSONDecodeError, AdapterValidationError) as error:
            raise HTTPException(status_code=422, detail=str(error) or "invalid multipart envelope") from error
        except (IngestValidationError, IngestConflictError, IngestNotFoundError, IngestPayloadTooLargeError,
                IngestUnsupportedMediaError, IngestArchiveError, IngestInternalError) as error:
            raise map_ingest_error(error) from error

    @app.get("/api/ingest/v1/receipts/{receipt_id}")
    def ingest_v1_receipt(
        receipt_id: str,
        authenticated_token: str = Depends(require_ingest_token),
    ) -> dict[str, object]:
        if not re.fullmatch(r"ir_[a-f0-9]{32}", receipt_id):
            raise HTTPException(status_code=404, detail="ingest receipt not found")
        receipt = store.find_ingest_receipt_by_id(receipt_id)
        if receipt is None:
            raise HTTPException(status_code=404, detail="ingest receipt not found")
        if not compare_digest(authenticated_token, resolved_settings.ingest_token):
            enforce_adapter_scope(receipt.source_adapter, authenticated_token)
        route = None
        if receipt.clip_id:
            route = knowledge_store.find_latest_route_decision_by_clip_id(int(receipt.clip_id))
        return {
            "ok": True, "receipt_id": receipt.receipt_id,
            "client_request_id": receipt.client_request_id, "clip_id": receipt.clip_id,
            "contract_version": receipt.contract_version, "source_adapter": receipt.source_adapter,
            "status": receipt.status, "archive_status": receipt.archive_status,
            "metadata_status": receipt.metadata_status, "error_code": receipt.error_code,
            "capture": {
                "client_batch_id": receipt.capture_client_batch_id,
                "parent_client_request_id": receipt.capture_parent_client_request_id,
                "part_index": receipt.capture_part_index, "part_count": receipt.capture_part_count,
                "part_role": receipt.capture_part_role,
            },
            "routing": {
                "status": "available" if route else "requested" if receipt.target_knowledge_base_id else "missing",
                "knowledge_base_id": route.knowledge_base_id if route else receipt.target_knowledge_base_id,
                "decision_type": route.decision_type if route else "",
            },
            "created_at": receipt.created_at, "updated_at": receipt.updated_at,
        }
    @app.get("/api/mobile-clips/batch/{client_batch_id}", dependencies=[Depends(require_token)])
    def mobile_clip_batch(client_batch_id: str) -> dict[str, object]:
        if not CAPTURE_ID_RE.fullmatch(client_batch_id):
            raise HTTPException(status_code=422, detail="invalid client_batch_id")
        clips = store.list_clips_by_client_batch_id(client_batch_id)
        attempts = store.list_capture_part_attempts_by_batch_id(client_batch_id)
        expected_count = attempts[0].part_count if attempts else max((clip.capture_part_count for clip in clips), default=0)
        received_indices = {clip.capture_part_index for clip in clips}
        failed_indices = {attempt.part_index for attempt in attempts if attempt.status == "failed" and attempt.part_index not in received_indices}
        missing_indices = [index for index in range(expected_count) if index not in received_indices]
        complete = expected_count > 0 and not missing_indices
        status = "completed" if complete else "failed" if failed_indices else "partial" if attempts or clips else "empty"
        return {
            "ok": True,
            "client_batch_id": client_batch_id,
            "received_count": len(clips),
            "expected_count": expected_count,
            "failed_count": len(failed_indices),
            "missing_part_indices": missing_indices,
            "status": status,
            "complete": complete,
            "clips": [
                {
                    "clip_id": str(clip.id), "client_request_id": clip.client_request_id,
                    "part_index": clip.capture_part_index, "part_role": clip.capture_part_role,
                    "source_type": clip.source_type, "filename": clip.filename, "created_at": clip.created_at,
                }
                for clip in clips
            ],
        }

    @app.get("/api/mobile-clips/{clip_id}/capture", dependencies=[Depends(require_token)])
    def mobile_clip_capture(clip_id: int) -> dict[str, object]:
        raw = store.find_raw_fields_by_clip_id(clip_id)
        if raw is None:
            raise HTTPException(status_code=404, detail="clip not found")
        metadata = store.find_normalized_metadata_by_clip_id(clip_id)
        route = knowledge_store.find_latest_route_decision_by_clip_id(clip_id)
        resolved = quality_resolver.resolve(raw)
        enrichment = resolved.enrichment
        sync = store.find_latest_ragflow_sync_job_by_clip_id(clip_id)
        return {
            "ok": True,
            "clip_id": str(raw.id),
            "client_request_id": raw.client_request_id,
            "capture": metadata.metadata.get("capture", capture_for_raw(raw)) if metadata else capture_for_raw(raw),
            "routing": {
                "status": "available" if route else "missing",
                "knowledge_base_id": route.knowledge_base_id if route else "",
                "decision_type": route.decision_type if route else "",
            },
            "enrichment": {
                "status": enrichment.status if enrichment else "not_started",
            },
            "ragflow_sync": {"status": sync.status if sync else "not_started", "phase": sync.phase if sync else ""},
            "metadata_status": "available" if metadata else "missing",
        }

    return app


def response_for(clip: StoredClip) -> dict[str, object]:
    return {
        "ok": True,
        "clip_id": str(clip.id),
        "client_request_id": clip.client_request_id,
        "duplicate": clip.duplicate,
        "title": clip.title,
        "platform": clip.platform,
        "content_hash": clip.content_hash,
        "filename": clip.filename,
        "size_bytes": clip.size_bytes,
        # Keep the legacy response key stable without exposing an internal
        # RAGFlow document identifier to ordinary mobile clients.
        "ragflow_document_id": "",
        "archive_status": clip.archive_status,
        "capture": {
            "client_batch_id": clip.capture_client_batch_id,
            "parent_client_request_id": clip.capture_parent_client_request_id,
            "part_index": clip.capture_part_index,
            "part_count": clip.capture_part_count,
            "part_role": clip.capture_part_role,
        },
    }


def public_knowledge_base_payload(payload: dict[str, object]) -> dict[str, object]:
    """Preserve the mobile KB schema while hiding connector identifiers."""
    public = dict(payload)
    public["ragflow_dataset_id"] = ""
    public["ragflow_dataset_name"] = ""
    return public


def capture_for_raw(raw: StoredClipRawFields) -> dict[str, object]:
    return {
        "client_batch_id": raw.capture_client_batch_id,
        "parent_client_request_id": raw.capture_parent_client_request_id,
        "part_index": raw.capture_part_index,
        "part_count": raw.capture_part_count,
        "part_role": raw.capture_part_role,
    }


def enrichment_metadata_for(enrichment) -> dict[str, object]:
    payload = enrichment_response_for(enrichment)
    payload["route_decision_id"] = enrichment.route_decision_id
    return payload


def enrichment_response_for(enrichment) -> dict[str, object]:
    return {
        "clip_id": enrichment.clip_id,
        "client_request_id": enrichment.client_request_id,
        "knowledge_base_id": enrichment.knowledge_base_id,
        "engine": enrichment.engine,
        "status": enrichment.status,
        "title": enrichment.title,
        "summary": enrichment.summary,
        "tags": enrichment.tags,
        "key_points": enrichment.key_points,
        "language": enrichment.language,
        "extracted_text": enrichment.extracted_text,
        "error_code": enrichment.error_code,
        "error_message": enrichment.error_message,
        "created_at": enrichment.created_at,
        "updated_at": enrichment.updated_at,
    }


def ragflow_sync_metadata_for(sync_job: StoredRagflowSyncJob) -> dict[str, object]:
    return {
        "operation": sync_job.operation,
        "status": sync_job.status,
        "dry_run": sync_job.dry_run,
        "remote_document_changed": sync_job.remote_document_changed,
        "ragflow_dataset_id": sync_job.ragflow_dataset_id,
        "ragflow_document_id": sync_job.ragflow_document_id,
        "reason": sync_job.reason,
        "plan": sync_job.plan,
        "phase": sync_job.phase,
        "error_code": sync_job.error_code,
        "error_message": sync_job.error_message,
        "updated_at": sync_job.updated_at,
    }


def ragflow_sync_response_for(sync_job: StoredRagflowSyncJob) -> dict[str, object]:
    return {
        "clip_id": sync_job.clip_id,
        "client_request_id": sync_job.client_request_id,
        "knowledge_base_id": sync_job.knowledge_base_id,
        "ragflow_dataset_id": sync_job.ragflow_dataset_id,
        "ragflow_document_id": sync_job.ragflow_document_id,
        "route_decision_id": sync_job.route_decision_id,
        "enrichment_id": sync_job.enrichment_id,
        "operation": sync_job.operation,
        "status": sync_job.status,
        "dry_run": sync_job.dry_run,
        "remote_document_changed": sync_job.remote_document_changed,
        "reason": sync_job.reason,
        "plan": sync_job.plan,
        "attempt_key": sync_job.attempt_key,
        "phase": sync_job.phase,
        "error_code": sync_job.error_code,
        "error_message": sync_job.error_message,
        "started_at": sync_job.started_at,
        "finished_at": sync_job.finished_at,
        "created_at": sync_job.created_at,
        "updated_at": sync_job.updated_at,
    }


def ragflow_document_content(raw: StoredClipRawFields, enrichment: object) -> str:
    title = str(getattr(enrichment, "title", "") or raw.title_hint or raw.filename or "PerClip")
    body = str(getattr(enrichment, "extracted_text", "") or raw.text or raw.note)
    source = f"\n\nSource: {raw.url}" if raw.url else ""
    return f"# {title}\n\n{body}{source}\n"
