from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

from quality_tools.q1_evaluator import build_report, evaluate_case, load_manifest, markdown_report


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "quality"
MANIFEST = FIXTURE_ROOT / "q1-web-v2.jsonl"
Q0_MANIFEST = FIXTURE_ROOT / "manifest.jsonl"
BASELINE_JSON = FIXTURE_ROOT.parents[2] / "docs" / "quality" / "baselines" / "q1-web-v2.json"
BASELINE_MARKDOWN = BASELINE_JSON.with_suffix(".md")
EXPECTED_IDS = [f"G{index:02d}" for index in range(1, 23)] + ["G37", "G38", "G39", "G40"]
Q1_MANIFEST_SHA256 = "316ed0a6090ecbcc922a8737e8ccb718190b52b4eb6e871015e4fdc6dd0d44bc"
Q0_MANIFEST_SHA256 = "9247815c9cad5bb6beb6528919cb37d565ce78c03b3acb7ab01149d49f6a05aa"


def test_q1_manifest_has_exact_contract_and_preserves_q0():
    rows = load_manifest(MANIFEST)

    assert hashlib.sha256(MANIFEST.read_bytes()).hexdigest() == Q1_MANIFEST_SHA256
    assert hashlib.sha256(Q0_MANIFEST.read_bytes()).hexdigest() == Q0_MANIFEST_SHA256
    assert [row["id"] for row in rows] == EXPECTED_IDS
    assert len(rows) == 26
    assert {row["corpus_version"] for row in rows} == {"q1-web-v2"}
    assert all(row["license"] == "CC0-1.0" for row in rows)


def test_q1_first_baseline_is_fully_deterministic_and_matches_all_contracts():
    first = build_report(MANIFEST, perclip_commit="determinism-commit")
    second = build_report(MANIFEST, perclip_commit="determinism-commit")

    assert first == second
    assert markdown_report(first) == markdown_report(second)
    assert first["schema_version"] == "perclip.quality-corpus-report.v2"
    assert first["baseline_mode"] == "first_v2_baseline"
    assert first["relative_comparison"] is None
    assert first["summary"] == {
        "case_count": 26,
        "contract_passed": 26,
        "contract_failed": 0,
        "all_contracts_match": True,
    }
    assert all(case["contract_match"] for case in first["cases"])
    assert {case["actual_source"] for case in first["cases"]} == {"quality_read_model"}
    assert "improved" not in json.dumps(first)
    assert "unchanged" not in json.dumps(first)
    assert "regressed" not in json.dumps(first)


def test_hard_gates_corpus_case_never_bypasses_or_synthesizes_quality_read_model():
    source = inspect.getsource(evaluate_case)
    assert "except IngestUnsupportedMediaError" not in source, "unsupported_binary_actual_is_synthesized"
    assert '"actual_source": "quality_read_model"' in source, "corpus_case_bypasses_quality_read_model"


def test_g17_uses_public_multipart_ingest_and_preserves_failure_boundaries():
    row = next(item for item in load_manifest(MANIFEST) if item["id"] == "G17")
    case = evaluate_case(row, FIXTURE_ROOT)

    assert case["actual_source"] == "quality_read_model"
    assert case["actual"]["user_status"] == "needs_attention"
    assert case["actual"]["processing_state"] == "failed"
    assert case["actual"]["content_title"] == "unsupported.bin"
    assert case["boundary_evidence"] == {
        "public_clip_identity": True,
        "raw_asset_preserved": True,
        "filename_provenance": True,
        "recall_excluded": True,
        "index_excluded": True,
    }


def test_frozen_q1_baseline_matches_evaluator_and_contains_no_private_values():
    baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    rebuilt = build_report(MANIFEST, perclip_commit=baseline["perclip_commit"])

    assert baseline == rebuilt
    assert BASELINE_MARKDOWN.read_text(encoding="utf-8") == markdown_report(rebuilt)
    assert baseline["manifest_hash"] == Q1_MANIFEST_SHA256
    assert len(baseline["perclip_commit"]) == 40
    serialized = json.dumps(baseline) + BASELINE_MARKDOWN.read_text(encoding="utf-8")
    for forbidden in ("/Users/", "/Volumes/", "Bearer ", "ragflow_dataset_id", "ragflow_document_id"):
        assert forbidden not in serialized
