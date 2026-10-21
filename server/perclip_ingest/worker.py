from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import Settings
from .enrichment import (
    ENGINE_DETERMINISTIC_V7,
    EnrichmentInputProjection,
    deterministic_enrich,
    explicit_title_hint,
    safe_short_text,
)
from .content_cleaning import clean_content
from .file_extraction import extract_file_text
from .knowledge_base_store import KnowledgeBaseStore
from .pipeline_store import PIPELINE_STAGES, PipelineStore, StoredPipelineJob
from .ragflow_adapter import (
    RagflowAdapterError,
    RagflowUnsupportedError,
    build_ragflow_adapter,
)
from .ragflow_index import (
    build_index_metadata,
    build_operation_key,
    compact_metadata_json,
    deterministic_document_name,
    verify_index,
)
from .routing import RoutingPreviewInput, preview_for_target, preview_route
from .storage import ClipStore
from .topics import (
    OpenAICompatibleEmbeddingProvider,
    TopicClassificationInput,
    TopicClassificationService,
    TopicStore,
)
from .platform_acquisition import (
    DEFAULT_PLATFORM_ACQUISITION_ADAPTERS,
    PlatformAcquisitionError,
    acquire_web_document,
)
from .platform_extraction import DEFAULT_PLATFORM_HTML_ADAPTERS, extract_html_with_adapters
from .web_extraction import SafeWebFetcher, WebFetchError, canonicalize_url


STAGE_ENGINE = {
    "archive_original": ("filesystem", "v1"),
    "extract": ("builtin-extractor", "v3"),
    "clean": ("deterministic-cleaner", "v4"),
    "enrich": (ENGINE_DETERMINISTIC_V7, "v7"),
    "classify_topic": ("perclip-fixed-topics", "v1"),
    "route": ("perclip-routing", "v1"),
    "index": ("ragflow", "v4"),
}

UNKNOWN_SOURCE_LABEL = "未明确来源"
UNAVAILABLE_CONTENT_LABEL = "内容暂不可用"


def _with_resolution_state(
    field: dict[str, object],
    *,
    resolved: bool,
    unknown_label: str,
    unknown_source: str,
) -> dict[str, object]:
    """Keep display availability separate from source-faithful resolution."""

    result = dict(field)
    if resolved:
        result["resolution_state"] = "resolved"
        return result
    result.update(
        value=unknown_label,
        source=unknown_source,
        confidence=None,
        reason="explicit_data_unavailable",
        resolution_state="explicit_unknown",
    )
    return result


class PipelineWorker:
    def __init__(
        self,
        settings: Settings,
        *,
        ragflow_adapter_override=None,
        lease_seconds: float = 300,
        lease_heartbeat_seconds: float | None = None,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.settings = settings
        self.store = ClipStore(settings.data_dir)
        self.store.init()
        self.knowledge_store = KnowledgeBaseStore(settings.data_dir)
        self.knowledge_store.init()
        self.pipeline = PipelineStore(settings.data_dir, clock=clock)
        self.pipeline.init()
        self.topic_store = TopicStore(settings.data_dir)
        self.topic_store.init()
        semantic_provider = None
        semantic_engine = "embedding"
        if settings.topic_embedding.enabled:
            semantic_provider = OpenAICompatibleEmbeddingProvider(
                endpoint=settings.topic_embedding.endpoint,
                api_key=settings.topic_embedding.api_key,
                model=settings.topic_embedding.model,
                timeout_seconds=settings.topic_embedding.timeout_seconds,
                retries=settings.topic_embedding.retries,
                max_input_chars=settings.topic_embedding.max_input_chars,
            )
            semantic_engine = ":".join(
                (
                    "openai-compatible",
                    settings.topic_embedding.model,
                    settings.topic_embedding.provider_version,
                )
            )
        self.topic_classifier = TopicClassificationService(
            self.topic_store,
            semantic_provider=semantic_provider,
            semantic_threshold=settings.topic_embedding.threshold,
            semantic_engine=semantic_engine,
        )
        self.pipeline.reconcile_acceptances(
            deployment_environment=settings.deployment_environment
        )
        self.asset_root = settings.asset_root or settings.data_dir / "PersonalClips"
        self.ragflow = ragflow_adapter_override or build_ragflow_adapter(settings.ragflow)
        self._sleep = sleep or time.sleep
        self.lease_seconds = lease_seconds
        self.lease_heartbeat_seconds = (
            lease_heartbeat_seconds
            if lease_heartbeat_seconds is not None
            else min(30.0, max(0.01, lease_seconds / 3))
        )
        if self.lease_heartbeat_seconds <= 0 or self.lease_heartbeat_seconds >= lease_seconds:
            raise ValueError("lease heartbeat must be positive and shorter than the lease")
        self.web_fetcher = SafeWebFetcher(
            max_bytes=settings.web_fetch_max_bytes,
            timeout_seconds=settings.web_fetch_timeout_seconds,
            proxy_host=settings.web_fetch_proxy_host or None,
            proxy_port=settings.web_fetch_proxy_port or None,
        )

    def run_once(self, *, limit: int = 20) -> int:
        completed = 0
        processed = 0
        while processed < max(1, int(limit)):
            claimed = self.pipeline.claim(limit=1, lease_seconds=self.lease_seconds)
            if not claimed:
                break
            job = claimed[0]
            processed += 1
            try:
                output_asset_id, lease_owned = self._run_stage_with_heartbeat(job)
                if not lease_owned:
                    continue
                next_stage = self._next_stage(job.stage)
                next_engine, next_version = STAGE_ENGINE.get(next_stage, ("perclip", "v1"))
                output_hash = self.pipeline.asset_hash(output_asset_id)
                if not self.pipeline.complete(
                    job,
                    output_asset_id=output_asset_id,
                    next_stage=next_stage,
                    next_engine=next_engine,
                    next_engine_version=next_version,
                    next_input_hash=output_hash or job.input_hash,
                ):
                    continue
                if job.stage == "route":
                    self.pipeline.mark_ready(clip_id=int(job.clip_id))
                completed += 1
            except RagflowUnsupportedError as error:
                self._fail_job(job, error, retryable=False)
            except PlatformAcquisitionError as error:
                # A platform adapter is reached only after the primary fetch has
                # failed and has already spent its single bounded fallback.
                self._fail_job(job, error, retryable=False)
            except (OSError, RagflowAdapterError, WebFetchError, sqlite3.OperationalError) as error:
                self._fail_job(
                    job, error, retryable=True,
                    retry_delay_seconds=min(300, 2 ** min(job.attempt_count, 8)),
                )
            except (ValueError, RuntimeError) as error:
                self._fail_job(job, error, retryable=False)
            except Exception as error:
                self._fail_job(job, error, retryable=False, safe_error_code="internal_stage_error")
        return completed

    def _run_stage_with_heartbeat(self, job: StoredPipelineJob) -> tuple[str, bool]:
        stopped = threading.Event()
        lease_lost = threading.Event()

        def heartbeat() -> None:
            while not stopped.wait(self.lease_heartbeat_seconds):
                try:
                    renewed = self.pipeline.renew_lease(
                        job, lease_seconds=self.lease_seconds
                    )
                except sqlite3.OperationalError:
                    renewed = False
                if not renewed:
                    lease_lost.set()
                    return

        thread = threading.Thread(target=heartbeat, name=f"perclip-lease-{job.id}", daemon=True)
        thread.start()
        try:
            output = self._run_stage(job)
        finally:
            stopped.set()
            thread.join(timeout=max(1.0, self.lease_heartbeat_seconds * 2))
        return output, not lease_lost.is_set()

    def _fail_job(
        self,
        job: StoredPipelineJob,
        error: Exception,
        *,
        retryable: bool,
        retry_delay_seconds: int = 30,
        safe_error_code: str = "",
    ) -> None:
        code = safe_error_code or self._safe_error_code(error)
        changed = self.pipeline.fail(
            job,
            safe_error_code=code,
            retryable=retryable,
            retry_delay_seconds=retry_delay_seconds,
        )
        if not changed or job.stage != "extract":
            return
        failed = self.pipeline.get_job(job.id)
        if failed is not None and failed.status == "failed":
            self._continue_after_extract_failure(job, code)

    def _run_stage(self, job: StoredPipelineJob) -> str:
        raw = self.store.find_raw_fields_by_clip_id(int(job.clip_id))
        if raw is None:
            raise ValueError("clip_not_found")
        if job.stage == "archive_original":
            return self._archive_original(raw)
        if job.stage == "extract":
            if raw.source_type == "url" and raw.url and self.settings.enable_web_fetch:
                return self._extract_web(raw)
            if raw.source_type == "file":
                original = self.pipeline.latest_asset(clip_id=raw.id, role="original")
                if original is None:
                    raise ValueError("original_asset_missing")
                result = extract_file_text(
                    raw.filename,
                    Path(str(original["storage_uri"])).read_bytes(),
                    raw.mime_type,
                )
                return self._write_derived_text(
                    raw,
                    role="extracted_text",
                    text=result.text,
                    engine=result.engine,
                    engine_version=result.engine_version,
                    metadata={
                        "extraction": {
                            "status": "failed" if result.status == "failed" else result.status.split(":", 1)[0],
                            "title": "",
                            "title_source": "",
                            "resolved_url": "",
                            "canonical_url": "",
                            "quality_score": None,
                            "quality_reason": result.quality_reason,
                            "safe_error_code": result.safe_error_code,
                            "recall_eligible": result.status != "failed" and bool(result.text.strip()),
                            "raw_fallback_used": False,
                        }
                    },
                )
            return self._write_derived_text(
                raw,
                role="extracted_text",
                text=self._extract_text(raw),
                metadata={"extraction": {"status": "completed", "safe_error_code": ""}},
            )
        if job.stage == "clean":
            extracted = self.pipeline.latest_asset(clip_id=raw.id, role="extracted_text")
            text = self._read_asset_text(extracted) if extracted else self._extract_text(raw)
            cleaned = clean_content(text)
            return self._write_derived_text(
                raw,
                role="clean_markdown",
                text=cleaned.text,
                engine=cleaned.engine,
                engine_version=cleaned.engine_version,
                metadata={
                    **self.pipeline.asset_metadata(extracted),
                    "cleaning": {
                        "status": "completed",
                        "removed_count": cleaned.removed_count,
                    },
                },
            )
        if job.stage == "enrich":
            route = self.knowledge_store.find_latest_route_decision_by_clip_id(raw.id)
            metadata = self.store.find_normalized_metadata_by_clip_id(raw.id)
            projection = self._enrichment_projection(raw)
            result = deterministic_enrich(
                raw,
                route,
                metadata.metadata if metadata else {},
                projection,
            )
            saved = self.store.save_enrichment(
                clip_id=raw.id,
                client_request_id=raw.client_request_id,
                knowledge_base_id=route.knowledge_base_id if route else "",
                route_decision_id=route.id if route else None,
                engine=result.engine,
                status=result.status,
                title=result.title,
                summary=result.summary,
                tags=result.tags,
                key_points=result.key_points,
                language=result.language,
                extracted_text=result.extracted_text,
                error_code=result.error_code,
                error_message="",
            )
            self._save_projection_metadata(raw, projection, saved)
            return ""
        if job.stage == "classify_topic":
            saved = self.store.find_normalized_metadata_by_clip_id(raw.id)
            metadata = dict(saved.metadata) if saved else {}
            processing = metadata.get("processing")
            processing = dict(processing) if isinstance(processing, dict) else {}
            active = processing.get("active_projection")
            active = dict(active) if isinstance(active, dict) else {}
            latest = processing.get("latest_attempted_projection")
            latest = dict(latest) if isinstance(latest, dict) else {}
            active_asset_id = str(active.get("source_asset_id") or "")
            if (
                not active_asset_id
                or str(latest.get("source_asset_id") or "") != active_asset_id
                or not bool(active.get("recall_eligible", False))
                or not bool(latest.get("recall_eligible", False))
                or bool(active.get("raw_fallback_used", False))
                or bool(latest.get("raw_fallback_used", False))
                or str(active.get("extraction_status") or "") == "failed"
                or str(latest.get("extraction_status") or "") == "failed"
            ):
                return ""
            asset = self.pipeline.find_asset(active_asset_id)
            if asset is None or str(asset.get("role") or "") != "clean_markdown":
                return ""
            public_id = self.pipeline.public_id_for(raw.id)
            generation = self._generation_public_id(public_id, active_asset_id)
            text = self._read_asset_text(asset)
            active_enrichment_id = processing.get("active_enrichment_id")
            active_enrichment = None
            if active_enrichment_id is not None:
                try:
                    active_enrichment = self.store.find_enrichment_by_id(
                        int(active_enrichment_id)
                    )
                except (TypeError, ValueError):
                    active_enrichment = None
            route = self.knowledge_store.find_latest_route_decision_by_clip_id(raw.id)
            knowledge_base = (
                self.knowledge_store.get_knowledge_base(
                    route.knowledge_base_id, include_deleted=True
                )
                if route is not None
                else None
            )
            classification_input = TopicClassificationInput.build(
                explicit_title=explicit_title_hint(raw),
                active_title=active_enrichment.title if active_enrichment else "",
                summary=active_enrichment.summary if active_enrichment else "",
                markdown=text,
                user_tags=active_enrichment.tags if active_enrichment else (),
                knowledge_base_name=knowledge_base.name if knowledge_base else "",
                source_context=raw.source_app or raw.source_type,
            )
            try:
                self.topic_classifier.classify(
                    clip_id=raw.id,
                    generation=generation,
                    projection=classification_input,
                )
            except Exception:
                # Topic classification is additive. A failed reclassification
                # preserves the previous active assignment and never blocks Core.
                pass
            return ""
        if job.stage == "route":
            route = self.knowledge_store.find_latest_route_decision_by_clip_id(raw.id)
            if route is None:
                clean_asset = self.pipeline.latest_asset(clip_id=raw.id, role="clean_markdown")
                clean_text = self._read_asset_text(clean_asset) if clean_asset else raw.text
                preview_input = RoutingPreviewInput(
                    source_type=raw.source_type,
                    title_hint=raw.title_hint,
                    note=raw.note,
                    text=clean_text,
                    url=raw.url,
                    mime_type=raw.mime_type,
                    filename=raw.filename,
                    device_name=raw.device_name,
                    source_app=raw.source_app,
                    client_request_id=raw.client_request_id,
                )
                preview = self._quality_route_preview(raw, clean_asset, preview_input)
                route = self.knowledge_store.save_route_decision(
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
            self.pipeline.associate_knowledge_base(
                clip_id=raw.id,
                knowledge_base_id=route.knowledge_base_id,
                association_type="manual" if route.manual_override else "automatic",
                route_decision_id=route.id,
            )
            self._save_routing_metadata(raw, route)
            return ""
        if job.stage == "index":
            return self._index(raw, job)
        raise ValueError("unsupported_pipeline_stage")

    def _archive_original(self, raw) -> str:
        source = Path(raw.original_path)
        if not source.is_file():
            raise OSError("staged_asset_missing")
        public_id = self.pipeline.public_id_for(raw.id)
        destination_dir = self.asset_root / public_id / "original"
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / source.name
        if source.resolve() != destination.resolve():
            temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
        asset_id = self.pipeline.register_asset(
            clip_id=raw.id,
            role="original",
            filename=raw.filename,
            mime_type=raw.mime_type,
            size_bytes=raw.size_bytes,
            content_hash=raw.content_hash,
            storage_uri=str(destination),
            engine="filesystem",
            engine_version="v1",
        )
        self.pipeline.update_clip_archive(
            clip_id=raw.id,
            storage_uri=str(destination),
            archive_status="archived",
        )
        return asset_id

    def _extract_web(self, raw) -> str:
        acquired = acquire_web_document(
            raw.url,
            self.web_fetcher,
            adapters=DEFAULT_PLATFORM_ACQUISITION_ADAPTERS,
        )
        fetched = acquired.fetched
        raw_asset_id = self._write_derived_bytes(
            raw,
            role=acquired.raw_role,
            data=fetched.body,
            filename=acquired.raw_filename,
            mime_type=fetched.content_type,
            engine=acquired.acquisition_engine,
            engine_version=acquired.acquisition_engine_version,
        )
        del raw_asset_id
        extracted = acquired.extraction or extract_html_with_adapters(
            fetched.body,
            fetched.content_type,
            base_url=fetched.resolved_url,
            adapters=DEFAULT_PLATFORM_HTML_ADAPTERS,
        )
        canonical_url = extracted.canonical_url or fetched.canonical_url
        canonical_source = extracted.canonical_url_source or "fetch.resolved_url"
        if extracted.quality_reason == "additional_pages_not_fetched":
            parsed_canonical = urlsplit(canonical_url)
            query = [
                (key, value)
                for key, value in parse_qsl(parsed_canonical.query, keep_blank_values=True)
                if not (key.casefold() in {"page", "p"} and value == "1")
            ]
            canonical_url = urlunsplit(
                (
                    parsed_canonical.scheme,
                    parsed_canonical.netloc,
                    parsed_canonical.path,
                    urlencode(query, doseq=True),
                    "",
                )
            )
            canonical_source = "pagination.first_page_normalization"
        input_hash = hashlib.sha256(fetched.body).hexdigest()
        output_hash = hashlib.sha256(extracted.text.encode("utf-8")).hexdigest()
        explicit_title = explicit_title_hint(raw)
        title_value = explicit_title or extracted.title
        title_source = "user.title_hint" if explicit_title else extracted.title_source
        recall_eligible = extracted.status == "completed" or (
            extracted.status == "partial" and extracted.quality_reason != "browser_render_required"
        )
        author_field = _with_resolution_state(
            self._field_record(extracted.author, extracted.author_source, extracted, input_hash, output_hash),
            resolved=bool(extracted.author.strip() and extracted.author_source.strip()),
            unknown_label=UNKNOWN_SOURCE_LABEL,
            unknown_source="policy.explicit_unknown_source",
        )
        content_resolved = bool(extracted.text.strip())
        fields = {
            "title": self._field_record(title_value, title_source, extracted, input_hash, output_hash),
            "safe_original_url": self._field_record(fetched.safe_original_url, "fetch.normalized_request_url", extracted, input_hash, output_hash),
            "resolved_url": self._field_record(fetched.resolved_url, "fetch.redirect_resolution", extracted, input_hash, output_hash),
            "canonical_url": self._field_record(canonical_url, canonical_source, extracted, input_hash, output_hash),
            "author": author_field,
            "core_content": {
                "value": "" if content_resolved else UNAVAILABLE_CONTENT_LABEL,
                "source": "extraction.text" if content_resolved else "policy.explicit_unavailable_content",
                "engine": extracted.engine,
                "engine_version": extracted.engine_version,
                "input_hash": input_hash,
                "output_hash": output_hash,
                "confidence": extracted.quality_score if content_resolved else None,
                "reason": "extracted_text_available" if content_resolved else "explicit_data_unavailable",
                "resolution_state": "resolved" if content_resolved else "explicit_unavailable",
            },
            "published_at": self._field_record(extracted.published_at, extracted.published_at_source, extracted, input_hash, output_hash),
            "language": self._field_record(extracted.language, extracted.language_source, extracted, input_hash, output_hash),
        }
        return self._write_derived_text(
            raw,
            role="extracted_text",
            text=extracted.text,
            engine=extracted.engine,
            engine_version=extracted.engine_version,
            metadata={
                "extraction": {
                    "status": extracted.status,
                    "title": title_value,
                    "title_source": title_source,
                    "safe_original_url": fetched.safe_original_url,
                    "normalized_request_url": fetched.safe_original_url,
                    "original_url_hash": hashlib.sha256(raw.url.encode("utf-8")).hexdigest(),
                    "resolved_url": fetched.resolved_url,
                    "canonical_url": canonical_url,
                    "canonical_url_source": canonical_source,
                    "active_display_url": canonical_url or fetched.resolved_url,
                    "canonical_validation": {
                        "result": extracted.canonical_validation_result,
                        "provenance": "html.link.canonical" if extracted.canonical_validation_result != "not_present" else "fetch.resolved_url",
                        "source_host": extracted.canonical_source_host,
                        "canonical_host": extracted.canonical_host,
                        "cross_origin": extracted.canonical_cross_origin,
                    },
                    "redirect_summary": {
                        "count": len(fetched.redirect_chain),
                        "chain": list(fetched.redirect_chain),
                    },
                    "acquisition": {
                        "engine": acquired.acquisition_engine,
                        "engine_version": acquired.acquisition_engine_version,
                        "fallback_used": acquired.fallback_used,
                        "primary_safe_error_code": acquired.primary_safe_error_code,
                        "fallback_redirect_count": acquired.fallback_redirect_count,
                    },
                    "quality_score": extracted.quality_score,
                    "quality_reason": extracted.quality_reason,
                    "safe_error_code": "",
                    "recall_eligible": recall_eligible,
                    "raw_fallback_used": False,
                    "fields": fields,
                    "input_hash": input_hash,
                    "output_hash": output_hash,
                }
            },
        )

    def _write_derived_text(
        self,
        raw,
        *,
        role: str,
        text: str,
        engine: str = "",
        engine_version: str = "v1",
        metadata: dict[str, object] | None = None,
    ) -> str:
        suffix = "md" if role == "clean_markdown" else "txt"
        return self._write_derived_bytes(
            raw,
            role=role,
            data=text.encode("utf-8"),
            filename=f"{role}.{suffix}",
            mime_type="text/markdown" if suffix == "md" else "text/plain",
            engine=engine or STAGE_ENGINE["clean" if role == "clean_markdown" else "extract"][0],
            engine_version=engine_version,
            metadata=metadata,
        )

    def _write_derived_bytes(
        self,
        raw,
        *,
        role: str,
        data: bytes,
        filename: str,
        mime_type: str,
        engine: str,
        engine_version: str,
        metadata: dict[str, object] | None = None,
    ) -> str:
        public_id = self.pipeline.public_id_for(raw.id)
        destination_dir = self.asset_root / public_id / "derived"
        destination_dir.mkdir(parents=True, exist_ok=True)
        content_hash = hashlib.sha256(data).hexdigest()
        destination = destination_dir / filename
        if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() != content_hash:
            candidate = Path(filename)
            destination = destination_dir / (
                f"{candidate.stem}-{content_hash[:16]}{candidate.suffix}"
            )
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, destination)
        return self.pipeline.register_asset(
            clip_id=raw.id,
            role=role,
            filename=destination.name,
            mime_type=mime_type,
            size_bytes=len(data),
            content_hash=content_hash,
            storage_uri=str(destination),
            engine=engine,
            engine_version=engine_version,
            metadata=metadata,
        )

    def _index(self, raw, job: StoredPipelineJob) -> str:
        saved = self.store.find_normalized_metadata_by_clip_id(raw.id)
        metadata = dict(saved.metadata) if saved else {}
        processing = dict(metadata.get("processing", {})) if isinstance(metadata.get("processing"), dict) else {}
        active = processing.get("active_projection")
        active = dict(active) if isinstance(active, dict) else {}
        active_asset_id = str(active.get("source_asset_id") or "")
        pending_asset_id = str(processing.get("index_pending_projection_id") or "")
        eligible = bool(active.get("index_eligible", False))
        explicit_promotion = str(job.payload.get("sync_mode") or "") == "real"
        ragflow_mode = self.settings.ragflow.effective_mode
        enrichment_metadata = (
            dict(metadata.get("enrichment", {}))
            if isinstance(metadata.get("enrichment"), dict)
            else {}
        )
        topic_provenance = self.topic_store.active_index_provenance(raw.id)
        topic_ids = list(topic_provenance["topic_ids"])
        topic_taxonomy_version = str(topic_provenance["taxonomy_version"])
        topic_assignment_generation = str(
            topic_provenance["assignment_generation"]
        )
        if ragflow_mode in {"off", "qa"}:
            self._record_index_attempt(
                raw,
                metadata,
                status="disabled" if ragflow_mode == "off" else "capability_only",
                reason=f"ragflow_mode_{ragflow_mode}",
                projection_id=active_asset_id,
            )
            return ""
        if not eligible or not active_asset_id:
            reason = str(active.get("index_reason") or "no_new_eligible_projection")
            self._record_index_attempt(
                raw,
                metadata,
                status="skipped_quality_gate",
                reason=reason,
                projection_id=str(active.get("source_asset_id") or ""),
            )
            return ""
        if pending_asset_id != active_asset_id and not explicit_promotion:
            attempted = processing.get("latest_attempted_projection")
            attempted = dict(attempted) if isinstance(attempted, dict) else {}
            self._record_index_attempt(
                raw,
                metadata,
                status="skipped_no_new_projection",
                reason="no_new_eligible_projection",
                projection_id=str(attempted.get("source_asset_id") or ""),
            )
            return ""
        clean_asset = self.pipeline.find_asset(active_asset_id)
        if clean_asset is None or str(clean_asset.get("role")) != "clean_markdown":
            self._record_index_attempt(
                raw,
                metadata,
                status="skipped_quality_gate",
                reason="active_clean_asset_missing",
                projection_id=active_asset_id,
            )
            return ""
        public_id = self.pipeline.public_id_for(raw.id)
        generation_id = self._generation_public_id(public_id, active_asset_id)
        index_generation_id = self._index_generation_public_id(
            public_id,
            active_asset_id,
            topic_ids,
            topic_taxonomy_version,
            topic_assignment_generation,
        )
        index_statuses: list[str] = []
        try:
            for association in self.pipeline.list_knowledge_base_associations(clip_id=raw.id):
                knowledge_base_id = str(association["knowledge_base_id"])
                knowledge_base = self.knowledge_store.get_knowledge_base(knowledge_base_id)
                if knowledge_base is None or not knowledge_base.ragflow_dataset_id:
                    continue
                operation_key = build_operation_key(
                    provider="ragflow",
                    dataset_id=knowledge_base.ragflow_dataset_id,
                    clip_public_id=public_id,
                    generation_public_id=index_generation_id,
                    content_hash=str(clean_asset["content_hash"]),
                    association_intent_id=str(
                        association.get("association_intent_id") or ""
                    ),
                )
                index_metadata = build_index_metadata(
                    clip_public_id=public_id,
                    generation_public_id=index_generation_id,
                    knowledge_base_id=knowledge_base_id,
                    topic_ids=topic_ids,
                    topic_taxonomy_version=topic_taxonomy_version,
                    topic_assignment_generation=topic_assignment_generation,
                    source_type=str(raw.source_type),
                    language=str(enrichment_metadata.get("language") or ""),
                    quality_status=(
                        "partial"
                        if str(active.get("extraction_status") or "") == "partial"
                        else "completed"
                    ),
                    content_hash=str(clean_asset["content_hash"]),
                    operation_key=operation_key,
                )
                attempt = self.pipeline.ensure_index_attempt(
                    operation_key=operation_key,
                    clip_id=raw.id,
                    knowledge_base_id=knowledge_base_id,
                    index_provider="ragflow",
                    dataset_id=knowledge_base.ragflow_dataset_id,
                    association_intent_id=str(
                        association.get("association_intent_id") or ""
                    ),
                    generation_id=index_generation_id,
                    content_hash=str(clean_asset["content_hash"]),
                    metadata_json=compact_metadata_json(index_metadata),
                    status="planned",
                )
                if str(attempt["status"]) == "indexed_verified":
                    index_statuses.append("indexed_verified")
                    continue
                if not self.settings.ragflow.real_sync_enabled:
                    self.pipeline.upsert_index_document(
                        clip_id=raw.id,
                        knowledge_base_id=knowledge_base_id,
                        index_provider="ragflow",
                        dataset_id=knowledge_base.ragflow_dataset_id,
                        document_id="",
                        content_hash=str(clean_asset["content_hash"]),
                        status="planned",
                    )
                    index_statuses.append("planned")
                    continue
                self._index_one(
                    dataset_id=knowledge_base.ragflow_dataset_id,
                    operation_key=operation_key,
                    public_id=public_id,
                    content_or_path=str(clean_asset["storage_uri"]),
                    metadata=index_metadata,
                )
                index_statuses.append("indexed_verified")
        except Exception:
            self._record_index_attempt(
                raw,
                metadata,
                status="failed",
                reason="ragflow_index_failed",
                projection_id=active_asset_id,
            )
            raise
        if "indexed_verified" in index_statuses:
            processing["index_pending_projection_id"] = ""
            processing["last_indexed_projection_id"] = active_asset_id
            active_index = self._index_state(
                status="indexed_verified",
                projection_id=active_asset_id,
                reason=str(active.get("index_reason") or "eligible_projection"),
            )
            latest_status = "completed"
            latest_reason = str(active.get("index_reason") or "eligible_projection")
        elif "planned" in index_statuses:
            processing["index_pending_projection_id"] = ""
            existing_active = processing.get("active_index")
            active_index = (
                dict(existing_active)
                if isinstance(existing_active, dict)
                else self._index_state(
                    status="not_indexed",
                    projection_id="",
                    reason="awaiting_verified_index",
                )
            )
            latest_status = "planned"
            latest_reason = "dry_run_no_remote_call"
        else:
            active_index = self._index_state(
                status="not_indexed",
                projection_id=active_asset_id,
                reason="no_dataset_mapping",
            )
            latest_status = "skipped_no_dataset_mapping"
            latest_reason = "no_dataset_mapping"
        processing["active_index"] = active_index
        processing["latest_index_attempt"] = self._index_attempt(
            status=latest_status,
            projection_id=active_asset_id,
            reason=latest_reason,
        )
        metadata["processing"] = processing
        self.store.save_normalized_metadata(
            clip_id=raw.id, client_request_id=raw.client_request_id, metadata=metadata
        )
        return ""

    def _index_one(
        self,
        *,
        dataset_id: str,
        operation_key: str,
        public_id: str,
        content_or_path: str,
        metadata: dict[str, object],
    ) -> None:
        attempt = self.pipeline.find_index_attempt(operation_key=operation_key)
        if attempt is None:
            raise RuntimeError("index attempt missing")
        document_id = str(attempt["document_id"])
        if not document_id:
            try:
                matches = self.ragflow.find_document_by_operation_key(
                    dataset_id, operation_key
                )
            except RagflowAdapterError:
                self.pipeline.update_index_attempt(
                    operation_key=operation_key,
                    status="failed_retryable",
                    safe_error_code="remote_lookup_failed",
                )
                raise
            if len(matches) > 1:
                self.pipeline.update_index_attempt(
                    operation_key=operation_key,
                    status="failed_terminal",
                    safe_error_code="remote_operation_ambiguous",
                )
                raise ValueError("remote_operation_ambiguous")
            if matches:
                document_id = matches[0].document_id
            else:
                self.pipeline.update_index_attempt(
                    operation_key=operation_key, status="uploading"
                )
                try:
                    reference = self.ragflow.upload_document(
                        dataset_id,
                        deterministic_document_name(public_id, operation_key),
                        content_or_path,
                        meta_fields=metadata,
                        dry_run=False,
                    )
                    document_id = reference.document_id
                except (OSError, RagflowAdapterError):
                    try:
                        recovered = self.ragflow.find_document_by_operation_key(
                            dataset_id, operation_key
                        )
                    except RagflowUnsupportedError:
                        self.pipeline.update_index_attempt(
                            operation_key=operation_key,
                            status="failed_terminal",
                            safe_error_code="remote_recovery_unsupported",
                        )
                        raise
                    except RagflowAdapterError:
                        self.pipeline.update_index_attempt(
                            operation_key=operation_key,
                            status="failed_retryable",
                            safe_error_code="remote_recovery_failed",
                        )
                        raise
                    if len(recovered) > 1:
                        self.pipeline.update_index_attempt(
                            operation_key=operation_key,
                            status="failed_terminal",
                            safe_error_code="remote_operation_ambiguous",
                        )
                        raise ValueError("remote_operation_ambiguous")
                    if not recovered:
                        self.pipeline.update_index_attempt(
                            operation_key=operation_key,
                            status="failed_retryable",
                            safe_error_code="remote_upload_outcome_unknown",
                        )
                        raise
                    document_id = recovered[0].document_id
            self.pipeline.update_index_attempt(
                operation_key=operation_key,
                status="uploaded",
                document_id=document_id,
            )
        try:
            self.ragflow.update_document_meta(
                dataset_id, document_id, metadata, dry_run=False
            )
        except RagflowUnsupportedError:
            self.pipeline.update_index_attempt(
                operation_key=operation_key,
                status="failed_terminal",
                safe_error_code="remote_metadata_unsupported",
            )
            raise
        except RagflowAdapterError:
            self.pipeline.update_index_attempt(
                operation_key=operation_key,
                status="failed_retryable",
                safe_error_code="remote_metadata_failed",
            )
            raise

        try:
            status = self.ragflow.get_document_status(dataset_id, document_id)
        except RagflowUnsupportedError:
            self.pipeline.update_index_attempt(
                operation_key=operation_key,
                status="failed_terminal",
                safe_error_code="remote_status_unsupported",
            )
            raise
        except RagflowAdapterError:
            self.pipeline.update_index_attempt(
                operation_key=operation_key,
                status="failed_retryable",
                safe_error_code="remote_status_failed",
            )
            raise
        if status.status == "unstart":
            try:
                self.ragflow.request_parse(dataset_id, document_id)
            except RagflowUnsupportedError:
                self.pipeline.update_index_attempt(
                    operation_key=operation_key,
                    status="failed_terminal",
                    remote_status=status.status,
                    safe_error_code="remote_parse_unsupported",
                )
                raise
            except RagflowAdapterError:
                self.pipeline.update_index_attempt(
                    operation_key=operation_key,
                    status="failed_retryable",
                    remote_status=status.status,
                    safe_error_code="remote_parse_request_failed",
                )
                raise
            self.pipeline.update_index_attempt(
                operation_key=operation_key,
                status="parse_requested",
                remote_status=status.status,
            )
        elif status.status in {"failed", "cancelled", "missing", "unknown"}:
            self.pipeline.update_index_attempt(
                operation_key=operation_key,
                status="failed_terminal",
                remote_status=status.status,
                safe_error_code=f"remote_status_{status.status}",
            )
            raise ValueError(f"remote_status_{status.status}")

        deadline = time.monotonic() + self.settings.ragflow.index_poll_timeout_seconds
        while status.status in {"unstart", "scheduled", "running"}:
            if time.monotonic() >= deadline:
                self.pipeline.update_index_attempt(
                    operation_key=operation_key,
                    status="failed_retryable",
                    remote_status=status.status,
                    safe_error_code="remote_parse_timeout",
                )
                raise RagflowAdapterError("remote_parse_timeout")
            self.pipeline.update_index_attempt(
                operation_key=operation_key,
                status="parsing",
                remote_status=status.status,
            )
            self._sleep(self.settings.ragflow.index_poll_backoff_seconds)
            try:
                status = self.ragflow.get_document_status(dataset_id, document_id)
            except RagflowUnsupportedError:
                self.pipeline.update_index_attempt(
                    operation_key=operation_key,
                    status="failed_terminal",
                    safe_error_code="remote_status_unsupported",
                )
                raise
            except RagflowAdapterError:
                self.pipeline.update_index_attempt(
                    operation_key=operation_key,
                    status="failed_retryable",
                    safe_error_code="remote_status_failed",
                )
                raise
            if status.status in {"failed", "cancelled", "missing", "unknown"}:
                self.pipeline.update_index_attempt(
                    operation_key=operation_key,
                    status="failed_terminal",
                    remote_status=status.status,
                    safe_error_code=f"remote_status_{status.status}",
                )
                raise ValueError(f"remote_status_{status.status}")

        try:
            chunks = self.ragflow.get_chunk_summary(dataset_id, document_id)
            vectors = self.ragflow.get_vector_evidence(dataset_id, document_id)
        except RagflowUnsupportedError:
            self.pipeline.update_index_attempt(
                operation_key=operation_key,
                status="failed_terminal",
                remote_status=status.status,
                safe_error_code="remote_verification_unsupported",
            )
            raise
        except RagflowAdapterError:
            self.pipeline.update_index_attempt(
                operation_key=operation_key,
                status="failed_retryable",
                remote_status=status.status,
                safe_error_code="remote_verification_failed",
            )
            raise
        verification = verify_index(
            status=status,
            chunks=chunks,
            vectors=vectors,
            expected_metadata=metadata,
        )
        if not verification.verified:
            self.pipeline.update_index_attempt(
                operation_key=operation_key,
                status="failed_terminal",
                remote_status=status.status,
                chunk_count=chunks.chunk_count,
                vector_count=vectors.vector_count,
                safe_error_code=verification.safe_error_code,
            )
            raise ValueError(verification.safe_error_code)
        self.pipeline.update_index_attempt(
            operation_key=operation_key,
            status="indexed_verified",
            remote_status=status.status,
            chunk_count=chunks.chunk_count,
            vector_count=vectors.vector_count,
            safe_error_code="",
        )
        self.pipeline.activate_verified_index(operation_key=operation_key)

    @staticmethod
    def _generation_public_id(public_id: str, asset_id: str) -> str:
        material = "\0".join((public_id, asset_id, "quality-read-generation-v1"))
        return "gen_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _index_generation_public_id(
        public_id: str,
        asset_id: str,
        topic_ids: list[str],
        taxonomy_version: str = "",
        assignment_generation: str = "",
    ) -> str:
        material = "\0".join(
            (
                public_id,
                asset_id,
                json.dumps(sorted(set(topic_ids)), separators=(",", ":")),
                taxonomy_version,
                assignment_generation,
                "ragflow-index-generation-v3",
            )
        )
        return "gen_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _index_state(*, status: str, projection_id: str, reason: str) -> dict[str, object]:
        return {
            "status": status,
            "projection_id": projection_id,
            "reason": reason,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _index_attempt(*, status: str, projection_id: str, reason: str) -> dict[str, object]:
        return {
            "status": status,
            "projection_id": projection_id,
            "reason": reason,
            "attempted_at": datetime.now(timezone.utc).isoformat(),
        }

    def _record_index_attempt(
        self,
        raw,
        metadata,
        *,
        status: str,
        reason: str,
        projection_id: str,
    ) -> None:
        processing = dict(metadata.get("processing", {})) if isinstance(metadata.get("processing"), dict) else {}
        if not isinstance(processing.get("active_index"), dict):
            prior_projection_id = str(processing.get("last_indexed_projection_id") or "")
            if prior_projection_id:
                index_statuses = {
                    str(item.get("status") or "")
                    for item in self.pipeline.processing_summary(clip_id=raw.id)["indexes"]
                }
                prior_status = (
                    "indexed_verified"
                    if "indexed_verified" in index_statuses
                    else "historical_unverified"
                )
                processing["active_index"] = self._index_state(
                    status=prior_status,
                    projection_id=prior_projection_id,
                    reason="legacy_index_state_migrated",
                )
            else:
                processing["active_index"] = self._index_state(
                    status="not_indexed",
                    projection_id="",
                    reason="never_indexed",
                )
        processing["latest_index_attempt"] = self._index_attempt(
            status=status,
            projection_id=projection_id,
            reason=reason,
        )
        metadata["processing"] = processing
        self.store.save_normalized_metadata(
            clip_id=raw.id, client_request_id=raw.client_request_id, metadata=metadata
        )

    def _continue_after_extract_failure(self, job: StoredPipelineJob, safe_error_code: str) -> None:
        raw = self.store.find_raw_fields_by_clip_id(int(job.clip_id))
        if raw is None:
            return
        explicit_title = explicit_title_hint(raw)
        # A failed URL fetch may retain user-supplied body text, but neither the
        # title nor the URL is evidence of independently acquired core content.
        fallback = raw.note.strip() or raw.text.strip()
        safe_url = "" if safe_error_code in {"private_address_blocked", "unsupported_url"} else self._safe_normalized_url(raw.url)
        input_hash = hashlib.sha256(raw.url.encode("utf-8")).hexdigest()
        output_hash = hashlib.sha256(fallback.encode("utf-8")).hexdigest()

        def minimal_field(value: str, source: str) -> dict[str, object]:
            present = bool(value.strip())
            return {
                "value": safe_short_text(value), "source": source if present else "",
                "engine": "raw-fallback", "engine_version": "v2",
                "input_hash": input_hash, "output_hash": output_hash,
                "confidence": 1.0 if present and source == "user.title_hint" else (0.8 if present else None),
                "reason": "selected_by_precedence" if present else "not_reliably_available",
            }
        asset_id = self._write_derived_text(
            raw,
            role="extracted_text",
            text=fallback,
            engine="raw-fallback",
            engine_version="v2",
            metadata={
                "extraction": {
                    "status": "failed",
                    "title": explicit_title,
                    "title_source": "user.title_hint" if explicit_title else "",
                    "safe_original_url": safe_url,
                    "normalized_request_url": safe_url,
                    "original_url_hash": input_hash,
                    "resolved_url": "",
                    "canonical_url": "",
                    "active_display_url": "",
                    "quality_score": None,
                    "quality_reason": "raw_fallback_after_terminal_failure",
                    "safe_error_code": safe_error_code,
                    "recall_eligible": False,
                    "raw_fallback_used": True,
                    "fields": {
                        "title": minimal_field(explicit_title, "user.title_hint"),
                        "author": _with_resolution_state(
                            minimal_field("", ""),
                            resolved=False,
                            unknown_label=UNKNOWN_SOURCE_LABEL,
                            unknown_source="policy.explicit_unknown_source",
                        ),
                        "core_content": {
                            **minimal_field(UNAVAILABLE_CONTENT_LABEL, "policy.explicit_unavailable_content"),
                            "confidence": None,
                            "reason": "explicit_data_unavailable",
                            "resolution_state": "explicit_unavailable",
                        },
                    },
                    "input_hash": input_hash,
                    "output_hash": output_hash,
                }
            },
        )
        self.pipeline.enqueue(
            clip_id=raw.id,
            stage="clean",
            engine=STAGE_ENGINE["clean"][0],
            engine_version=STAGE_ENGINE["clean"][1],
            input_hash=self.pipeline.asset_hash(asset_id) or job.input_hash,
            payload={"fallback_from_failed_job_id": job.id},
        )

    def _enrichment_projection(self, raw) -> EnrichmentInputProjection:
        clean = self.pipeline.latest_asset(clip_id=raw.id, role="clean_markdown")
        extracted = self.pipeline.latest_asset(clip_id=raw.id, role="extracted_text")
        source = clean or extracted
        metadata = self.pipeline.asset_metadata(source)
        extraction = metadata.get("extraction")
        extraction = extraction if isinstance(extraction, dict) else {}
        text = self._read_asset_text(source) if source else self._extract_text(raw)
        if (
            not text.strip()
            and str(extraction.get("status") or "") != "failed"
            and source is not extracted
            and extracted is not None
        ):
            source = extracted
            metadata = self.pipeline.asset_metadata(source)
            extraction = metadata.get("extraction")
            extraction = extraction if isinstance(extraction, dict) else {}
            text = self._read_asset_text(source)
        quality = extraction.get("quality_score")
        extraction_status = str(extraction.get("status") or ("completed" if source else "raw_fallback"))
        projected_text = text
        if not projected_text and extraction_status != "failed":
            projected_text = self._extract_text(raw)
        canonical_url = str(extraction.get("canonical_url") or "")
        if not canonical_url and raw.url.strip():
            try:
                canonical_url = canonicalize_url(raw.url)
            except WebFetchError:
                canonical_url = ""
        return EnrichmentInputProjection(
            text=projected_text,
            title=explicit_title_hint(raw) or str(extraction.get("title") or ""),
            resolved_url=str(extraction.get("resolved_url") or ""),
            canonical_url=canonical_url,
            extraction_status=extraction_status,
            quality_score=float(quality) if isinstance(quality, (int, float)) else None,
            source_asset_id=str(source.get("id") or "") if source else "",
            source_asset_role=str(source.get("role") or "raw") if source else "raw",
            safe_error_code=str(extraction.get("safe_error_code") or ""),
            quality_reason=str(extraction.get("quality_reason") or ""),
            recall_eligible=bool(extraction.get("recall_eligible", True)),
            raw_fallback_used=bool(extraction.get("raw_fallback_used", False)),
            structured_metadata=dict(extraction.get("fields", {})) if isinstance(extraction.get("fields"), dict) else {},
        )

    def _save_projection_metadata(self, raw, projection: EnrichmentInputProjection, enrichment) -> None:
        saved = self.store.find_normalized_metadata_by_clip_id(raw.id)
        metadata = dict(saved.metadata) if saved else {}
        clip = dict(metadata.get("clip", {})) if isinstance(metadata.get("clip"), dict) else {}
        attempt = {**projection.to_metadata(), "enrichment_id": enrichment.id}
        provenance = (
            dict(metadata.get("provenance", {}))
            if isinstance(metadata.get("provenance"), dict)
            else {}
        )
        processing = (
            dict(metadata.get("processing", {}))
            if isinstance(metadata.get("processing"), dict)
            else {}
        )
        processing["extraction_status"] = projection.extraction_status
        processing["quality_reason"] = projection.quality_reason
        processing["safe_error_code"] = projection.safe_error_code
        processing["raw_fallback_used"] = projection.raw_fallback_used
        processing["recall_eligible"] = projection.recall_eligible
        processing["extraction"] = attempt
        processing["latest_attempted_projection"] = attempt
        processing["latest_attempted_enrichment_id"] = enrichment.id
        usable = projection.index_eligible
        if usable:
            processing["latest_successful_projection"] = attempt
            processing["active_projection"] = attempt
            processing["active_enrichment_id"] = enrichment.id
            processing["index_pending_projection_id"] = projection.source_asset_id
        elif not isinstance(processing.get("active_projection"), dict):
            processing["active_projection"] = attempt
            processing["active_enrichment_id"] = enrichment.id
            processing["index_pending_projection_id"] = ""
        active = dict(processing["active_projection"])
        active_enrichment_id = int(processing.get("active_enrichment_id") or enrichment.id)
        active_enrichment = self.store.find_enrichment_by_id(active_enrichment_id) or enrichment
        clip.update(
            {
                "title_hint": active_enrichment.title,
                "text": active_enrichment.extracted_text,
                "url": str(active.get("canonical_url") or active.get("resolved_url") or ""),
                "language_hint": active_enrichment.language,
                "tags_hint": active_enrichment.tags,
            }
        )
        metadata["clip"] = clip
        provenance["source_url"] = clip["url"]
        metadata["provenance"] = provenance
        metadata["processing"] = processing
        metadata["projection"] = active
        metadata["enrichment"] = {
            "clip_id": active_enrichment.clip_id,
            "client_request_id": active_enrichment.client_request_id,
            "knowledge_base_id": active_enrichment.knowledge_base_id,
            "route_decision_id": active_enrichment.route_decision_id,
            "engine": active_enrichment.engine,
            "status": active_enrichment.status,
            "title": active_enrichment.title,
            "summary": active_enrichment.summary,
            "tags": active_enrichment.tags,
            "key_points": active_enrichment.key_points,
            "language": active_enrichment.language,
            "extracted_text": active_enrichment.extracted_text,
            "error_code": active_enrichment.error_code,
            "error_message": active_enrichment.error_message,
        }
        self.store.save_normalized_metadata(
            clip_id=raw.id,
            client_request_id=raw.client_request_id,
            metadata=metadata,
        )

    def _quality_route_preview(self, raw, clean_asset, payload: RoutingPreviewInput):
        metadata = self.pipeline.asset_metadata(clean_asset) if clean_asset else {}
        extraction = metadata.get("extraction")
        extraction = extraction if isinstance(extraction, dict) else {}
        if not bool(extraction.get("recall_eligible", True)):
            inbox = next(
                (
                    item
                    for item in self.knowledge_store.list_knowledge_bases()
                    if not item.is_archived and item.name.strip().casefold() in {"收件箱", "inbox"}
                ),
                None,
            )
            if inbox is not None:
                reason = str(extraction.get("quality_reason") or extraction.get("safe_error_code") or "quality_attention_required")
                return preview_for_target(
                    inbox,
                    decision_type="quality",
                    matched_rule_id="",
                    matched_rule_ids=[],
                    confidence=1.0,
                    manual_override=False,
                    reason=f'quality gate "{reason}" -> "{inbox.name}"',
                )
        return preview_route(self.knowledge_store, payload)

    @staticmethod
    def _field_record(value, source, extracted, input_hash: str, output_hash: str) -> dict[str, object]:
        safe_value = safe_short_text(str(value or ""))
        present = bool(safe_value)
        return {
            "value": safe_value,
            "source": str(source or ""),
            "engine": extracted.engine,
            "engine_version": extracted.engine_version,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "confidence": 1.0 if present and source in {"user.title_hint", "html.link.canonical", "fetch.normalized_request_url"} else (0.8 if present else None),
            "reason": "selected_by_precedence" if present else "not_reliably_available",
        }

    def _save_routing_metadata(self, raw, route) -> None:
        saved = self.store.find_normalized_metadata_by_clip_id(raw.id)
        if saved is None:
            return
        knowledge_base = self.knowledge_store.get_knowledge_base(
            route.knowledge_base_id, include_deleted=True
        )
        metadata = dict(saved.metadata)
        metadata["routing"] = {
            "knowledge_base_id": route.knowledge_base_id,
            "knowledge_base_name": knowledge_base.name if knowledge_base else "",
            "ragflow_dataset_id": route.ragflow_dataset_id,
            "decision_type": route.decision_type,
            "matched_rule_ids": route.matched_rule_ids,
            "reason": route.reason,
            "manual_override": route.manual_override,
            "routed_at": route.created_at,
        }
        self.store.save_normalized_metadata(
            clip_id=raw.id,
            client_request_id=raw.client_request_id,
            metadata=metadata,
        )

    @staticmethod
    def _extract_text(raw) -> str:
        if raw.text.strip():
            return raw.text.strip()
        if raw.note.strip():
            return raw.note.strip()
        if raw.url.strip():
            return raw.url.strip()
        return raw.filename.strip()

    @staticmethod
    def _safe_normalized_url(value: str) -> str:
        try:
            return canonicalize_url(value)
        except WebFetchError:
            return ""

    @staticmethod
    def _read_asset_text(asset: dict[str, object]) -> str:
        path = Path(str(asset["storage_uri"]))
        return path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def _next_stage(stage: str) -> str:
        index = PIPELINE_STAGES.index(stage)
        return PIPELINE_STAGES[index + 1] if index + 1 < len(PIPELINE_STAGES) else ""

    @staticmethod
    def _safe_error_code(error: Exception) -> str:
        if isinstance(error, WebFetchError):
            candidate = str(error).strip().lower()
            if candidate in {
                "unsupported_url", "dns_resolution_failed", "private_address_blocked",
                "redirect_limit_exceeded", "redirect_missing_location",
                "upstream_http_error", "unsupported_content_type", "response_too_large",
                "web_fetch_failed", "bilibili_identity_unsupported",
                "bilibili_acquisition_fetch_failed", "bilibili_metadata_invalid",
                "bilibili_metadata_unavailable", "bilibili_identity_mismatch",
                "bilibili_metadata_insufficient", "bilibili_metadata_source_mismatch",
                "bilibili_metadata_content_type_invalid",
            }:
                return candidate
            return "web_fetch_failed"
        if isinstance(error, RagflowAdapterError):
            return "ragflow_index_failed"
        if isinstance(error, sqlite3.OperationalError):
            return "database_temporarily_unavailable"
        if isinstance(error, OSError):
            return "asset_io_failed"
        candidate = str(error).strip().lower()
        if candidate in {
            "clip_not_found", "original_asset_missing", "clean_asset_missing",
            "route_decision_missing", "unsupported_pipeline_stage",
        }:
            return candidate
        return "pipeline_stage_failed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the durable PerClip processing worker")
    parser.add_argument("--once", action="store_true", help="claim one batch and exit")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)
    worker = PipelineWorker(Settings.from_env())
    while True:
        processed = worker.run_once(limit=max(1, args.limit))
        if args.once:
            return 0
        if processed == 0:
            time.sleep(max(0.1, args.poll_seconds))


if __name__ == "__main__":
    sys.exit(main())
