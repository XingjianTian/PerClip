from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from perclip_ingest.config import Settings
from perclip_ingest.main import create_app
from perclip_ingest.topics import (
    ClassificationResult,
    ExactRuleClassifier,
    TAXONOMY_VERSION,
    TOPIC_ASSIGNMENT_CONTRACT,
    TOPIC_DEFINITIONS,
    TopicClassificationInput,
    TopicClassificationService,
    TopicStore,
)
from quality_tools.topics_q2 import evaluate


class RaisingClassifier:
    def classify(self, text: str):
        del text
        raise RuntimeError("synthetic classifier failure")


class CountingEmbeddingProvider:
    def __init__(self, *, fail: bool = False):
        self.calls = 0
        self.fail = fail

    def embed(self, text: str):
        del text
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider unavailable")
        return (1.0, 0.0)


def test_registry_is_versioned_fixed_and_complete(tmp_path):
    store = TopicStore(tmp_path)
    store.init()
    assert len(TOPIC_DEFINITIONS) == 16
    assert {definition.topic_id for definition in TOPIC_DEFINITIONS} >= {
        "ai_ml", "software_automation", "unclassified"
    }
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        assert db.execute("select count(*) from topic_definitions").fetchone()[0] == 16
        assert {
            row[0] for row in db.execute("select distinct alias_type from topic_aliases")
        } == {"exact_alias", "entity_hint"}
        assert {
            row[0] for row in db.execute("select distinct taxonomy_version from topic_definitions")
        } == {TAXONOMY_VERSION}


def test_registry_bootstrap_does_not_overwrite_runtime_edits(tmp_path):
    store = TopicStore(tmp_path)
    store.init()
    store.update_topic(
        "ai_ml",
        {
            "display_name": "AI 运行时名称",
            "enabled": False,
            "sort_order": 88,
            "exclusions": ["不涉及模型"],
        },
    )
    alias_id = store.add_alias(
        topic_id="digital_tech", alias="掌上设备", alias_type="exact_alias"
    )

    store.init()

    snapshot = store.snapshot()
    ai = snapshot.by_id["ai_ml"]
    assert ai.display_name == "AI 运行时名称"
    assert ai.enabled is False
    assert ai.sort_order == 88
    assert ai.exclusions == ("不涉及模型",)
    assert any(alias.alias_id == alias_id for alias in snapshot.aliases)
    assert snapshot.taxonomy_version.startswith(f"{TAXONOMY_VERSION}.r")


def test_runtime_snapshot_exclusions_disabled_filter_and_title_boost(tmp_path):
    store = TopicStore(tmp_path)
    store.init()
    service = TopicClassificationService(store)
    work = service.classify(
        clip_id=20,
        generation="gen_work",
        projection=TopicClassificationInput.build(
            explicit_title="工作项目复盘",
            summary="交付后的成长反思",
            markdown="项目里程碑",
        ),
    )
    assert work["primary"]["topic_id"] == "work_projects"
    assert "growth_reflection" in {
        item["topic_id"] for item in work["secondary"]
    }

    negative = service.classify(
        clip_id=21,
        generation="gen_negative",
        text="普通软件开发，不讨论 AI 模型",
    )
    assert negative["primary"]["topic_id"] == "software_automation"
    store.update_topic("software_automation", {"enabled": False})
    disabled = service.classify(
        clip_id=22,
        generation="gen_disabled",
        text="Docker 软件开发自动化",
    )
    assert disabled["primary"]["topic_id"] == "unclassified"


def test_optional_semantic_provider_is_cached_and_failure_falls_back(tmp_path):
    store = TopicStore(tmp_path)
    store.init()
    provider = CountingEmbeddingProvider()
    service = TopicClassificationService(
        store,
        semantic_provider=provider,
        semantic_threshold=0.5,
        semantic_engine="openai-compatible:test:v1",
    )
    first = service.classify(
        clip_id=30, generation="gen_a", text="没有明确主题词的语义文本"
    )
    prototype_and_query_calls = provider.calls
    second = service.classify(
        clip_id=31, generation="gen_b", text="另一条没有明确主题词的文本"
    )
    assert first["classifier_source"] == "embedding"
    assert second["classifier_source"] == "embedding"
    assert provider.calls == prototype_and_query_calls + 1

    failing = TopicClassificationService(
        store,
        semantic_provider=CountingEmbeddingProvider(fail=True),
    )
    fallback = failing.classify(
        clip_id=32, generation="gen_c", text="没有任何精确规则"
    )
    assert fallback["primary"]["topic_id"] == "unclassified"
    assert fallback["latest_attempted_status"] == "succeeded"


def test_exact_entity_rule_preserves_entity_and_ai_semantics():
    result = ExactRuleClassifier().classify("Claude 和 Codex 的推理对比")
    assert result is not None
    assert result.primary_topic_id == "ai_ml"
    assert result.entities == ("Claude", "Codex")


def test_exact_rule_uses_positive_examples_without_weakening_alias_priority():
    positive = ExactRuleClassifier().classify("课程实验采用形成性评价")
    assert positive is not None
    assert positive.primary_topic_id == "education_research"
    assert positive.engine == "exact-alias-positive-entity-v2"
    assert "实验" in positive.evidence

    alias = ExactRuleClassifier().classify("Docker 软件开发自动化")
    assert alias is not None
    assert alias.primary_topic_id == "software_automation"

    negated = ExactRuleClassifier().classify("课程说明：不涉及实验，也不讨论科研")
    assert negated is None


def test_lifecycle_is_idempotent_manual_wins_and_failure_preserves_active(tmp_path):
    store = TopicStore(tmp_path)
    store.init()
    service = TopicClassificationService(store)
    first = service.classify(clip_id=7, generation="gen_a", text="足球比赛记录")
    assert first["primary"]["topic_id"] == "football_sports"
    service.classify(clip_id=7, generation="gen_a", text="足球比赛记录")
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        assert db.execute("select count(*) from topic_classification_runs").fetchone()[0] == 1

    manual = store.set_manual_override(
        clip_id=7, generation="gen_a", topic_id="history_culture"
    )
    assert manual["primary"]["source"] == "manual"
    after_auto = service.classify(
        clip_id=7, generation="gen_b", text="ChatGPT 人工智能大模型"
    )
    assert after_auto["primary"]["topic_id"] == "history_culture"
    assert after_auto["stale"] is False
    restored = store.clear_manual_override(7)
    assert restored["primary"]["topic_id"] == "football_sports"
    assert restored["manual_override"] is False

    service.classify(clip_id=8, generation="gen_good", text="足球比赛记录")
    failing = TopicClassificationService(store, classifiers=(RaisingClassifier(),))
    with pytest.raises(RuntimeError):
        failing.classify(clip_id=8, generation="gen_failed", text="没有规则命中的中性句子")
    assert store.assignment_payload(8)["primary"]["topic_id"] == "football_sports"
    assert store.assignment_payload(7)["primary"]["topic_id"] == "football_sports"
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        failed = db.execute(
            """select status,safe_error_code from topic_classification_runs
            where clip_id=8 order by created_at desc limit 1"""
        ).fetchone()
    assert failed == ("failed", "topic_classification_failed")


def test_user_rule_precedes_alias(tmp_path):
    store = TopicStore(tmp_path)
    store.init()
    store.add_user_rule(rule="我的特殊项目", topic_id="history_culture")
    result = TopicClassificationService(store).classify(
        clip_id=9, generation="gen_rule", text="我的特殊项目也提到了 ChatGPT"
    )
    assert result["primary"] == {
        "topic_id": "history_culture",
        "display_name": "历史与文化",
        "source": "user_rule",
    }
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        assert db.execute(
            "select alias_type from topic_aliases where alias='我的特殊项目'"
        ).fetchone()[0] == "user_rule"


def test_authenticated_registry_operator_api_supports_runtime_edits(tmp_path):
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))
    auth = {"Authorization": "Bearer secret"}
    store = TopicStore(tmp_path)
    TopicClassificationService(store).classify(
        clip_id=31,
        generation="gen_existing_football",
        text="足球比赛训练",
    )
    assert api.get("/api/topics").status_code == 401
    initial = api.get("/api/topics", headers=auth)
    assert initial.status_code == 200
    initial_version = initial.json()["registry"]["taxonomy_version"]

    renamed = api.patch(
        "/api/topics/ai_ml",
        headers=auth,
        json={"display_name": "AI 与模型"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["registry"]["taxonomy_version"] == initial_version

    alias = api.post(
        "/api/topics/ai_ml/aliases",
        headers=auth,
        json={"alias": "推理助手", "alias_type": "exact_alias"},
    )
    assert alias.status_code == 200
    alias_id = alias.json()["alias_id"]
    assert alias.json()["registry"]["taxonomy_version"] != initial_version

    rule = api.post(
        "/api/topic-rules",
        headers=auth,
        json={"rule": "紫藤专题", "topic_id": "history_culture"},
    )
    assert rule.status_code == 200
    assert api.delete(
        f"/api/topic-rules/{rule.json()['rule_id']}", headers=auth
    ).status_code == 200
    assert api.delete(
        f"/api/topics/ai_ml/aliases/{alias_id}", headers=auth
    ).status_code == 200

    disabled = api.patch(
        "/api/topics/football_sports",
        headers=auth,
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["reclassification_scheduled"] == 0
    preserved = store.assignment_payload(31)
    assert preserved["primary"]["topic_id"] == "football_sports"
    assert preserved["topic_disabled"] is True
    assert api.post(
        "/api/topic-rules",
        headers=auth,
        json={"rule": "球赛专题", "topic_id": "football_sports"},
    ).status_code == 422


def test_public_assignment_hides_confidence_engine_and_run_ids(tmp_path):
    store = TopicStore(tmp_path)
    store.init()
    payload = TopicClassificationService(store).classify(
        clip_id=10, generation="gen_public", text="Docker 软件开发自动化"
    )
    assert payload["contract_version"] == TOPIC_ASSIGNMENT_CONTRACT
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "confidence" not in serialized
    assert "engine" not in serialized
    assert "run_id" not in serialized
    assert payload["active_generation"] == "gen_public"
    assert payload["active_taxonomy_version"] == TAXONOMY_VERSION
    assert payload["latest_attempted_status"] == "succeeded"
    assert payload["classifier_source"] == "exact_rule"


def test_q2_production_default_and_semantic_boundary_are_separate_and_private():
    fixtures = __import__("pathlib").Path(__file__).parents[2] / "tests" / "fixtures"
    production_corpus = json.loads(
        (fixtures / "q2-production-default-v1.json").read_text(encoding="utf-8")
    )
    semantic_corpus = json.loads(
        (fixtures / "q2-semantic-boundary-v1.json").read_text(encoding="utf-8")
    )
    production = evaluate(production_corpus)
    semantic = evaluate(semantic_corpus)
    metrics = production["metrics"]
    assert production["corpus_id"] == "q2-production-default-v1"
    assert production["mode"] == "production_default"
    assert production["case_count"] >= 60
    assert metrics["primary_accuracy"] == 1.0
    assert metrics["hard_negative_accuracy"] == 1.0
    assert metrics["ambiguous_top2_accuracy"] == 1.0
    assert metrics["false_positive_rate"] == 0.0
    assert metrics["repeat_stability"] == 1.0
    assert metrics["privacy_leak_count"] == 0
    assert semantic["corpus_id"] == "q2-semantic-boundary-v1"
    assert semantic["represents_model_quality"] is False
    assert semantic["metrics"] == {
        "deterministic_repeatability": 1.0,
        "threshold_contract": 1.0,
        "fallback_contract": 1.0,
    }
