from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/plan_stage26_core_memory_closure.py"
SOURCE = ROOT / "docs/quality/candidates/stage25-3-core-recall-gap-plan-v1.json"
CANDIDATE = ROOT / "docs/quality/candidates/stage26-core-memory-product-closure-v1.json"


def _module():
    spec = importlib.util.spec_from_file_location("stage26_closure", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stage26_closure_plan_is_deterministic_and_conserves_full_60():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    generated = _module().build(source)
    committed = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    assert generated == committed
    assert committed["sample_count"] == committed["title_search_target_count"] == 60
    assert committed["core_recall_availability_count"] == 60
    assert Counter(item["source_platform"] for item in committed["cases"]) == {
        "bilibili": 10,
        "douyin": 10,
        "wechat_official_account": 10,
        "xiaohongshu": 10,
        "web": 10,
        "zhihu": 10,
    }
    assert committed["explicit_unknown_source_count"] == 12
    assert committed["explicit_unavailable_content_count"] == 10
    assert committed["rag_or_semantic_search_required"] is False
    assert committed["real_url_or_production_action_authorized"] is False


def test_stage26_closure_plan_contains_only_safe_identifiers_and_states():
    serialized = CANDIDATE.read_text(encoding="utf-8")
    for forbidden in ("http://", "https://", "cookie", "authorization", "password", "token="):
        assert forbidden not in serialized.casefold()
    for item in json.loads(serialized)["cases"]:
        assert item["title_query_token"] == item["sample_id"]
        assert item["required_journey"] == ["persist", "list", "title_keyword_search", "detail"]
