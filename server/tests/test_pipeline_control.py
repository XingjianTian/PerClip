from __future__ import annotations

import pytest

from perclip_ingest.pipeline_control import main
from perclip_ingest.pipeline_store import PipelineStore
from perclip_ingest.storage import ClipStore


def configure_local_control(monkeypatch, tmp_path) -> None:
    ClipStore(tmp_path).init()
    PipelineStore(tmp_path).init()
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "unit-control-secret")
    monkeypatch.setenv("PERCLIP_PROCESSING_MODE", "worker")
    monkeypatch.delenv("RAGFLOW_BASE_URL", raising=False)
    monkeypatch.delenv("RAGFLOW_API_KEY", raising=False)
    monkeypatch.delenv("PERCLIP_ENABLE_REAL_RAGFLOW_SYNC", raising=False)
    monkeypatch.delenv("PERCLIP_RAGFLOW_SYNC_ALLOW_DATASET_IDS", raising=False)


def test_retry_cli_requires_exact_confirmation(monkeypatch, tmp_path):
    configure_local_control(monkeypatch, tmp_path)

    with pytest.raises(SystemExit) as error:
        main(
            [
                "retry-failed",
                "--job-id", "1",
                "--request-id", "retry-cli-1",
                "--confirm", "wrong",
            ]
        )

    assert error.value.code == 2


def test_real_sync_promotion_cli_requires_all_runtime_safety_gates(monkeypatch, tmp_path):
    configure_local_control(monkeypatch, tmp_path)

    with pytest.raises(SystemExit) as error:
        main(
            [
                "promote-real-sync",
                "--clip-id", "1",
                "--request-id", "promote-cli-1",
                "--confirm", "PROMOTE_PLANNED_RAGFLOW_REAL_SYNC",
            ]
        )

    assert error.value.code == 2
