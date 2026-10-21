from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


APPLY_CONFIRMATION = "BACKFILL_EXISTING_UNIFIED_READ_MODEL"
REQUIRED_TABLES = {
    "clips",
    "clip_identities",
    "clip_knowledge_bases",
    "knowledge_bases",
    "clip_route_decisions",
}


class ExistingDataBackfillError(ValueError):
    pass


@dataclass(frozen=True)
class BackfillAudit:
    report: dict[str, object]
    default_knowledge_base_id: str
    clip_rows_hash: str
    review_fingerprint: str


def utc_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect_read_only(database: Path, *, immutable: bool = False) -> sqlite3.Connection:
    uri = f"file:{database.resolve().as_posix()}?mode=ro"
    if immutable:
        uri += "&immutable=1"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    db.execute("pragma foreign_keys=on")
    return db


def _connect_backup_read_only(database: Path) -> sqlite3.Connection:
    try:
        db = _connect_read_only(database)
        db.execute("pragma schema_version").fetchone()
        return db
    except sqlite3.OperationalError:
        try:
            db.close()
        except UnboundLocalError:
            pass
        wal = database.with_name(database.name + "-wal")
        if wal.exists():
            raise ExistingDataBackfillError("verified backup WAL could not be read")
        return _connect_read_only(database, immutable=True)


def _table_names(db: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in db.execute(
            "select name from sqlite_master where type='table'"
        ).fetchall()
    }


def _scalar(db: sqlite3.Connection, sql: str, parameters: tuple[object, ...] = ()) -> int:
    return int(db.execute(sql, parameters).fetchone()[0])


def _table_rows_hash(
    db: sqlite3.Connection,
    table: str,
    *,
    columns: list[str] | None = None,
) -> str:
    quoted_table = '"' + table.replace('"', '""') + '"'
    resolved_columns = columns or [
        str(row[1])
        for row in db.execute(f"pragma table_info({quoted_table})").fetchall()
    ]
    if not resolved_columns:
        raise ExistingDataBackfillError("table schema is unavailable")
    quoted_columns = ", ".join(
        '"' + column.replace('"', '""') + '"'
        for column in resolved_columns
    )
    serialized_rows = sorted(
        json.dumps(
            [row[column] for column in resolved_columns],
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        for row in db.execute(
            f"select {quoted_columns} from {quoted_table}"
        ).fetchall()
    )
    payload = {
        "columns": resolved_columns,
        "rows": serialized_rows,
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def _clip_rows_hash(db: sqlite3.Connection) -> str:
    return _table_rows_hash(db, "clips")


def _audit_connection(db: sqlite3.Connection) -> BackfillAudit:
    tables = _table_names(db)
    missing_tables = REQUIRED_TABLES - tables
    if missing_tables:
        raise ExistingDataBackfillError("unified pipeline schema is incomplete")

    default_rows = db.execute(
        """
        select id from knowledge_bases
        where deleted_at='' and is_archived=0 and is_default=1
        order by id
        """
    ).fetchall()
    active_knowledge_bases = _scalar(
        db,
        "select count(*) from knowledge_bases where deleted_at='' and is_archived=0",
    )
    if len(default_rows) != 1 or active_knowledge_bases != 1:
        raise ExistingDataBackfillError(
            "exactly one active default knowledge base is required"
        )
    default_knowledge_base_id = str(default_rows[0]["id"])

    clips = _scalar(db, "select count(*) from clips")
    identities = _scalar(db, "select count(*) from clip_identities")
    missing_identities = _scalar(
        db,
        """
        select count(*) from clips c
        left join clip_identities i on i.clip_id=c.id
        where i.clip_id is null
        """,
    )
    duplicate_public_ids = _scalar(
        db,
        """
        select count(*) from (
            select public_id from clip_identities
            group by public_id having count(*) > 1
        )
        """,
    )
    orphan_identities = _scalar(
        db,
        """
        select count(*) from clip_identities i
        left join clips c on c.id=i.clip_id
        where c.id is null
        """,
    )
    associations = _scalar(db, "select count(*) from clip_knowledge_bases")
    missing_associations = _scalar(
        db,
        """
        select count(*) from clips c
        left join clip_knowledge_bases a
          on a.clip_id=c.id and a.knowledge_base_id=?
        where a.clip_id is null
        """,
        (default_knowledge_base_id,),
    )
    associations_to_other_knowledge_bases = _scalar(
        db,
        "select count(*) from clip_knowledge_bases where knowledge_base_id<>?",
        (default_knowledge_base_id,),
    )
    orphan_associations = _scalar(
        db,
        """
        select count(*) from clip_knowledge_bases a
        left join clips c on c.id=a.clip_id
        left join knowledge_bases k on k.id=a.knowledge_base_id
        where c.id is null or k.id is null
        """,
    )
    route_decisions = _scalar(db, "select count(*) from clip_route_decisions")
    clips_with_matching_route = _scalar(
        db,
        """
        select count(*) from clips c
        join clip_route_decisions d on d.id=(
            select latest.id from clip_route_decisions latest
            where latest.clip_id=cast(c.id as text)
            order by latest.id desc limit 1
        )
        where d.knowledge_base_id=?
        """,
        (default_knowledge_base_id,),
    )
    outbox_jobs = (
        _scalar(db, "select count(*) from outbox_jobs")
        if "outbox_jobs" in tables
        else 0
    )
    processing_runs = (
        _scalar(db, "select count(*) from processing_runs")
        if "processing_runs" in tables
        else 0
    )
    index_attempts = (
        _scalar(db, "select count(*) from index_attempts")
        if "index_attempts" in tables
        else 0
    )
    source_events = (
        _scalar(db, "select count(*) from source_events")
        if "source_events" in tables
        else 0
    )
    assets = (
        _scalar(db, "select count(*) from assets")
        if "assets" in tables
        else 0
    )
    enrichments = (
        _scalar(db, "select count(*) from clip_enrichments")
        if "clip_enrichments" in tables
        else 0
    )
    topic_assignments = (
        _scalar(db, "select count(*) from clip_topic_assignments")
        if "clip_topic_assignments" in tables
        else 0
    )
    index_documents = (
        _scalar(db, "select count(*) from index_documents")
        if "index_documents" in tables
        else 0
    )
    triggers = _scalar(
        db,
        "select count(*) from sqlite_master where type='trigger'",
    )
    quick_check = str(db.execute("pragma quick_check").fetchone()[0])

    if identities != clips - missing_identities:
        raise ExistingDataBackfillError("identity count is inconsistent")
    if associations != clips - missing_associations:
        raise ExistingDataBackfillError("knowledge base association count is inconsistent")
    if duplicate_public_ids or orphan_identities or orphan_associations:
        raise ExistingDataBackfillError("existing identity or association state is inconsistent")
    if associations_to_other_knowledge_bases:
        raise ExistingDataBackfillError("unexpected knowledge base association exists")
    if any(
        (
            outbox_jobs,
            processing_runs,
            index_attempts,
            source_events,
            assets,
            enrichments,
            topic_assignments,
            index_documents,
        )
    ):
        raise ExistingDataBackfillError("historical processing state must remain empty")
    if triggers:
        raise ExistingDataBackfillError("unexpected database trigger exists")
    if quick_check != "ok":
        raise ExistingDataBackfillError("database integrity check failed")

    clip_rows_hash = _clip_rows_hash(db)
    fingerprint_payload = {
        "clips": clips,
        "clip_rows_hash": clip_rows_hash,
        "identity_rows_hash": _table_rows_hash(db, "clip_identities"),
        "association_rows_hash": _table_rows_hash(db, "clip_knowledge_bases"),
        "knowledge_base_rows_hash": _table_rows_hash(db, "knowledge_bases"),
        "route_decision_rows_hash": _table_rows_hash(db, "clip_route_decisions"),
        "default_knowledge_base_hash": hashlib.sha256(
            default_knowledge_base_id.encode()
        ).hexdigest(),
        "active_knowledge_bases": active_knowledge_bases,
        "identities": identities,
        "missing_identities": missing_identities,
        "associations": associations,
        "missing_associations": missing_associations,
        "route_decisions": route_decisions,
        "clips_with_matching_route": clips_with_matching_route,
        "outbox_jobs": outbox_jobs,
        "processing_runs": processing_runs,
        "index_attempts": index_attempts,
        "source_events": source_events,
        "assets": assets,
        "enrichments": enrichments,
        "topic_assignments": topic_assignments,
        "index_documents": index_documents,
        "quick_check": quick_check,
    }
    review_fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    report: dict[str, object] = {
        "mode": "dry_run",
        "clips": clips,
        "active_default_knowledge_bases": 1,
        "existing_identities": identities,
        "missing_identities": missing_identities,
        "existing_associations": associations,
        "missing_associations": missing_associations,
        "route_decisions": route_decisions,
        "clips_with_matching_route": clips_with_matching_route,
        "outbox_jobs": outbox_jobs,
        "processing_runs": processing_runs,
        "index_attempts": index_attempts,
        "source_events": source_events,
        "assets": assets,
        "enrichments": enrichments,
        "topic_assignments": topic_assignments,
        "index_documents": index_documents,
        "duplicate_public_ids": duplicate_public_ids,
        "orphan_identities": orphan_identities,
        "orphan_associations": orphan_associations,
        "quick_check": quick_check,
        "review_fingerprint": review_fingerprint,
        "database_mutated": False,
        "ragflow_mutated": False,
    }
    return BackfillAudit(
        report=report,
        default_knowledge_base_id=default_knowledge_base_id,
        clip_rows_hash=clip_rows_hash,
        review_fingerprint=review_fingerprint,
    )


def audit_existing_data(data_dir: Path) -> dict[str, object]:
    database = data_dir.resolve() / "perclip.sqlite3"
    if not database.is_file():
        raise ExistingDataBackfillError("PerClip database not found")
    with _connect_read_only(database) as db:
        return _audit_connection(db).report


def _validate_backup(
    backup_database: Path,
    *,
    live_db: sqlite3.Connection,
    expected_clips: int,
    expected_clip_rows_hash: str,
) -> None:
    backup_database = backup_database.resolve()
    if not backup_database.is_file():
        raise ExistingDataBackfillError("verified backup database not found")
    # A closed SQLite backup can inherit WAL journal mode without a companion
    # WAL file. Fall back to immutable only when no WAL exists; otherwise the
    # ordinary read-only connection must include the current WAL contents.
    with _connect_backup_read_only(backup_database) as backup:
        tables = _table_names(backup)
        if "clips" not in tables:
            raise ExistingDataBackfillError("verified backup has no clips table")
        clips = _scalar(backup, "select count(*) from clips")
        clip_rows_hash = _clip_rows_hash(backup)
        quick_check = str(backup.execute("pragma quick_check").fetchone()[0])
        live_tables = _table_names(live_db)
        legacy_state_matches = True
        for table in sorted(
            tables
            - {
                "sqlite_sequence",
                "clip_identities",
                "clip_knowledge_bases",
            }
        ):
            if table not in live_tables:
                legacy_state_matches = False
                break
            quoted_table = '"' + table.replace('"', '""') + '"'
            backup_columns = [
                str(row[1])
                for row in backup.execute(
                    f"pragma table_info({quoted_table})"
                ).fetchall()
            ]
            live_columns = {
                str(row[1])
                for row in live_db.execute(
                    f"pragma table_info({quoted_table})"
                ).fetchall()
            }
            if not set(backup_columns).issubset(live_columns):
                legacy_state_matches = False
                break
            if _table_rows_hash(
                backup,
                table,
                columns=backup_columns,
            ) != _table_rows_hash(
                live_db,
                table,
                columns=backup_columns,
            ):
                legacy_state_matches = False
                break
    if (
        clips != expected_clips
        or clip_rows_hash != expected_clip_rows_hash
        or quick_check != "ok"
        or not legacy_state_matches
    ):
        raise ExistingDataBackfillError(
            "verified backup does not match reviewed legacy data"
        )


def _insert_public_identity(
    db: sqlite3.Connection,
    *,
    clip_id: int,
    created_at: str,
) -> None:
    for _ in range(5):
        public_id = f"pc_{uuid.uuid4().hex}"
        try:
            db.execute(
                """
                insert into clip_identities(clip_id, public_id, created_at)
                values (?, ?, ?)
                """,
                (clip_id, public_id, created_at),
            )
            return
        except sqlite3.IntegrityError as error:
            if "public_id" not in str(error):
                raise
    raise ExistingDataBackfillError("could not allocate a unique public identity")


def apply_existing_data_backfill(
    data_dir: Path,
    *,
    confirmation: str,
    expected_review_fingerprint: str,
    verified_backup: Path,
) -> dict[str, object]:
    if confirmation != APPLY_CONFIRMATION:
        raise ExistingDataBackfillError("explicit backfill confirmation is required")
    if not expected_review_fingerprint:
        raise ExistingDataBackfillError("reviewed dry-run fingerprint is required")

    database = data_dir.resolve() / "perclip.sqlite3"
    if not database.is_file():
        raise ExistingDataBackfillError("PerClip database not found")
    if database.resolve() == verified_backup.resolve():
        raise ExistingDataBackfillError("verified backup must be separate from the live database")

    db = sqlite3.connect(database, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("pragma foreign_keys=on")
    try:
        db.execute("begin immediate")
        before = _audit_connection(db)
        if before.review_fingerprint != expected_review_fingerprint:
            raise ExistingDataBackfillError("database differs from the reviewed dry-run")
        expected_clips = int(before.report["clips"])
        _validate_backup(
            verified_backup,
            live_db=db,
            expected_clips=expected_clips,
            expected_clip_rows_hash=before.clip_rows_hash,
        )

        total_changes_before = db.total_changes
        now = utc_text()
        missing_identity_rows = db.execute(
            """
            select c.id from clips c
            left join clip_identities i on i.clip_id=c.id
            where i.clip_id is null
            order by c.id
            """
        ).fetchall()
        for row in missing_identity_rows:
            _insert_public_identity(db, clip_id=int(row["id"]), created_at=now)

        missing_association_rows = db.execute(
            """
            select c.id from clips c
            left join clip_knowledge_bases a
              on a.clip_id=c.id and a.knowledge_base_id=?
            where a.clip_id is null
            order by c.id
            """,
            (before.default_knowledge_base_id,),
        ).fetchall()
        for row in missing_association_rows:
            clip_id = int(row["id"])
            route = db.execute(
                """
                select id, knowledge_base_id from clip_route_decisions
                where clip_id=cast(? as text)
                order by id desc limit 1
                """,
                (clip_id,),
            ).fetchone()
            route_decision_id = (
                int(route["id"])
                if route is not None
                and str(route["knowledge_base_id"])
                == before.default_knowledge_base_id
                else None
            )
            db.execute(
                """
                insert into clip_knowledge_bases(
                    clip_id, knowledge_base_id, association_type, route_decision_id,
                    association_intent_id, created_at
                ) values (?, ?, 'imported', ?, ?, ?)
                """,
                (
                    clip_id,
                    before.default_knowledge_base_id,
                    route_decision_id,
                    f"assoc_{uuid.uuid4().hex}",
                    now,
                ),
            )

        inserted_identities = len(missing_identity_rows)
        inserted_associations = len(missing_association_rows)
        if db.total_changes - total_changes_before != inserted_identities + inserted_associations:
            raise ExistingDataBackfillError("unexpected database mutation detected")

        after = _audit_connection(db)
        if int(after.report["missing_identities"]) != 0:
            raise ExistingDataBackfillError("identity backfill is incomplete")
        if int(after.report["missing_associations"]) != 0:
            raise ExistingDataBackfillError("knowledge base backfill is incomplete")
        if int(after.report["clips"]) != expected_clips:
            raise ExistingDataBackfillError("clip count changed during backfill")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return {
        "mode": "apply",
        "clips": expected_clips,
        "inserted_identities": inserted_identities,
        "inserted_associations": inserted_associations,
        "remaining_missing_identities": 0,
        "remaining_missing_associations": 0,
        "quick_check": "ok",
        "database_mutated": bool(inserted_identities or inserted_associations),
        "clips_mutated": False,
        "processing_state_mutated": False,
        "ragflow_mutated": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit or backfill the existing unified PerClip read model"
    )
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--expect-review-fingerprint", default="")
    parser.add_argument("--verified-backup", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.apply:
            if args.verified_backup is None:
                raise ExistingDataBackfillError("--verified-backup is required for apply")
            report = apply_existing_data_backfill(
                args.data_dir,
                confirmation=args.confirm,
                expected_review_fingerprint=args.expect_review_fingerprint,
                verified_backup=args.verified_backup,
            )
        else:
            report = audit_existing_data(args.data_dir)
    except (ExistingDataBackfillError, sqlite3.Error) as error:
        print(
            json.dumps(
                {"ok": False, "error": str(error)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
