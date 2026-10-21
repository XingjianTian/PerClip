from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from .config import RagflowSettings
from .ragflow_adapter import (
    HttpRagflowAdapter,
    RagflowAdapterError,
    RagflowCapabilityReport,
    RagflowHttpClient,
    RagflowUnsupportedError,
)
from .ragflow_index import (
    RagflowChunkSummary,
    RagflowDocumentStatus,
    RagflowVectorEvidence,
    safe_hash_alias,
)


OPERATOR_EVIDENCE_SCHEMA = "perclip-ragflow-operator-evidence.v1"
ALLOWED_OPERATOR_EVIDENCE_TYPES = frozenset({"operator_es_exact_document"})


@dataclass(frozen=True)
class OperatorEvidenceSnapshot:
    chunk_count: int
    vector_count: int
    covered_chunk_count: int
    evidence_type: str

    def __post_init__(self) -> None:
        for value in (
            self.chunk_count,
            self.vector_count,
            self.covered_chunk_count,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("invalid operator evidence count")
        if self.evidence_type not in ALLOWED_OPERATOR_EVIDENCE_TYPES:
            raise ValueError("unsupported operator evidence type")


class OperatorEvidenceProvider(Protocol):
    def inspect(
        self, *, dataset_id: str, document_id: str
    ) -> OperatorEvidenceSnapshot:
        ...


class ExternalCommandEvidenceProvider:
    """Run an explicit operator verifier without putting remote IDs in argv."""

    def __init__(self, command: Sequence[str], *, timeout_seconds: float = 30.0):
        if not command or any(not str(item).strip() for item in command):
            raise ValueError("operator verifier command must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("operator verifier timeout must be positive")
        self.command = tuple(str(item) for item in command)
        self.timeout_seconds = timeout_seconds

    def inspect(
        self, *, dataset_id: str, document_id: str
    ) -> OperatorEvidenceSnapshot:
        request = {
            "schema": OPERATOR_EVIDENCE_SCHEMA,
            "dataset_id": dataset_id,
            "document_id": document_id,
        }
        try:
            result = subprocess.run(
                self.command,
                input=json.dumps(request, separators=(",", ":")),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RagflowAdapterError(
                "operator vector verifier is unavailable"
            ) from error
        if result.returncode != 0:
            raise RagflowAdapterError("operator vector verifier failed safely")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RagflowUnsupportedError(
                "operator vector verifier returned invalid JSON"
            ) from error
        self._validate_identity(payload, dataset_id=dataset_id, document_id=document_id)
        try:
            return OperatorEvidenceSnapshot(
                chunk_count=payload["chunk_count"],
                vector_count=payload["vector_count"],
                covered_chunk_count=payload["covered_chunk_count"],
                evidence_type=payload["evidence_type"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise RagflowUnsupportedError(
                "operator vector verifier returned invalid evidence"
            ) from error

    @staticmethod
    def _validate_identity(
        payload: Any, *, dataset_id: str, document_id: str
    ) -> None:
        if not isinstance(payload, dict):
            raise RagflowUnsupportedError(
                "operator vector verifier returned invalid evidence"
            )
        if payload.get("schema") != OPERATOR_EVIDENCE_SCHEMA:
            raise RagflowUnsupportedError(
                "operator vector verifier schema mismatch"
            )
        if payload.get("dataset_alias") != safe_hash_alias(dataset_id):
            raise RagflowUnsupportedError(
                "operator vector verifier dataset mismatch"
            )
        if payload.get("document_alias") != safe_hash_alias(document_id):
            raise RagflowUnsupportedError(
                "operator vector verifier document mismatch"
            )


class OperatorVerifiedRagflowAdapter(HttpRagflowAdapter):
    """Staging-only HTTP adapter augmented by exact internal index evidence."""

    def __init__(
        self,
        settings: RagflowSettings,
        evidence_provider: OperatorEvidenceProvider,
        client: RagflowHttpClient | None = None,
    ) -> None:
        super().__init__(settings, client)
        self.evidence_provider = evidence_provider

    def get_vector_evidence(
        self, dataset_id: str, document_id: str
    ) -> RagflowVectorEvidence:
        self.require_allowed_dataset(dataset_id)
        public_chunks = super().get_chunk_summary(dataset_id, document_id)
        operator = self.evidence_provider.inspect(
            dataset_id=dataset_id, document_id=document_id
        )
        if operator.chunk_count != public_chunks.chunk_count:
            raise RagflowUnsupportedError(
                "public and operator chunk counts do not match"
            )
        if operator.covered_chunk_count != operator.chunk_count:
            raise RagflowUnsupportedError(
                "operator vector coverage is incomplete"
            )
        return RagflowVectorEvidence(
            document_id=document_id,
            vector_count=operator.vector_count,
            covered_chunk_count=operator.covered_chunk_count,
            evidence_type=operator.evidence_type,
        )

    def verify_deleted(
        self, dataset_id: str, document_id: str
    ) -> tuple[
        RagflowDocumentStatus, RagflowChunkSummary, RagflowVectorEvidence
    ]:
        status = self.get_document_status(dataset_id, document_id)
        if status.status != "missing":
            return super().verify_deleted(dataset_id, document_id)
        operator = self.evidence_provider.inspect(
            dataset_id=dataset_id, document_id=document_id
        )
        if operator.covered_chunk_count != operator.chunk_count:
            raise RagflowUnsupportedError(
                "operator deletion coverage is incomplete"
            )
        return (
            status,
            RagflowChunkSummary(document_id, operator.chunk_count),
            RagflowVectorEvidence(
                document_id=document_id,
                vector_count=operator.vector_count,
                covered_chunk_count=operator.covered_chunk_count,
                evidence_type=operator.evidence_type,
            ),
        )

    def capability_report(self) -> RagflowCapabilityReport:
        report = super().capability_report()
        capabilities = dict(report.capabilities)
        capabilities["document_vector_evidence"] = "enabled_operator_verifier"
        return RagflowCapabilityReport(
            adapter_status="real_sync_operator_verified",
            configured=report.configured,
            capabilities=capabilities,
            notes=[
                *report.notes,
                "Vector evidence comes from an explicitly configured staging operator verifier.",
            ],
        )
