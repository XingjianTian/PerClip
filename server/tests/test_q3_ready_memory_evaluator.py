from __future__ import annotations

import json
from pathlib import Path

import pytest

from quality_tools.q3_ready_memory_evaluator import (
    _route_matches,
    _tag_precision,
    build_report,
    load_corpus,
    markdown_report,
)
from quality_tools.key_points_candidate import deterministic_key_points
from quality_tools.semantic_recall_candidate import (
    candidate_primary_topic,
    candidate_semantic_tags,
)


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests" / "fixtures" / "quality" / "q3-ready-memory-v1.json"
BASELINE_JSON = ROOT / "docs" / "quality" / "baselines" / "q3-ready-memory-v1.json"
BASELINE_MARKDOWN = BASELINE_JSON.with_suffix(".md")


def test_q3_corpus_contract_is_strict_and_cross_domain(tmp_path):
    corpus = load_corpus(CORPUS)
    assert corpus["corpus_id"] == "q3-ready-memory-v1"
    assert [case["id"] for case in corpus["cases"]] == [
        "R01", "R02", "R03", "R04", "R05", "R06"
    ]

    invalid = dict(corpus)
    invalid["cases"] = [dict(corpus["cases"][0])]
    invalid["cases"][0]["expected"] = {"primary_topic": "ai_ml"}
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid expected contract"):
        load_corpus(path)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda case: case["expected"].__setitem__("free_tags", "AI"), "free_tags must be a string list"),
        (lambda case: case["expected"].__setitem__("primary_topic", 7), "primary_topic must be a non-empty string"),
        (lambda case: case.__setitem__("routing_rule", {"type": "keyword"}), "invalid routing_rule contract"),
    ],
)
def test_q3_corpus_rejects_malformed_typed_values(tmp_path, mutate, message):
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    mutate(corpus["cases"][0])
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_corpus(path)


def test_free_tag_precision_rejects_irrelevant_tags_without_transport_pollution():
    assert _tag_precision(["大模型推理"], ["大模型", "推理"])
    assert not _tag_precision(["足球"], ["大模型", "推理"])
    assert _tag_precision([], [])
    assert not _tag_precision(["稍后再看"], [])


def test_route_correctness_requires_decision_type_and_target():
    default_case = {"expected": {"route_decision_type": "default"}}
    rule_case = {
        "expected": {"route_decision_type": "rule"},
        "routing_rule": {"type": "keyword", "pattern": "Docker", "target_name": "工程资料"},
    }
    assert _route_matches(default_case, "default", "个人收藏")
    assert not _route_matches(default_case, "default", "错误目标")
    assert _route_matches(rule_case, "rule", "工程资料")
    assert not _route_matches(rule_case, "rule", "个人收藏")


def test_q3_evaluator_is_repeatable_and_closes_current_named_gaps():
    first = build_report(CORPUS, perclip_commit="baseline-commit")
    second = build_report(CORPUS, perclip_commit="baseline-commit")
    assert first == second
    assert markdown_report(first) == markdown_report(second)
    assert first["summary"]["case_count"] == 6
    assert first["summary"]["repeatable"] is True
    assert first["summary"]["dimension_passed"]["key_points_coverage"] == 6
    assert "key_points_coverage" not in first["summary"]["gap_counts"]
    assert first["baseline_mode"] == "deterministic_v7_semantic_recall"
    assert first["summary"]["dimension_passed"]["free_tag_recall"] == 6
    assert first["summary"]["dimension_passed"]["free_tag_precision"] == 6
    assert first["summary"]["dimension_passed"]["fixed_topic"] == 6
    assert first["summary"]["dimension_passed"]["grounding"] == 6
    assert first["summary"]["ready_semantic_passed"] == 6
    assert first["summary"]["gap_counts"] == {}


def test_frozen_q3_baseline_matches_evaluator_and_is_safe():
    baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    rebuilt = build_report(CORPUS, perclip_commit=baseline["perclip_commit"])
    assert rebuilt == baseline
    assert BASELINE_MARKDOWN.read_text(encoding="utf-8") == markdown_report(rebuilt)
    serialized = json.dumps(baseline, ensure_ascii=False) + markdown_report(rebuilt)
    for forbidden in ("/Users/", "/Volumes/", "Bearer ", "ragflow_dataset_id", "kb_"):
        assert forbidden not in serialized


def test_production_key_points_are_source_grounded_and_candidate_does_not_change_q3():
    baseline = build_report(CORPUS, perclip_commit="candidate-commit")
    candidate = build_report(
        CORPUS,
        perclip_commit="candidate-commit",
        key_points_provider=deterministic_key_points,
        baseline_mode="stage24_6c_key_points_candidate",
    )

    assert baseline["summary"]["dimension_passed"]["key_points_coverage"] == 6
    assert baseline["summary"]["ready_semantic_passed"] == 6
    assert candidate["summary"]["dimension_passed"]["key_points_coverage"] == 6
    assert candidate["summary"]["ready_semantic_passed"] == 6
    assert candidate["summary"]["repeatable"] is True
    corpus = {case["id"]: case for case in load_corpus(CORPUS)["cases"]}
    for result in candidate["cases"]:
        source = " ".join(corpus[result["id"]]["text"].split()).casefold()
        assert all(" ".join(point.split()).casefold() in source for point in result["actual"]["key_points"])


def test_key_points_candidate_rejects_short_reminder_and_respects_limit():
    assert deterministic_key_points("稍后再看。") == []
    assert deterministic_key_points("第一条信息足够完整。第二条信息同样完整。第三条信息继续补充。", limit=2) == [
        "第一条信息足够完整。",
        "第二条信息同样完整。",
    ]


def test_semantic_recall_candidate_is_grounded_bounded_and_not_arbitrary():
    assert candidate_semantic_tags(
        "Docker 自动化交付清单",
        "Docker 镜像在 GitHub Actions 中构建。",
    ) == ["Docker", "GitHub"]
    assert candidate_semantic_tags(
        "课程实验的形成性评价",
        "课程实验记录过程证据。",
    ) == ["课程", "实验"]
    assert candidate_semantic_tags("普通提醒", "稍后再看。") == []
    assert candidate_primary_topic("课程实验的形成性评价", "记录实验过程") == "education_research"


def test_historical_semantic_recall_candidate_matches_current_production_result():
    baseline = build_report(CORPUS, perclip_commit="candidate-commit")
    candidate = build_report(
        CORPUS,
        perclip_commit="candidate-commit",
        semantic_tags_provider=candidate_semantic_tags,
        primary_topic_provider=candidate_primary_topic,
        baseline_mode="stage24_6d_semantic_recall_candidate",
    )

    assert baseline["summary"]["ready_semantic_passed"] == 6
    assert candidate["summary"]["ready_semantic_passed"] == 6
    assert candidate["summary"]["dimension_passed"]["free_tag_recall"] == 6
    assert candidate["summary"]["dimension_passed"]["fixed_topic"] == 6
    assert candidate["summary"]["gap_counts"] == {}
    assert candidate["summary"]["repeatable"] is True
    corpus = {case["id"]: case for case in load_corpus(CORPUS)["cases"]}
    for result in candidate["cases"]:
        source = "\n".join((corpus[result["id"]]["title"], corpus[result["id"]]["text"])).casefold()
        assert len(result["actual"]["free_tags"]) <= 2
        assert all(tag.casefold() in source for tag in result["actual"]["free_tags"])
    docker = next(result for result in candidate["cases"] if result["id"] == "R02")
    assert docker["actual"]["free_tags"] == ["Docker", "GitHub"]
    assert docker["gaps"] == []


def test_semantic_recall_candidate_markdown_states_evidence_boundaries():
    candidate = build_report(
        CORPUS,
        perclip_commit="candidate-commit",
        semantic_tags_provider=candidate_semantic_tags,
        primary_topic_provider=candidate_primary_topic,
        baseline_mode="stage24_6d_semantic_recall_candidate",
    )

    markdown = markdown_report(candidate)
    assert markdown.startswith("# q3-ready-memory-v1 historical offline candidate evidence\n")
    assert "production summary/key-points/routing plus offline-only candidate tag/topic providers" in markdown
    assert "preserves the Stage 24.6D fixture-fit experiment" in markdown
    assert "current production results must be read from the production baseline" in markdown
    assert "not real-URL generalization evidence" in markdown
    assert "reduced tag precision to 2/6 (over-tagging)" in markdown
    assert "# q3-ready-memory-v1 baseline" not in markdown
