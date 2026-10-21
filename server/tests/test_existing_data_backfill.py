from __future__ import annotations

import hashlib
import sqlite3

import pytest

from perclip_ingest.existing_data_backfill import (
    APPLY_CONFIRMATION,
    ExistingDataBackfillError,
    apply_existing_data_backfill,
    audit_existing_data,
)
from perclip_ingest.knowledge_base_store import KnowledgeBaseStore
from perclip_ingest.pipeline_store import PipelineStore
from perclip_ingest.storage import ClipStore


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seed_existing_database(tmp_path, *, clips=3):
    data_dir = tmp_path / "data"
    ClipStore(data_dir).init()
    KnowledgeBaseStore(data_dir).init()
    PipelineStore(data_dir).init()
    database = data_dir / "perclip.sqlite3"
    with sqlite3.connect(database) as db:
        now = "2026-07-25T00:00:00+00:00"
        for index in range(clips):
            db.execute(
                """
                insert into clips(
                    client_request_id, source_type, title_hint, note, text, url,
                    mime_type, device_name, source_app, captured_at, filename,
                    size_bytes, original_path, content_hash, ragflow_document_id,
                    archive_status, created_at
                ) values (?, 'text', ?, '', ?, '', 'text/plain', '', 'legacy',
                    ?, '', 0, '', ?, '', 'clip_to_ragflow', ?)
                """,
                (
                    f"legacy-{index}",
                    f"Legacy {index}",
                    f"body {index}",
                    now,
                    f"hash-{index}",
                    now,
                ),
            )
        default_kb = db.execute(
            "select id from knowledge_bases where is_default=1"
        ).fetchone()[0]
        db.execute(
            """
            insert into clip_route_decisions(
                clip_id, client_request_id, knowledge_base_id, decision_type,
                reason, created_at
            ) values ('1', 'legacy-0', ?, 'legacy', 'existing evidence', ?)
            """,
            (default_kb, now),
        )
    backup = tmp_path / "verified-backup.sqlite3"
    with sqlite3.connect(database) as source, sqlite3.connect(backup) as destination:
        source.backup(destination)
    return data_dir, backup


def table_count(database, table):
    with sqlite3.connect(database) as db:
        return db.execute(f"select count(*) from {table}").fetchone()[0]


def test_dry_run_is_read_only_and_reports_counts_only(tmp_path):
    data_dir, _backup = seed_existing_database(tmp_path)
    database = data_dir / "perclip.sqlite3"
    before = sha256(database)

    report = audit_existing_data(data_dir)

    assert report["mode"] == "dry_run"
    assert report["clips"] == 3
    assert report["missing_identities"] == 3
    assert report["missing_associations"] == 3
    assert report["route_decisions"] == 1
    assert report["clips_with_matching_route"] == 1
    assert report["outbox_jobs"] == 0
    assert len(report["review_fingerprint"]) == 64
    assert report["database_mutated"] is False
    assert report["ragflow_mutated"] is False
    assert sha256(database) == before


def test_apply_requires_confirmation_fingerprint_and_separate_backup(tmp_path):
    data_dir, backup = seed_existing_database(tmp_path)
    report = audit_existing_data(data_dir)

    with pytest.raises(ExistingDataBackfillError, match="confirmation"):
        apply_existing_data_backfill(
            data_dir,
            confirmation="",
            expected_review_fingerprint=report["review_fingerprint"],
            verified_backup=backup,
        )
    with pytest.raises(ExistingDataBackfillError, match="fingerprint"):
        apply_existing_data_backfill(
            data_dir,
            confirmation=APPLY_CONFIRMATION,
            expected_review_fingerprint="",
            verified_backup=backup,
        )
    with pytest.raises(ExistingDataBackfillError, match="separate"):
        apply_existing_data_backfill(
            data_dir,
            confirmation=APPLY_CONFIRMATION,
            expected_review_fingerprint=report["review_fingerprint"],
            verified_backup=data_dir / "perclip.sqlite3",
        )


def test_apply_is_minimal_transactional_and_idempotent_after_fresh_review(tmp_path):
    data_dir, backup = seed_existing_database(tmp_path)
    database = data_dir / "perclip.sqlite3"
    with sqlite3.connect(database) as db:
        clips_before = db.execute("select * from clips order by id").fetchall()
        route_before = db.execute(
            "select * from clip_route_decisions order by id"
        ).fetchall()

    dry_run = audit_existing_data(data_dir)
    applied = apply_existing_data_backfill(
        data_dir,
        confirmation=APPLY_CONFIRMATION,
        expected_review_fingerprint=dry_run["review_fingerprint"],
        verified_backup=backup,
    )

    assert applied["inserted_identities"] == 3
    assert applied["inserted_associations"] == 3
    assert applied["clips_mutated"] is False
    assert applied["processing_state_mutated"] is False
    assert applied["ragflow_mutated"] is False
    with sqlite3.connect(database) as db:
        clips_after = db.execute("select * from clips order by id").fetchall()
        route_after = db.execute(
            "select * from clip_route_decisions order by id"
        ).fetchall()
        identities = db.execute(
            "select clip_id, public_id from clip_identities order by clip_id"
        ).fetchall()
        associations = db.execute(
            """
            select clip_id, association_type, route_decision_id
            from clip_knowledge_bases order by clip_id
            """
        ).fetchall()
    assert clips_after == clips_before
    assert route_after == route_before
    assert all(public_id.startswith("pc_") for _, public_id in identities)
    assert len({public_id for _, public_id in identities}) == 3
    assert [row[1] for row in associations] == ["imported"] * 3
    assert associations[0][2] == 1
    assert associations[1][2] is None
    assert associations[2][2] is None
    for table in (
        "source_events",
        "assets",
            "outbox_jobs",
            "processing_runs",
            "clip_enrichments",
            "index_documents",
            "index_attempts",
    ):
        assert table_count(database, table) == 0

    second_review = audit_existing_data(data_dir)
    second = apply_existing_data_backfill(
        data_dir,
        confirmation=APPLY_CONFIRMATION,
        expected_review_fingerprint=second_review["review_fingerprint"],
        verified_backup=backup,
    )
    assert second["inserted_identities"] == 0
    assert second["inserted_associations"] == 0
    assert second["database_mutated"] is False


def test_apply_rolls_back_every_insert_when_database_changes_after_review(tmp_path):
    data_dir, backup = seed_existing_database(tmp_path)
    database = data_dir / "perclip.sqlite3"
    dry_run = audit_existing_data(data_dir)
    with sqlite3.connect(database) as db:
        db.execute("update clips set title_hint='changed' where id=1")

    with pytest.raises(ExistingDataBackfillError, match="differs"):
        apply_existing_data_backfill(
            data_dir,
            confirmation=APPLY_CONFIRMATION,
            expected_review_fingerprint=dry_run["review_fingerprint"],
            verified_backup=backup,
        )
    assert table_count(database, "clip_identities") == 0
    assert table_count(database, "clip_knowledge_bases") == 0


def test_apply_rejects_backup_with_same_count_but_different_clip_data(tmp_path):
    data_dir, backup = seed_existing_database(tmp_path)
    dry_run = audit_existing_data(data_dir)
    with sqlite3.connect(backup) as db:
        db.execute("update clips set title_hint='different backup' where id=1")

    with pytest.raises(ExistingDataBackfillError, match="legacy data"):
        apply_existing_data_backfill(
            data_dir,
            confirmation=APPLY_CONFIRMATION,
            expected_review_fingerprint=dry_run["review_fingerprint"],
            verified_backup=backup,
        )
    assert table_count(data_dir / "perclip.sqlite3", "clip_identities") == 0
    assert table_count(data_dir / "perclip.sqlite3", "clip_knowledge_bases") == 0


def test_apply_rejects_route_drift_after_review(tmp_path):
    data_dir, backup = seed_existing_database(tmp_path)
    dry_run = audit_existing_data(data_dir)
    with sqlite3.connect(data_dir / "perclip.sqlite3") as db:
        db.execute(
            "update clip_route_decisions set reason='changed after review' where id=1"
        )

    with pytest.raises(ExistingDataBackfillError, match="differs"):
        apply_existing_data_backfill(
            data_dir,
            confirmation=APPLY_CONFIRMATION,
            expected_review_fingerprint=dry_run["review_fingerprint"],
            verified_backup=backup,
        )
    assert table_count(data_dir / "perclip.sqlite3", "clip_identities") == 0
    assert table_count(data_dir / "perclip.sqlite3", "clip_knowledge_bases") == 0


def test_audit_rejects_multiple_active_knowledge_bases(tmp_path):
    data_dir, _backup = seed_existing_database(tmp_path)
    KnowledgeBaseStore(data_dir).create_knowledge_base(name="Unexpected")

    with pytest.raises(ExistingDataBackfillError, match="exactly one"):
        audit_existing_data(data_dir)
