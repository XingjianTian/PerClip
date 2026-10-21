from __future__ import annotations

import hashlib
import sqlite3

import pytest

from perclip_ingest.legacy_migration import APPLY_CONFIRMATION, LegacyImporter, LegacyMigrationError
from perclip_ingest.pipeline_store import PipelineStore
from perclip_ingest.storage import ClipStore


def create_legacy_db(tmp_path):
    markdown = tmp_path / "legacy-one.md"
    markdown.write_text("# Imported memory\n\nUseful body", encoding="utf-8")
    missing = tmp_path / "missing.md"
    database = tmp_path / "personal_clips.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute(
            """
            create table items(
                id integer primary key, created_at text not null, launcher_id text,
                message_id text, source_type text not null, platform text not null,
                title text not null, markdown_path text not null, original_path text,
                source_url text, ragflow_document_id text, status text not null,
                metadata_json text not null
            )
            """
        )
        rows = [
            (1, "2026-01-01T10:00:00", "wechat", "m1", "url", "webpage", "Imported",
             str(markdown), "", "https://example.com/a", "doc-1", "active", "{}"),
            (2, "2026-01-02T10:00:00", "wechat", "m2", "url", "webpage", "Missing",
             str(missing), "", "https://example.com/b", "doc-2", "active", "{}"),
            (3, "2026-01-03T10:00:00", "wechat", "m3", "text", "text_note", "Old",
             str(markdown), "", "", "doc-3", "superseded", "{}"),
        ]
        db.executemany("insert into items values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return database


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_audit_is_read_only_and_reports_only_counts(tmp_path):
    legacy = create_legacy_db(tmp_path)
    before = sha256(legacy)
    importer = LegacyImporter(legacy_db=legacy, data_dir=tmp_path / "target", dataset_id="dataset-test")

    report = importer.audit()

    assert report["legacy_items"] == 3
    assert report["status_counts"] == {"active": 2, "superseded": 1}
    assert report["active_candidates"] == 2
    assert report["missing_markdown_files"] == 1
    assert report["legacy_database_mutated"] is False
    assert sha256(legacy) == before
    assert not (tmp_path / "target" / "perclip.sqlite3").exists()


def test_apply_requires_confirmation_dataset_and_backup_then_is_idempotent(tmp_path):
    legacy = create_legacy_db(tmp_path)
    target = tmp_path / "target"
    ClipStore(target).init()
    PipelineStore(target).init()
    importer_without_dataset = LegacyImporter(legacy_db=legacy, data_dir=target)
    with pytest.raises(LegacyMigrationError, match="confirmation"):
        importer_without_dataset.apply(confirmation="", backup_dir=tmp_path / "backups")
    with pytest.raises(LegacyMigrationError, match="dataset mapping"):
        importer_without_dataset.apply(confirmation=APPLY_CONFIRMATION, backup_dir=tmp_path / "backups")

    before = sha256(legacy)
    importer = LegacyImporter(legacy_db=legacy, data_dir=target, dataset_id="dataset-test")
    first = importer.apply(confirmation=APPLY_CONFIRMATION, backup_dir=tmp_path / "backups")
    second = importer.apply(confirmation=APPLY_CONFIRMATION, backup_dir=tmp_path / "backups")

    assert first == {
        "mode": "apply", "imported_active": 1, "mapped_inactive": 1,
        "skipped_missing": 1, "legacy_database_mutated": False, "ragflow_mutated": False,
    }
    assert second["imported_active"] == second["mapped_inactive"] == second["skipped_missing"] == 0
    assert sha256(legacy) == before
    assert len(list((tmp_path / "backups").glob("perclip-before-legacy-import-*.sqlite3"))) >= 1
    with sqlite3.connect(target / "perclip.sqlite3") as db:
        assert db.execute("select count(*) from legacy_import_map").fetchone()[0] == 3
        assert db.execute("select count(*) from clips").fetchone()[0] == 1
        assert db.execute("select adapter from source_events").fetchone()[0] == "import"
        metadata = db.execute("select metadata_json from clip_metadata").fetchone()[0]
        index = db.execute("select dataset_id, document_id, status from index_documents").fetchone()
    assert index == ("dataset-test", "doc-1", "legacy_existing")
    assert '"launcher_type":"import"' in metadata
    assert '"decision_type":"import"' in metadata
