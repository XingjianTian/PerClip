from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from perclip_ingest.topics import (
    EmbeddingSimilarityClassifier,
    ExactRuleClassifier,
    FakeEmbeddingProvider,
    TAXONOMY_VERSION,
    UNCLASSIFIED_TOPIC_ID,
    TopicAlias,
    TopicClassificationInput,
    TopicRegistrySnapshot,
    UserOverrideClassifier,
    bootstrap_snapshot,
    extract_entities_and_keywords,
)


def _projection(case: dict[str, object]) -> TopicClassificationInput:
    return TopicClassificationInput.build(
        explicit_title=case.get("explicit_title", ""),
        active_title=case.get("active_title", ""),
        summary=case.get("summary", ""),
        markdown=case.get("text", ""),
        user_tags=case.get("user_tags", ()),
        knowledge_base_name=case.get("knowledge_base_name", ""),
        source_context=case.get("source_context", ""),
    )


def _registry_for_case(case: dict[str, object]) -> TopicRegistrySnapshot:
    snapshot = bootstrap_snapshot()
    disabled = str(case.get("disabled_topic_id") or "")
    definitions = tuple(
        replace(definition, enabled=False)
        if definition.topic_id == disabled
        else definition
        for definition in snapshot.definitions
    )
    aliases = list(snapshot.aliases)
    alias_edit = case.get("alias_edit")
    if isinstance(alias_edit, dict):
        alias = str(alias_edit.get("alias") or "")
        topic_id = str(alias_edit.get("topic_id") or "")
        if alias and topic_id:
            aliases.append(
                TopicAlias(
                    max((item.alias_id for item in aliases), default=0) + 1,
                    topic_id,
                    alias,
                    "exact_alias",
                )
            )
    return TopicRegistrySnapshot(
        str(case.get("taxonomy_version") or snapshot.taxonomy_version),
        definitions,
        tuple(aliases),
    )


def classify_production_case(case: dict[str, object]) -> dict[str, object]:
    projection = _projection(case)
    registry = _registry_for_case(case)
    override = str(case.get("override_topic_id") or "")
    result = UserOverrideClassifier(override, registry).classify(projection)
    if result is None:
        user_rules = tuple(
            (str(rule["rule"]), str(rule["topic_id"]))
            for rule in case.get("user_rules", ())
            if isinstance(rule, dict)
        )
        result = ExactRuleClassifier(user_rules, registry=registry).classify(projection)
    if result is None:
        entities, keywords = extract_entities_and_keywords(
            projection.rendered(), registry
        )
        return {
            "primary": UNCLASSIFIED_TOPIC_ID,
            "top2": [UNCLASSIFIED_TOPIC_ID],
            "entities": list(entities),
            "keywords": list(keywords),
            "source": "unclassified",
        }
    return {
        "primary": result.primary_topic_id,
        "top2": [result.primary_topic_id, *result.secondary_topic_ids[:1]],
        "entities": list(result.entities),
        "keywords": list(result.keywords),
        "source": result.source,
    }


def evaluate_production_default(corpus: dict[str, object]) -> dict[str, object]:
    cases = list(corpus["cases"])
    first = {str(case["id"]): classify_production_case(case) for case in cases}
    second = {str(case["id"]): classify_production_case(case) for case in cases}
    total = len(cases)
    hard_negatives = [case for case in cases if case.get("hard_negative")]
    ambiguous = [case for case in cases if case.get("ambiguous")]
    expected_unclassified = {
        str(case["id"])
        for case in cases
        if str(case["primary"]) == UNCLASSIFIED_TOPIC_ID
    }
    predicted_unclassified = {
        case_id
        for case_id, result in first.items()
        if result["primary"] == UNCLASSIFIED_TOPIC_ID
    }
    false_positives = predicted_unclassified ^ expected_unclassified
    outputs_text = json.dumps(first, ensure_ascii=False)
    sensitive_markers = [
        str(case["sensitive_marker"])
        for case in cases
        if case.get("sensitive_marker")
    ]
    return {
        "corpus_id": corpus["corpus_id"],
        "taxonomy_version": TAXONOMY_VERSION,
        "mode": "production_default",
        "case_count": total,
        "metrics": {
            "exact_rule_coverage": (
                sum(
                    first[str(case["id"])]["source"]
                    in {"manual", "user_rule", "exact_rule"}
                    for case in cases
                )
                / total
                if total
                else 0.0
            ),
            "primary_accuracy": (
                sum(
                    first[str(case["id"])]["primary"] == case["primary"]
                    for case in cases
                )
                / total
                if total
                else 0.0
            ),
            "unclassified_rate": len(predicted_unclassified) / total if total else 0.0,
            "false_positive_rate": len(false_positives) / total if total else 0.0,
            "hard_negative_accuracy": (
                sum(
                    first[str(case["id"])]["primary"] == case["primary"]
                    for case in hard_negatives
                )
                / len(hard_negatives)
                if hard_negatives
                else 1.0
            ),
            "ambiguous_top2_accuracy": (
                sum(
                    set(case.get("top2", [case["primary"]]))
                    <= set(first[str(case["id"])]["top2"])
                    for case in ambiguous
                )
                / len(ambiguous)
                if ambiguous
                else 1.0
            ),
            "repeat_stability": (
                sum(first[key] == second[key] for key in first) / total
                if total
                else 1.0
            ),
            "privacy_leak_count": sum(
                marker in outputs_text for marker in sensitive_markers
            ),
        },
        "cases": first,
    }


def evaluate_semantic_boundary(corpus: dict[str, object]) -> dict[str, object]:
    cases = list(corpus["cases"])
    provider = FakeEmbeddingProvider()
    repeatable = 0
    threshold_pass = 0
    fallback_pass = 0
    outputs: dict[str, dict[str, object]] = {}
    for case in cases:
        projection = _projection(case)
        threshold = float(case.get("threshold", 0.50))
        first = EmbeddingSimilarityClassifier(
            provider, threshold=threshold
        ).classify(projection)
        second = EmbeddingSimilarityClassifier(
            provider, threshold=threshold
        ).classify(projection)
        normalized_first = (
            {
                "primary": first.primary_topic_id,
                "secondary": list(first.secondary_topic_ids),
                "source": first.source,
            }
            if first is not None
            else {"primary": UNCLASSIFIED_TOPIC_ID, "secondary": [], "source": "fallback"}
        )
        normalized_second = (
            {
                "primary": second.primary_topic_id,
                "secondary": list(second.secondary_topic_ids),
                "source": second.source,
            }
            if second is not None
            else {"primary": UNCLASSIFIED_TOPIC_ID, "secondary": [], "source": "fallback"}
        )
        repeatable += normalized_first == normalized_second
        expects_fallback = bool(case.get("expect_fallback"))
        fallback_pass += (first is None) == expects_fallback
        threshold_pass += (first is None) if threshold > 1 else True
        outputs[str(case["id"])] = normalized_first
    total = len(cases)
    return {
        "corpus_id": corpus["corpus_id"],
        "mode": "semantic_boundary_only",
        "represents_model_quality": False,
        "case_count": total,
        "metrics": {
            "deterministic_repeatability": repeatable / total if total else 1.0,
            "threshold_contract": threshold_pass / total if total else 1.0,
            "fallback_contract": fallback_pass / total if total else 1.0,
        },
        "cases": outputs,
    }


def evaluate(corpus: dict[str, object]) -> dict[str, object]:
    if corpus.get("corpus_id") == "q2-semantic-boundary-v1":
        return evaluate_semantic_boundary(corpus)
    return evaluate_production_default(corpus)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.corpus.read_text(encoding="utf-8")))
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    metrics = result["metrics"]
    return (
        0
        if metrics.get("primary_accuracy", 1.0) >= 0.85
        and metrics.get("privacy_leak_count", 0) == 0
        and metrics.get("deterministic_repeatability", 1.0) == 1.0
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
