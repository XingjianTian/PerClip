from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from perclip_ingest.config import Settings
from perclip_ingest.main import create_app


HEADERS = {"Authorization": "Bearer secret"}


def _client(data_dir) -> TestClient:
    return TestClient(
        create_app(Settings(data_dir=data_dir, ingest_token="secret", processing_mode="worker")),
    )


def test_mobile_save_is_immediately_searchable_idempotent_and_restart_durable(tmp_path):
    client = _client(tmp_path)
    request = {
        "source_type": "text",
        "client_request_id": "stage27:save-to-search",
        "title_hint": "Stage 27 自动可检索标题",
        "text": "最小 Core Memory 正文",
        "routing_mode": "default_only",
    }

    first = client.post("/api/mobile-clips", headers=HEADERS, data=request)
    replay = client.post("/api/mobile-clips", headers=HEADERS, data=request)

    assert first.status_code == replay.status_code == 200
    assert first.json()["duplicate"] is False
    assert replay.json()["duplicate"] is True
    assert replay.json()["clip_id"] == first.json()["clip_id"]

    found = client.get(
        "/api/knowledge/clips",
        headers=HEADERS,
        params={"query": "自动可检索"},
    )
    assert found.status_code == 200, found.text
    payload = found.json()
    assert payload["summary"]["matching_count"] == 1
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["title"] == request["title_hint"]
    assert item["correlation_identity"] == request["client_request_id"]

    restarted = _client(tmp_path)
    persisted = restarted.get(
        "/api/knowledge/clips",
        headers=HEADERS,
        params={"query": "自动可检索"},
    ).json()
    assert persisted["summary"]["matching_count"] == 1
    assert persisted["items"][0]["public_clip_id"] == item["public_clip_id"]

    detail = restarted.get(
        f"/api/clips/{item['public_clip_id']}/quality",
        headers=HEADERS,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["quality_read"]["active_content"]["title"] == request["title_hint"]
    assert detail.json()["quality_read"]["active_content"]["original_text"] == request["text"]

    with sqlite3.connect(tmp_path / "perclip.sqlite3") as database:
        assert database.execute(
            "select count(*) from clips where client_request_id=?",
            (request["client_request_id"],),
        ).fetchone()[0] == 1
