#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "docs/quality/candidates/stage25-3-core-recall-gap-plan-v1.json"
DEFAULT_JSON = ROOT / "docs/quality/candidates/stage26-core-memory-product-closure-v1.json"
DEFAULT_MD = ROOT / "docs/quality/candidates/stage26-core-memory-product-closure-v1.md"


def build(source: dict[str, object]) -> dict[str, object]:
    source_cases = list(source.get("cases", []))
    cases: list[dict[str, object]] = []
    for raw in source_cases:
        item = dict(raw)
        states = dict(item["availability_states"])
        sample_id = str(item["sample_id"])
        cases.append(
            {
                "sample_id": sample_id,
                "source_platform": str(item["source_platform"]),
                "title_query_token": sample_id,
                "source_identity_state": str(states["source_identity"]),
                "core_content_state": str(states["core_content"]),
                "required_journey": ["persist", "list", "title_keyword_search", "detail"],
            }
        )
    platforms = Counter(str(item["source_platform"]) for item in cases)
    return {
        "schema_version": "perclip.stage26.core-memory-product-closure.v1",
        "milestone_id": "Stage26-Core-Memory-Product-Closure",
        "sample_count": len(cases),
        "platform_counts": dict(sorted(platforms.items())),
        "title_search_target_count": len(cases),
        "explicit_unknown_source_count": sum(
            item["source_identity_state"] == "explicit_unknown" for item in cases
        ),
        "explicit_unavailable_content_count": sum(
            item["core_content_state"] == "explicit_unavailable" for item in cases
        ),
        "core_recall_availability_count": int(source.get("core_recall_complete_count", 0)),
        "rag_or_semantic_search_required": False,
        "real_url_or_production_action_authorized": False,
        "review_at": "full_stage26_milestone_only",
        "cases": cases,
    }


def markdown(plan: dict[str, object]) -> str:
    counts = dict(plan["platform_counts"])
    lines = [
        "# Stage 26 Core Memory product-closure ledger",
        "",
        f"- Safe cases: {plan['sample_count']}",
        f"- Core Recall availability conserved: {plan['core_recall_availability_count']}/60",
        f"- Title-keyword targets: {plan['title_search_target_count']}/60",
        f"- Explicit unknown source: {plan['explicit_unknown_source_count']}",
        f"- Explicit unavailable content: {plan['explicit_unavailable_content_count']}",
        "- RAG / semantic search required: no",
        "- Real URL / production action authorized: no",
        "",
        "| Platform | Count |",
        "|---|---:|",
    ]
    lines.extend(f"| `{name}` | {count} |" for name, count in counts.items())
    lines.extend(
        [
            "",
            "Each safe case must persist, appear in Knowledge List, match its deterministic title token, and open as a detail record. No semantic payload or URL is stored in this ledger.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()
    plan = build(json.loads(args.input.read_text(encoding="utf-8")))
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown_output.write_text(markdown(plan), encoding="utf-8")


if __name__ == "__main__":
    main()
