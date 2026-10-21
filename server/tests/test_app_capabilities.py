from __future__ import annotations

import json

from fastapi.testclient import TestClient

from perclip_ingest.config import Settings
from perclip_ingest.main import create_app


def client(tmp_path) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))


def test_app_capabilities_require_auth(tmp_path):
    response = client(tmp_path).get("/api/app-capabilities")

    assert response.status_code == 401


def test_app_capabilities_publish_stable_safe_contract(tmp_path):
    response = client(tmp_path).get(
        "/api/app-capabilities",
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "api_contract": "perclip.app.v1",
        "service": "perclip-ingest",
        "features": {
            "knowledge_bases": True,
            "routing": True,
            "recall": True,
            "recall_domain": True,
                "mobile_batch_status": True,
                "ingest_v1": True,
                "durable_processing": False,
                    "processing_status": True,
                        "quality_read_model": True,
                        "knowledge_list_v2": True,
                        "memory_planet": True,
                        "ragflow_capabilities": True,
            },
            "contracts": {"knowledge_list": "perclip.knowledge-list.v2"},
            "knowledge_list_bootstrap": {
                "version": 1,
                "status": "pending",
                "started_at": "",
                "completed_at": "",
                "rows_recorded": 0,
            },
        }
    serialized = json.dumps(response.json())
    for forbidden in (
        "token",
        "host",
        "path",
        "sqlite",
        "dataset_id",
        "document_id",
        "api_key",
        "environment",
    ):
        assert forbidden not in serialized.lower()
