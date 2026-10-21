from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from perclip_ingest.config import RagflowSettings
from perclip_ingest.ragflow_adapter import (
    RagflowAdapterError,
    RagflowUnsupportedError,
)
from perclip_ingest.ragflow_index import safe_hash_alias
from perclip_ingest.ragflow_operator_verifier import (
    ExternalCommandEvidenceProvider,
    OperatorEvidenceSnapshot,
    OperatorVerifiedRagflowAdapter,
)

FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "tests"
    / "fixtures"
    / "staging"
    / "perclip_ragflow_synthetic_v1.json"
)


def _provider_script(payload: dict[str, object], *, exit_code: int = 0) -> list[str]:
    return [
        sys.executable,
        "-c",
        (
            "import json,sys;"
            "json.load(sys.stdin);"
            f"print({json.dumps(json.dumps(payload))});"
            f"raise SystemExit({exit_code})"
        ),
    ]


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "perclip-ragflow-operator-evidence.v1",
        "dataset_alias": safe_hash_alias("dataset-test"),
        "document_alias": safe_hash_alias("document-test"),
        "chunk_count": 2,
        "vector_count": 2,
        "covered_chunk_count": 2,
        "evidence_type": "operator_es_exact_document",
    }
    payload.update(overrides)
    return payload


def test_real_multichunk_fixture_is_disposable_newline_separated_and_bounded():
    corpus = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    items = {
        item["key"]: item
        for item in corpus["items"]
        if isinstance(item, dict) and "key" in item
    }
    fixture = items["real_multichunk_disposable"]
    paragraphs = fixture["paragraphs"]
    separator = fixture["paragraph_separator"]
    repeat = fixture["paragraph_repeat"]
    expanded_paragraphs = [
        paragraph
        for paragraph in paragraphs
        for _ in range(repeat)
    ]
    canonical_text = separator.join(expanded_paragraphs)

    assert fixture["scenario"] == "real_multichunk_vector_coverage"
    assert fixture["retain"] is False
    assert len(paragraphs) >= 12
    assert repeat >= 2
    assert separator == "\n\n"
    expected_separator_count = (
        sum(paragraph.count(separator) for paragraph in expanded_paragraphs)
        + len(expanded_paragraphs)
        - 1
    )
    assert canonical_text.count(separator) == expected_separator_count
    assert len(canonical_text.encode("utf-8")) >= 40_000
    assert all(paragraph.startswith("## Station ") for paragraph in paragraphs)
    assert "PERCLIP_MULTICHUNK_FIRST" in paragraphs[0]
    assert "PERCLIP_MULTICHUNK_MIDDLE" in paragraphs[len(paragraphs) // 2]
    assert "PERCLIP_MULTICHUNK_LAST" in paragraphs[-1]


def test_external_provider_accepts_only_alias_bound_complete_evidence():
    provider = ExternalCommandEvidenceProvider(_provider_script(_payload()))

    evidence = provider.inspect(
        dataset_id="dataset-test", document_id="document-test"
    )

    assert evidence == OperatorEvidenceSnapshot(
        chunk_count=2,
        vector_count=2,
        covered_chunk_count=2,
        evidence_type="operator_es_exact_document",
    )


@pytest.mark.parametrize(
    "payload",
    [
        _payload(dataset_alias=safe_hash_alias("other")),
        _payload(document_alias=safe_hash_alias("other")),
        _payload(schema="other"),
        _payload(chunk_count=True),
        _payload(evidence_type="guessed"),
    ],
)
def test_external_provider_fails_closed_for_untrusted_output(payload):
    provider = ExternalCommandEvidenceProvider(_provider_script(payload))

    with pytest.raises(RagflowUnsupportedError):
        provider.inspect(dataset_id="dataset-test", document_id="document-test")


def test_external_provider_does_not_surface_command_stderr_or_remote_ids():
    provider = ExternalCommandEvidenceProvider(
        [
            sys.executable,
            "-c",
            "import sys;sys.stderr.write('private-dataset private-document');raise SystemExit(2)",
        ]
    )

    with pytest.raises(RagflowAdapterError) as error:
        provider.inspect(dataset_id="private-dataset", document_id="private-document")

    assert "private-dataset" not in str(error.value)
    assert "private-document" not in str(error.value)


class ChunkClient:
    def get_chunks(
        self, base_url, api_key, dataset_id, document_id, page, page_size
    ):
        return {
            "data": {
                "chunks": [{"id": "chunk-1"}, {"id": "chunk-2"}],
                "total": 2,
            }
        }


class DeletedClient(ChunkClient):
    def get_document(
        self, base_url, api_key, dataset_id, document_id
    ):
        return {"data": {"docs": [], "total": 0}}


class StaticEvidenceProvider:
    def __init__(self, snapshot: OperatorEvidenceSnapshot):
        self.snapshot = snapshot

    def inspect(self, *, dataset_id: str, document_id: str):
        return self.snapshot


def _settings() -> RagflowSettings:
    return RagflowSettings(
        base_url="http://ragflow",
        api_key="key",
        enable_real_sync=True,
        sync_allow_dataset_ids=frozenset({"dataset-test"}),
    )


def test_operator_adapter_requires_public_and_internal_chunk_count_agreement():
    adapter = OperatorVerifiedRagflowAdapter(
        _settings(),
        StaticEvidenceProvider(
            OperatorEvidenceSnapshot(2, 2, 2, "operator_es_exact_document")
        ),
        ChunkClient(),
    )

    evidence = adapter.get_vector_evidence("dataset-test", "document-test")

    assert evidence.vector_count == 2
    assert evidence.covered_chunk_count == 2
    assert evidence.evidence_type == "operator_es_exact_document"
    assert (
        adapter.capability_report().capabilities["document_vector_evidence"]
        == "enabled_operator_verifier"
    )


def test_operator_adapter_verifies_deleted_without_inaccessible_public_chunk_route():
    adapter = OperatorVerifiedRagflowAdapter(
        _settings(),
        StaticEvidenceProvider(
            OperatorEvidenceSnapshot(0, 0, 0, "operator_es_exact_document")
        ),
        DeletedClient(),
    )

    status, chunks, vectors = adapter.verify_deleted(
        "dataset-test", "document-test"
    )

    assert status.status == "missing"
    assert chunks.chunk_count == vectors.vector_count == 0
    assert vectors.covered_chunk_count == 0


@pytest.mark.parametrize(
    "snapshot",
    [
        OperatorEvidenceSnapshot(1, 1, 1, "operator_es_exact_document"),
        OperatorEvidenceSnapshot(2, 1, 1, "operator_es_exact_document"),
    ],
)
def test_operator_adapter_fails_closed_for_count_or_coverage_mismatch(snapshot):
    adapter = OperatorVerifiedRagflowAdapter(
        _settings(), StaticEvidenceProvider(snapshot), ChunkClient()
    )

    with pytest.raises(RagflowUnsupportedError):
        adapter.get_vector_evidence("dataset-test", "document-test")
