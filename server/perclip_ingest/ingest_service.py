from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import uuid

from .archiver import ArchiveOutcome, MobileClipPayload
from .ingest_models import INGEST_CONTRACT_VERSION, IngestCommand, IngestResult
from .knowledge_base_store import KnowledgeBaseConflictError, KnowledgeBaseError, KnowledgeBaseNotFoundError, KnowledgeBaseStore
from .metadata_contract import NormalizedMetadataInput, build_normalized_metadata
from .mime_policy import is_allowed_mime_type, normalize_mime_type
from .routing import RoutingPreviewInput, preview_route
from .storage import CaptureOwnershipConflict, ClipStore, StoredClip, StoredClipRawFields
from .pipeline_store import PipelineStore


CAPTURE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
CAPTURE_PART_ROLES = {"single", "file", "image", "text", "url", "mixed"}
CAPTURE_SOURCE_INTENTS = {"share", "manual", "retry", "unknown"}
CAPTURE_OWNERSHIP_CONFLICT_DETAIL = "client_request_id already belongs to another capture part"


class IngestError(Exception):
    detail = "ingest failed"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.detail)
        self.detail = detail or self.detail


class IngestValidationError(IngestError):
    detail = "invalid ingest request"


class IngestConflictError(IngestError):
    detail = "ingest request conflicts with existing receipt"


class IngestNotFoundError(IngestError):
    detail = "ingest receipt not found"


class IngestPayloadTooLargeError(IngestError):
    detail = "file too large"


class IngestUnsupportedMediaError(IngestError):
    detail = "unsupported file mime type"


class IngestArchiveError(IngestError):
    detail = "archive failed"


class IngestInternalError(IngestError):
    detail = "ingest finalization failed"


def _clean(value: str, limit: int = 256) -> str:
    return "".join(char for char in value.strip() if char >= " " and char != "\x7f")[:limit]


def safe_asset_filename(value: str) -> str:
    return _clean(Path(value.replace("\\", "/")).name, 255)


def receipt_recovery_policy(replay_policy: str) -> tuple[bool, bool]:
    """Return (recover failed-with-clip, recover failed-without-clip)."""
    if replay_policy == "strict_v1":
        return True, False
    return True, True


def request_signature(command: IngestCommand) -> str:
    asset_hash = hashlib.sha256(command.asset.payload).hexdigest() if command.asset else ""
    hash_text = lambda value: hashlib.sha256(value.encode()).hexdigest() if value else ""
    signature = {
        "contract_version": command.contract_version,
        "source": {
            "adapter": command.source.adapter, "client_id": command.source.client_id,
            "event_id": command.source.event_id, "source_app": _clean(command.source.source_app, 128),
        },
        "clip": {
            "source_type": command.clip.source_type, "title_hash": hash_text(command.clip.title_hint),
            "note_hash": hash_text(command.clip.note), "text_hash": hash_text(command.clip.text),
            "url_hash": hash_text(command.clip.url), "mime_type": normalize_mime_type(command.clip.mime_type),
            "captured_at": command.clip.captured_at, "captured_timezone": command.clip.captured_timezone,
            "device_name": _clean(command.clip.device_name),
        },
        "capture": command.capture.__dict__,
        "routing_target": command.routing.target_knowledge_base_id,
        "routing_mode": command.routing.mode,
        "asset": {"filename": safe_asset_filename(command.asset.filename) if command.asset else "",
                  "mime_type": normalize_mime_type(command.asset.mime_type) if command.asset else "", "sha256": asset_hash},
    }
    return hashlib.sha256(json.dumps(signature, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class IngestService:
    def __init__(self, *, store: ClipStore, knowledge_store: KnowledgeBaseStore, archiver=None,
                 max_file_bytes: int = 25 * 1024 * 1024, receipt_stale_after_seconds: int = 300,
                 pipeline_store: PipelineStore | None = None, processing_mode: str = "inline",
                 deployment_environment: str = "local") -> None:
        self.store = store
        self.knowledge_store = knowledge_store
        self.archiver = archiver
        self.max_file_bytes = max_file_bytes
        self.receipt_stale_after_seconds = receipt_stale_after_seconds
        self.pipeline_store = pipeline_store
        self.processing_mode = processing_mode
        self.deployment_environment = deployment_environment

    async def ingest(self, command: IngestCommand) -> IngestResult:
        self._validate(command)
        signature = request_signature(command)
        preflight_receipt = self.store.find_ingest_receipt_by_request_id(command.client_request_id)
        if command.replay_policy == "legacy_mobile" and preflight_receipt is not None and (
            preflight_receipt.contract_version != "legacy_mobile"
            or preflight_receipt.source_adapter != "android"
            or preflight_receipt.request_signature != "legacy_mobile"
        ):
            raise IngestConflictError("client_request_id belongs to a strict ingest receipt")
        request_token = self.store.acquire_request_lock_token(command.client_request_id)
        if request_token is None:
            raise IngestConflictError("request already processing")
        batch_lock = f"capture-batch:{command.capture.client_batch_id}" if command.capture.client_batch_id else ""
        batch_token = self.store.acquire_request_lock_token(batch_lock) if batch_lock else ""
        if batch_lock and batch_token is None:
            self.store.release_request_lock_token(command.client_request_id, request_token)
            raise IngestConflictError("capture batch already processing")
        source_lock = ""
        source_token = ""
        if self.processing_mode == "worker" and self.pipeline_store is not None:
            source_key = self.pipeline_store.source_event_key(
                adapter=command.source.adapter,
                client_id=command.source.client_id,
                event_id=command.source.event_id,
                client_request_id=command.client_request_id,
            )
            if source_key:
                source_lock = f"source-event:{hashlib.sha256(source_key.encode()).hexdigest()}"
                source_token = self.store.acquire_request_lock_token(source_lock) or ""
                if not source_token:
                    if batch_lock and batch_token:
                        self.store.release_request_lock_token(batch_lock, batch_token)
                    self.store.release_request_lock_token(command.client_request_id, request_token)
                    raise IngestConflictError("source event already processing")
        receipt_id = ""
        attempt_registered = False
        stored: StoredClip | None = None
        try:
            strict = command.replay_policy == "strict_v1"
            contract = command.contract_version if strict else "legacy_mobile"
            adapter = command.source.adapter if strict else "android"
            receipt_signature = signature if strict else "legacy_mobile"
            recover_with_clip, recover_without_clip = receipt_recovery_policy(command.replay_policy)
            if not command.client_request_id and not strict:
                receipt = None
                receipt_action = "created"
            else:
                receipt, receipt_action = self.store.claim_or_recover_ingest_receipt(
                    receipt_id=f"ir_{uuid.uuid4().hex}", client_request_id=command.client_request_id,
                    contract_version=contract, source_adapter=adapter, request_signature=receipt_signature,
                    stale_after_seconds=self.receipt_stale_after_seconds,
                    capture_client_batch_id=command.capture.client_batch_id,
                    capture_parent_client_request_id=command.capture.parent_client_request_id,
                    capture_part_index=command.capture.part_index, capture_part_count=command.capture.part_count,
                    capture_part_role=command.capture.part_role,
                    target_knowledge_base_id=command.routing.target_knowledge_base_id,
                    recover_failed_with_clip=recover_with_clip,
                    recover_failed_without_clip=recover_without_clip,
                )
                receipt_id = receipt.receipt_id
            if receipt_action == "conflict":
                receipt_id = ""
                raise IngestConflictError()
            if receipt_action == "active":
                receipt_id = ""
                raise IngestConflictError("ingest request already processing")
            if receipt_action == "failed":
                receipt_id = ""
                raise IngestConflictError("ingest request previously failed")
            if receipt_action == "received":
                existing = self.store.find_by_request_id(command.client_request_id)
                if existing is None or receipt is None or receipt.clip_id != str(existing.id):
                    raise IngestConflictError()
                if not strict:
                    attach = self._validate_existing_ownership(existing, command)
                    self._validate_batch(command)
                    if attach:
                        self.store.attach_capture_identity_if_missing(
                            clip_id=existing.id, batch_id=command.capture.client_batch_id,
                            parent_id=command.capture.parent_client_request_id,
                            part_index=command.capture.part_index, part_count=command.capture.part_count,
                            part_role=command.capture.part_role,
                        )
                        existing = self.store.find_by_request_id(command.client_request_id) or existing
                    self._ensure_metadata(existing, command, refresh_capture=attach)
                    self._attempt(command, "received")
                return self._result(existing, receipt_id=receipt_id, duplicate=True,
                                    target=receipt.target_knowledge_base_id)
            if receipt_action == "reconcile":
                stored = self.store.find_by_request_id(command.client_request_id)
                return self._reconcile_existing(command, receipt_id, stored)

            duplicate = self.store.find_by_request_id(command.client_request_id)
            if duplicate is not None:
                if receipt_action == "created" and strict:
                    raise IngestConflictError("client_request_id belongs to an unverifiable legacy clip")
                stored = duplicate
                return self._reconcile_existing(command, receipt_id, stored)

            self._validate_batch(command)
            if command.routing.target_knowledge_base_id and command.routing.mode != "default_only":
                try:
                    self.knowledge_store.require_active_knowledge_base(command.routing.target_knowledge_base_id)
                except KnowledgeBaseNotFoundError as error:
                    raise IngestNotFoundError("target knowledge base not found") from error
                except KnowledgeBaseConflictError as error:
                    raise IngestConflictError("target knowledge base unavailable") from error
                except KnowledgeBaseError as error:
                    raise IngestValidationError("invalid target knowledge base") from error
            self._attempt(command, "processing")
            attempt_registered = bool(command.capture.client_batch_id)

            asset = command.asset
            payload = asset.payload if asset else b""
            filename = safe_asset_filename(asset.filename) if asset else ""
            detected_mime = normalize_mime_type((asset.mime_type if asset else "") or command.clip.mime_type)
            if asset:
                if len(payload) > self.max_file_bytes:
                    raise IngestPayloadTooLargeError()
                if not is_allowed_mime_type(detected_mime):
                    raise IngestUnsupportedMediaError()
            if not payload and not command.clip.text and not command.clip.url and not command.clip.note:
                raise IngestValidationError("empty clip payload")
            if (
                self.processing_mode == "worker"
                and self.pipeline_store is not None
                and not self.pipeline_store.source_event_is_available(
                    adapter=command.source.adapter,
                    client_id=command.source.client_id,
                    event_id=command.source.event_id,
                    client_request_id=command.client_request_id,
                )
            ):
                raise IngestConflictError("source event already belongs to another request")

            received_at = datetime.now(timezone.utc).isoformat()
            captured_at = command.clip.captured_at or received_at
            outcome = ArchiveOutcome(ok=True)
            archive_status = "local"
            if self.archiver and self.processing_mode == "inline":
                outcome = await self.archiver.archive(MobileClipPayload(
                    source_type=command.clip.source_type, title_hint=command.clip.title_hint,
                    note=command.clip.note, text=command.clip.text, url=command.clip.url,
                    mime_type=detected_mime, device_name=_clean(command.clip.device_name),
                    source_app=_clean(command.source.source_app), captured_at=captured_at,
                    client_request_id=command.client_request_id, filename=filename, payload=payload,
                ))
                archive_status = "clip_to_ragflow" if outcome.ok else "archive_failed"
                if not outcome.ok:
                    raise IngestArchiveError()
            elif self.processing_mode == "worker":
                archive_status = "accepted"

            stored = self.store.save(
                client_request_id=command.client_request_id, source_type=command.clip.source_type,
                title_hint=outcome.title or command.clip.title_hint, note=command.clip.note,
                text=command.clip.text, url=command.clip.url, mime_type=detected_mime,
                device_name=_clean(command.clip.device_name), source_app=_clean(command.source.source_app),
                captured_at=captured_at, filename=filename, payload=payload,
                archived_original_path=outcome.original_path, ragflow_document_id=outcome.ragflow_document_id,
                archive_status=archive_status, capture_client_batch_id=command.capture.client_batch_id,
                capture_parent_client_request_id=command.capture.parent_client_request_id,
                capture_part_index=command.capture.part_index, capture_part_count=command.capture.part_count,
                capture_part_role=command.capture.part_role,
            )
            route = (
                self._route(stored, command, strict=strict)
                if (
                    self.processing_mode == "inline"
                    or command.routing.target_knowledge_base_id
                    or command.routing.mode == "default_only"
                )
                else None
            )
            metadata = build_normalized_metadata(NormalizedMetadataInput(
                source_type=command.clip.source_type, title_hint=outcome.title or command.clip.title_hint,
                note=command.clip.note, text=command.clip.text, url=command.clip.url,
                mime_type=detected_mime, device_name=_clean(command.clip.device_name),
                source_app=_clean(command.source.source_app), captured_at=captured_at,
                client_request_id=command.client_request_id, filename=stored.filename,
                has_file=asset is not None, size_bytes=stored.size_bytes, content_hash=stored.content_hash,
                storage_uri=stored.original_path, received_at=received_at, archive_status=stored.archive_status,
                ragflow_document_id=stored.ragflow_document_id,
                source_adapter=command.source.adapter,
                source_client_id=command.source.client_id,
                source_event_id=command.source.event_id,
                client_batch_id=command.capture.client_batch_id,
                parent_client_request_id=command.capture.parent_client_request_id,
                part_index=command.capture.part_index, part_count=command.capture.part_count,
                part_role=command.capture.part_role, source_intent=command.capture.source_intent,
                captured_timezone=command.clip.captured_timezone,
                content_fingerprint=command.capture.content_fingerprint or stored.content_hash,
            ))
            if route is not None:
                metadata = self._with_routing(metadata, route)
            self.store.save_normalized_metadata(clip_id=stored.id, client_request_id=command.client_request_id,
                                                metadata=metadata)
            if self.processing_mode == "worker":
                if self.pipeline_store is None:
                    raise IngestInternalError("pipeline store unavailable")
                self.pipeline_store.register_acceptance(
                    clip_id=stored.id,
                    client_request_id=command.client_request_id,
                    adapter=command.source.adapter,
                    client_id=command.source.client_id,
                    event_id=command.source.event_id,
                    source_app=command.source.source_app,
                    occurred_at=captured_at,
                    deployment_environment=self.deployment_environment,
                    filename=stored.filename,
                    mime_type=detected_mime,
                    size_bytes=stored.size_bytes,
                    content_hash=stored.content_hash,
                    storage_uri=stored.original_path,
                    knowledge_base_id=route.knowledge_base_id if route is not None else "",
                    route_decision_id=route.id if route is not None else None,
                    association_type=(
                        "manual"
                        if command.routing.target_knowledge_base_id and command.routing.mode != "default_only"
                        else "automatic"
                    ),
                )
            self._attempt(command, "received")
            self._finish_receipt(receipt_id, stored, "available", command)
            return self._result(stored, receipt_id=receipt_id, duplicate=stored.duplicate,
                                target=command.routing.target_knowledge_base_id)
        except Exception as error:
            self._record_failure(command, signature, receipt_id, stored, attempt_registered, error)
            if stored is not None and isinstance(error, (IngestConflictError, IngestValidationError)):
                raise
            if stored is not None:
                raise IngestInternalError() from error
            raise
        finally:
            if source_lock and source_token:
                self.store.release_request_lock_token(source_lock, source_token)
            if batch_lock and batch_token:
                self.store.release_request_lock_token(batch_lock, batch_token)
            self.store.release_request_lock_token(command.client_request_id, request_token)

    def _validate(self, command: IngestCommand) -> None:
        if command.contract_version != INGEST_CONTRACT_VERSION:
            raise IngestValidationError("unsupported contract_version")
        if command.replay_policy == "strict_v1" and not command.client_request_id:
            raise IngestValidationError("client_request_id is required")
        if command.clip.source_type not in {"text", "url", "image", "file", "screen_clip"}:
            raise IngestValidationError("unsupported source_type")
        capture = command.capture
        if capture.client_batch_id and not CAPTURE_ID_RE.fullmatch(capture.client_batch_id):
            raise IngestValidationError("invalid client_batch_id")
        if capture.parent_client_request_id and not CAPTURE_ID_RE.fullmatch(capture.parent_client_request_id):
            raise IngestValidationError("invalid parent_client_request_id")
        if not 1 <= capture.part_count <= 100 or not 0 <= capture.part_index < capture.part_count:
            raise IngestValidationError("invalid client part index/count")
        if not capture.client_batch_id and (capture.part_index != 0 or capture.part_count != 1):
            raise IngestValidationError("multipart capture requires client_batch_id")
        if capture.client_batch_id and not capture.parent_client_request_id:
            raise IngestValidationError("capture batch requires parent_client_request_id")
        if capture.client_batch_id and not command.client_request_id:
            raise IngestValidationError("capture batch requires client_request_id")
        if capture.part_role not in CAPTURE_PART_ROLES:
            raise IngestValidationError("invalid part_role")
        if capture.source_intent not in CAPTURE_SOURCE_INTENTS:
            raise IngestValidationError("invalid source_intent")
        if capture.content_fingerprint and not re.fullmatch(r"[a-f0-9]{64}", capture.content_fingerprint.lower()):
            raise IngestValidationError("invalid content_fingerprint")
        if command.routing.mode not in {"", "default_only"}:
            raise IngestValidationError("unsupported routing mode")

    def _validate_existing_ownership(self, clip: StoredClip, command: IngestCommand) -> bool:
        c = command.capture
        if clip.client_request_id != command.client_request_id:
            raise IngestConflictError(CAPTURE_OWNERSHIP_CONFLICT_DETAIL)
        if clip.capture_client_batch_id:
            if (c.client_batch_id, c.parent_client_request_id, command.client_request_id, c.part_index, c.part_count, c.part_role) != (
                clip.capture_client_batch_id, clip.capture_parent_client_request_id, clip.client_request_id,
                clip.capture_part_index, clip.capture_part_count, clip.capture_part_role,
            ):
                raise IngestConflictError(CAPTURE_OWNERSHIP_CONFLICT_DETAIL)
            return False
        if not c.client_batch_id:
            return False
        if not c.parent_client_request_id or c.part_index != 0 or c.part_count != 1:
            raise IngestConflictError(CAPTURE_OWNERSHIP_CONFLICT_DETAIL)
        return True

    def _validate_batch(self, command: IngestCommand) -> None:
        try:
            self.store.validate_capture_batch_part(
                batch_id=command.capture.client_batch_id,
                parent_id=command.capture.parent_client_request_id,
                client_request_id=command.client_request_id, part_index=command.capture.part_index,
                part_count=command.capture.part_count, part_role=command.capture.part_role,
            )
        except CaptureOwnershipConflict as error:
            raise IngestConflictError(CAPTURE_OWNERSHIP_CONFLICT_DETAIL) from error
        except ValueError as error:
            raise IngestValidationError(str(error)) from error

    def _attempt(self, command: IngestCommand, status: str, error_code: str = "") -> None:
        self.store.upsert_capture_part_attempt(
            batch_id=command.capture.client_batch_id, parent_id=command.capture.parent_client_request_id,
            client_request_id=command.client_request_id, part_index=command.capture.part_index,
            part_count=command.capture.part_count, part_role=command.capture.part_role,
            status=status, error_code=error_code,
        )

    def _route(self, stored: StoredClip, command: IngestCommand, *, strict: bool = False):
        try:
            existing = self.knowledge_store.find_latest_route_decision_by_clip_id(stored.id)
            if existing is not None:
                return existing
            preview = preview_route(self.knowledge_store, RoutingPreviewInput(
                source_type=command.clip.source_type, title_hint=stored.title, note=command.clip.note,
                text=command.clip.text, url=command.clip.url,
                mime_type=normalize_mime_type((command.asset.mime_type if command.asset else "") or command.clip.mime_type),
                filename=stored.filename, device_name=command.clip.device_name,
                source_app=command.source.source_app, client_request_id=command.client_request_id,
                target_knowledge_base_id=command.routing.target_knowledge_base_id,
                routing_mode=command.routing.mode,
            ))
            return self.knowledge_store.save_route_decision(
                clip_id=stored.id, client_request_id=command.client_request_id,
                knowledge_base_id=preview.knowledge_base_id, ragflow_dataset_id=preview.ragflow_dataset_id,
                decision_type=preview.decision_type, matched_rule_id=preview.matched_rule_id,
                matched_rule_ids=preview.matched_rule_ids, confidence=preview.confidence,
                manual_override=preview.manual_override, reason=preview.reason,
            )
        except Exception:
            if strict:
                raise
            return None

    def _reconcile_existing(self, command: IngestCommand, receipt_id: str,
                            stored: StoredClip | None = None) -> IngestResult:
        receipt = self.store.find_ingest_receipt_by_id(receipt_id)
        if receipt is None:
            raise IngestConflictError()
        if stored is None:
            try:
                clip_id = int(receipt.clip_id)
            except (TypeError, ValueError) as error:
                raise IngestConflictError() from error
            raw = self.store.find_raw_fields_by_clip_id(clip_id)
            stored = self.store.find_by_request_id(command.client_request_id)
            if raw is None or stored is None or raw.client_request_id != command.client_request_id:
                raise IngestConflictError()
        self._validate_existing_ownership(stored, command)
        self._validate_batch(command)
        route = self._route(stored, command, strict=command.replay_policy == "strict_v1")
        raw = self.store.find_raw_fields_by_clip_id(stored.id)
        if raw is None:
            raise IngestInternalError()
        existing = self.store.find_normalized_metadata_by_clip_id(stored.id)
        metadata = dict(existing.metadata) if existing else self._metadata_from_raw(raw)
        capture = dict(metadata.get("capture", {}))
        capture.update(source_intent=command.capture.source_intent,
                       captured_timezone=command.clip.captured_timezone,
                       content_fingerprint=command.capture.content_fingerprint or stored.content_hash)
        metadata["capture"] = capture
        if route is not None:
            metadata = self._with_routing(metadata, route)
        self.store.save_normalized_metadata(clip_id=stored.id, client_request_id=command.client_request_id,
                                            metadata=metadata)
        self._attempt(command, "received")
        self._finish_receipt(receipt_id, stored, "available", command)
        return self._result(stored, receipt_id=receipt_id, duplicate=True,
                            target=command.routing.target_knowledge_base_id)

    def _record_failure(self, command: IngestCommand, signature: str, receipt_id: str,
                        stored: StoredClip | None, attempt_registered: bool, error: Exception) -> None:
        if attempt_registered:
            try:
                self._attempt(command, "failed", "post_store_repairable" if stored else "ingest_error")
            except Exception:
                pass
        if not receipt_id:
            return
        strict = command.replay_policy == "strict_v1"
        metadata_status = "available" if stored and self.store.find_normalized_metadata_by_clip_id(stored.id) else "missing"
        try:
            self.store.finish_ingest_receipt(
                receipt_id=receipt_id, status="failed", clip_id=str(stored.id) if stored else "",
                archive_status=stored.archive_status if stored else "failed", metadata_status=metadata_status,
                error_code="post_store_repairable" if stored else self._safe_error_code(error),
                expected_contract_version=command.contract_version if strict else "legacy_mobile",
                expected_source_adapter=command.source.adapter if strict else "android",
                expected_request_signature=signature if strict else "legacy_mobile",
            )
        except Exception:
            pass

    def _with_routing(self, metadata: dict[str, object], route) -> dict[str, object]:
        kb = self.knowledge_store.get_knowledge_base(route.knowledge_base_id, include_deleted=True)
        result = dict(metadata)
        result["routing"] = {
            "knowledge_base_id": route.knowledge_base_id, "knowledge_base_name": kb.name if kb else "",
            "ragflow_dataset_id": route.ragflow_dataset_id, "decision_type": route.decision_type,
            "matched_rule_ids": route.matched_rule_ids, "reason": route.reason,
            "manual_override": route.manual_override, "routed_at": route.created_at,
        }
        return result

    def _ensure_metadata(self, clip: StoredClip, command: IngestCommand, *, refresh_capture: bool = False) -> None:
        raw = self.store.find_raw_fields_by_clip_id(clip.id)
        if raw is None:
            return
        existing = self.store.find_normalized_metadata_by_clip_id(clip.id)
        if existing and not refresh_capture:
            return
        metadata = dict(existing.metadata) if existing else self._metadata_from_raw(raw)
        if existing and refresh_capture:
            capture = dict(self._metadata_from_raw(raw)["capture"])
            capture.update(source_intent=command.capture.source_intent,
                           captured_timezone=command.clip.captured_timezone,
                           content_fingerprint=command.capture.content_fingerprint or raw.content_hash)
            metadata["capture"] = capture
        route = self.knowledge_store.find_latest_route_decision_by_clip_id(raw.id)
        if route:
            metadata = self._with_routing(metadata, route)
        self.store.save_normalized_metadata(clip_id=raw.id, client_request_id=raw.client_request_id,
                                            metadata=metadata)

    @staticmethod
    def _metadata_from_raw(raw: StoredClipRawFields) -> dict[str, object]:
        return build_normalized_metadata(NormalizedMetadataInput(
            source_type=raw.source_type, title_hint=raw.title_hint, note=raw.note, text=raw.text,
            url=raw.url, mime_type=raw.mime_type, device_name=raw.device_name, source_app=raw.source_app,
            captured_at=raw.captured_at, client_request_id=raw.client_request_id, filename=raw.filename,
            has_file=raw.source_type in {"file", "image"}, size_bytes=raw.size_bytes,
            content_hash=raw.content_hash, storage_uri=raw.original_path, received_at=raw.created_at,
            archive_status=raw.archive_status, ragflow_document_id=raw.ragflow_document_id,
            client_batch_id=raw.capture_client_batch_id,
            parent_client_request_id=raw.capture_parent_client_request_id,
            part_index=raw.capture_part_index, part_count=raw.capture_part_count,
            part_role=raw.capture_part_role, content_fingerprint=raw.content_hash,
        ))

    def _finish_receipt(self, receipt_id: str, clip: StoredClip, metadata_status: str, command: IngestCommand) -> None:
        if receipt_id:
            strict = command.replay_policy == "strict_v1"
            receipt = self.store.finish_ingest_receipt(
                receipt_id=receipt_id, status="received", clip_id=str(clip.id),
                archive_status=clip.archive_status, metadata_status=metadata_status,
                expected_contract_version=command.contract_version if strict else "legacy_mobile",
                expected_source_adapter=command.source.adapter if strict else "android",
                expected_request_signature=request_signature(command) if strict else "legacy_mobile",
            )
            if receipt is None or receipt.status != "received" or receipt.clip_id != str(clip.id):
                raise IngestInternalError()

    @staticmethod
    def _safe_error_code(error: Exception) -> str:
        return {
            IngestValidationError: "validation_error",
            IngestConflictError: "conflict_error",
            IngestNotFoundError: "not_found",
            IngestPayloadTooLargeError: "payload_too_large",
            IngestUnsupportedMediaError: "unsupported_media",
            IngestArchiveError: "archive_error",
            IngestInternalError: "internal_error",
        }.get(type(error), "ingest_error")

    def _result(self, clip: StoredClip, *, receipt_id: str, duplicate: bool, target: str) -> IngestResult:
        route = self.knowledge_store.find_latest_route_decision_by_clip_id(clip.id)
        return IngestResult(
            receipt_id=receipt_id, clip_id=str(clip.id), client_request_id=clip.client_request_id,
            duplicate=duplicate, title=clip.title, platform=clip.platform,
            content_hash=clip.content_hash, filename=clip.filename, size_bytes=clip.size_bytes,
            archive_status=clip.archive_status,
            metadata_status="available" if self.store.find_normalized_metadata_by_clip_id(clip.id) else "missing",
            capture={"client_batch_id": clip.capture_client_batch_id,
                     "parent_client_request_id": clip.capture_parent_client_request_id,
                     "part_index": clip.capture_part_index, "part_count": clip.capture_part_count,
                     "part_role": clip.capture_part_role},
            routing={"status": "available" if route else "missing",
                     "knowledge_base_id": route.knowledge_base_id if route else target,
                     "decision_type": route.decision_type if route else ""},
        )
