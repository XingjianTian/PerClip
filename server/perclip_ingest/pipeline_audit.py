from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


class PipelineAuditError(ValueError):
    pass


def audit_pipeline(data_dir: Path) -> dict[str, object]:
    database = data_dir.resolve() / "perclip.sqlite3"
    if not database.is_file():
        raise PipelineAuditError("PerClip database not found")
    uri = f"file:{database.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        required = {
            "clips", "clip_identities", "source_events", "assets", "outbox_jobs",
            "processing_runs", "clip_knowledge_bases", "index_documents",
            "pipeline_control_events",
        }
        tables = {
            str(row[0])
            for row in db.execute("select name from sqlite_master where type='table'").fetchall()
        }
        if not required.issubset(tables):
            raise PipelineAuditError("PerClip pipeline schema is incomplete")
        scalar = lambda sql: int(db.execute(sql).fetchone()[0])
        jobs = {
            str(status): int(count)
            for status, count in db.execute(
                "select status, count(*) from outbox_jobs group by status order by status"
            ).fetchall()
        }
        indexes = {
            str(status): int(count)
            for status, count in db.execute(
                "select status, count(*) from index_documents group by status order by status"
            ).fetchall()
        }
        controls = {
            str(action): int(count)
            for action, count in db.execute(
                "select action, count(*) from pipeline_control_events group by action order by action"
            ).fetchall()
        }
        return {
            "mode": "read_only",
            "clips": scalar("select count(*) from clips"),
            "accepted_without_identity": scalar(
                """select count(*) from clips c left join clip_identities i on i.clip_id=c.id
                   where c.archive_status='accepted' and i.clip_id is null"""
            ),
            "identities_without_source_event": scalar(
                """select count(*) from clip_identities i left join source_events s on s.clip_id=i.clip_id
                   where s.clip_id is null"""
            ),
            "assets_with_missing_file": sum(
                1
                for (storage_uri,) in db.execute(
                    "select storage_uri from assets where storage_uri != ''"
                ).fetchall()
                if not Path(str(storage_uri)).is_file()
            ),
            "clips_without_knowledge_base": scalar(
                """select count(*) from clip_identities i
                   left join clip_knowledge_bases ckb on ckb.clip_id=i.clip_id
                   where ckb.clip_id is null"""
            ),
            "duplicate_public_ids": scalar(
                """select count(*) from (
                   select public_id from clip_identities group by public_id having count(*) > 1
                )"""
            ),
            "jobs_by_status": jobs,
            "index_documents_by_status": indexes,
            "control_events_by_action": controls,
            "database_mutated": False,
            "ragflow_mutated": False,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only PerClip pipeline consistency audit")
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = audit_pipeline(args.data_dir)
    except PipelineAuditError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
