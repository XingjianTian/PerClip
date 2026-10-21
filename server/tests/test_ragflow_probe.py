from __future__ import annotations

import json
import sqlite3
from urllib.error import URLError

from fastapi.testclient import TestClient

from perclip_ingest.config import RagflowSettings, Settings
from perclip_ingest.main import create_app
from perclip_ingest.ragflow_probe import ProbeHttpResult, probe_ragflow


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer secret"}


def test_ragflow_probe_endpoint_requires_token(tmp_path):
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))

    response = api.get("/api/ragflow/probe")

    assert response.status_code == 401


def test_ragflow_probe_endpoint_returns_disabled_when_unconfigured(tmp_path):
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))

    response = api.get("/api/ragflow/probe", headers=auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["ragflow"]["configured"] is False
    assert payload["ragflow"]["status"] == "disabled"
    assert payload["ragflow"]["capabilities"] == {
        "dataset_list": False,
        "dataset_create": False,
        "document_upload": False,
        "document_meta_fields": False,
        "document_delete": False,
        "cross_dataset_move": False,
    }


def test_configured_probe_reports_reachable_dataset_list_without_leaking_key():
    class FakeClient:
        def get_json(self, base_url: str, api_key: str, path: str) -> ProbeHttpResult:
            assert base_url == "https://user:pass@example.test/ragflow?debug=true"
            assert api_key == "test-ragflow-key"
            assert path == "/api/v1/datasets"
            return ProbeHttpResult(
                status_code=200,
                json_body={"data": [{"id": "dataset-1", "name": "Research"}]},
                response_shape="dict_with_data",
            )

    result = probe_ragflow(
        RagflowSettings(
            base_url="https://user:pass@example.test/ragflow?debug=true",
            api_key="test-ragflow-key",
        ),
        client=FakeClient(),
        checked_at="2026-07-10T00:00:00+00:00",
    ).to_dict()

    assert result["ok"] is True
    assert result["ragflow"]["configured"] is True
    assert result["ragflow"]["status"] == "reachable"
    assert result["ragflow"]["base_url"] == "https://example.test/ragflow"
    assert result["ragflow"]["capabilities"]["dataset_list"] is True
    assert result["ragflow"]["capabilities"]["dataset_create"] is False
    assert result["ragflow"]["capabilities"]["document_upload"] is False
    assert "test-ragflow-key" not in json.dumps(result, ensure_ascii=False)
    assert "user:pass" not in json.dumps(result, ensure_ascii=False)


def test_configured_probe_reports_unreachable_without_leaking_key():
    class FailingClient:
        def get_json(self, base_url: str, api_key: str, path: str) -> ProbeHttpResult:
            raise URLError("network includes test-ragflow-key but must not be returned")

    result = probe_ragflow(
        RagflowSettings(base_url="http://127.0.0.1:18080", api_key="test-ragflow-key"),
        client=FailingClient(),
    ).to_dict()

    payload = json.dumps(result, ensure_ascii=False)
    assert result["ok"] is True
    assert result["ragflow"]["configured"] is True
    assert result["ragflow"]["status"] == "unreachable"
    assert result["ragflow"]["capabilities"]["dataset_list"] == "unknown"
    assert "test-ragflow-key" not in payload
    assert "authorization" not in payload.lower()


def test_configured_probe_reports_unknown_api_for_unrecognized_shape():
    class ShapeClient:
        def get_json(self, base_url: str, api_key: str, path: str) -> ProbeHttpResult:
            return ProbeHttpResult(
                status_code=200,
                json_body="ok",
                response_shape="str",
            )

    result = probe_ragflow(
        RagflowSettings(base_url="http://127.0.0.1:18080", api_key="test-ragflow-key"),
        client=ShapeClient(),
    ).to_dict()

    assert result["ragflow"]["status"] == "unknown_api"
    assert result["ragflow"]["capabilities"]["dataset_list"] is False
    assert result["ragflow"]["response_shape"] == "str"


def test_probe_endpoint_does_not_store_probe_results_or_sensitive_values(tmp_path):
    def fake_probe(settings: RagflowSettings) -> dict[str, object]:
        return {
            "ok": True,
            "ragflow": {
                "configured": True,
                "status": "reachable",
                "base_url": "http://127.0.0.1:18080",
                "capabilities": {
                    "dataset_list": True,
                    "dataset_create": False,
                    "document_upload": False,
                    "document_meta_fields": False,
                    "document_delete": False,
                    "cross_dataset_move": False,
                },
                "warnings": [],
                "checked_at": "2026-07-10T00:00:00+00:00",
                "latency_ms": 1,
                "response_shape": "dict_with_data",
            },
        }

    api = TestClient(
        create_app(
            Settings(
                data_dir=tmp_path,
                ingest_token="secret",
                ragflow=RagflowSettings(base_url="http://127.0.0.1:18080", api_key="test-ragflow-key"),
            ),
            ragflow_probe_override=fake_probe,
        )
    )

    response = api.get("/api/ragflow/probe", headers=auth_headers())

    assert response.status_code == 200
    payload = json.dumps(response.json(), ensure_ascii=False).lower()
    for forbidden in ["test-ragflow-key", "authorization", "password", "cookie"]:
        assert forbidden not in payload
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        tables = {row[0] for row in db.execute("select name from sqlite_master where type = 'table'")}
    assert "ragflow_probe_results" not in tables
