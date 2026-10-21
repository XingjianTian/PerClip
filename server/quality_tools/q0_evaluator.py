from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from perclip_ingest.config import RagflowSettings, Settings
from perclip_ingest.content_cleaning import clean_content
from perclip_ingest.ingest_models import (
    INGEST_CONTRACT_VERSION,
    IngestAsset,
    IngestCapture,
    IngestClip,
    IngestCommand,
    IngestRouting,
    IngestSource,
)
from perclip_ingest.ingest_service import IngestService, IngestUnsupportedMediaError
from perclip_ingest.knowledge_base_store import KnowledgeBaseStore
from perclip_ingest.pipeline_store import PipelineStore
from perclip_ingest.ragflow_adapter import RagflowAdapterError, RagflowDocumentRef
from perclip_ingest.recall import candidate_from_row
from perclip_ingest.storage import ClipStore
from perclip_ingest.web_extraction import (
    ALLOWED_CONTENT_TYPES,
    REDIRECT_STATUSES,
    WebFetchError,
    WebFetchResult,
    canonicalize_url,
    extract_html,
)
from perclip_ingest.worker import PipelineWorker, STAGE_ENGINE


REPORT_SCHEMA = "perclip.quality.q0.v2"
EVALUATOR_ENGINE = "perclip-q0-evaluator"
EVALUATOR_VERSION = "v2"
CANDIDATE_EVALUATOR_VERSION = "v5"
EVALUATION_TIME = datetime(2026, 7, 21, tzinfo=timezone.utc)


class EvaluationClock:
    def __init__(self) -> None:
        self.value = datetime.now(timezone.utc) + timedelta(seconds=1)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float = 1.0) -> None:
        self.value += timedelta(seconds=seconds)


class ResponsePlanFetcher:
    """Test-only transport adapter; it never opens a socket or relaxes production policy."""

    def __init__(self, fixture_root: Path, plan_path: str, *, default_max_bytes: int = 5 * 1024 * 1024) -> None:
        self.fixture_root = fixture_root
        self.plan_path = plan_path
        self.plan = json.loads((fixture_root / plan_path).read_text(encoding="utf-8"))
        self.max_bytes = int(self.plan.get("max_bytes", default_max_bytes))
        self.max_redirects = int(self.plan.get("max_redirects", 5))
        self._steps: dict[str, dict[str, Any]] = {}
        for step in self.plan.get("steps", []):
            self._steps[canonicalize_url(str(step["url"]))] = dict(step)

    def fetch(self, url: str) -> WebFetchResult:
        original = canonicalize_url(url)
        current = original
        for redirect_count in range(self.max_redirects + 1):
            step = self._steps.get(current)
            if step is None:
                raise WebFetchError("web_fetch_failed")
            resolution = str(step.get("resolution", "public"))
            connection = str(step.get("connect_address", "validated"))
            if resolution != "public" or connection in {"blocked", "private_rebind"}:
                raise WebFetchError("private_address_blocked")
            if step.get("error") == "timeout":
                raise WebFetchError("web_fetch_failed")
            status = int(step.get("status", 200))
            headers = {str(key).lower(): str(value) for key, value in dict(step.get("headers", {})).items()}
            if status in REDIRECT_STATUSES:
                if redirect_count >= self.max_redirects:
                    raise WebFetchError("redirect_limit_exceeded")
                location = headers.get("location", "").strip()
                if not location:
                    raise WebFetchError("redirect_missing_location")
                current = canonicalize_url(urljoin(current, location))
                continue
            if status < 200 or status >= 300:
                raise WebFetchError("upstream_http_error")
            content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type not in ALLOWED_CONTENT_TYPES:
                raise WebFetchError("unsupported_content_type")
            declared = headers.get("content-length", "")
            if declared.isdigit() and int(declared) > self.max_bytes:
                raise WebFetchError("response_too_large")
            body = self._body(step)
            if len(body) > self.max_bytes:
                raise WebFetchError("response_too_large")
            return WebFetchResult(
                safe_original_url=original,
                resolved_url=current,
                canonical_url=canonicalize_url(current),
                content_type=content_type,
                body=body,
                redirect_chain=tuple(
                    item for item in [current] if current != original
                ),
            )
        raise WebFetchError("redirect_limit_exceeded")

    def _body(self, step: dict[str, Any]) -> bytes:
        if step.get("body_fixture"):
            return (self.fixture_root / str(step["body_fixture"])).read_bytes()
        if step.get("body_size"):
            return b"x" * int(step["body_size"])
        return str(step.get("inline_body", "")).encode("utf-8")


class NoopRagflow:
    def upload_document(self, *_args, **_kwargs):
        raise AssertionError("Q0 corpus cases must not call RAGFlow")

    def update_document_meta(self, *_args, **_kwargs):
        raise AssertionError("Q0 corpus cases must not call RAGFlow")


class FailingRagflow:
    def find_document_by_operation_key(self, *_args, **_kwargs):
        raise RagflowAdapterError("synthetic_index_fault")

    def upload_document(self, *_args, **_kwargs):
        raise RagflowAdapterError("synthetic_index_fault")

    def update_document_meta(self, *_args, **_kwargs):
        raise RagflowAdapterError("synthetic_index_fault")


class RecordingRagflow:
    def __init__(self) -> None:
        self.uploads = 0
        self.meta_updates = 0

    def upload_document(self, dataset_id, name, content_or_path, meta_fields=None, dry_run=True):
        del content_or_path
        self.uploads += 1
        return RagflowDocumentRef(
            dataset_id=dataset_id,
            document_id=f"synthetic-{self.uploads}",
            name=name,
            meta_fields=meta_fields or {},
            dry_run=dry_run,
        )

    def update_document_meta(self, *_args, **_kwargs):
        self.meta_updates += 1
        return {"ok": True}


def load_manifest(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected_ids = [f"G{index:02d}" for index in range(1, 23)] + [f"G{index:02d}" for index in range(37, 41)]
    if [str(row.get("id")) for row in rows] != expected_ids:
        raise ValueError("Q0 manifest must contain exactly G01-G22 and G37-G40")
    root = path.parent
    for row in rows:
        if (
            row.get("tier") != "q0-web"
            or row.get("fixture_version") != "q0-web-v1"
            or row.get("license") != "CC0-1.0"
            or not row.get("source_class")
            or not isinstance(row.get("expected"), dict)
        ):
            raise ValueError(f"invalid Q0 metadata for {row.get('id')}")
        artifacts = row.get("artifacts", [])
        if not artifacts:
            raise ValueError(f"missing Q0 artifacts for {row.get('id')}")
        for artifact in artifacts:
            relative_path = Path(str(artifact.get("path", "")))
            if (
                relative_path.is_absolute()
                or ".." in relative_path.parts
                or not artifact.get("license")
                or not artifact.get("source_class")
                or not artifact.get("sha256")
            ):
                raise ValueError(f"invalid Q0 artifact metadata for {row.get('id')}")
            artifact_path = root / relative_path
            digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            if digest != artifact.get("sha256"):
                raise ValueError(f"fixture hash mismatch: {artifact_path}")
    return rows


def _settings(data_dir: Path) -> Settings:
    return Settings(
        data_dir=data_dir,
        ingest_token="quality-local-only",
        processing_mode="worker",
        asset_root=data_dir / "PersonalClips",
        deployment_environment="quality",
        enable_web_fetch=True,
        web_fetch_max_bytes=8192,
        web_fetch_timeout_seconds=1,
    )


def _real_index_settings(data_dir: Path, dataset_id: str) -> Settings:
    return Settings(
        data_dir=data_dir,
        ingest_token="quality-local-only",
        processing_mode="worker",
        asset_root=data_dir / "PersonalClips",
        deployment_environment="quality",
        enable_web_fetch=True,
        web_fetch_max_bytes=8192,
        web_fetch_timeout_seconds=1,
        ragflow=RagflowSettings(
            base_url="http://ragflow.invalid",
            api_key="synthetic",
            enable_real_sync=True,
            sync_allow_dataset_ids=frozenset({dataset_id}),
        ),
    )


def _service(settings: Settings) -> IngestService:
    store = ClipStore(settings.data_dir)
    store.init()
    knowledge = KnowledgeBaseStore(settings.data_dir)
    knowledge.init()
    pipeline = PipelineStore(settings.data_dir)
    pipeline.init()
    return IngestService(
        store=store,
        knowledge_store=knowledge,
        pipeline_store=pipeline,
        processing_mode="worker",
        deployment_environment="quality",
    )


def _configure_quality_routing(service: IngestService) -> None:
    store = service.knowledge_store
    research = store.create_knowledge_base(name="研究资料", is_default=True)
    work = store.create_knowledge_base(name="工作方法")
    life = store.create_knowledge_base(name="生活记录")
    inbox = store.create_knowledge_base(name="收件箱")
    for name, pattern, target, priority in (
        ("Dynamic pages", "需要浏览器渲染", inbox.id, 10),
        ("Offline queue", "离线队列", work.id, 20),
        ("Fixture runner", "Fixture Runner", work.id, 30),
        ("Launcher checks", "桌面图标", work.id, 40),
        ("Weekly reading", "每周阅读", life.id, 50),
    ):
        store.create_routing_rule(
            name=name,
            rule_type="keyword",
            pattern=pattern,
            target_knowledge_base_id=target,
            priority=priority,
        )
    assert research.is_default


def _case_command(row: dict[str, Any], fixture_root: Path) -> IngestCommand:
    fixture_id = str(row["id"])
    fields = dict(row["input"])
    source_type = str(fields["source_type"])
    fixture = fixture_root / str(row["fixture_path"])
    title_hint = str(fields.get("title_hint", ""))
    text = ""
    url = str(fields.get("url", ""))
    source_app = "PerClip Q0 Synthetic"
    asset = None
    if source_type == "text":
        if fixture.suffix == ".json":
            shared = json.loads(fixture.read_text(encoding="utf-8"))
            text = str(shared.get("text", ""))
            url = str(shared.get("url", ""))
            source_app = str(shared.get("source_app", source_app))
        else:
            text = fixture.read_text(encoding="utf-8")
    elif source_type == "file":
        asset = IngestAsset(
            filename=str(fields.get("filename", fixture.name)),
            mime_type=str(fields.get("mime_type", "application/octet-stream")),
            payload=fixture.read_bytes(),
        )
    return IngestCommand(
        contract_version=INGEST_CONTRACT_VERSION,
        client_request_id=f"quality:q0:{fixture_id.lower()}",
        source=IngestSource(adapter="api", client_id="q0", event_id=fixture_id.lower(), source_app=source_app),
        clip=IngestClip(
            source_type=source_type,
            title_hint=title_hint,
            text=text,
            url=url,
            mime_type=str(fields.get("mime_type", "")),
            captured_at=EVALUATION_TIME.isoformat(),
            captured_timezone="UTC",
        ),
        capture=IngestCapture(part_role="file" if source_type == "file" else source_type, source_intent="share"),
        routing=IngestRouting(),
        asset=asset,
    )


def _table_counts(data_dir: Path) -> dict[str, int]:
    with sqlite3.connect(data_dir / "perclip.sqlite3") as db:
        return {
            table: int(db.execute(f"select count(*) from {table}").fetchone()[0])
            for table in ("clips", "clip_identities", "source_events", "assets", "outbox_jobs", "index_documents")
        }


def _run_worker(worker: PipelineWorker, clock: EvaluationClock, data_dir: Path) -> tuple[dict[str, float], float]:
    timings: dict[str, float] = {}
    started = time.perf_counter_ns()
    for _ in range(16):
        with sqlite3.connect(data_dir / "perclip.sqlite3") as db:
            db.execute("update outbox_jobs set max_attempts=1 where status in ('pending','retry','running')")
            row = db.execute(
                "select stage from outbox_jobs where status in ('pending','retry') order by id limit 1"
            ).fetchone()
        if row is None:
            break
        stage = str(row[0])
        stage_start = time.perf_counter_ns()
        worker.run_once(limit=1)
        timings[stage] = timings.get(stage, 0.0) + (time.perf_counter_ns() - stage_start) / 1_000_000
        clock.advance()
    return {key: round(value, 3) for key, value in timings.items()}, round((time.perf_counter_ns() - started) / 1_000_000, 3)


def _ordered_anchors(text: str, anchors: list[str]) -> bool:
    offset = 0
    for anchor in anchors:
        index = text.find(anchor, offset)
        if index < 0:
            return False
        offset = index + len(anchor)
    return True


def _normalized(value: str) -> str:
    return " ".join(value.split()).strip()


def _input_hash(row: dict[str, Any]) -> str:
    payload = "\n".join(str(artifact["sha256"]) for artifact in row["artifacts"])
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _metric_result(*, applicable: bool, passed: bool) -> dict[str, bool | None]:
    return {
        "applicable": applicable,
        "passed": passed if applicable else None,
    }


def evaluate_case(row: dict[str, Any], fixture_root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"perclip-{row['id'].lower()}-") as directory:
        data_dir = Path(directory)
        settings = _settings(data_dir)
        service = _service(settings)
        _configure_quality_routing(service)
        command = _case_command(row, fixture_root)
        expected_fields = dict(row["expected"])
        accepted = False
        rejection_error = ""
        result = None
        try:
            result = asyncio.run(service.ingest(command))
            accepted = True
        except IngestUnsupportedMediaError:
            rejection_error = "unsupported_media_type"

        if not accepted:
            actual = {
                "accepted": False,
                "state": "failed",
                "safe_error": rejection_error or "ingest_failed",
                "title": str(command.asset.filename if command.asset else command.clip.title_hint),
                "body": "",
                "canonical_url": "",
                "tags": [],
                "route": "",
                "recall_eligible": False,
                "raw_asset_preserved": False,
                "projection_consumed": False,
                "unverified_partial_body_retained": False,
            }
            timings: dict[str, float] = {}
            end_to_end = 0.0
            idempotent = True
        else:
            assert result is not None
            clock = EvaluationClock()
            worker = PipelineWorker(settings, ragflow_adapter_override=NoopRagflow(), clock=clock)
            if row.get("response_plan"):
                worker.web_fetcher = ResponsePlanFetcher(fixture_root, str(row["response_plan"]), default_max_bytes=settings.web_fetch_max_bytes)
            timings, end_to_end = _run_worker(worker, clock, data_dir)
            store = ClipStore(data_dir)
            pipeline = PipelineStore(data_dir)
            knowledge = KnowledgeBaseStore(data_dir)
            clip_id = int(result.clip_id)
            enrichment = store.find_latest_enrichment_by_clip_id(clip_id)
            metadata = store.find_normalized_metadata_by_clip_id(clip_id)
            projection = dict(metadata.metadata.get("projection", {})) if metadata and isinstance(metadata.metadata.get("projection"), dict) else {}
            body = enrichment.extracted_text if enrichment else ""
            extract_jobs = [job for job in pipeline.processing_summary(clip_id=clip_id)["jobs"] if job["stage"] == "extract"]
            failed_extract = next((job for job in extract_jobs if job["status"] == "failed"), None)
            extraction_state = "failed" if failed_extract else str(projection.get("extraction_status", ""))
            safe_error = str(failed_extract["safe_error_code"] if failed_extract else projection.get("safe_error_code", ""))
            route = knowledge.find_latest_route_decision_by_clip_id(clip_id)
            recall_row = store.find_recall_source_row_by_clip_id(clip_id)
            recall_candidate = candidate_from_row(*recall_row) if recall_row else None
            original = pipeline.latest_asset(clip_id=clip_id, role="original")
            raw = store.find_raw_fields_by_clip_id(clip_id)
            raw_preserved = bool(
                original
                and raw
                and Path(str(original["storage_uri"])).is_file()
                and hashlib.sha256(Path(str(original["storage_uri"])).read_bytes()).hexdigest()
                == hashlib.sha256(Path(raw.original_path).read_bytes()).hexdigest()
            )
            clean = pipeline.latest_asset(clip_id=clip_id, role="clean_markdown")
            projection_consumed = bool(
                clean
                and projection.get("source_asset_role") == "clean_markdown"
                and enrichment
                and enrichment.extracted_text == Path(str(clean["storage_uri"])).read_text(encoding="utf-8")
            )
            actual = {
                "accepted": True,
                "state": extraction_state,
                "safe_error": safe_error,
                "title": enrichment.title if enrichment else "",
                "body": body,
                "canonical_url": str(projection.get("canonical_url", "")),
                "tags": list(enrichment.tags if enrichment else []),
                "route": recall_row[2] if recall_row else "",
                "recall_eligible": recall_candidate is not None,
                "raw_asset_preserved": raw_preserved,
                "projection_consumed": projection_consumed,
                "unverified_partial_body_retained": bool(failed_extract and pipeline.latest_asset(clip_id=clip_id, role="raw_html")),
            }
            before = _table_counts(data_dir)
            replay = asyncio.run(service.ingest(command))
            after = _table_counts(data_dir)
            idempotent = replay.duplicate and replay.clip_id == result.clip_id and before == after

        body = str(actual["body"])
        contract_matches = {
            "title_accuracy": _normalized(str(actual["title"])) == _normalized(str(expected_fields["title"])),
            "body_anchors": _ordered_anchors(body, list(expected_fields["body_anchors"])),
            "noise_residue": not any(marker in body for marker in expected_fields["excluded"]),
            "canonical_url": str(actual["canonical_url"]) == str(expected_fields["canonical_url"]),
            "state_calibration": str(actual["state"]) == str(expected_fields["state"]),
            "safe_error": str(actual["safe_error"]) == str(expected_fields["safe_error"]),
            "routing": str(actual.get("route", "")) == str(expected_fields["route"]),
            "recall_eligibility": bool(actual["recall_eligible"]) == bool(expected_fields["recall_eligible"]),
            "tags": set(expected_fields["tags"]).issubset(set(actual["tags"])),
        }
        accepted = bool(actual["accepted"])
        body_anchors_declared = bool(expected_fields.get("body_anchors"))
        excluded_declared = bool(expected_fields.get("excluded"))
        canonical_declared = bool(command.clip.url and expected_fields.get("canonical_url"))
        title_declared = bool(expected_fields.get("title"))
        safe_error_declared = bool(
            expected_fields.get("state") == "failed" and expected_fields.get("safe_error")
        )
        route_declared = bool(expected_fields.get("route"))
        recall_declared = "recall_eligible" in expected_fields
        tags_declared = "tags" in expected_fields
        state_declared = bool(expected_fields.get("state"))
        metric_results = {
            "raw_asset_preservation": _metric_result(
                applicable=accepted,
                passed=bool(actual["raw_asset_preserved"]),
            ),
            "title_accuracy": _metric_result(
                applicable=title_declared,
                passed=contract_matches["title_accuracy"],
            ),
            "body_anchors": _metric_result(
                applicable=body_anchors_declared,
                passed=contract_matches["body_anchors"],
            ),
            "noise_residue": _metric_result(
                applicable=excluded_declared,
                passed=contract_matches["noise_residue"],
            ),
            "canonical_url": _metric_result(
                applicable=canonical_declared,
                passed=contract_matches["canonical_url"],
            ),
            "state_calibration": _metric_result(
                applicable=state_declared,
                passed=contract_matches["state_calibration"],
            ),
            "safe_error": _metric_result(
                applicable=safe_error_declared,
                passed=contract_matches["safe_error"],
            ),
            "routing": _metric_result(
                applicable=route_declared,
                passed=contract_matches["routing"],
            ),
            "recall_eligibility": _metric_result(
                applicable=recall_declared,
                passed=contract_matches["recall_eligibility"],
            ),
            "projection_consumption": _metric_result(
                applicable=accepted,
                passed=bool(actual["projection_consumed"]),
            ),
            "retry_idempotency": _metric_result(
                applicable=accepted,
                passed=idempotent,
            ),
            "tags": _metric_result(
                applicable=tags_declared,
                passed=contract_matches["tags"],
            ),
        }
        return {
            "id": row["id"],
            "source_class": row["source_class"],
            "fixture_version": row["fixture_version"],
            "input_hash": _input_hash(row),
            "expected": expected_fields,
            "actual": actual,
            "safe_error": actual["safe_error"],
            "stage_timings_ms": timings,
            "end_to_end_ms": end_to_end,
            "contract_matches": contract_matches,
            "all_case_contract_match": all(contract_matches.values()),
            "metric_results": metric_results,
            "comparison_to_previous": "baseline",
        }


def _control_command(identifier: str, *, target: str = "") -> IngestCommand:
    return IngestCommand(
        contract_version=INGEST_CONTRACT_VERSION,
        client_request_id=f"quality:probe:{identifier}",
        source=IngestSource(adapter="api", client_id="q0", event_id=identifier, source_app="PerClip Q0 Synthetic"),
        clip=IngestClip(source_type="text", title_hint="Control probe", text="Synthetic control probe body", mime_type="text/plain", captured_at=EVALUATION_TIME.isoformat(), captured_timezone="UTC"),
        capture=IngestCapture(part_role="text", source_intent="manual"),
        routing=IngestRouting(target_knowledge_base_id=target),
    )


def _failed_url_control_command(identifier: str, *, target: str) -> IngestCommand:
    return IngestCommand(
        contract_version=INGEST_CONTRACT_VERSION,
        client_request_id=f"quality:probe:{identifier}",
        source=IngestSource(adapter="api", client_id="q0", event_id=identifier, source_app="PerClip Q0 Synthetic"),
        clip=IngestClip(
            source_type="url",
            title_hint="Explicit content title",
            url="https://example.test/control/failure?token=synthetic-sensitive-value",
            mime_type="text/html",
            captured_at=EVALUATION_TIME.isoformat(),
            captured_timezone="UTC",
        ),
        capture=IngestCapture(part_role="url", source_intent="manual"),
        routing=IngestRouting(target_knowledge_base_id=target),
    )


def run_control_probes() -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="perclip-q0-recovery-") as directory:
        data_dir = Path(directory)
        settings = _settings(data_dir)
        service = _service(settings)
        asyncio.run(service.ingest(_control_command("lease-a")))
        asyncio.run(service.ingest(_control_command("lease-b")))
        clock = EvaluationClock()
        pipeline = PipelineStore(data_dir, clock=clock)
        old = pipeline.claim(limit=1, lease_seconds=10)[0]
        with pipeline.connect() as db:
            pending_before = int(db.execute("select count(*) from outbox_jobs where status='pending'").fetchone()[0]) == 1
        clock.advance(11)
        current = pipeline.claim(limit=1, lease_seconds=10)[0]
        stale_rejected = (
            not pipeline.renew_lease(old, lease_seconds=10)
            and not pipeline.complete(old)
            and not pipeline.fail(old, safe_error_code="stale", retryable=False)
        )
        recovered = current.id == old.id and current.lease_token != old.lease_token and pipeline.complete(current)

    with tempfile.TemporaryDirectory(prefix="perclip-q0-ragflow-") as directory:
        data_dir = Path(directory)
        settings = _real_index_settings(data_dir, "synthetic-dataset")
        service = _service(settings)
        knowledge = KnowledgeBaseStore(data_dir)
        target = knowledge.create_knowledge_base(name="Synthetic Fault KB", is_default=True, ragflow_dataset_id="synthetic-dataset", ragflow_dataset_name="Synthetic Dataset")
        accepted = asyncio.run(service.ingest(_control_command("ragflow-fault", target=target.id)))
        clock = EvaluationClock()
        worker = PipelineWorker(settings, ragflow_adapter_override=FailingRagflow(), clock=clock)
        _run_worker(worker, clock, data_dir)
        pipeline = PipelineStore(data_dir)
        state = pipeline.processing_summary(clip_id=int(accepted.clip_id))
        statuses = {str(job["stage"]): str(job["status"]) for job in state["jobs"]}
        codes = {str(job["stage"]): str(job["safe_error_code"]) for job in state["jobs"]}
        fault_isolated = (
            statuses.get("archive_original") == "completed"
            and statuses.get("clean") == "completed"
            and statuses.get("index") == "failed"
            and codes.get("index") == "ragflow_index_failed"
            and {"original", "clean_markdown"}.issubset(set(state["asset_roles"]))
        )

    with tempfile.TemporaryDirectory(prefix="perclip-q0-explicit-route-") as directory:
        data_dir = Path(directory)
        settings = _settings(data_dir)
        service = _service(settings)
        target = service.knowledge_store.create_knowledge_base(
            name="Explicit target", ragflow_dataset_id="explicit-dataset"
        )
        accepted = asyncio.run(
            service.ingest(_failed_url_control_command("explicit-route", target=target.id))
        )
        clock = EvaluationClock()
        explicit_adapter = RecordingRagflow()
        worker = PipelineWorker(settings, ragflow_adapter_override=explicit_adapter, clock=clock)

        def fail_fetch(_url: str):
            raise WebFetchError("web_fetch_failed")

        worker.web_fetcher.fetch = fail_fetch
        _run_worker(worker, clock, data_dir)
        route = service.knowledge_store.find_latest_route_decision_by_clip_id(
            int(accepted.clip_id)
        )
        explicit_route_preserved = bool(
            route
            and route.knowledge_base_id == target.id
            and route.manual_override
            and route.decision_type == "manual"
        )
        failed_projection_not_indexed = explicit_adapter.uploads == 0
        explicit_failed_intent_preserved = explicit_route_preserved and failed_projection_not_indexed
        metadata = service.store.find_normalized_metadata_by_clip_id(int(accepted.clip_id))
        metadata_text = json.dumps(metadata.metadata if metadata else {}, ensure_ascii=False)
        raw_fallback_not_indexed = (
            failed_projection_not_indexed
            and '"raw_fallback_used": true' in metadata_text
        )
        sensitive_url_not_exposed = "synthetic-sensitive-value" not in metadata_text
        inbox = service.knowledge_store.create_knowledge_base(
            name="收件箱", ragflow_dataset_id="inbox-dataset"
        )
        automatic = asyncio.run(
            service.ingest(_failed_url_control_command("automatic-inbox", target=""))
        )
        worker.web_fetcher.fetch = lambda _url: (_ for _ in ()).throw(
            WebFetchError("private_address_blocked")
        )
        _run_worker(worker, clock, data_dir)
        automatic_route = service.knowledge_store.find_latest_route_decision_by_clip_id(
            int(automatic.clip_id)
        )
        failed_inbox_projection_not_indexed = bool(
            automatic_route
            and automatic_route.knowledge_base_id == inbox.id
            and explicit_adapter.uploads == 0
        )

    with tempfile.TemporaryDirectory(prefix="perclip-q0-partial-index-") as directory:
        data_dir = Path(directory)
        settings = _settings(data_dir)
        service = _service(settings)
        target = service.knowledge_store.create_knowledge_base(
            name="Partial target", is_default=True, ragflow_dataset_id="partial-dataset"
        )
        accepted = asyncio.run(
            service.ingest(_failed_url_control_command("usable-partial", target=target.id))
        )
        clock = EvaluationClock()
        partial_adapter = RecordingRagflow()
        worker = PipelineWorker(settings, ragflow_adapter_override=partial_adapter, clock=clock)
        worker.web_fetcher.fetch = lambda _url: WebFetchResult(
            safe_original_url="https://example.test/control/failure",
            resolved_url="https://example.test/control/failure",
            canonical_url="https://example.test/control/failure",
            content_type="text/html",
            body=b"<html><head><title>Partial</title></head><body><main><p>Useful first page.</p><p>Next page</p></main></body></html>",
        )
        _run_worker(worker, clock, data_dir)
        partial_metadata = service.store.find_normalized_metadata_by_clip_id(int(accepted.clip_id))
        partial_active = partial_metadata.metadata["processing"]["active_projection"]
        usable_partial_indexed = (
            partial_active["extraction_status"] == "partial"
            and partial_active["index_reason"] == "usable_partial_projection"
            and partial_adapter.uploads == 0
            and partial_metadata.metadata["processing"]["latest_index_attempt"]["status"]
            == "planned"
        )

    with tempfile.TemporaryDirectory(prefix="perclip-q0-binary-index-") as directory:
        data_dir = Path(directory)
        settings = _settings(data_dir)
        service = _service(settings)
        target = service.knowledge_store.create_knowledge_base(
            name="Binary target", is_default=True, ragflow_dataset_id="binary-dataset"
        )
        binary_command = IngestCommand(
            contract_version=INGEST_CONTRACT_VERSION,
            client_request_id="quality:probe:unsupported-binary",
            source=IngestSource(adapter="api", client_id="q0", event_id="unsupported-binary", source_app="PerClip Q0 Synthetic"),
            clip=IngestClip(source_type="file", mime_type="application/octet-stream", captured_at=EVALUATION_TIME.isoformat(), captured_timezone="UTC"),
            capture=IngestCapture(part_role="file", source_intent="manual"),
            routing=IngestRouting(target_knowledge_base_id=target.id),
            asset=IngestAsset(filename="unsupported.bin", mime_type="application/octet-stream", payload=b"synthetic printable bytes"),
        )
        binary_accepted = asyncio.run(service.ingest(binary_command))
        binary_adapter = RecordingRagflow()
        worker = PipelineWorker(settings, ragflow_adapter_override=binary_adapter)
        _run_worker(worker, EvaluationClock(), data_dir)
        binary_metadata = service.store.find_normalized_metadata_by_clip_id(int(binary_accepted.clip_id))
        unsupported_binary_not_indexed = (
            binary_adapter.uploads == 0
            and binary_metadata.metadata["processing"]["active_projection"]["safe_error_code"] == "unsupported_media_type"
        )

    with tempfile.TemporaryDirectory(prefix="perclip-q0-active-projection-") as directory:
        data_dir = Path(directory)
        settings = _settings(data_dir)
        service = _service(settings)
        target = service.knowledge_store.create_knowledge_base(
            name="Lifecycle target", is_default=True, ragflow_dataset_id="lifecycle-dataset"
        )
        accepted = asyncio.run(
            service.ingest(_failed_url_control_command("projection-lifecycle", target=target.id))
        )
        clock = EvaluationClock()
        adapter = RecordingRagflow()
        worker = PipelineWorker(settings, ragflow_adapter_override=adapter, clock=clock)

        def success_fetch(title: str, body: str) -> WebFetchResult:
            return WebFetchResult(
                safe_original_url="https://example.test/control/failure",
                resolved_url="https://example.test/control/failure",
                canonical_url="https://example.test/control/failure",
                content_type="text/html",
                body=(
                    f"<html><head><title>{title}</title></head>"
                    f"<body><main><p>{body}</p></main></body></html>"
                ).encode(),
            )

        worker.web_fetcher.fetch = lambda _url: success_fetch("First projection", "First durable body")
        _run_worker(worker, clock, data_dir)
        clip_id = int(accepted.clip_id)
        first_metadata = service.store.find_normalized_metadata_by_clip_id(clip_id)
        first_active = dict(first_metadata.metadata["processing"]["active_projection"])
        first_active_index = dict(first_metadata.metadata["processing"]["active_index"])
        first_index_count = adapter.uploads
        reprocess = worker.pipeline.enqueue(
            clip_id=clip_id,
            stage="extract",
            engine="builtin-extractor",
            engine_version="v3",
            input_hash="control-failed-reprocess",
        )
        worker.web_fetcher.fetch = fail_fetch
        _run_worker(worker, clock, data_dir)
        failed_metadata = service.store.find_normalized_metadata_by_clip_id(clip_id)
        failed_processing = failed_metadata.metadata["processing"]
        recall_row = service.store.find_recall_source_row_by_clip_id(clip_id)
        active_preserved = (
            failed_processing["latest_attempted_projection"]["extraction_status"] == "failed"
            and failed_processing["active_projection"]["source_asset_id"] == first_active["source_asset_id"]
        )
        recall_preserved = bool(recall_row and candidate_from_row(*recall_row))
        failed_reprocess_index_preserved = adapter.uploads == first_index_count == 0
        failed_reprocess_active_index_preserved = (
            failed_processing["active_index"] == first_active_index
            and failed_processing["latest_index_attempt"]["status"] == "skipped_no_new_projection"
        )
        worker.pipeline.retry_failed_job(
            job_id=reprocess.id, request_id="control-lifecycle-retry", authorized=True
        )
        worker.web_fetcher.fetch = lambda _url: success_fetch("Retry projection", "Second durable body")
        for _ in range(8):
            if worker.run_once(limit=1) == 0:
                break
            clock.advance()
        retry_metadata = service.store.find_normalized_metadata_by_clip_id(clip_id)
        retry_processing = retry_metadata.metadata["processing"]
        retry_success_advanced = (
            retry_processing["active_projection"]["source_asset_id"]
            != first_active["source_asset_id"]
            and retry_processing["active_index"] == first_active_index
            and retry_processing["latest_index_attempt"]["projection_id"]
            == retry_processing["active_projection"]["source_asset_id"]
            and retry_processing["latest_index_attempt"]["status"] == "planned"
            and adapter.uploads == 0
        )
        retry_active = dict(retry_processing["active_projection"])
        retry_active_index = dict(retry_processing["active_index"])
        worker.pipeline.enqueue(
            clip_id=clip_id,
            stage="extract",
            engine="builtin-extractor",
            engine_version="v3",
            input_hash="control-unusable-partial-reprocess",
        )
        worker.web_fetcher.fetch = lambda _url: WebFetchResult(
            safe_original_url="https://example.test/control/failure",
            resolved_url="https://example.test/control/failure",
            canonical_url="https://example.test/control/failure",
            content_type="text/html",
            body=(
                b"<html><head><title>Unusable shell</title><script>render()</script></head>"
                b"<body><div>Loading synthetic shell.</div></body></html>"
            ),
        )
        _run_worker(worker, clock, data_dir)
        partial_metadata = service.store.find_normalized_metadata_by_clip_id(clip_id)
        partial_processing = partial_metadata.metadata["processing"]
        partial_recall_row = service.store.find_recall_source_row_by_clip_id(clip_id)
        partial_recall_candidate = (
            candidate_from_row(*partial_recall_row) if partial_recall_row else None
        )
        partial_active_preserved = (
            partial_processing["latest_attempted_projection"]["extraction_status"] == "partial"
            and partial_processing["latest_attempted_projection"]["recall_eligible"] is False
            and partial_processing["active_projection"] == retry_active
            and partial_processing["latest_successful_projection"] == retry_active
        )
        partial_recall_preserved = bool(
            partial_recall_candidate
            and "Second durable body" in partial_recall_candidate.reveal_text
        )
        partial_active_index_preserved = (
            partial_processing["active_index"] == retry_active_index
            and partial_processing["latest_index_attempt"]["status"] == "skipped_no_new_projection"
            and adapter.uploads == 0
        )

    normal_text = "\n".join(
        [
            "OAuth token rotation policy",
            "secret management best practices",
            "cookie security model",
            "authorization design",
            "passwordless authentication",
            "Basic authentication security",
            "JSON 中 token 字段的设计",
        ]
    )
    cleaned_normal = clean_content(normal_text).text
    normal_secret_text_preserved = all(line in cleaned_normal for line in normal_text.splitlines())
    structured_source = "\n".join(
        [
            '"token": "synthetic-json-value"',
            "'api_key': 'synthetic-single-value'",
            "secret: synthetic-yaml-value",
            "PASSWORD=synthetic-env-value",
            "Authorization: Bearer synthetic-bearer-value",
            "Authorization: Basic c3ludGhldGljLWJhc2lj",
            "Authorization: Token synthetic-token-value",
            "Authorization: ApiKey synthetic-apikey-value",
        ]
    )
    structured_cleaned = clean_content(structured_source).text
    structured_secret_values_redacted = (
        all(
            value not in structured_cleaned
            for value in (
                "synthetic-json-value",
                "synthetic-single-value",
                "synthetic-yaml-value",
                "synthetic-env-value",
                "synthetic-bearer-value",
                "c3ludGhldGljLWJhc2lj",
                "synthetic-token-value",
                "synthetic-apikey-value",
            )
        )
        and clean_content(structured_cleaned).text == structured_cleaned
        and structured_cleaned.count("[redacted]") == 8
    )
    heading_text_preserved = clean_content("第1节\n第一节\n编号 12\n日期 2026-07-22").text.split("\n\n") == [
        "第1节", "第一节", "编号 12", "日期 2026-07-22"
    ]
    unsafe_canonical = extract_html(
        b'<html><head><title>T</title><link rel="canonical" href="http://169.254.169.254/latest/meta-data"></head><body><main><p>Useful body.</p></main></body></html>',
        "text/html",
        base_url="https://source.example/article",
    )
    unsafe_canonical_rejected = (
        unsafe_canonical.canonical_url == ""
        and unsafe_canonical.canonical_validation_result == "rejected_non_public_host"
    )
    return {
        "worker_claims_only_next_job": pending_before,
        "worker_recovery": recovered,
        "stale_token_rejected": stale_rejected,
        "fake_ragflow_fault_isolation": fault_isolated,
        "explicit_route_preserved_on_failure": explicit_route_preserved,
        "failed_projection_not_indexed": failed_projection_not_indexed,
        "explicit_failed_projection_not_indexed_and_intent_preserved": explicit_failed_intent_preserved,
        "raw_fallback_not_indexed": raw_fallback_not_indexed,
        "successful_projection_preserved_after_failed_reprocess": active_preserved,
        "recall_preserved_after_failed_reprocess": recall_preserved,
        "failed_reprocess_does_not_replace_index": failed_reprocess_index_preserved,
        "active_index_state_preserved_after_failed_reprocess": failed_reprocess_active_index_preserved,
        "successful_projection_preserved_after_unusable_partial_reprocess": partial_active_preserved,
        "recall_preserved_after_unusable_partial_reprocess": partial_recall_preserved,
        "active_index_state_preserved_after_unusable_partial_reprocess": partial_active_index_preserved,
        "retry_success_advances_active_and_index": retry_success_advanced,
        "unsafe_canonical_rejected": unsafe_canonical_rejected,
        "normal_secret_text_preserved": normal_secret_text_preserved,
        "normal_security_prose_preserved": normal_secret_text_preserved,
        "structured_secret_values_redacted": structured_secret_values_redacted,
        "production_cleaner_preserves_section_numbering": heading_text_preserved,
        "sensitive_url_not_exposed": sensitive_url_not_exposed,
        "failed_inbox_projection_not_indexed": failed_inbox_projection_not_indexed,
        "usable_partial_indexed": usable_partial_indexed,
        "unsupported_binary_not_indexed": unsupported_binary_not_indexed,
    }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * fraction + 0.999999)))
    return round(ordered[index], 3)


def _metric(cases: list[dict[str, Any]], key: str) -> dict[str, object]:
    results = [case["metric_results"][key] for case in cases]
    eligible = sum(bool(result["applicable"]) for result in results)
    passed = sum(result["passed"] is True for result in results)
    return {
        "passed": passed,
        "eligible": eligible,
        "not_applicable": len(results) - eligible,
        "rate": round(passed / eligible, 4) if eligible else 0.0,
    }


def build_report(
    manifest_path: Path,
    *,
    perclip_commit: str,
    comparison_mode: str = "baseline",
) -> dict[str, Any]:
    if comparison_mode != "baseline":
        raise ValueError("Q0 evaluator currently accepts comparison_mode='baseline' only")
    rows = load_manifest(manifest_path)
    cases = [evaluate_case(row, manifest_path.parent) for row in rows]
    metric_keys = list(cases[0]["metric_results"])
    timings: dict[str, list[float]] = {}
    for case in cases:
        for stage, value in case["stage_timings_ms"].items():
            timings.setdefault(stage, []).append(float(value))
    failed_categories = {
        key: [
            case["id"]
            for case in cases
            if case["metric_results"][key]["applicable"]
            and case["metric_results"][key]["passed"] is False
        ]
        for key in metric_keys
    }
    contract_mismatches = {
        key: [case["id"] for case in cases if not case["contract_matches"][key]]
        for key in cases[0]["contract_matches"]
    }
    contract_passed = sum(bool(case["all_case_contract_match"]) for case in cases)
    return {
        "schema_version": REPORT_SCHEMA,
        "fixture_version": rows[0]["fixture_version"],
        "perclip_commit": perclip_commit,
        "engine_versions": {
            "evaluator": f"{EVALUATOR_ENGINE}/{EVALUATOR_VERSION}",
            **{stage: f"{engine}/{version}" for stage, (engine, version) in STAGE_ENGINE.items()},
        },
        "manifest_input_hash": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "cases": cases,
        "aggregate": {
            "fixture_count": len(cases),
            "all_case_contract_match": {
                "passed": contract_passed,
                "total": len(cases),
                "rate": round(contract_passed / len(cases), 4) if cases else 0.0,
            },
            "applicable_metric_result": {key: _metric(cases, key) for key in metric_keys},
            "control_metrics": run_control_probes(),
            "local_fixture_pipeline_latency": {
                "unit": "ms",
                "scope": "socket-free local fixtures on the current test host",
                "excluded_boundaries": [
                    "real DNS",
                    "public network RTT",
                    "real webpage download",
                    "real NAS I/O",
                    "real OCR/ASR/LLM",
                    "real RAGFlow",
                ],
                "end_to_end": {"p50": _percentile([case["end_to_end_ms"] for case in cases], 0.50), "p95": _percentile([case["end_to_end_ms"] for case in cases], 0.95)},
                "by_stage": {stage: {"p50": _percentile(values, 0.50), "p95": _percentile(values, 0.95)} for stage, values in sorted(timings.items())},
            },
            "failure_categories": {key: value for key, value in failed_categories.items() if value},
            "contract_mismatch_categories": {
                key: value for key, value in contract_mismatches.items() if value
            },
            "comparison": {
                "comparison_mode": "baseline",
                "baseline_cases": len(cases),
                "improved": 0,
                "unchanged": 0,
                "regressed": 0,
            },
        },
    }


def build_candidate_report(
    manifest_path: Path,
    *,
    baseline_path: Path,
    perclip_commit: str,
) -> dict[str, Any]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate = build_report(manifest_path, perclip_commit=perclip_commit)
    baseline_cases = {str(case["id"]): case for case in baseline["cases"]}
    contract_changes: list[dict[str, object]] = []
    if baseline.get("fixture_version") != candidate.get("fixture_version"):
        contract_changes.append({"field": "fixture_version", "baseline": baseline.get("fixture_version"), "candidate": candidate.get("fixture_version")})
    if baseline.get("manifest_input_hash") != candidate.get("manifest_input_hash"):
        contract_changes.append({"field": "manifest_input_hash", "baseline": baseline.get("manifest_input_hash"), "candidate": candidate.get("manifest_input_hash")})

    comparison_counts = {"improved": 0, "unchanged": 0, "regressed": 0}
    for case in candidate["cases"]:
        previous = baseline_cases.get(str(case["id"]))
        if previous is None:
            contract_changes.append({"field": "case_missing_from_baseline", "id": case["id"]})
            case["comparison_to_q0"] = "regressed"
            case["metric_diffs"] = {}
            comparison_counts["regressed"] += 1
            continue
        for field in ("expected", "input_hash", "fixture_version"):
            if previous.get(field) != case.get(field):
                contract_changes.append({"field": field, "id": case["id"]})
        metric_diffs: dict[str, dict[str, object]] = {}
        improved = False
        regressed = False
        for name, result in case["metric_results"].items():
            old_result = previous["metric_results"][name]
            old_value = old_result.get("passed") if old_result.get("applicable") else None
            new_value = result.get("passed") if result.get("applicable") else None
            if old_value != new_value or old_result.get("applicable") != result.get("applicable"):
                metric_diffs[name] = {
                    "baseline_applicable": old_result.get("applicable"),
                    "baseline_passed": old_value,
                    "candidate_applicable": result.get("applicable"),
                    "candidate_passed": new_value,
                }
            if old_value is False and new_value is True:
                improved = True
            if old_value is True and new_value is False:
                regressed = True
            if old_result.get("applicable") != result.get("applicable"):
                regressed = True
        state = "regressed" if regressed else ("improved" if improved else "unchanged")
        case["comparison_to_previous"] = state
        case["comparison_to_q0"] = state
        case["metric_diffs"] = metric_diffs
        case["actual_diffs"] = {
            key: {"baseline": previous["actual"].get(key), "candidate": case["actual"].get(key)}
            for key in sorted(set(previous["actual"]) | set(case["actual"]))
            if previous["actual"].get(key) != case["actual"].get(key)
        }
        comparison_counts[state] += 1

    missing_ids = sorted(set(baseline_cases) - {str(case["id"]) for case in candidate["cases"]})
    contract_changes.extend({"field": "case_missing_from_candidate", "id": identifier} for identifier in missing_ids)
    metrics = candidate["aggregate"]["applicable_metric_result"]
    cases_by_id = {str(case["id"]): case for case in candidate["cases"]}
    hard_blockers: list[str] = []
    if contract_changes:
        hard_blockers.append("immutable_q0_contract_changed")
    for metric in ("raw_asset_preservation", "projection_consumption", "retry_idempotency"):
        if metrics[metric]["passed"] != metrics[metric]["eligible"]:
            hard_blockers.append(f"{metric}_not_100_percent")
    for identifier in [f"G{index:02d}" for index in range(10, 17)]:
        case = cases_by_id[identifier]
        if not (
            case["actual"]["state"] == "failed"
            and case["actual"]["safe_error"] == case["expected"]["safe_error"]
            and case["actual"]["route"] == "收件箱"
            and case["actual"]["recall_eligible"] is False
            and case["actual"]["unverified_partial_body_retained"] is False
        ):
            hard_blockers.append(f"security_failure_contract:{identifier}")
    binary = cases_by_id["G17"]["actual"]
    if not (
        binary["accepted"]
        and binary["raw_asset_preserved"]
        and binary["state"] == "failed"
        and binary["safe_error"] == "unsupported_media_type"
        and binary["route"] == "收件箱"
        and binary["recall_eligible"] is False
        and "PERCLIP_SYNTHETIC_UNSUPPORTED_BINARY" not in binary["body"]
    ):
        hard_blockers.append("unknown_binary_fail_closed_contract")
    if not all(candidate["aggregate"]["control_metrics"].values()):
        hard_blockers.append("control_probe_failure")
    controls = candidate["aggregate"]["control_metrics"]
    blocker_controls = {
        "failed_projection_not_indexed": "failed_projection_indexed",
        "raw_fallback_not_indexed": "raw_fallback_indexed",
        "successful_projection_preserved_after_failed_reprocess": "successful_projection_lost_after_failed_reprocess",
        "recall_preserved_after_failed_reprocess": "recall_disappears_after_failed_reprocess",
        "successful_projection_preserved_after_unusable_partial_reprocess": "successful_projection_lost_after_unusable_partial_reprocess",
        "recall_preserved_after_unusable_partial_reprocess": "recall_disappears_after_unusable_partial_reprocess",
        "active_index_state_preserved_after_failed_reprocess": "active_index_state_lost_after_failed_reprocess",
        "active_index_state_preserved_after_unusable_partial_reprocess": "active_index_state_lost_after_unusable_partial_reprocess",
        "structured_secret_values_redacted": "structured_secret_value_exposed",
        "unsafe_canonical_rejected": "unsafe_canonical_accepted",
        "sensitive_url_not_exposed": "sensitive_url_exposed",
    }
    for control, blocker in blocker_controls.items():
        if not controls.get(control, False):
            hard_blockers.append(blocker)
    if comparison_counts["regressed"]:
        hard_blockers.append("q0_metric_regression")

    baseline_latency = float(baseline["aggregate"]["local_fixture_pipeline_latency"]["end_to_end"]["p95"])
    candidate_latency = float(candidate["aggregate"]["local_fixture_pipeline_latency"]["end_to_end"]["p95"])
    latency_change = round((candidate_latency - baseline_latency) / baseline_latency, 4) if baseline_latency else None
    baseline_engines = dict(baseline.get("engine_versions", {}))
    candidate["engine_versions"]["evaluator"] = f"{EVALUATOR_ENGINE}/{CANDIDATE_EVALUATOR_VERSION}"
    candidate_engines = dict(candidate.get("engine_versions", {}))
    engine_changes = {
        key: {"baseline": baseline_engines.get(key, ""), "candidate": candidate_engines.get(key, "")}
        for key in sorted(set(baseline_engines) | set(candidate_engines))
        if baseline_engines.get(key) != candidate_engines.get(key)
    }
    candidate["schema_version"] = "perclip.quality.q0-candidate.v1"
    candidate["semantic_tags_not_targeted"] = True
    candidate["known_contract_ambiguities"] = [
        "q0_web_v1_title_expected_mixes_content_titles_with_processing_status_for_failed_or_partial_cases; any correction requires a new corpus version"
    ]
    candidate["aggregate"]["comparison"] = {
        "comparison_mode": "candidate",
        "baseline_commit": baseline.get("perclip_commit", ""),
        "candidate_commit": perclip_commit,
        "baseline_cases": len(baseline_cases),
        "candidate_cases": len(candidate["cases"]),
        **comparison_counts,
        "contract_changes": contract_changes,
        "engine_changes": engine_changes,
        "hard_blockers": sorted(set(hard_blockers)),
        "latency_p95": {
            "baseline_ms": baseline_latency,
            "candidate_ms": candidate_latency,
            "relative_change": latency_change,
            "comparable_only_on_same_fixture_and_test_host": True,
            "above_ten_percent": bool(latency_change is not None and latency_change > 0.10),
            "disposition": "review measurement environment; not a production SLO",
        },
    }
    return candidate


def markdown_report(report: dict[str, Any]) -> str:
    aggregate = report["aggregate"]
    comparison = aggregate["comparison"]
    is_candidate = comparison.get("comparison_mode") == "candidate"
    lines = [
        "# PerClip Q0-Web Candidate" if is_candidate else "# PerClip Q0-Web baseline",
        "",
        f"- Fixture version: `{report['fixture_version']}`",
        f"- PerClip commit: `{report['perclip_commit']}`",
        f"- Evaluator: `{report['engine_versions']['evaluator']}`",
        f"- Manifest SHA-256: `{report['manifest_input_hash']}`",
        f"- Cases: {aggregate['fixture_count']}",
        (
            f"- Comparison mode: `candidate` (baseline `{comparison['baseline_commit']}`; "
            f"candidate `{comparison['candidate_commit']}`)"
            if is_candidate
            else "- Comparison mode: `baseline` (26 baseline cases; no previous baseline)"
        ),
        f"- Comparison counts: improved {comparison['improved']} / unchanged {comparison['unchanged']} / regressed {comparison['regressed']}",
        "",
        "## Contract and applicable metrics",
        "",
        f"- All-case contract match: {aggregate['all_case_contract_match']['passed']} / {aggregate['all_case_contract_match']['total']} ({aggregate['all_case_contract_match']['rate']:.1%})",
        "",
        "| Metric | Passed | Eligible | Not applicable | Rate |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, metric in aggregate["applicable_metric_result"].items():
        lines.append(
            f"| {name} | {metric['passed']} | {metric['eligible']} | "
            f"{metric['not_applicable']} | {metric['rate']:.1%} |"
        )
    if is_candidate:
        lines.extend([
            "",
            "## Candidate safety and contract review",
            "",
            f"- Hard blockers: {', '.join(comparison['hard_blockers']) or 'none'}",
            f"- Contract changes: {len(comparison['contract_changes'])}",
            "- Semantic tags: not targeted in this stage.",
            "- Known contract ambiguity: Q0-Web v1 mixes content titles with processing status for some failed/partial cases; this Candidate does not rewrite immutable expected values.",
            f"- Local fixture p95 change: {comparison['latency_p95']['relative_change']}",
            "- Latency is comparable only on the same fixtures and test host.",
            "",
            "### Engine changes",
            "",
        ])
        if comparison["engine_changes"]:
            for name, change in comparison["engine_changes"].items():
                lines.append(f"- {name}: `{change['baseline']}` → `{change['candidate']}`")
        else:
            lines.append("- none")
    lines.extend(["", "## Control metrics", ""])
    for name, value in aggregate["control_metrics"].items():
        lines.append(f"- {name}: {'pass' if value else 'fail'}")
    latency = aggregate["local_fixture_pipeline_latency"]
    lines.extend([
        "",
        "## Local fixture pipeline latency",
        "",
        f"- Local fixture pipeline p50: {latency['end_to_end']['p50']} ms",
        f"- Local fixture pipeline p95: {latency['end_to_end']['p95']} ms",
        "- Scope: socket-free fixtures on the current test host.",
        "- Excludes real DNS, public RTT/download, NAS I/O, OCR/ASR/LLM, and RAGFlow.",
        "- This is only comparable within the same fixtures and test environment; it is not a home-NAS, cloud-server, production-SLO, or user-experience latency measurement.",
        "",
        "| Stage | p50 ms | p95 ms |",
        "| --- | ---: | ---: |",
    ])
    for stage, values in latency["by_stage"].items():
        lines.append(f"| {stage} | {values['p50']} | {values['p95']} |")
    lines.extend(["", "## Main baseline failure categories", ""])
    for name, fixtures in aggregate["failure_categories"].items():
        lines.append(f"- {name}: {', '.join(fixtures)}")
    lines.extend(["", "## Per-case results", "", "| ID | Expected | Actual | Safe error | Contract match | Comparison | Failed applicable metrics |", "| --- | --- | --- | --- | --- | --- | --- |"])
    for case in report["cases"]:
        failed = [
            key
            for key, value in case["metric_results"].items()
            if value["applicable"] and value["passed"] is False
        ]
        lines.append(
            f"| {case['id']} | {case['expected']['state']} | {case['actual']['state']} | "
            f"{case['safe_error'] or '—'} | {'yes' if case['all_case_contract_match'] else 'no'} | "
            f"{case.get('comparison_to_q0', case['comparison_to_previous'])} | "
            f"{', '.join(failed) or '—'} |"
        )
    lines.extend([
        "",
        (
            "This Candidate is measured against the immutable Q0 baseline. A hard blocker"
            if is_candidate
            else "Q0 is a measurement baseline, not a candidate-release claim. The current"
        ),
        (
            "prevents release candidacy but does not rewrite Q0 expectations. Semantic tags were not targeted."
            if is_candidate
            else "extractor, cleaner, enricher, routing and Recall algorithms were not changed"
        ),
        (
            "No public web page or real external service was used."
            if is_candidate
            else "to improve these results. No public web page or real external service was used."
        ),
        "",
    ])
    return "\n".join(lines)


def current_commit(repo_root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local-only PerClip Q0-Web evaluator")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--commit", default="")
    parser.add_argument("--mode", choices=("baseline", "candidate"), default="baseline")
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args(argv)
    manifest = args.manifest.resolve()
    repo_root = manifest.parents[3]
    commit = args.commit or current_commit(repo_root)
    if args.mode == "candidate":
        if args.baseline is None:
            parser.error("--baseline is required in candidate mode")
        report = build_candidate_report(
            manifest,
            baseline_path=args.baseline.resolve(),
            perclip_commit=commit,
        )
    else:
        report = build_report(manifest, perclip_commit=commit, comparison_mode=args.mode)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({
        "fixture_count": report["aggregate"]["fixture_count"],
        "fixture_version": report["fixture_version"],
        "json": str(args.json),
        "markdown": str(args.markdown),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
