from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "server"))

from perclip_ingest.config import Settings  # noqa: E402
from perclip_ingest.main import create_app  # noqa: E402

from integrations.wechat_bridge.mapping import WechatIngestMapper
from integrations.wechat_bridge.models import WechatTextEvent


def event(text: str) -> WechatTextEvent:
    return WechatTextEvent(event_id="integration-event", text=text,
                           occurred_at=datetime.fromisoformat("2026-07-13T09:00:00+08:00"),
                           timezone="Asia/Shanghai")


def test_bridge_json_contract_against_current_create_app(tmp_path):
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="test-token")))
    headers = {"Authorization": "Bearer test-token"}
    target = api.post("/api/knowledge-bases", headers=headers, json={"name": "Temporary target"}).json()["knowledge_base"]
    mapper = WechatIngestMapper("integration", "")
    envelope = mapper.map(event("stable fixture"), target["id"]).envelope

    first = api.post("/api/ingest/v1/clips", headers=headers, json=envelope)
    replay = api.post("/api/ingest/v1/clips", headers=headers, json=envelope)
    changed = api.post("/api/ingest/v1/clips", headers=headers,
                       json=mapper.map(event("changed fixture"), target["id"]).envelope)

    assert first.status_code == replay.status_code == 200
    assert first.json()["duplicate"] is False and replay.json()["duplicate"] is True
    assert first.json()["routing"]["knowledge_base_id"] == target["id"]
    assert changed.status_code == 409
    forbidden = ("original_path", "storage_uri", "ragflow_dataset", "ragflow_document")
    assert not any(item in first.text.lower() for item in forbidden)
    receipt = api.get(f"/api/ingest/v1/receipts/{first.json()['receipt_id']}", headers=headers)
    assert receipt.status_code == 200
    assert receipt.json()["routing"]["knowledge_base_id"] == target["id"]
