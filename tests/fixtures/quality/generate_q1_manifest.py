from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "manifest.jsonl"
DESTINATION = ROOT / "q1-web-v2.jsonl"
CORPUS_VERSION = "q1-web-v2"

TITLE_PROVENANCE = {
    "G01": "user.title_hint",
    "G02": "user.title_hint",
    "G03": "user.title_hint",
    "G04": "html.title",
    "G05": "html.title",
    "G06": "html.title",
    "G07": "html.title",
    "G08": "html.title",
    "G09": "html.title",
    "G14": "user.title_hint",
    "G17": "file.filename",
    "G18": "html.title",
    "G19": "html.title",
    "G20": "meta.og:title",
    "G21": "body.first_line",
    "G37": "user.title_hint",
    "G38": "html.title",
    "G39": "html.title",
    "G40": "html.title",
}
TITLE_NOT_APPLICABLE = {"G10", "G11", "G12", "G13", "G15", "G16", "G22"}


def build_rows() -> list[dict[str, object]]:
    source_rows = [
        json.loads(line)
        for line in SOURCE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows: list[dict[str, object]] = []
    for source in source_rows:
        identifier = str(source["id"])
        original_expected = dict(source["expected"])
        input_payload = copy.deepcopy(source["input"])
        if identifier == "G14":
            input_payload["title_hint"] = "Timeout research reference"
        applicable = identifier not in TITLE_NOT_APPLICABLE
        title = str(original_expected["title"]) if applicable else ""
        if identifier == "G14":
            title = "Timeout research reference"
        elif identifier == "G21":
            title = "正文首句作为候选。"
        processing_state = str(original_expected["state"])
        recall_eligible = bool(original_expected["recall_eligible"])
        index_eligible = processing_state == "completed" or (
            processing_state == "partial" and recall_eligible
        )
        user_status = (
            "ready"
            if processing_state == "completed" or index_eligible
            else "needs_attention"
        )
        rows.append(
            {
                "id": identifier,
                "corpus_version": CORPUS_VERSION,
                "tier": "q1-web",
                "source_class": source["source_class"],
                "fixture_path": source["fixture_path"],
                "response_plan": source["response_plan"],
                "input": input_payload,
                "expected": {
                    "content_title_applicable": applicable,
                    "content_title": title,
                    "title_provenance": TITLE_PROVENANCE.get(identifier, ""),
                    "processing_state": processing_state,
                    "safe_error_code": str(original_expected["safe_error"]),
                    "user_status": user_status,
                    "recall_eligible": recall_eligible,
                    "index_eligible": index_eligible,
                },
                "artifacts": copy.deepcopy(source["artifacts"]),
                "license": source["license"],
            }
        )
    return rows


def main() -> None:
    payload = "\n".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for row in build_rows()
    ) + "\n"
    DESTINATION.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
