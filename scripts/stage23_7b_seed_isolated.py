#!/usr/bin/env python3
"""Create the disposable 501-item Stage 23.7B fixture and explicitly bootstrap it."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--token", default="stage23-7b-synthetic-token")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    server = root / "server"
    sys.path.insert(0, str(server))

    from fastapi.testclient import TestClient
    from perclip_ingest.config import Settings
    from perclip_ingest.main import create_app
    from tests.test_knowledge_list_v2 import add_kb, seed_clips

    args.data_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(Settings(data_dir=args.data_dir, ingest_token=args.token))
    seed_clips(args.data_dir, 501)
    with sqlite3.connect(args.data_dir / "perclip.sqlite3") as db:
        add_kb(db, "kb-secondary", "Synthetic Secondary")
        db.execute(
            "update clips set title_hint=?,source_app='Synthetic Search',source_type='url',url='https://example.invalid/needle' where id=499",
            ("Synthetic deep-page marker ALPHA-499",),
        )
        db.execute("update clips set source_app='Synthetic Files',source_type='file',filename='fixture.pdf',mime_type='application/pdf' where id%7=0")
        db.execute("update clips set source_app='Synthetic Images',source_type='image',filename='fixture.png',mime_type='image/png' where id%11=0")
        db.execute(
            "insert into clip_knowledge_bases(clip_id,knowledge_base_id,association_type,route_decision_id,association_intent_id,created_at) values(499,'kb-secondary','manual',null,'','2026-01-01T00:00:00Z')"
        )
        enrichment = db.execute(
            """insert into clip_enrichments(clip_id,engine,status,title,summary,created_at,updated_at)
               values('1','stage23-7b','completed','Synthetic topic sample','Disposable correction sample',
                      '2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"""
        )
        metadata = {
            "contract_version": "perclip.clip.v1",
            "processing": {
                "active_enrichment_id": enrichment.lastrowid,
                "active_projection": {
                    "extraction_status": "completed",
                    "recall_eligible": True,
                    "index_eligible": True,
                },
            },
        }
        db.execute(
            "insert into clip_metadata(clip_id,client_request_id,contract_version,metadata_json,created_at) values(1,'request-1','perclip.clip.v1',?,'2026-01-01T00:00:00Z')",
            (json.dumps(metadata),),
        )
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {args.token}"}
    bootstrap = client.post("/api/knowledge/bootstrap", headers=headers)
    bootstrap.raise_for_status()
    summary = client.get("/api/knowledge/summary", headers=headers)
    summary.raise_for_status()
    search = client.get("/api/knowledge/summary", headers=headers, params={"query": "ALPHA-499"})
    search.raise_for_status()
    print(json.dumps({
        "bootstrap": bootstrap.json()["bootstrap"],
        "total_count": summary.json()["summary"]["total_count"],
        "deep_search_matching_count": search.json()["summary"]["matching_count"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
