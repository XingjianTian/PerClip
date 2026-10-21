from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from perclip_ingest.main import create_app
from perclip_ingest.pipeline_store import PipelineStore
from perclip_ingest.worker import PipelineWorker

from .q0_evaluator import (
    EvaluationClock,
    NoopRagflow,
    ResponsePlanFetcher,
    _case_command,
    _configure_quality_routing,
    _run_worker,
    _service,
    _settings,
)


SCHEMA_VERSION = "perclip.quality-corpus-report.v2"
CORPUS_VERSION = "q1-web-v2"
EXPECTED_FIELDS = {
    "content_title_applicable",
    "content_title",
    "title_provenance",
    "processing_state",
    "safe_error_code",
    "user_status",
    "recall_eligible",
    "index_eligible",
}


def load_manifest(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows or any(row.get("corpus_version") != CORPUS_VERSION for row in rows):
        raise ValueError(f"manifest must contain only {CORPUS_VERSION} rows")
    if len({str(row["id"]) for row in rows}) != len(rows):
        raise ValueError("manifest case ids must be unique")
    for row in rows:
        if set(row.get("expected", {})) != EXPECTED_FIELDS:
            raise ValueError(f"{row['id']} has an invalid v2 expected contract")
        for artifact in row.get("artifacts", []):
            artifact_path = path.parent / str(artifact["path"])
            digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            if digest != str(artifact["sha256"]):
                raise ValueError(f"{row['id']} artifact hash mismatch: {artifact['path']}")
    return rows


def manifest_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _actual_contract(read_model: dict[str, object]) -> dict[str, object]:
    active = dict(read_model["active_content"])
    quality = dict(read_model["quality"])
    provenance = dict(read_model["provenance"])
    title = str(active["title"])
    title_source = str(provenance["title_source"])
    return {
        "content_title_applicable": bool(title and title_source),
        "content_title": title,
        "title_provenance": title_source,
        "processing_state": quality["state"],
        "safe_error_code": dict(read_model["processing"])["safe_error"],
        "user_status": read_model["user_status"],
        "recall_eligible": quality["recall_eligible"],
        "index_eligible": quality["index_eligible"],
    }


def evaluate_case(row: dict[str, Any], fixture_root: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"perclip-q1-{str(row['id']).lower()}-") as directory:
        data_dir = Path(directory)
        settings = _settings(data_dir)
        service = _service(settings)
        _configure_quality_routing(service)
        command = _case_command(row, fixture_root)
        api = TestClient(create_app(settings, ragflow_adapter_override=NoopRagflow()))
        if command.asset is not None:
            envelope = {
                "contract_version": command.contract_version,
                "client_request_id": command.client_request_id,
                "source": asdict(command.source),
                "clip": asdict(command.clip),
                "capture": asdict(command.capture),
                "routing": asdict(command.routing),
            }
            response = api.post(
                "/api/ingest/v1/clips/multipart",
                headers={"Authorization": f"Bearer {settings.ingest_token}"},
                data={"envelope_json": json.dumps(envelope)},
                files={
                    "file": (
                        command.asset.filename,
                        command.asset.payload,
                        command.asset.mime_type,
                    )
                },
            )
            if response.status_code != 202:
                raise RuntimeError(f"{row['id']} multipart ingest failed: {response.status_code}")
            clip_id = int(response.json()["clip_id"])
        else:
            result = asyncio.run(service.ingest(command))
            clip_id = int(result.clip_id)

        clock = EvaluationClock()
        worker = PipelineWorker(
            settings, ragflow_adapter_override=NoopRagflow(), clock=clock
        )
        if row.get("response_plan"):
            worker.web_fetcher = ResponsePlanFetcher(
                fixture_root,
                str(row["response_plan"]),
                default_max_bytes=settings.web_fetch_max_bytes,
            )
        _run_worker(worker, clock, data_dir)
        pipeline = PipelineStore(data_dir)
        public_id = pipeline.public_id_for(clip_id)
        response = api.get(
            f"/api/clips/{public_id}/quality",
            headers={"Authorization": f"Bearer {settings.ingest_token}"},
        )
        if response.status_code != 200:
            raise RuntimeError(f"{row['id']} quality read failed: {response.status_code}")
        read_model = dict(response.json()["quality_read"])
        actual = _actual_contract(read_model)

        expected = dict(row["expected"])
        matches = {field: actual[field] == expected[field] for field in sorted(EXPECTED_FIELDS)}
        result_payload = {
            "id": row["id"],
            "source_class": row["source_class"],
            "actual_source": "quality_read_model",
            "input_hash": hashlib.sha256(
                "\n".join(str(item["sha256"]) for item in row["artifacts"]).encode("ascii")
            ).hexdigest(),
            "expected": expected,
            "actual": actual,
            "matches": matches,
            "contract_match": all(matches.values()),
        }
        if row["id"] == "G17":
            original = pipeline.latest_asset(clip_id=clip_id, role="original")
            with sqlite3.connect(data_dir / "perclip.sqlite3") as db:
                index_count = int(
                    db.execute(
                        "select count(*) from index_documents where clip_id=?", (clip_id,)
                    ).fetchone()[0]
                )
            recall = api.get(
                f"/api/recall/clips/{public_id}",
                headers={"Authorization": f"Bearer {settings.ingest_token}"},
            )
            result_payload["boundary_evidence"] = {
                "public_clip_identity": public_id.startswith("pc_"),
                "raw_asset_preserved": bool(
                    original and Path(str(original["storage_uri"])).is_file()
                ),
                "filename_provenance": actual["title_provenance"] == "file.filename",
                "recall_excluded": recall.status_code == 404,
                "index_excluded": index_count == 0,
            }
        return result_payload


def build_report(manifest_path: Path, *, perclip_commit: str) -> dict[str, object]:
    rows = load_manifest(manifest_path)
    cases = [evaluate_case(row, manifest_path.parent) for row in rows]
    passed = sum(bool(case["contract_match"]) for case in cases)
    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_version": CORPUS_VERSION,
        "perclip_commit": perclip_commit,
        "manifest_hash": manifest_hash(manifest_path),
        "baseline_mode": "first_v2_baseline",
        "relative_comparison": None,
        "summary": {
            "case_count": len(cases),
            "contract_passed": passed,
            "contract_failed": len(cases) - passed,
            "all_contracts_match": passed == len(cases),
        },
        "cases": cases,
    }


def markdown_report(report: dict[str, object]) -> str:
    summary = dict(report["summary"])
    lines = [
        f"# {report['corpus_version']} baseline",
        "",
        f"- Schema: `{report['schema_version']}`",
        f"- Implementation commit: `{report['perclip_commit']}`",
        f"- Manifest SHA-256: `{report['manifest_hash']}`",
        "- Mode: first Corpus v2 baseline; no relative Q0-Web v1 score is claimed",
        f"- Contract cases: {summary['contract_passed']}/{summary['case_count']} passed",
        "",
        "| Case | Title applicable | Content title | Provenance | Processing | User status | Recall | Index | Match |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in report["cases"]:
        actual = dict(case["actual"])
        title = str(actual["content_title"]).replace("|", "\\|") or "—"
        lines.append(
            "| {id} | {applicable} | {title} | {provenance} | {processing} | {user} | {recall} | {index} | {match} |".format(
                id=case["id"],
                applicable="yes" if actual["content_title_applicable"] else "no",
                title=title,
                provenance=actual["title_provenance"] or "—",
                processing=actual["processing_state"],
                user=actual["user_status"],
                recall="yes" if actual["recall_eligible"] else "no",
                index="yes" if actual["index_eligible"] else "no",
                match="pass" if case["contract_match"] else "fail",
            )
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local-only q1-web-v2 evaluator")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    report = build_report(args.manifest, perclip_commit=args.commit)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.markdown.write_text(markdown_report(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "corpus_version": report["corpus_version"],
                "manifest_hash": report["manifest_hash"],
                "passed": report["summary"]["contract_passed"],
                "cases": report["summary"]["case_count"],
                "json": str(args.json),
                "markdown": str(args.markdown),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
