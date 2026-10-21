from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any
from collections.abc import Callable

from perclip_ingest.enrichment import EnrichmentInputProjection, deterministic_enrich
from perclip_ingest.knowledge_base_store import ClipRouteDecision, KnowledgeBaseStore
from perclip_ingest.routing import RoutingPreviewInput, preview_route
from perclip_ingest.storage import StoredClipRawFields
from perclip_ingest.topics import TopicClassificationInput, TopicClassificationService, TopicStore


CORPUS_ID = "q3-ready-memory-v1"
CORPUS_SCHEMA = "perclip.ready-memory-corpus.v1"
REPORT_SCHEMA = "perclip.ready-memory-report.v1"
FORBIDDEN_FREE_TAGS = {
    "audio", "file", "html", "image", "knowledge-base", "pdf", "screen_clip",
    "text", "url",
}


def load_corpus(path: Path) -> dict[str, Any]:
    corpus = json.loads(path.read_text(encoding="utf-8"))
    if corpus.get("corpus_id") != CORPUS_ID or corpus.get("schema_version") != CORPUS_SCHEMA:
        raise ValueError("unexpected Ready Memory corpus contract")
    cases = corpus.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("corpus cases must be a non-empty list")
    ids = [str(case.get("id") or "") for case in cases]
    if any(not case_id for case_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("corpus case ids must be non-empty and unique")
    required_expected = {
        "summary_concepts", "key_point_concepts", "free_tags", "primary_topic",
        "route_decision_type",
    }
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("corpus cases must be objects")
        if not all(str(case.get(field) or "").strip() for field in ("title", "text", "url")):
            raise ValueError(f"{case['id']} must contain title, text, and url")
        expected = case.get("expected")
        if not isinstance(expected, dict) or set(expected) != required_expected:
            raise ValueError(f"{case['id']} has an invalid expected contract")
        for field in ("summary_concepts", "key_point_concepts", "free_tags"):
            values = expected[field]
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ValueError(f"{case['id']} expected {field} must be a string list")
        if not expected["summary_concepts"]:
            raise ValueError(f"{case['id']} expected summary_concepts must not be empty")
        for field in ("primary_topic", "route_decision_type"):
            if not isinstance(expected[field], str) or not expected[field].strip():
                raise ValueError(f"{case['id']} expected {field} must be a non-empty string")
        rule = case.get("routing_rule")
        if rule is not None and (
            not isinstance(rule, dict)
            or set(rule) != {"type", "pattern", "target_name"}
            or any(not isinstance(rule[field], str) or not rule[field].strip() for field in rule)
        ):
            raise ValueError(f"{case['id']} has an invalid routing_rule contract")
    return corpus


def corpus_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contains_all(value: str, concepts: list[object]) -> bool:
    folded = value.casefold()
    return all(str(concept).casefold() in folded for concept in concepts)


def _tag_recall(actual: list[str], expected: list[object]) -> bool:
    folded = {tag.casefold() for tag in actual}
    return all(str(tag).casefold() in folded for tag in expected)


def _tag_precision(actual: list[str], expected: list[object]) -> bool:
    expected_folded = [str(tag).casefold() for tag in expected]
    return all(
        any(wanted in tag.casefold() or tag.casefold() in wanted for wanted in expected_folded)
        for tag in actual
    ) if expected_folded else not actual


def _route_matches(case: dict[str, Any], decision_type: str, target_name: str) -> bool:
    expected = dict(case["expected"])
    rule = case.get("routing_rule")
    expected_target = str(rule["target_name"]) if isinstance(rule, dict) else "个人收藏"
    return (
        decision_type == expected["route_decision_type"]
        and target_name == expected_target
    )


def _is_grounded(value: str, source: str) -> bool:
    normalized = " ".join(value.split()).casefold()
    return not normalized or normalized in " ".join(source.split()).casefold()


def _raw(case: dict[str, Any]) -> StoredClipRawFields:
    return StoredClipRawFields(
        id=1,
        client_request_id=f"q3-{str(case['id']).lower()}",
        source_type="url",
        title_hint="",
        note="",
        text="",
        url=str(case["url"]),
        mime_type="text/html",
        device_name="quality-evaluator",
        source_app=str(case.get("source_app") or "Browser"),
        captured_at="2026-01-01T00:00:00Z",
        filename="",
        size_bytes=0,
        original_path="",
        content_hash="",
        ragflow_document_id="",
        archive_status="local",
        created_at="2026-01-01T00:00:00Z",
    )


def _route(data_dir: Path, case: dict[str, Any]):
    store = KnowledgeBaseStore(data_dir)
    store.init()
    rule = case.get("routing_rule")
    if isinstance(rule, dict):
        target = store.create_knowledge_base(name=str(rule["target_name"]))
        store.create_routing_rule(
            name=f"q3-{case['id']}",
            rule_type=str(rule["type"]),
            pattern=str(rule["pattern"]),
            target_knowledge_base_id=target.id,
        )
    preview = preview_route(
        store,
        RoutingPreviewInput(
            source_type="url",
            title_hint=str(case["title"]),
            text=str(case["text"]),
            url=str(case["url"]),
            source_app=str(case.get("source_app") or "Browser"),
        ),
    )
    decision = ClipRouteDecision(
        id=1,
        clip_id="1",
        client_request_id=f"q3-{str(case['id']).lower()}",
        knowledge_base_id=preview.knowledge_base_id,
        ragflow_dataset_id="",
        decision_type=preview.decision_type,
        matched_rule_id=preview.matched_rule_id,
        matched_rule_ids=preview.matched_rule_ids,
        confidence=preview.confidence,
        manual_override=preview.manual_override,
        reason=preview.reason,
        created_at="2026-01-01T00:00:00Z",
        previous_knowledge_base_id="",
        reindex_status="",
        lineage_id="",
    )
    return decision, preview


def evaluate_case(
    case: dict[str, Any],
    data_dir: Path,
    *,
    key_points_provider: Callable[[str], list[str]] | None = None,
    semantic_tags_provider: Callable[[str, str], list[str]] | None = None,
    primary_topic_provider: Callable[[str, str], str] | None = None,
) -> dict[str, object]:
    route, preview = _route(data_dir, case)
    source = str(case["text"])
    grounding_source = "\n".join((str(case["title"]), source))
    enrichment = deterministic_enrich(
        _raw(case),
        route,
        {},
        EnrichmentInputProjection(
            text=source,
            title=str(case["title"]),
            resolved_url=str(case["url"]),
            canonical_url=str(case["url"]),
            extraction_status="completed",
            recall_eligible=True,
        ),
    )
    topic_store = TopicStore(data_dir)
    topic_store.init()
    topic = TopicClassificationService(topic_store).classify(
        clip_id=1,
        generation="gen_q3",
        projection=TopicClassificationInput.build(
            active_title=enrichment.title,
            summary=enrichment.summary,
            markdown=source,
            user_tags=enrichment.tags,
            knowledge_base_name=preview.knowledge_base_name,
            source_context=str(case.get("source_app") or "Browser"),
        ),
    )
    expected = dict(case["expected"])
    key_points = key_points_provider(source) if key_points_provider is not None else enrichment.key_points
    evaluated_tags = (
        semantic_tags_provider(str(case["title"]), source)
        if semantic_tags_provider is not None
        else enrichment.tags
    )
    evaluated_topic = (
        primary_topic_provider(str(case["title"]), source)
        if primary_topic_provider is not None
        else str(topic["primary"]["topic_id"])
    )
    semantic_tags = [tag for tag in evaluated_tags if tag.casefold() not in FORBIDDEN_FREE_TAGS]
    has_pollution = any(tag.casefold() in FORBIDDEN_FREE_TAGS for tag in evaluated_tags)
    checks = {
        "summary_essence": _contains_all(enrichment.summary, list(expected["summary_concepts"])),
        "key_points_coverage": _contains_all("\n".join(key_points), list(expected["key_point_concepts"])),
        "free_tag_recall": _tag_recall(semantic_tags, list(expected["free_tags"])),
        "free_tag_precision": not has_pollution
        and _tag_precision(semantic_tags, list(expected["free_tags"])),
        "fixed_topic": evaluated_topic == expected["primary_topic"],
        "routing": _route_matches(case, preview.decision_type, preview.knowledge_base_name),
        "grounding": _is_grounded(enrichment.summary, grounding_source)
        and all(_is_grounded(tag, grounding_source) for tag in semantic_tags)
        and all(_is_grounded(point, grounding_source) for point in key_points),
    }
    gaps = [name for name, passed in checks.items() if not passed]
    return {
        "id": case["id"],
        "actual": {
            "enrichment_engine": enrichment.engine,
            "summary": enrichment.summary,
            "key_points": key_points,
            "free_tags": evaluated_tags,
            "primary_topic": evaluated_topic,
            "classifier_source": (
                "stage24_6d_semantic_recall_candidate"
                if primary_topic_provider is not None
                else topic["classifier_source"]
            ),
            "route_decision_type": preview.decision_type,
            "route_target_name": preview.knowledge_base_name,
        },
        "checks": checks,
        "gaps": gaps,
        "ready_semantic_pass": not gaps,
    }


def build_report(
    corpus_path: Path,
    *,
    perclip_commit: str,
    key_points_provider: Callable[[str], list[str]] | None = None,
    semantic_tags_provider: Callable[[str, str], list[str]] | None = None,
    primary_topic_provider: Callable[[str, str], str] | None = None,
    baseline_mode: str = "deterministic_v7_semantic_recall",
) -> dict[str, object]:
    corpus = load_corpus(corpus_path)
    runs: list[list[dict[str, object]]] = []
    for run_index in range(2):
        with tempfile.TemporaryDirectory(prefix=f"perclip-q3-{run_index}-") as directory:
            runs.append(
                [
                    evaluate_case(
                        case,
                        Path(directory) / str(case["id"]),
                        key_points_provider=key_points_provider,
                        semantic_tags_provider=semantic_tags_provider,
                        primary_topic_provider=primary_topic_provider,
                    )
                    for case in corpus["cases"]
                ]
            )
    cases = runs[0]
    repeatable = runs[0] == runs[1]
    check_names = tuple(next(iter(cases))["checks"])
    totals = {
        name: sum(bool(case["checks"][name]) for case in cases)
        for name in check_names
    }
    gap_counts = {
        name: len(cases) - passed
        for name, passed in totals.items()
        if passed != len(cases)
    }
    return {
        "schema_version": REPORT_SCHEMA,
        "corpus_id": CORPUS_ID,
        "perclip_commit": perclip_commit,
        "corpus_hash": corpus_hash(corpus_path),
        "baseline_mode": baseline_mode,
        "summary": {
            "case_count": len(cases),
            "ready_semantic_passed": sum(bool(case["ready_semantic_pass"]) for case in cases),
            "dimension_passed": totals,
            "gap_counts": gap_counts,
            "repeatable": repeatable,
        },
        "cases": cases,
    }


def markdown_report(report: dict[str, object]) -> str:
    summary = dict(report["summary"])
    mode = str(report.get("baseline_mode") or "")
    if mode == "stage24_6d_semantic_recall_candidate":
        heading = "# q3-ready-memory-v1 historical offline candidate evidence"
        scope_lines = [
            "- Scope: production summary/key-points/routing plus offline-only candidate tag/topic providers",
            "- This mode preserves the Stage 24.6D fixture-fit experiment; current production results must be read from the production baseline.",
            "- Candidate 6/6 is six-case direction evidence only; it is not real-URL generalization evidence.",
            "- Risk: a broader three-tag exploration kept recall at 6/6 but reduced tag precision to 2/6 (over-tagging).",
        ]
    else:
        heading = "# q3-ready-memory-v1 baseline"
        scope_lines = [
            "- Scope: local deterministic production enrichment, topic, and routing components",
            "- Key points are scored from production projection-backed enrichment",
        ]
    lines = [
        heading,
        "",
        f"- Implementation commit: `{report['perclip_commit']}`",
        f"- Corpus cases: {summary['case_count']}",
        f"- End-to-end semantic passes: {summary['ready_semantic_passed']}/{summary['case_count']}",
        *scope_lines,
        "",
        "| Case | Summary | Key points | Tags recall | Tags precision | Topic | Route | Grounding | Result |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    labels = ("summary_essence", "key_points_coverage", "free_tag_recall", "free_tag_precision", "fixed_topic", "routing", "grounding")
    for case in report["cases"]:
        checks = case["checks"]
        marks = ["pass" if checks[label] else "fail" for label in labels]
        lines.append(
            f"| {case['id']} | " + " | ".join(marks) +
            f" | {'pass' if case['ready_semantic_pass'] else 'fail'} |"
        )
    lines.extend(["", "## Named gaps"])
    for name, count in summary["gap_counts"].items():
        lines.append(f"- `{name}`: {count} case(s)")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local-only Q3 Ready Memory evaluator")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--key-points-candidate", action="store_true")
    parser.add_argument("--semantic-recall-candidate", action="store_true")
    args = parser.parse_args(argv)
    key_points_provider = None
    baseline_mode = "deterministic_v7_semantic_recall"
    if args.key_points_candidate:
        from quality_tools.key_points_candidate import deterministic_key_points

        key_points_provider = deterministic_key_points
        baseline_mode = "stage24_6c_key_points_candidate"
    semantic_tags_provider = None
    primary_topic_provider = None
    if args.semantic_recall_candidate:
        from quality_tools.semantic_recall_candidate import (
            candidate_primary_topic,
            candidate_semantic_tags,
        )

        semantic_tags_provider = candidate_semantic_tags
        primary_topic_provider = candidate_primary_topic
        baseline_mode = "stage24_6d_semantic_recall_candidate"
    report = build_report(
        args.corpus,
        perclip_commit=args.commit,
        key_points_provider=key_points_provider,
        semantic_tags_provider=semantic_tags_provider,
        primary_topic_provider=primary_topic_provider,
        baseline_mode=baseline_mode,
    )
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
