from __future__ import annotations

import json
import sqlite3

import pytest

from perclip_ingest.runtime_audit import RuntimeAuditError, audit_runtime
from tools.audit_perclip_ragflow import build_parser, main


def _perclip_database(path):
    with sqlite3.connect(path) as db:
        db.execute(
            """
            create table clips(
                client_request_id text,
                source_type text,
                archive_status text,
                ragflow_document_id text,
                title_hint text,
                text text,
                url text,
                original_path text
            )
            """
        )
        db.executemany(
            "insert into clips values (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("request-secret-1", "text", "ready", "doc-a", "private title", "private body", "https://private.invalid/a", "/private/a"),
                ("request-secret-2", "url", "ready", "doc-a", "private title 2", "private body 2", "https://private.invalid/b", "/private/b"),
                ("request-secret-3", "file", "failed", "doc-missing", "private filename", "", "", "/private/c"),
            ],
        )


def _personal_database(path):
    with sqlite3.connect(path) as db:
        db.execute(
            """
            create table items(
                source_type text,
                status text,
                ragflow_document_id text,
                title text,
                source_url text,
                original_path text
            )
            """
        )
        db.executemany(
            "insert into items values (?, ?, ?, ?, ?, ?)",
            [
                ("text", "active", "doc-a", "legacy private", "https://private.invalid/c", "/private/d"),
                ("file", "undone", "doc-deleted", "legacy private 2", "", "/private/e"),
            ],
        )


def test_runtime_audit_reconciles_without_exposing_private_fields(tmp_path):
    perclip = tmp_path / "perclip.sqlite3"
    personal = tmp_path / "personal.sqlite3"
    snapshot = tmp_path / "ragflow.json"
    _perclip_database(perclip)
    _personal_database(personal)
    snapshot.write_text(
        json.dumps(
            {
                "documents": [
                    {"id": "doc-a", "run": "3", "chunk_count": 1, "title": "remote private title"},
                    {"id": "doc-remote", "run": "3", "chunk_count": 2, "title": "remote private title 2"},
                ],
                "chunks": [
                    {"id": "chunk-a", "document_id": "doc-a", "has_vector": True, "content": "private chunk"},
                    {"id": "chunk-b", "document_id": "doc-remote", "has_vector": True, "content": "private chunk 2"},
                    {"id": "chunk-c", "document_id": "doc-deleted", "has_vector": True, "content": "deleted private chunk"},
                ],
            }
        ),
        encoding="utf-8",
    )
    mtimes = {path: path.stat().st_mtime_ns for path in (perclip, personal, snapshot)}

    report = audit_runtime(
        perclip_db=perclip,
        personalclips_db=personal,
        ragflow_snapshot=snapshot,
    )

    assert report["perclip"]["clip_rows"] == 3
    assert report["perclip"]["unique_document_ids"] == 2
    assert report["perclip"]["duplicate_document_groups"][0]["clip_rows"] == 2
    assert report["reconciliation"] == {
        "perclip_in_ragflow": 1,
        "perclip_only": 1,
        "ragflow_not_perclip": 1,
        "personalclips_in_ragflow": 1,
        "personalclips_only": 1,
        "three_way": 1,
    }
    assert report["ragflow"]["snapshot_chunks"] == 3
    assert report["ragflow"]["database_chunk_sum"] == 3
    assert report["ragflow"]["vector_chunks"] == 3
    assert len(report["ragflow"]["orphan_chunk_documents"]) == 1
    assert report["privacy"]["content_fields_read"] is False
    assert report["database_mutated"] is False
    assert report["ragflow_mutated"] is False
    assert report["network_used"] is False

    rendered = json.dumps(report, ensure_ascii=False)
    for secret in (
        "request-secret",
        "private title",
        "private body",
        "private chunk",
        "private.invalid",
        "/private/",
        "doc-a",
        "doc-missing",
        "doc-deleted",
        "doc-remote",
    ):
        assert secret not in rendered
    assert {path: path.stat().st_mtime_ns for path in mtimes} == mtimes


def test_runtime_audit_can_run_with_only_perclip_database(tmp_path):
    perclip = tmp_path / "perclip.sqlite3"
    _perclip_database(perclip)

    report = audit_runtime(perclip_db=perclip)

    assert report["personalclips"]["item_rows"] == 0
    assert report["ragflow"]["document_rows"] == 0
    assert report["mode"] == "read_only_offline"


def test_runtime_audit_preserves_zero_run_values(tmp_path):
    perclip = tmp_path / "perclip.sqlite3"
    snapshot = tmp_path / "ragflow.json"
    _perclip_database(perclip)
    snapshot.write_text(
        json.dumps(
            {
                "documents": [
                    {"id": "int-zero", "run": 0, "chunk_count": 0},
                    {"id": "string-zero", "run": "0", "chunk_count": "0"},
                    {"id": "none", "run": None, "chunk_count": 0},
                    {"id": "missing", "chunk_count": 0},
                ],
                "chunks": [],
            }
        ),
        encoding="utf-8",
    )

    report = audit_runtime(perclip_db=perclip, ragflow_snapshot=snapshot)

    assert report["ragflow"]["run_counts"] == {"0": 2, "unknown": 2}


@pytest.mark.parametrize(
    "document",
    [
        {"id": "", "run": 0, "chunk_count": 0},
        {"id": 1, "run": 0, "chunk_count": 0},
        {"id": "doc", "run": False, "chunk_count": 0},
        {"id": "doc", "run": 0.5, "chunk_count": 0},
        {"id": "doc", "run": "", "chunk_count": 0},
        {"id": "doc", "run": 0, "chunk_count": -1},
        {"id": "doc", "run": 0, "chunk_count": 1.5},
        {"id": "doc", "run": 0, "chunk_count": True},
        {"id": "doc", "run": 0, "chunk_count": "-1"},
        {"id": "doc", "run": 0, "chunk_count": "1.0"},
        {"id": "doc", "run": 0, "chunk_count": "private-value"},
    ],
)
def test_runtime_audit_rejects_invalid_document_snapshot_rows(tmp_path, document):
    perclip = tmp_path / "perclip.sqlite3"
    snapshot = tmp_path / "ragflow.json"
    _perclip_database(perclip)
    snapshot.write_text(
        json.dumps({"documents": [document], "chunks": []}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeAuditError) as raised:
        audit_runtime(perclip_db=perclip, ragflow_snapshot=snapshot)

    assert str(raised.value) == "RAGFlow audit snapshot is invalid"
    assert "private-value" not in str(raised.value)


@pytest.mark.parametrize(
    "chunk",
    [
        {"id": "", "document_id": "doc", "has_vector": True},
        {"id": 1, "document_id": "doc", "has_vector": True},
        {"id": "chunk", "document_id": "", "has_vector": True},
        {"id": "chunk", "document_id": 1, "has_vector": True},
        {"id": "chunk", "document_id": "doc", "has_vector": "false"},
        {"id": "chunk", "document_id": "doc", "has_vector": 1},
        {"id": "chunk", "document_id": "doc", "has_vector": None},
    ],
)
def test_runtime_audit_rejects_invalid_chunk_snapshot_rows(tmp_path, chunk):
    perclip = tmp_path / "perclip.sqlite3"
    snapshot = tmp_path / "ragflow.json"
    _perclip_database(perclip)
    snapshot.write_text(
        json.dumps({"documents": [], "chunks": [chunk]}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeAuditError, match="RAGFlow audit snapshot is invalid"):
        audit_runtime(perclip_db=perclip, ragflow_snapshot=snapshot)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"documents": []},
        {"chunks": []},
        {"documents": {}, "chunks": []},
        {"documents": [], "chunks": {}},
        {"documents": ["private-document"], "chunks": []},
        {"documents": [], "chunks": ["private-chunk"]},
    ],
)
def test_runtime_audit_rejects_invalid_snapshot_shapes_without_echo(tmp_path, payload):
    perclip = tmp_path / "perclip.sqlite3"
    snapshot = tmp_path / "ragflow.json"
    _perclip_database(perclip)
    snapshot.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeAuditError) as raised:
        audit_runtime(perclip_db=perclip, ragflow_snapshot=snapshot)

    assert str(raised.value) == "RAGFlow audit snapshot is invalid"
    assert "private-document" not in str(raised.value)
    assert "private-chunk" not in str(raised.value)


@pytest.mark.parametrize("suffix", ["-wal", "-shm"])
def test_runtime_audit_rejects_nonempty_sqlite_sidecars(tmp_path, suffix):
    perclip = tmp_path / "perclip.sqlite3"
    _perclip_database(perclip)
    sidecar = tmp_path / f"perclip.sqlite3{suffix}"
    sidecar.write_bytes(b"not-an-offline-snapshot")
    database_mtime = perclip.stat().st_mtime_ns

    with pytest.raises(RuntimeAuditError) as raised:
        audit_runtime(perclip_db=perclip)

    assert "create a consistent snapshot first" in str(raised.value)
    assert perclip.stat().st_mtime_ns == database_mtime
    assert sidecar.read_bytes() == b"not-an-offline-snapshot"


def test_runtime_audit_reports_database_and_snapshot_chunk_counts_separately(tmp_path):
    perclip = tmp_path / "perclip.sqlite3"
    snapshot = tmp_path / "ragflow.json"
    _perclip_database(perclip)
    snapshot.write_text(
        json.dumps(
            {
                "documents": [{"id": "doc-a", "run": 3, "chunk_count": "7"}],
                "chunks": [
                    {"id": "chunk-a", "document_id": "doc-a", "has_vector": False}
                ],
            }
        ),
        encoding="utf-8",
    )

    report = audit_runtime(perclip_db=perclip, ragflow_snapshot=snapshot)

    assert report["ragflow"]["database_chunk_sum"] == 7
    assert report["ragflow"]["snapshot_chunks"] == 1
    assert report["ragflow"]["vector_chunks"] == 0


def test_runtime_audit_aliases_are_stable_and_never_emit_raw_ids(tmp_path):
    perclip = tmp_path / "perclip.sqlite3"
    snapshot = tmp_path / "ragflow.json"
    _perclip_database(perclip)
    snapshot.write_text(
        json.dumps(
            {
                "documents": [{"id": "doc-a", "run": 3, "chunk_count": 0}],
                "chunks": [
                    {
                        "id": "private-orphan-chunk",
                        "document_id": "private-orphan-document",
                        "has_vector": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    first = audit_runtime(perclip_db=perclip, ragflow_snapshot=snapshot)
    second = audit_runtime(perclip_db=perclip, ragflow_snapshot=snapshot)

    assert (
        first["perclip"]["duplicate_document_groups"]
        == second["perclip"]["duplicate_document_groups"]
    )
    assert (
        first["ragflow"]["orphan_chunk_documents"]
        == second["ragflow"]["orphan_chunk_documents"]
    )
    rendered = json.dumps(first)
    assert "private-orphan-document" not in rendered
    assert "private-orphan-chunk" not in rendered
    assert "doc-a" not in rendered


def test_runtime_audit_fails_closed_on_unsupported_database_schema(tmp_path):
    database = tmp_path / "unsupported.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("create table clips(id integer primary key)")

    with pytest.raises(
        RuntimeAuditError, match="audit database schema is unsupported"
    ):
        audit_runtime(perclip_db=database)


def test_runtime_audit_cli_has_no_mutation_options_or_network_calls(
    tmp_path, monkeypatch, capsys
):
    perclip = tmp_path / "perclip.sqlite3"
    _perclip_database(perclip)
    option_names = {
        option
        for action in build_parser()._actions
        for option in action.option_strings
    }
    assert option_names == {
        "-h",
        "--help",
        "--perclip-db",
        "--personalclips-db",
        "--ragflow-snapshot",
    }

    def reject_network(*_args, **_kwargs):
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr("socket.socket", reject_network)
    assert main(["--perclip-db", str(perclip)]) == 0
    output = capsys.readouterr().out
    assert '"network_used": false' in output
    assert '"database_mutated": false' in output
