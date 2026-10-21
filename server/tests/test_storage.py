from pathlib import Path
import sqlite3

from perclip_ingest.metadata_contract import CONTRACT_VERSION
from perclip_ingest.storage import ClipStore


def test_request_lock_blocks_duplicate_request_until_released(tmp_path):
    store = ClipStore(tmp_path)
    store.init()

    assert store.acquire_request_lock("same-request") is True
    assert store.acquire_request_lock("same-request") is False
    store.release_request_lock("same-request")
    assert store.acquire_request_lock("same-request") is True


def test_request_lock_ignores_blank_request_ids(tmp_path):
    store = ClipStore(tmp_path)
    store.init()

    assert store.acquire_request_lock("") is True
    assert store.acquire_request_lock("   ") is True

    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        lock_count = db.execute("select count(*) from request_locks").fetchone()[0]
    assert lock_count == 0


def test_request_lock_reclaims_stale_entries(tmp_path):
    store = ClipStore(tmp_path)
    store.init()
    stale_epoch = 1
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.execute(
            "insert into request_locks (client_request_id, created_at_epoch) values (?, ?)",
            ("old-request", stale_epoch),
        )

    assert store.acquire_request_lock("old-request") is True


def test_request_lock_token_prevents_stale_owner_from_releasing_successor(tmp_path):
    store = ClipStore(tmp_path)
    store.init()
    first = store.acquire_request_lock_token("tokenized-request")
    assert first
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.execute("update request_locks set created_at_epoch=1 where client_request_id=?", ("tokenized-request",))
    successor = store.acquire_request_lock_token("tokenized-request")
    assert successor and successor != first
    store.release_request_lock_token("tokenized-request", first)
    assert store.acquire_request_lock_token("tokenized-request") is None
    store.release_request_lock_token("tokenized-request", successor)
    assert store.acquire_request_lock_token("tokenized-request") is not None


def test_save_recovers_duplicate_request_id_race_without_extra_local_file(tmp_path):
    store = ClipStore(tmp_path)
    store.init()

    first = store.save(
        client_request_id="same-request",
        source_type="text",
        title_hint="first",
        note="",
        text="original",
        url="",
        mime_type="text/plain",
        device_name="device",
        source_app="app",
        captured_at="2026-06-30T00:00:00Z",
        filename="",
        payload=b"",
    )
    duplicate = store.save(
        client_request_id="same-request",
        source_type="text",
        title_hint="second",
        note="",
        text="duplicate",
        url="",
        mime_type="text/plain",
        device_name="device",
        source_app="app",
        captured_at="2026-06-30T00:00:01Z",
        filename="",
        payload=b"",
    )

    clip_files = list(Path(tmp_path / "clips").rglob("*.txt"))
    assert duplicate.duplicate is True
    assert duplicate.id == first.id
    assert duplicate.original_path == first.original_path
    assert [path.read_text(encoding="utf-8") for path in clip_files] == ["original"]


def test_save_and_read_normalized_metadata(tmp_path):
    store = ClipStore(tmp_path)
    store.init()
    clip = store.save(
        client_request_id="metadata-request",
        source_type="text",
        title_hint="metadata",
        note="",
        text="payload",
        url="",
        mime_type="text/plain",
        device_name="device",
        source_app="app",
        captured_at="2026-06-30T00:00:00Z",
        filename="",
        payload=b"",
    )
    metadata = {
        "contract_version": CONTRACT_VERSION,
        "clip": {"client_request_id": "metadata-request"},
        "provenance": {},
        "assets": [],
        "processing": {},
        "security": {},
    }

    stored = store.save_normalized_metadata(
        clip_id=clip.id,
        client_request_id="metadata-request",
        metadata=metadata,
    )
    by_clip_id = store.find_normalized_metadata_by_clip_id(clip.id)
    by_request_id = store.find_normalized_metadata_by_request_id("metadata-request")

    assert stored.contract_version == CONTRACT_VERSION
    assert by_clip_id is not None
    assert by_clip_id.metadata == metadata
    assert by_request_id is not None
    assert by_request_id.clip_id == clip.id


def test_init_migrates_old_clip_database_without_metadata_table(tmp_path):
    db_path = tmp_path / "perclip.sqlite3"
    tmp_path.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            create table clips (
                id integer primary key autoincrement,
                client_request_id text unique,
                source_type text not null,
                title_hint text not null,
                note text not null,
                text text not null,
                url text not null,
                mime_type text not null,
                device_name text not null,
                source_app text not null,
                captured_at text not null,
                original_path text not null,
                content_hash text not null,
                created_at text not null
            )
            """
        )
        db.execute(
            """
            insert into clips (
                client_request_id, source_type, title_hint, note, text, url, mime_type,
                device_name, source_app, captured_at, original_path, content_hash, created_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "old-request",
                "text",
                "old title",
                "",
                "old payload",
                "",
                "text/plain",
                "device",
                "app",
                "2026-06-30T00:00:00Z",
                "/old/path.txt",
                "oldhash",
                "2026-06-30T00:00:01Z",
            ),
        )

    store = ClipStore(tmp_path)
    store.init()
    old_clip = store.find_by_request_id("old-request")

    assert old_clip is not None
    assert old_clip.title == "old title"
    assert old_clip.filename == ""
    assert old_clip.size_bytes == 0
    assert old_clip.ragflow_document_id == ""
    assert old_clip.archive_status == "local"
    assert store.find_normalized_metadata_by_request_id("old-request") is None
    with sqlite3.connect(db_path) as db:
        tables = {row[0] for row in db.execute("select name from sqlite_master where type = 'table'")}
    assert "clip_metadata" in tables
