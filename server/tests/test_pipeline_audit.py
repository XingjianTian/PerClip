from __future__ import annotations

import hashlib

import pytest

from perclip_ingest.config import Settings
from perclip_ingest.pipeline_audit import PipelineAuditError, audit_pipeline
from perclip_ingest.worker import PipelineWorker


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_pipeline_audit_is_read_only_and_reports_consistency_counts(tmp_path):
    PipelineWorker(
        Settings(
            data_dir=tmp_path,
            ingest_token="secret",
            processing_mode="worker",
            asset_root=tmp_path / "PersonalClips",
        )
    )
    database = tmp_path / "perclip.sqlite3"
    before = sha256(database)

    report = audit_pipeline(tmp_path)

    assert report["mode"] == "read_only"
    assert report["clips"] == 0
    assert report["accepted_without_identity"] == 0
    assert report["database_mutated"] is False
    assert report["ragflow_mutated"] is False
    assert sha256(database) == before


def test_pipeline_audit_requires_initialized_schema(tmp_path):
    with pytest.raises(PipelineAuditError, match="not found"):
        audit_pipeline(tmp_path)
