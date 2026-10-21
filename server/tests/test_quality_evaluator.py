from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from perclip_ingest.ingest_service import IngestService
from perclip_ingest.web_extraction import WebFetchError
from perclip_ingest.worker import PipelineWorker
from quality_tools.q0_evaluator import (
    ResponsePlanFetcher,
    build_candidate_report,
    build_report,
    load_manifest,
    markdown_report,
)


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "quality"
MANIFEST = FIXTURE_ROOT / "manifest.jsonl"
BASELINE_JSON = FIXTURE_ROOT.parents[2] / "docs" / "quality" / "baselines" / "q0-web-v1.json"
BASELINE_MARKDOWN = BASELINE_JSON.with_suffix(".md")
EXPECTED_IDS = [f"G{index:02d}" for index in range(1, 23)] + [
    "G37",
    "G38",
    "G39",
    "G40",
]


def test_q0_manifest_has_exact_tier_and_verified_artifact_hashes():
    rows = load_manifest(MANIFEST)

    assert len(rows) == 26
    assert [row["id"] for row in rows] == EXPECTED_IDS
    assert {row["fixture_version"] for row in rows} == {"q0-web-v1"}
    assert {row["license"] for row in rows} == {"CC0-1.0"}
    assert sum(len(row["artifacts"]) for row in rows) == 40
    assert all(row["source_class"] for row in rows)
    assert all(
        artifact["license"] and artifact["source_class"]
        for row in rows
        for artifact in row["artifacts"]
    )


def test_response_plan_transport_is_socket_free_and_models_redirect_security_and_oversize():
    redirected = ResponsePlanFetcher(FIXTURE_ROOT, "response-plans/G09.json").fetch(
        "https://example.test/start?utm_source=fixture"
    )
    assert redirected.resolved_url == "https://example.test/final/redirected"
    assert "来源链可审计" in redirected.body.decode("utf-8")

    with pytest.raises(WebFetchError, match="private_address_blocked"):
        ResponsePlanFetcher(FIXTURE_ROOT, "response-plans/G13.json").fetch(
            "https://rebind.example.test/article"
        )
    with pytest.raises(WebFetchError, match="response_too_large"):
        ResponsePlanFetcher(FIXTURE_ROOT, "response-plans/G15.json").fetch(
            "https://example.test/large/article"
        )


def test_q0_evaluator_runs_current_pipeline_and_emits_required_baseline_fields(monkeypatch):
    calls = {"ingest": 0, "worker": 0}
    original_ingest = IngestService.ingest
    original_run_once = PipelineWorker.run_once

    async def observed_ingest(self, command):
        calls["ingest"] += 1
        return await original_ingest(self, command)

    def observed_run_once(self, *, limit=20):
        calls["worker"] += 1
        return original_run_once(self, limit=limit)

    monkeypatch.setattr(IngestService, "ingest", observed_ingest)
    monkeypatch.setattr(PipelineWorker, "run_once", observed_run_once)
    report = build_report(MANIFEST, perclip_commit="test-commit")

    assert report["schema_version"] == "perclip.quality.q0.v2"
    assert report["fixture_version"] == "q0-web-v1"
    assert report["perclip_commit"] == "test-commit"
    assert report["aggregate"]["fixture_count"] == 26
    assert report["aggregate"]["comparison"] == {
        "comparison_mode": "baseline",
        "baseline_cases": 26,
        "improved": 0,
        "unchanged": 0,
        "regressed": 0,
    }
    assert {case["comparison_to_previous"] for case in report["cases"]} == {"baseline"}
    assert all(report["aggregate"]["control_metrics"].values())
    assert set(report["aggregate"]["applicable_metric_result"]) >= {
        "raw_asset_preservation",
        "title_accuracy",
        "body_anchors",
        "noise_residue",
        "canonical_url",
        "state_calibration",
        "routing",
        "recall_eligibility",
        "projection_consumption",
        "retry_idempotency",
    }
    for metric in report["aggregate"]["applicable_metric_result"].values():
        assert set(metric) == {"passed", "eligible", "not_applicable", "rate"}
        assert metric["eligible"] + metric["not_applicable"] == 26
    assert report["aggregate"]["applicable_metric_result"]["body_anchors"]["eligible"] < 26
    assert report["aggregate"]["applicable_metric_result"]["safe_error"]["eligible"] < 26
    latency = report["aggregate"]["local_fixture_pipeline_latency"]
    assert set(latency["end_to_end"]) == {"p50", "p95"}
    assert "real DNS" in latency["excluded_boundaries"]
    assert calls["ingest"] >= 26
    assert calls["worker"] >= 26

    oversized = next(case for case in report["cases"] if case["id"] == "G15")
    assert oversized["actual"]["state"] == "failed"
    assert oversized["safe_error"] == "response_too_large"
    assert oversized["actual"]["unverified_partial_body_retained"] is False
    assert set(oversized) >= {
        "input_hash",
        "expected",
        "actual",
        "safe_error",
        "stage_timings_ms",
        "contract_matches",
        "all_case_contract_match",
        "metric_results",
        "comparison_to_previous",
    }
    assert oversized["metric_results"]["body_anchors"] == {
        "applicable": False,
        "passed": None,
    }

    summary = markdown_report(report)
    assert "# PerClip Q0-Web baseline" in summary
    assert "Main baseline failure categories" in summary
    assert "Not applicable" in summary
    assert "Local fixture pipeline latency" in summary
    assert "not a home-NAS, cloud-server, production-SLO" in summary
    assert "extractor, cleaner, enricher" in summary


def _without_timing(report: dict) -> dict:
    normalized = copy.deepcopy(report)
    normalized["aggregate"].pop("local_fixture_pipeline_latency", None)
    normalized["aggregate"].get("comparison", {}).pop("latency_p95", None)
    normalized.pop("generated_at", None)
    for case in normalized["cases"]:
        case.pop("stage_timings_ms", None)
        case.pop("end_to_end_ms", None)
        case.pop("generated_at", None)
        case.pop("run_id", None)
        case.pop("temporary_directory", None)
    return normalized


def _without_markdown_timing(markdown: str, stage_names: set[str]) -> str:
    lines = []
    for line in markdown.splitlines():
        if line.startswith("- Local fixture pipeline p50:"):
            lines.append("- Local fixture pipeline p50: <timing>")
        elif line.startswith("- Local fixture pipeline p95:"):
            lines.append("- Local fixture pipeline p95: <timing>")
        elif line.startswith("- Local fixture p95 change:"):
            lines.append("- Local fixture p95 change: <timing>")
        elif line.startswith("| ") and line.split("|", 2)[1].strip() in stage_names:
            lines.append(f"| {line.split('|', 2)[1].strip()} | <timing> | <timing> |")
        else:
            lines.append(line)
    return "\n".join(lines)


def test_full_q0_is_non_timing_deterministic_across_two_runs():
    first = build_report(MANIFEST, perclip_commit="determinism-commit")
    second = build_report(MANIFEST, perclip_commit="determinism-commit")

    assert _without_timing(first) == _without_timing(second)
    first_stages = set(first["aggregate"]["local_fixture_pipeline_latency"]["by_stage"])
    second_stages = set(second["aggregate"]["local_fixture_pipeline_latency"]["by_stage"])
    assert first_stages == second_stages
    assert _without_markdown_timing(markdown_report(first), first_stages) == _without_markdown_timing(
        markdown_report(second), second_stages
    )
    assert first["manifest_input_hash"] == second["manifest_input_hash"]
    assert [case["id"] for case in first["cases"]] == EXPECTED_IDS
    for first_case, second_case in zip(first["cases"], second["cases"], strict=True):
        for field in ("input_hash", "fixture_version", "expected", "actual", "safe_error"):
            assert first_case[field] == second_case[field]


def test_frozen_q0_baseline_integrity_and_safe_provenance():
    baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    rows = load_manifest(MANIFEST)

    assert baseline["fixture_version"] == "q0-web-v1"
    assert [case["id"] for case in baseline["cases"]] == EXPECTED_IDS
    assert baseline["aggregate"]["fixture_count"] == 26
    assert baseline["manifest_input_hash"] == hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{40}", baseline["perclip_commit"])
    assert all(case["fixture_version"] == baseline["fixture_version"] for case in baseline["cases"])
    assert all(row["license"] and row["source_class"] for row in rows)
    assert all(
        hashlib.sha256((FIXTURE_ROOT / artifact["path"]).read_bytes()).hexdigest()
        == artifact["sha256"]
        for row in rows
        for artifact in row["artifacts"]
    )

    serialized = BASELINE_JSON.read_text(encoding="utf-8") + BASELINE_MARKDOWN.read_text(encoding="utf-8")
    for forbidden in (
        "/Users/",
        "/Volumes/",
        "RAGFLOW_API_KEY",
        "PERSONAL_CLIPS_DATASET_ID",
        "Bearer ",
        "gho_",
        "http://ragflow.",
    ):
        assert forbidden not in serialized


def test_candidate_compares_to_immutable_q0_without_contract_or_denominator_drift():
    report = build_candidate_report(
        MANIFEST,
        baseline_path=BASELINE_JSON,
        perclip_commit="candidate-commit",
    )

    comparison = report["aggregate"]["comparison"]
    baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    assert report["schema_version"] == "perclip.quality.q0-candidate.v1"
    assert report["semantic_tags_not_targeted"] is True
    assert comparison["comparison_mode"] == "candidate"
    assert comparison["baseline_commit"] == baseline["perclip_commit"]
    assert comparison["candidate_commit"] == "candidate-commit"
    assert comparison["baseline_cases"] == comparison["candidate_cases"] == 26
    assert comparison["contract_changes"] == []
    assert comparison["regressed"] == 0
    assert comparison["hard_blockers"] == []
    controls = report["aggregate"]["control_metrics"]
    for name in (
        "successful_projection_preserved_after_unusable_partial_reprocess",
        "recall_preserved_after_unusable_partial_reprocess",
        "active_index_state_preserved_after_failed_reprocess",
        "active_index_state_preserved_after_unusable_partial_reprocess",
        "structured_secret_values_redacted",
        "normal_security_prose_preserved",
    ):
        assert controls[name] is True
    assert set(comparison["engine_changes"]) == {
        "evaluator", "extract", "clean", "enrich", "index", "classify_topic"
    }
    assert set(comparison["latency_p95"]) == {
        "baseline_ms",
        "candidate_ms",
        "relative_change",
        "comparable_only_on_same_fixture_and_test_host",
        "above_ten_percent",
        "disposition",
    }
    assert all(case["comparison_to_q0"] in {"improved", "unchanged", "regressed"} for case in report["cases"])
    assert all("metric_diffs" in case and "actual_diffs" in case for case in report["cases"])
    baseline_denominators = baseline["aggregate"]["applicable_metric_result"]
    for metric, values in report["aggregate"]["applicable_metric_result"].items():
        assert (values["eligible"], values["not_applicable"]) == (
            baseline_denominators[metric]["eligible"],
            baseline_denominators[metric]["not_applicable"],
        )

    markdown = markdown_report(report)
    assert "# PerClip Q0-Web Candidate" in markdown
    assert "Hard blockers: none" in markdown
    assert "Semantic tags: not targeted" in markdown


def test_full_candidate_is_non_timing_deterministic_across_two_runs():
    first = build_candidate_report(
        MANIFEST,
        baseline_path=BASELINE_JSON,
        perclip_commit="candidate-determinism",
    )
    second = build_candidate_report(
        MANIFEST,
        baseline_path=BASELINE_JSON,
        perclip_commit="candidate-determinism",
    )

    assert _without_timing(first) == _without_timing(second)
    stages = set(first["aggregate"]["local_fixture_pipeline_latency"]["by_stage"])
    assert stages == set(second["aggregate"]["local_fixture_pipeline_latency"]["by_stage"])
    assert _without_markdown_timing(markdown_report(first), stages) == _without_markdown_timing(
        markdown_report(second), stages
    )
