from __future__ import annotations

from pathlib import Path
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from perclip_ingest.metadata_contract import CONTRACT_VERSION
from perclip_ingest.config import RagflowSettings, Settings
from perclip_ingest.main import classify_content_length, create_app
from perclip_ingest.pipeline_store import PipelineStore
from perclip_ingest.storage import ClipStore


class FakeArchiver:
    def __init__(self, ok=True):
        self.ok = ok
        self.payloads = []

    async def archive(self, payload):
        self.payloads.append(payload)
        if not self.ok:
            return type(
                "Outcome",
                (),
                {
                    "ok": False,
                    "title": "",
                    "original_path": "",
                    "ragflow_document_id": "",
                    "message": "fake archive failure",
                },
            )()
        return type(
            "Outcome",
            (),
            {
                "ok": True,
                "title": payload.title_hint or payload.filename or "fake title",
                "original_path": "/personalclips/fake.md",
                "ragflow_document_id": "doc-fake",
                "message": "ok",
            },
        )()


def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, ingest_token="secret"))
    return TestClient(app)


def metadata_for_request(tmp_path, client_request_id: str) -> dict[str, object]:
    metadata = ClipStore(tmp_path).find_normalized_metadata_by_request_id(client_request_id)
    assert metadata is not None
    return metadata.metadata


def route_decisions_for_request(tmp_path, client_request_id: str) -> list[dict[str, object]]:
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """
            select * from clip_route_decisions
            where client_request_id = ?
            order by id asc
            """,
            (client_request_id,),
        ).fetchall()
    decisions = []
    for row in rows:
        payload = dict(row)
        payload["matched_rule_ids"] = json.loads(payload.pop("matched_rule_ids_json"))
        decisions.append(payload)
    return decisions


def legacy_response_keys() -> set[str]:
    return {
        "ok",
        "duplicate",
        "title",
        "platform",
        "clip_id",
        "client_request_id",
        "content_hash",
        "filename",
        "size_bytes",
        "ragflow_document_id",
        "archive_status",
        "capture",
    }


def test_health(tmp_path):
    response = client(tmp_path).get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["service"] == "perclip-ingest"
    assert response.json()["archive_mode"] == "local"


def test_verify_mobile_token(tmp_path):
    response = client(tmp_path).get(
        "/api/mobile-clips/verify",
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["auth"] == "mobile_ingest_token"


def test_verify_mobile_token_rejects_bad_token(tmp_path):
    response = client(tmp_path).get(
        "/api/mobile-clips/verify",
        headers={"Authorization": "Bearer wrong"},
    )

    assert response.status_code == 401


def test_verify_mobile_token_rejects_bad_authorization_scheme(tmp_path):
    response = client(tmp_path).get(
        "/api/mobile-clips/verify",
        headers={"Authorization": "Token secret"},
    )

    assert response.status_code == 401


def test_rejects_bad_token(tmp_path):
    response = client(tmp_path).post("/api/mobile-clips", data={"source_type": "text", "text": "hello"})
    assert response.status_code == 401


def test_accepts_text_clip(tmp_path):
    response = client(tmp_path).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={
            "source_type": "text",
            "title_hint": "测试文字",
            "text": "PerClip text payload",
            "client_request_id": "req-1",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["title"] == "测试文字"
    assert payload["duplicate"] is False
    assert payload["archive_status"] == "local"
    assert payload["ragflow_document_id"] == ""
    assert payload["filename"].endswith("_text.txt")
    assert payload["size_bytes"] == len("PerClip text payload".encode())
    assert (tmp_path / "perclip.sqlite3").exists()
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        row = db.execute("select device_name, source_app, filename, size_bytes from clips").fetchone()
    assert row[2] == payload["filename"]
    assert row[3] == payload["size_bytes"]
    metadata = metadata_for_request(tmp_path, "req-1")
    assert metadata["contract_version"] == CONTRACT_VERSION
    assert metadata["clip"]["source_type"] == "text"
    assert metadata["clip"]["title_hint"] == "测试文字"
    assert metadata["assets"][0]["text"] == "PerClip text payload"
    assert "original_path" not in payload
    assert payload["client_request_id"] == "req-1"
    assert metadata["routing"]["decision_type"] == "default"
    assert metadata["routing"]["knowledge_base_name"] == "个人收藏"


def test_deduplicates_client_request_id(tmp_path):
    headers = {"Authorization": "Bearer secret"}
    data = {
        "source_type": "url",
        "title_hint": "链接",
        "url": "https://example.com",
        "client_request_id": "same-request",
    }
    first = client(tmp_path).post("/api/mobile-clips", headers=headers, data=data)
    second = client(tmp_path).post("/api/mobile-clips", headers=headers, data=data)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert first.json()["clip_id"] == second.json()["clip_id"]
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        metadata_count = db.execute("select count(*) from clip_metadata").fetchone()[0]
    assert metadata_count == 1


def test_duplicate_request_backfills_missing_normalized_metadata(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    first = api.post(
        "/api/mobile-clips",
        headers=headers,
        data={
            "source_type": "text",
            "title_hint": "Original",
            "text": "original text",
            "client_request_id": "missing-metadata",
            "device_name": "Pixel",
            "source_app": "Reader",
        },
    )
    assert first.status_code == 200
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.execute("delete from clip_metadata where client_request_id = ?", ("missing-metadata",))
        db.commit()

    second = api.post(
        "/api/mobile-clips",
        headers=headers,
        data={
            "source_type": "text",
            "title_hint": "Changed",
            "text": "changed text",
            "client_request_id": "missing-metadata",
        },
    )

    assert second.status_code == 200
    payload = second.json()
    assert payload["duplicate"] is True
    assert payload["title"] == "Original"
    assert set(payload) == legacy_response_keys()
    metadata = metadata_for_request(tmp_path, "missing-metadata")
    assert metadata["clip"]["title_hint"] == "Original"
    assert metadata["clip"]["text"] == "original text"
    assert metadata["provenance"]["launcher_id"] == "Pixel"
    assert metadata["provenance"]["source_app"] == "Reader"
    assert metadata["assets"][0]["text"] == "original text"
    assert "original_path" not in payload
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        metadata_count = db.execute("select count(*) from clip_metadata").fetchone()[0]
    assert metadata_count == 1


def test_duplicate_request_with_existing_metadata_does_not_rewrite_metadata(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    data = {
        "source_type": "url",
        "title_hint": "Existing",
        "url": "https://example.com/existing",
        "client_request_id": "existing-metadata",
    }
    first = api.post("/api/mobile-clips", headers=headers, data=data)
    assert first.status_code == 200
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        before = db.execute(
            "select created_at, metadata_json from clip_metadata where client_request_id = ?",
            ("existing-metadata",),
        ).fetchone()

    second = api.post("/api/mobile-clips", headers=headers, data=data | {"title_hint": "Changed"})

    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        metadata_count = db.execute("select count(*) from clip_metadata").fetchone()[0]
        after = db.execute(
            "select created_at, metadata_json from clip_metadata where client_request_id = ?",
            ("existing-metadata",),
        ).fetchone()
    assert metadata_count == 1
    assert after == before


def test_mobile_clip_without_target_routes_to_default_knowledge_base(tmp_path):
    api = client(tmp_path)
    response = api.post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={
            "source_type": "text",
            "title_hint": "Default route",
            "text": "default body",
            "client_request_id": "default-route",
        },
    )

    assert response.status_code == 200
    assert set(response.json()) == legacy_response_keys()
    decisions = route_decisions_for_request(tmp_path, "default-route")
    assert len(decisions) == 1
    assert decisions[0]["knowledge_base_id"] == "kb_default"
    assert decisions[0]["decision_type"] == "default"
    assert decisions[0]["manual_override"] == 0
    assert decisions[0]["ragflow_dataset_id"] == ""
    metadata = metadata_for_request(tmp_path, "default-route")
    assert metadata["routing"]["knowledge_base_id"] == "kb_default"
    assert metadata["routing"]["knowledge_base_name"] == "个人收藏"
    assert metadata["routing"]["manual_override"] is False


def test_mobile_clip_with_active_target_writes_manual_route_decision(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    target = api.post(
        "/api/knowledge-bases",
        headers=headers,
        json={
            "name": "Teaching",
            "ragflow_dataset_id": "dataset-teaching",
            "ragflow_dataset_name": "Teaching dataset",
        },
    ).json()["knowledge_base"]

    response = api.post(
        "/api/mobile-clips",
        headers=headers,
        data={
            "source_type": "text",
            "title_hint": "Manual",
            "text": "manual body",
            "client_request_id": "manual-route",
            "target_knowledge_base_id": target["id"],
        },
    )

    assert response.status_code == 200
    assert set(response.json()) == legacy_response_keys()
    decisions = route_decisions_for_request(tmp_path, "manual-route")
    assert len(decisions) == 1
    assert decisions[0]["knowledge_base_id"] == target["id"]
    assert decisions[0]["ragflow_dataset_id"] == "dataset-teaching"
    assert decisions[0]["decision_type"] == "manual"
    assert decisions[0]["manual_override"] == 1
    assert decisions[0]["matched_rule_id"] == ""
    assert decisions[0]["matched_rule_ids"] == []
    metadata = metadata_for_request(tmp_path, "manual-route")
    assert metadata["routing"] == {
        "knowledge_base_id": target["id"],
        "knowledge_base_name": "Teaching",
        "ragflow_dataset_id": "dataset-teaching",
        "decision_type": "manual",
        "matched_rule_ids": [],
        "reason": decisions[0]["reason"],
        "manual_override": True,
        "routed_at": decisions[0]["created_at"],
    }


def test_mobile_clip_rejects_archived_or_missing_target_before_save(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    archived = api.post("/api/knowledge-bases", headers=headers, json={"name": "Archived"}).json()["knowledge_base"]
    assert api.post(f"/api/knowledge-bases/{archived['id']}/archive", headers=headers).status_code == 200

    archived_response = api.post(
        "/api/mobile-clips",
        headers=headers,
        data={
            "source_type": "text",
            "text": "archived target",
            "client_request_id": "archived-target",
            "target_knowledge_base_id": archived["id"],
        },
    )
    missing_response = api.post(
        "/api/mobile-clips",
        headers=headers,
        data={
            "source_type": "text",
            "text": "missing target",
            "client_request_id": "missing-target",
            "target_knowledge_base_id": "kb_missing",
        },
    )

    assert archived_response.status_code == 409
    assert missing_response.status_code == 404
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        clip_count = db.execute(
            "select count(*) from clips where client_request_id in (?, ?)",
            ("archived-target", "missing-target"),
        ).fetchone()[0]
        decision_count = db.execute(
            "select count(*) from clip_route_decisions where client_request_id in (?, ?)",
            ("archived-target", "missing-target"),
        ).fetchone()[0]
    assert clip_count == 0
    assert decision_count == 0


def test_mobile_clip_source_app_rule_writes_rule_decision(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    target = api.post("/api/knowledge-bases", headers=headers, json={"name": "Browser"}).json()["knowledge_base"]
    rule = api.post(
        "/api/routing-rules",
        headers=headers,
        json={
            "name": "Chrome",
            "rule_type": "source_app",
            "pattern": "Chrome",
            "target_knowledge_base_id": target["id"],
        },
    ).json()["routing_rule"]

    response = api.post(
        "/api/mobile-clips",
        headers=headers,
        data={
            "source_type": "url",
            "title_hint": "Chrome page",
            "url": "https://example.com",
            "source_app": "Chrome",
            "client_request_id": "source-app-rule",
        },
    )

    assert response.status_code == 200
    decision = route_decisions_for_request(tmp_path, "source-app-rule")[0]
    assert decision["knowledge_base_id"] == target["id"]
    assert decision["decision_type"] == "rule"
    assert decision["matched_rule_id"] == rule["id"]
    assert decision["matched_rule_ids"] == [rule["id"]]
    assert decision["manual_override"] == 0
    assert "Chrome" in decision["reason"]


def test_mobile_clip_default_only_uses_capture_time_default_and_bypasses_historical_rule(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    knowledge_bases = api.get("/api/knowledge-bases", headers=headers).json()["knowledge_bases"]
    assert any(item["is_default"] for item in knowledge_bases)
    target = api.post("/api/knowledge-bases", headers=headers, json={"name": "Historical rule"}).json()["knowledge_base"]
    capture_time_default = api.post(
        "/api/knowledge-bases",
        headers=headers,
        json={"name": "Capture-time default"},
    ).json()["knowledge_base"]
    api.post(
        "/api/routing-rules",
        headers=headers,
        json={
            "name": "Chrome",
            "rule_type": "source_app",
            "pattern": "Chrome",
            "target_knowledge_base_id": target["id"],
        },
    )

    response = api.post(
        "/api/mobile-clips",
        headers=headers,
        data={
            "source_type": "url",
            "url": "https://example.com",
            "source_app": "Chrome",
            "client_request_id": "default-only-mobile",
            "routing_mode": "default_only",
            "target_knowledge_base_id": capture_time_default["id"],
        },
    )

    assert response.status_code == 200
    decision = route_decisions_for_request(tmp_path, "default-only-mobile")[0]
    assert decision["knowledge_base_id"] == capture_time_default["id"]
    assert decision["decision_type"] == "default"
    assert decision["matched_rule_ids"] == []
    assert decision["manual_override"] == 0
    assert "capture-time default" in decision["reason"]


@pytest.mark.parametrize("unavailable_kind", ["archived", "deleted", "unknown"])
def test_mobile_clip_default_only_unavailable_capture_target_falls_back(tmp_path, unavailable_kind):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    knowledge_bases = api.get("/api/knowledge-bases", headers=headers).json()["knowledge_bases"]
    current_default = next(item for item in knowledge_bases if item["is_default"])
    old_default = api.post(
        "/api/knowledge-bases",
        headers=headers,
        json={"name": f"Old default {unavailable_kind}"},
    ).json()["knowledge_base"]
    if unavailable_kind == "archived":
        assert api.post(f"/api/knowledge-bases/{old_default['id']}/archive", headers=headers).status_code == 200
        target_id = old_default["id"]
    elif unavailable_kind == "deleted":
        assert api.delete(f"/api/knowledge-bases/{old_default['id']}", headers=headers).status_code == 200
        target_id = old_default["id"]
    else:
        target_id = "kb_unknown"

    response = api.post(
        "/api/mobile-clips",
        headers=headers,
        data={
            "source_type": "text",
            "text": "fallback body",
            "client_request_id": f"default-only-{unavailable_kind}",
            "routing_mode": "default_only",
            "target_knowledge_base_id": target_id,
        },
    )

    assert response.status_code == 200
    decision = route_decisions_for_request(tmp_path, f"default-only-{unavailable_kind}")[0]
    assert decision["knowledge_base_id"] == current_default["id"]
    assert decision["decision_type"] == "default"
    assert decision["manual_override"] == 0
    assert decision["matched_rule_ids"] == []
    assert "unavailable" in decision["reason"]


def test_mobile_clip_default_only_duplicate_keeps_first_route_after_default_change(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    knowledge_bases = api.get("/api/knowledge-bases", headers=headers).json()["knowledge_bases"]
    capture_time_default = next(item for item in knowledge_bases if item["is_default"])
    next_default = api.post(
        "/api/knowledge-bases",
        headers=headers,
        json={"name": "Next default"},
    ).json()["knowledge_base"]
    data = {
        "source_type": "text",
        "text": "stable route body",
        "client_request_id": "default-only-stable-replay",
        "routing_mode": "default_only",
        "target_knowledge_base_id": capture_time_default["id"],
    }

    first = api.post("/api/mobile-clips", headers=headers, data=data)
    assert api.post(f"/api/knowledge-bases/{next_default['id']}/set-default", headers=headers).status_code == 200
    assert api.post(f"/api/knowledge-bases/{capture_time_default['id']}/archive", headers=headers).status_code == 200
    second = api.post("/api/mobile-clips", headers=headers, data=data)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    decisions = route_decisions_for_request(tmp_path, "default-only-stable-replay")
    assert len(decisions) == 1
    assert decisions[0]["knowledge_base_id"] == capture_time_default["id"]


def test_mobile_clip_rejects_unknown_routing_mode(tmp_path):
    response = client(tmp_path).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={
            "source_type": "text",
            "text": "hello",
            "client_request_id": "unknown-routing-mode",
            "routing_mode": "future_mode",
        },
    )

    assert response.status_code == 422


def test_mobile_clip_multi_rule_match_persists_all_rule_ids(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    domain_target = api.post("/api/knowledge-bases", headers=headers, json={"name": "GitHub"}).json()["knowledge_base"]
    pdf_target = api.post("/api/knowledge-bases", headers=headers, json={"name": "PDF"}).json()["knowledge_base"]
    keyword_target = api.post("/api/knowledge-bases", headers=headers, json={"name": "PerClip"}).json()["knowledge_base"]
    domain_rule = api.post(
        "/api/routing-rules",
        headers=headers,
        json={
            "name": "GitHub domain",
            "rule_type": "url_domain",
            "pattern": "github.com",
            "target_knowledge_base_id": domain_target["id"],
        },
    ).json()["routing_rule"]
    mime_rule = api.post(
        "/api/routing-rules",
        headers=headers,
        json={
            "name": "PDF mime",
            "rule_type": "mime_type",
            "pattern": "application/pdf",
            "target_knowledge_base_id": pdf_target["id"],
        },
    ).json()["routing_rule"]
    keyword_rule = api.post(
        "/api/routing-rules",
        headers=headers,
        json={
            "name": "PerClip keyword",
            "rule_type": "keyword",
            "pattern": "PerClip",
            "target_knowledge_base_id": keyword_target["id"],
        },
    ).json()["routing_rule"]

    response = api.post(
        "/api/mobile-clips",
        headers=headers,
        data={
            "source_type": "file",
            "title_hint": "PerClip design",
            "url": "https://github.com/example/design.pdf",
            "client_request_id": "multi-rule",
        },
        files={"file": ("design.pdf", b"%PDF sample", "application/pdf")},
    )

    assert response.status_code == 200
    decision = route_decisions_for_request(tmp_path, "multi-rule")[0]
    assert decision["knowledge_base_id"] == domain_target["id"]
    assert decision["matched_rule_id"] == domain_rule["id"]
    assert decision["matched_rule_ids"] == [domain_rule["id"], mime_rule["id"], keyword_rule["id"]]
    metadata = metadata_for_request(tmp_path, "multi-rule")
    assert metadata["routing"]["matched_rule_ids"] == [domain_rule["id"], mime_rule["id"], keyword_rule["id"]]


def test_mobile_clip_duplicate_reuses_route_decision_and_legacy_response(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    target = api.post("/api/knowledge-bases", headers=headers, json={"name": "Manual target"}).json()["knowledge_base"]
    data = {
        "source_type": "text",
        "title_hint": "Duplicate",
        "text": "duplicate body",
        "client_request_id": "duplicate-route",
        "target_knowledge_base_id": target["id"],
    }

    first = api.post("/api/mobile-clips", headers=headers, data=data)
    archived = api.post(f"/api/knowledge-bases/{target['id']}/archive", headers=headers)
    assert archived.status_code == 200
    second = api.post("/api/mobile-clips", headers=headers, data=data)

    assert first.status_code == 200
    assert second.status_code == 200
    assert set(second.json()) == legacy_response_keys()
    assert second.json()["duplicate"] is True
    decisions = route_decisions_for_request(tmp_path, "duplicate-route")
    assert len(decisions) == 1
    assert decisions[0]["decision_type"] == "manual"
    assert decisions[0]["knowledge_base_id"] == target["id"]


def test_mobile_clip_route_decision_and_metadata_omit_known_server_secrets(tmp_path):
    secret_values = [
        "secret",
        "change-me-server-side-ragflow-key",
        "change-me-baidu-api-key",
        "change-me-baidu-secret-key",
        "nas-password",
        "ssh-password",
        "cloud-secret",
        "social-secret",
    ]
    response = client(tmp_path).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={
            "source_type": "text",
            "title_hint": "Safe routing",
            "text": "safe routing text",
            "client_request_id": "safe-routing",
        },
    )

    assert response.status_code == 200
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        decision_row = db.execute(
            """
            select knowledge_base_id, ragflow_dataset_id, decision_type, matched_rule_id,
                   matched_rule_ids_json, reason
            from clip_route_decisions
            where client_request_id = ?
            """,
            ("safe-routing",),
        )
        decision_json = json.dumps(list(decision_row.fetchone()), ensure_ascii=False)
        metadata_json = db.execute(
            "select metadata_json from clip_metadata where client_request_id = ?",
            ("safe-routing",),
        ).fetchone()[0]
    for secret_value in secret_values:
        assert secret_value not in decision_json
        assert secret_value not in metadata_json


def test_mobile_clip_route_decision_preserves_existing_archive_fields(tmp_path):
    archiver = FakeArchiver()
    app = create_app(Settings(data_dir=tmp_path, ingest_token="secret"), archiver_override=archiver)
    response = TestClient(app).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={
            "source_type": "text",
            "title_hint": "Archive routed",
            "text": "hello",
            "client_request_id": "archive-routed",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "original_path" not in payload
    assert payload["ragflow_document_id"] == ""
    assert payload["archive_status"] == "clip_to_ragflow"
    decision = route_decisions_for_request(tmp_path, "archive-routed")[0]
    assert decision["decision_type"] == "default"
    metadata = metadata_for_request(tmp_path, "archive-routed")
    assert metadata["processing"]["original_path"] == "/personalclips/fake.md"
    assert metadata["processing"]["ragflow_document_id"] == "doc-fake"
    assert metadata["processing"]["archive_status"] == "clip_to_ragflow"
    assert metadata["routing"]["knowledge_base_id"] == "kb_default"


def test_move_clip_requires_token(tmp_path):
    response = client(tmp_path).post(
        "/api/clips/1/move",
        json={"target_knowledge_base_id": "kb_default", "reason": "user moved from Clip Library detail"},
    )

    assert response.status_code == 401


def test_move_clip_rejects_missing_clip_or_target_before_metadata_update(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    missing_clip = api.post(
        "/api/clips/999/move",
        headers=headers,
        json={"target_knowledge_base_id": "kb_default", "reason": "user moved from Clip Library detail"},
    )
    uploaded = api.post(
        "/api/mobile-clips",
        headers=headers,
        data={
            "source_type": "text",
            "title_hint": "Move source",
            "text": "move body",
            "client_request_id": "move-missing-target",
        },
    )
    assert uploaded.status_code == 200
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        clip_id = db.execute(
            "select id from clips where client_request_id = ?",
            ("move-missing-target",),
        ).fetchone()[0]
    missing_target = api.post(
        f"/api/clips/{clip_id}/move",
        headers=headers,
        json={"target_knowledge_base_id": "kb_missing", "reason": "user moved from Clip Library detail"},
    )

    assert missing_clip.status_code == 404
    assert missing_target.status_code == 404
    decisions = route_decisions_for_request(tmp_path, "move-missing-target")
    assert len(decisions) == 1
    assert decisions[0]["knowledge_base_id"] == "kb_default"


def test_move_clip_rejects_archived_target(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    archived = api.post("/api/knowledge-bases", headers=headers, json={"name": "Move archived"}).json()["knowledge_base"]
    assert api.post(f"/api/knowledge-bases/{archived['id']}/archive", headers=headers).status_code == 200
    uploaded = api.post(
        "/api/mobile-clips",
        headers=headers,
        data={
            "source_type": "text",
            "title_hint": "Move archived source",
            "text": "move body",
            "client_request_id": "move-archived-target",
        },
    )
    assert uploaded.status_code == 200
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        clip_id = db.execute(
            "select id from clips where client_request_id = ?",
            ("move-archived-target",),
        ).fetchone()[0]

    response = api.post(
        f"/api/clips/{clip_id}/move",
        headers=headers,
        json={"target_knowledge_base_id": archived["id"], "reason": "user moved from Clip Library detail"},
    )

    assert response.status_code == 409
    decisions = route_decisions_for_request(tmp_path, "move-archived-target")
    assert len(decisions) == 1
    assert decisions[0]["knowledge_base_id"] == "kb_default"


def test_move_clip_appends_manual_decision_updates_metadata_and_preserves_archive_fields(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    source = api.post(
        "/api/knowledge-bases",
        headers=headers,
        json={
            "name": "Source KB",
            "ragflow_dataset_id": "dataset-source",
            "ragflow_dataset_name": "Source dataset",
        },
    ).json()["knowledge_base"]
    target = api.post(
        "/api/knowledge-bases",
        headers=headers,
        json={
            "name": "Teaching",
            "ragflow_dataset_id": "dataset-teaching",
            "ragflow_dataset_name": "Teaching dataset",
        },
    ).json()["knowledge_base"]
    uploaded = api.post(
        "/api/mobile-clips",
        headers=headers,
        data={
            "source_type": "text",
            "title_hint": "Move me",
            "text": "move body",
            "client_request_id": "move-success",
            "target_knowledge_base_id": source["id"],
        },
    )
    assert uploaded.status_code == 200
    before_metadata = metadata_for_request(tmp_path, "move-success")
    before_processing = dict(before_metadata["processing"])
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        clip_id = db.execute(
            "select id from clips where client_request_id = ?",
            ("move-success",),
        ).fetchone()[0]

    response = api.post(
        f"/api/clips/{clip_id}/move",
        headers=headers,
        json={"target_knowledge_base_id": target["id"], "reason": "user moved from Clip Library detail"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["reindex_required"] is True
    assert payload["remote_document_changed"] is False
    decision = payload["route_decision"]
    assert decision["clip_id"] == str(clip_id)
    assert decision["client_request_id"] == "move-success"
    assert decision["knowledge_base_id"] == target["id"]
    assert decision["ragflow_dataset_id"] == "dataset-teaching"
    assert decision["decision_type"] == "manual"
    assert decision["matched_rule_id"] == ""
    assert decision["matched_rule_ids"] == []
    assert decision["confidence"] == 1.0
    assert decision["manual_override"] is True
    assert decision["reason"] == 'manual move: user moved clip to "Teaching"'
    assert decision["previous_knowledge_base_id"] == source["id"]
    assert decision["reindex_status"] == "required"
    assert decision["lineage_id"] == f"clip:{clip_id}"

    decisions = route_decisions_for_request(tmp_path, "move-success")
    assert len(decisions) == 2
    assert decisions[0]["knowledge_base_id"] == source["id"]
    assert decisions[1]["knowledge_base_id"] == target["id"]
    assert decisions[1]["previous_knowledge_base_id"] == source["id"]
    assert decisions[1]["reindex_status"] == "required"
    assert decisions[1]["lineage_id"] == f"clip:{clip_id}"

    metadata = metadata_for_request(tmp_path, "move-success")
    assert metadata["routing"]["knowledge_base_id"] == target["id"]
    assert metadata["routing"]["knowledge_base_name"] == "Teaching"
    assert metadata["routing"]["ragflow_dataset_id"] == "dataset-teaching"
    assert metadata["routing"]["decision_type"] == "manual"
    assert metadata["routing"]["matched_rule_ids"] == []
    assert metadata["routing"]["reason"] == decision["reason"]
    assert metadata["routing"]["manual_override"] is True
    assert metadata["routing"]["routed_at"] == decision["created_at"]
    assert metadata["routing"]["previous_knowledge_base_id"] == source["id"]
    assert metadata["routing"]["reindex_status"] == "required"
    assert metadata["routing"]["lineage_id"] == f"clip:{clip_id}"
    assert metadata["processing"] == before_processing


def test_move_clip_backfills_metadata_routing_when_missing(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    target = api.post("/api/knowledge-bases", headers=headers, json={"name": "Backfilled"}).json()["knowledge_base"]
    uploaded = api.post(
        "/api/mobile-clips",
        headers=headers,
        data={
            "source_type": "text",
            "title_hint": "Backfill route",
            "text": "move body",
            "client_request_id": "move-backfill",
        },
    )
    assert uploaded.status_code == 200
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        clip_id = db.execute(
            "select id from clips where client_request_id = ?",
            ("move-backfill",),
        ).fetchone()[0]
        metadata_json = db.execute(
            "select metadata_json from clip_metadata where client_request_id = ?",
            ("move-backfill",),
        ).fetchone()[0]
        metadata = json.loads(metadata_json)
        metadata.pop("routing", None)
        db.execute(
            "update clip_metadata set metadata_json = ? where client_request_id = ?",
            (json.dumps(metadata), "move-backfill"),
        )
        db.commit()

    response = api.post(
        f"/api/clips/{clip_id}/move",
        headers=headers,
        json={"target_knowledge_base_id": target["id"], "reason": "user moved from Clip Library detail"},
    )

    assert response.status_code == 200
    metadata = metadata_for_request(tmp_path, "move-backfill")
    assert metadata["clip"]["title_hint"] == "Backfill route"
    assert metadata["routing"]["knowledge_base_id"] == target["id"]
    assert metadata["routing"]["reindex_status"] == "required"


def test_move_clip_accepts_android_clip_id_prefix_without_changing_legacy_upload_response(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    target = api.post("/api/knowledge-bases", headers=headers, json={"name": "Android target"}).json()["knowledge_base"]
    response = api.post(
        "/api/mobile-clips",
        headers=headers,
        data={
            "source_type": "text",
            "title_hint": "Android local",
            "text": "body",
            "client_request_id": "android-local-clip:",
        },
    )
    assert response.status_code == 200
    assert set(response.json()) == legacy_response_keys()

    move_response = api.post(
        "/api/clips/android-local-clip/move",
        headers=headers,
        json={"target_knowledge_base_id": target["id"], "reason": "user moved from Clip Library detail"},
    )

    assert move_response.status_code == 200
    assert move_response.json()["route_decision"]["client_request_id"] == "android-local-clip:"
    assert move_response.json()["route_decision"]["knowledge_base_id"] == target["id"]


def test_move_clip_rejects_ambiguous_android_clip_id_prefix_without_new_decision(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    target = api.post("/api/knowledge-bases", headers=headers, json={"name": "Multipart target"}).json()["knowledge_base"]
    for request_id, filename in [
        ("multi-local-clip:1:fileA.txt", "fileA.txt"),
        ("multi-local-clip:2:fileB.txt", "fileB.txt"),
    ]:
        response = api.post(
            "/api/mobile-clips",
            headers=headers,
            data={
                "source_type": "file",
                "title_hint": filename,
                "client_request_id": request_id,
            },
            files={"file": (filename, b"part", "text/plain")},
        )
        assert response.status_code == 200

    before_counts = [
        len(route_decisions_for_request(tmp_path, "multi-local-clip:1:fileA.txt")),
        len(route_decisions_for_request(tmp_path, "multi-local-clip:2:fileB.txt")),
    ]
    move_response = api.post(
        "/api/clips/multi-local-clip/move",
        headers=headers,
        json={"target_knowledge_base_id": target["id"], "reason": "user moved from Clip Library detail"},
    )
    after_counts = [
        len(route_decisions_for_request(tmp_path, "multi-local-clip:1:fileA.txt")),
        len(route_decisions_for_request(tmp_path, "multi-local-clip:2:fileB.txt")),
    ]

    assert move_response.status_code == 409
    assert move_response.json()["detail"] == "multiple clip parts require batch move"
    assert after_counts == before_counts


def test_move_clip_allows_numeric_or_exact_client_request_id_for_single_part(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    numeric_target = api.post("/api/knowledge-bases", headers=headers, json={"name": "Numeric target"}).json()["knowledge_base"]
    exact_target = api.post("/api/knowledge-bases", headers=headers, json={"name": "Exact target"}).json()["knowledge_base"]
    for request_id, filename in [
        ("exact-local-clip:1:fileA.txt", "fileA.txt"),
        ("exact-local-clip:2:fileB.txt", "fileB.txt"),
    ]:
        response = api.post(
            "/api/mobile-clips",
            headers=headers,
            data={
                "source_type": "file",
                "title_hint": filename,
                "client_request_id": request_id,
            },
            files={"file": (filename, b"part", "text/plain")},
        )
        assert response.status_code == 200
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        numeric_clip_id = db.execute(
            "select id from clips where client_request_id = ?",
            ("exact-local-clip:1:fileA.txt",),
        ).fetchone()[0]

    numeric_move = api.post(
        f"/api/clips/{numeric_clip_id}/move",
        headers=headers,
        json={"target_knowledge_base_id": numeric_target["id"], "reason": "user moved from Clip Library detail"},
    )
    exact_move = api.post(
        "/api/clips/exact-local-clip:2:fileB.txt/move",
        headers=headers,
        json={"target_knowledge_base_id": exact_target["id"], "reason": "user moved from Clip Library detail"},
    )

    assert numeric_move.status_code == 200
    assert numeric_move.json()["route_decision"]["knowledge_base_id"] == numeric_target["id"]
    assert exact_move.status_code == 200
    assert exact_move.json()["route_decision"]["client_request_id"] == "exact-local-clip:2:fileB.txt"
    assert exact_move.json()["route_decision"]["knowledge_base_id"] == exact_target["id"]


def test_move_clip_outputs_and_storage_omit_known_server_secrets(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    target = api.post("/api/knowledge-bases", headers=headers, json={"name": "Secret safe"}).json()["knowledge_base"]
    uploaded = api.post(
        "/api/mobile-clips",
        headers=headers,
        data={
            "source_type": "text",
            "title_hint": "Secret safe move",
            "text": "body",
            "client_request_id": "move-secret-safe",
        },
    )
    assert uploaded.status_code == 200
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        clip_id = db.execute(
            "select id from clips where client_request_id = ?",
            ("move-secret-safe",),
        ).fetchone()[0]

    response = api.post(
        f"/api/clips/{clip_id}/move",
        headers=headers,
        json={
            "target_knowledge_base_id": target["id"],
            "reason": "token api_key password cookie authorization ragflow secret should not be stored",
        },
    )

    assert response.status_code == 200
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        route_rows = db.execute(
            "select * from clip_route_decisions where client_request_id = ?",
            ("move-secret-safe",),
        ).fetchall()
        metadata_json = db.execute(
            "select metadata_json from clip_metadata where client_request_id = ?",
            ("move-secret-safe",),
        ).fetchone()[0]
    combined = json.dumps(response.json(), ensure_ascii=False) + json.dumps([tuple(row) for row in route_rows]) + metadata_json
    for secret_value in [
        "change-me-server-side-ragflow-key",
        "change-me-baidu-api-key",
        "change-me-baidu-secret-key",
        "nas-password",
        "ssh-password",
        "cloud-secret",
        "social-secret",
        "api_key",
        "authorization",
    ]:
        assert secret_value not in combined


def test_busy_client_request_id_returns_409_before_archiving(tmp_path):
    store = ClipStore(tmp_path)
    store.init()
    assert store.acquire_request_lock("busy-request")
    archiver = FakeArchiver()
    app = create_app(Settings(data_dir=tmp_path, ingest_token="secret"), archiver_override=archiver)

    response = TestClient(app).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={
            "source_type": "text",
            "text": "hello",
            "client_request_id": "busy-request",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "request already processing"
    assert archiver.payloads == []


def test_blank_client_request_id_does_not_force_deduplication(tmp_path):
    headers = {"Authorization": "Bearer secret"}
    first = client(tmp_path).post(
        "/api/mobile-clips",
        headers=headers,
        data={"source_type": "text", "text": "first"},
    )
    second = client(tmp_path).post(
        "/api/mobile-clips",
        headers=headers,
        data={"source_type": "text", "text": "second"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is False
    assert first.json()["clip_id"] != second.json()["clip_id"]


def test_accepts_file_clip(tmp_path):
    response = client(tmp_path).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={"source_type": "file", "client_request_id": "file-1"},
        files={"file": ("demo.pdf", b"%PDF sample", "application/pdf")},
    )
    assert response.status_code == 200
    assert "original_path" not in response.json()
    assert response.json()["filename"] == "demo.pdf"
    assert response.json()["size_bytes"] == len(b"%PDF sample")
    metadata = metadata_for_request(tmp_path, "file-1")
    assert metadata["clip"]["source_type"] == "file"
    assert metadata["assets"][0]["filename"] == "demo.pdf"
    assert metadata["assets"][0]["mime_type"] == "application/pdf"
    assert metadata["assets"][0]["size_bytes"] == len(b"%PDF sample")
    assert metadata["assets"][0]["content_hash"] == response.json()["content_hash"]
    assert metadata["assets"][0]["text"] == ""


def test_sanitizes_traversal_filename_to_local_clip_dir(tmp_path):
    response = client(tmp_path).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={"source_type": "file", "client_request_id": "file-traversal"},
        files={"file": ("../../evil?.pdf", b"safe", "application/pdf")},
    )

    assert response.status_code == 200
    original_path = metadata_for_request(tmp_path, "file-traversal")["processing"]["original_path"]
    assert ".." not in original_path
    assert original_path.endswith("evil_.pdf")
    assert response.json()["filename"] == "evil_.pdf"
    assert response.json()["size_bytes"] == len(b"safe")
    assert (tmp_path / "clips") in Path(original_path).parents
    assert not (tmp_path / "evil_.pdf").exists()


def test_same_filename_uploads_do_not_overwrite_previous_payload(tmp_path):
    first = client(tmp_path).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={"source_type": "file", "client_request_id": "same-name-1"},
        files={"file": ("same.pdf", b"first", "application/pdf")},
    )
    second = client(tmp_path).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={"source_type": "file", "client_request_id": "same-name-2"},
        files={"file": ("same.pdf", b"second", "application/pdf")},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    first_path = Path(metadata_for_request(tmp_path, "same-name-1")["processing"]["original_path"])
    second_path = Path(metadata_for_request(tmp_path, "same-name-2")["processing"]["original_path"])
    assert first_path != second_path
    assert first_path.read_bytes() == b"first"
    assert second_path.read_bytes() == b"second"
    assert first.json()["filename"] == "same.pdf"
    assert second.json()["filename"] == "same.pdf"
    assert first.json()["size_bytes"] == 5
    assert second.json()["size_bytes"] == 6


def test_rejects_unsupported_file_mime_type(tmp_path):
    response = client(tmp_path).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={"source_type": "file", "client_request_id": "bad-mime"},
        files={"file": ("run.exe", b"MZ", "application/x-msdownload")},
    )

    assert response.status_code == 415
    assert response.json()["detail"] == "unsupported file mime type"


def test_accepts_audio_file_mime_type(tmp_path):
    response = client(tmp_path).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={"source_type": "file", "client_request_id": "audio-file"},
        files={"file": ("recording.m4a", b"audio-bytes", "audio/mp4")},
    )

    assert response.status_code == 200
    assert response.json()["filename"] == "recording.m4a"
    assert response.json()["size_bytes"] == 11


def test_rejects_file_larger_than_file_limit(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, ingest_token="secret", max_file_bytes=3))
    response = TestClient(app).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={"source_type": "file", "client_request_id": "too-large-file"},
        files={"file": ("demo.pdf", b"1234", "application/pdf")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "file too large"


def test_accepts_file_at_exact_file_limit(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, ingest_token="secret", max_file_bytes=4))
    response = TestClient(app).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={"source_type": "file", "client_request_id": "exact-file-limit"},
        files={"file": ("demo.pdf", b"1234", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["size_bytes"] == 4


def test_rejects_request_larger_than_request_limit(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            ingest_token="secret",
            max_file_bytes=20,
            max_request_bytes=20,
        ),
    )
    response = TestClient(app).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={
            "source_type": "text",
            "text": "x" * 200,
            "client_request_id": "too-large-request",
        },
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "request too large"


def test_classifies_content_length_boundaries():
    assert classify_content_length(None, 20) == "ok"
    assert classify_content_length("", 20) == "ok"
    assert classify_content_length("20", 20) == "ok"
    assert classify_content_length("21", 20) == "too_large"


def test_classifies_invalid_content_length():
    assert classify_content_length("not-a-number", 20) == "invalid"
    assert classify_content_length("-1", 20) == "invalid"


def test_archiver_success_overrides_response_path_and_doc_id(tmp_path):
    archiver = FakeArchiver()
    app = create_app(Settings(data_dir=tmp_path, ingest_token="secret"), archiver_override=archiver)
    response = TestClient(app).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={
            "source_type": "text",
            "title_hint": "来自安卓",
            "text": "hello",
            "client_request_id": "archive-1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["archive_status"] == "clip_to_ragflow"
    assert "original_path" not in payload
    assert payload["ragflow_document_id"] == ""
    assert archiver.payloads[0].source_type == "text"
    metadata = metadata_for_request(tmp_path, "archive-1")
    assert metadata["processing"]["archive_status"] == "clip_to_ragflow"
    assert metadata["processing"]["original_path"] == "/personalclips/fake.md"
    assert metadata["processing"]["ragflow_document_id"] == "doc-fake"
    assert metadata["security"]["credential_scope"] == ["ragflow:personalclips"]


def test_archiver_failure_returns_502_without_recording_duplicate(tmp_path):
    archiver = FakeArchiver(ok=False)
    app = create_app(Settings(data_dir=tmp_path, ingest_token="secret"), archiver_override=archiver)
    response = TestClient(app).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={
            "source_type": "text",
            "title_hint": "失败",
            "text": "hello",
            "client_request_id": "archive-fail",
        },
    )

    assert response.status_code == 502
    retry = TestClient(app).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={
            "source_type": "text",
            "title_hint": "失败",
            "text": "hello",
            "client_request_id": "archive-fail",
        },
    )
    assert retry.status_code == 502


def test_accepts_url_clip_and_stores_normalized_metadata(tmp_path):
    response = client(tmp_path).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={
            "source_type": "url",
            "title_hint": "Example",
            "text": "Example page",
            "url": "https://example.com",
            "client_request_id": "url-normalized",
            "device_name": "Pixel",
            "source_app": "Chrome",
            "captured_at": "2026-07-09T10:00:00Z",
        },
    )

    assert response.status_code == 200
    metadata = metadata_for_request(tmp_path, "url-normalized")
    assert metadata["clip"]["source_type"] == "url"
    assert metadata["clip"]["url"] == "https://example.com/"
    assert metadata["clip"]["captured_at"] == "2026-07-09T10:00:00Z"
    assert metadata["provenance"]["launcher_id"] == "Pixel"
    assert metadata["provenance"]["source_app"] == "Chrome"
    assert metadata["provenance"]["source_url"] == "https://example.com/"


def test_accepts_screen_clip_and_stores_normalized_metadata(tmp_path):
    response = client(tmp_path).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={
            "source_type": "screen_clip",
            "title_hint": "Screen title",
            "text": "来源：Example App\nScreen content",
            "client_request_id": "screen-normalized",
            "source_app": "Example App",
        },
    )

    assert response.status_code == 200
    metadata = metadata_for_request(tmp_path, "screen-normalized")
    assert metadata["clip"]["source_type"] == "screen_clip"
    assert metadata["provenance"]["capture_method"] == "accessibility"
    assert metadata["assets"][0]["role"] == "screenshot"
    assert metadata["assets"][0]["text"] == "来源：Example App\nScreen content"


def test_legacy_multipart_upload_response_fields_stay_compatible(tmp_path):
    response = client(tmp_path).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={
            "source_type": "text",
            "title_hint": "Legacy",
            "text": "legacy payload",
            "client_request_id": "legacy-response",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "ok",
        "duplicate",
        "title",
        "platform",
        "clip_id",
        "client_request_id",
        "content_hash",
        "filename",
        "size_bytes",
        "ragflow_document_id",
        "archive_status",
        "capture",
    }
    assert payload["ok"] is True
    assert payload["duplicate"] is False


def test_normalized_metadata_does_not_store_server_secrets(tmp_path):
    secret_values = [
        "secret",
        "change-me-server-side-ragflow-key",
        "change-me-baidu-api-key",
        "change-me-baidu-secret-key",
        "nas-password",
        "ssh-password",
        "cloud-secret",
        "social-secret",
    ]
    response = client(tmp_path).post(
        "/api/mobile-clips",
        headers={"Authorization": "Bearer secret"},
        data={
            "source_type": "text",
            "title_hint": "Safe",
            "text": "safe text",
            "client_request_id": "safe-metadata",
        },
    )

    assert response.status_code == 200
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        metadata_json = db.execute("select metadata_json from clip_metadata").fetchone()[0]
    for secret_value in secret_values:
        assert secret_value not in metadata_json
    metadata = metadata_for_request(tmp_path, "safe-metadata")
    assert metadata["security"]["auth_context"] == {
        "method": "mobile_ingest_token",
        "verified": True,
    }
    assert metadata["security"]["token_id"] == ""


def test_new_knowledge_base_apis_require_authentication(tmp_path):
    api = client(tmp_path)

    for method, path in [
        ("get", "/api/knowledge-bases"),
        ("post", "/api/knowledge-bases"),
        ("get", "/api/routing-rules"),
        ("post", "/api/routing-rules"),
        ("post", "/api/routing/preview"),
        ("get", "/api/ragflow/capabilities"),
    ]:
        if method == "get":
            response = getattr(api, method)(path)
        else:
            response = getattr(api, method)(path, json={})
        assert response.status_code == 401


def test_ragflow_dry_run_apis_require_authentication(tmp_path):
    api = client(tmp_path)
    kb_id = "kb_default"

    for path in [
        f"/api/knowledge-bases/{kb_id}/ragflow/dry-run-create",
        f"/api/knowledge-bases/{kb_id}/ragflow/dry-run-update",
        f"/api/knowledge-bases/{kb_id}/ragflow/dry-run-delete",
    ]:
        response = api.post(path, json={})
        assert response.status_code == 401


def test_knowledge_base_api_crud_and_default_delete_guard(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}

    initial = api.get("/api/knowledge-bases", headers=headers)
    assert initial.status_code == 200
    default = initial.json()["knowledge_bases"][0]
    assert default["is_default"] is True

    created = api.post(
        "/api/knowledge-bases",
        headers=headers,
        json={"name": "Research", "description": "Papers", "icon": "article", "color": "blue"},
    )
    assert created.status_code == 200
    knowledge_base = created.json()["knowledge_base"]
    assert knowledge_base["name"] == "Research"

    updated = api.patch(
        f"/api/knowledge-bases/{knowledge_base['id']}",
        headers=headers,
        json={"name": "Papers", "description": "PDF inbox"},
    )
    assert updated.status_code == 200
    assert updated.json()["knowledge_base"]["name"] == "Papers"
    assert updated.json()["knowledge_base"]["description"] == "PDF inbox"

    new_default = api.post(f"/api/knowledge-bases/{knowledge_base['id']}/set-default", headers=headers)
    assert new_default.status_code == 200
    assert new_default.json()["knowledge_base"]["is_default"] is True

    delete_old_default = api.delete(f"/api/knowledge-bases/{default['id']}", headers=headers)
    assert delete_old_default.status_code == 200
    assert delete_old_default.json()["ragflow_dataset_deleted"] is False

    delete_current_default = api.delete(f"/api/knowledge-bases/{knowledge_base['id']}", headers=headers)
    assert delete_current_default.status_code == 409


def test_knowledge_base_list_projects_ranked_top_topics(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    target = api.post(
        "/api/knowledge-bases",
        headers=headers,
        json={"name": "Topic aggregation"},
    ).json()["knowledge_base"]

    definitions = [
        ("software_automation", "软件开发与自动化", 3),
        ("education_research", "教学与科研", 4),
        ("finance_economy", "投资与经济", 6),
        ("unclassified", "待归类", 16),
    ]
    assignment_topics = [
        "software_automation", "software_automation", "software_automation",
        "education_research", "education_research",
        "finance_economy", "finance_economy",
        "unclassified",
    ]
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.executescript(
            """
            create table if not exists topic_definitions (
                topic_id text primary key, display_name text not null,
                description text not null, positive_examples_json text not null,
                exclusions_json text not null, enabled integer not null,
                sort_order integer not null, taxonomy_version text not null
            );
            create table if not exists clip_topic_assignments (
                id text primary key, clip_id integer not null,
                run_id text, generation text not null, topic_id text not null,
                role text not null, source text not null, confidence real not null,
                taxonomy_version text not null, active integer not null,
                manual_override integer not null, created_at text not null
            );
            """
        )
        db.executemany(
            """insert into topic_definitions values(?,?, '', '[]', '[]', 1, ?, 'test.v1')
            on conflict(topic_id) do update set display_name=excluded.display_name,
            sort_order=excluded.sort_order""",
            definitions,
        )

    store = ClipStore(tmp_path)
    pipeline = PipelineStore(tmp_path)
    for index, topic in enumerate(assignment_topics, start=1):
        request_id = f"topic-{index}"
        uploaded = api.post(
            "/api/mobile-clips",
            headers=headers,
            data={
                "source_type": "text",
                "title_hint": request_id,
                "text": f"memory for {request_id}",
                "client_request_id": request_id,
                "target_knowledge_base_id": target["id"],
            },
        )
        assert uploaded.status_code == 200
        pipeline.associate_knowledge_base(
            clip_id=int(uploaded.json()["clip_id"]),
            knowledge_base_id=target["id"],
            association_type="manual",
        )
        store.save_enrichment(
            clip_id=uploaded.json()["clip_id"],
            client_request_id=request_id,
            knowledge_base_id=target["id"],
            route_decision_id=None,
            engine="test",
            status="completed",
            title=request_id,
            summary="summary",
            tags=["perclip_internal", "自由标签不应出现在首页"],
            language="zh",
            extracted_text="memory",
        )
        with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
            db.execute(
                """insert into clip_topic_assignments values(
                ?, ?, null, 'gen_test', ?, 'primary', 'exact_rule', 1.0,
                'test.v1', 1, 0, '2026-07-27T00:00:00Z')""",
                (f"assignment-{index}", int(uploaded.json()["clip_id"]), topic),
            )

    response = api.get("/api/knowledge-bases", headers=headers)
    assert response.status_code == 200
    projected = next(item for item in response.json()["knowledge_bases"] if item["id"] == target["id"])
    assert projected["top_topics"] == [
        {"id": "software_automation", "label": "软件开发与自动化", "clip_count": 3},
        {"id": "education_research", "label": "教学与科研", "clip_count": 2},
        {"id": "finance_economy", "label": "投资与经济", "clip_count": 2},
    ]
    assert all(topic["label"] != "待归类" for topic in projected["top_topics"])


def test_knowledge_base_api_archive_and_rule_target_rejection(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    created = api.post("/api/knowledge-bases", headers=headers, json={"name": "Archive target"})
    target = created.json()["knowledge_base"]

    archived = api.post(f"/api/knowledge-bases/{target['id']}/archive", headers=headers)
    assert archived.status_code == 200
    assert archived.json()["knowledge_base"]["is_archived"] is True

    rule = api.post(
        "/api/routing-rules",
        headers=headers,
        json={
            "name": "Archived target",
            "rule_type": "keyword",
            "pattern": "PerClip",
            "target_knowledge_base_id": target["id"],
        },
    )
    assert rule.status_code == 409


def test_routing_rule_api_crud_and_secret_pattern_rejection(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    target = api.post("/api/knowledge-bases", headers=headers, json={"name": "Technical"}).json()["knowledge_base"]

    created = api.post(
        "/api/routing-rules",
        headers=headers,
        json={
            "name": "GitHub",
            "rule_type": "url_domain",
            "pattern": "github.com",
            "target_knowledge_base_id": target["id"],
            "priority": 5,
        },
    )
    assert created.status_code == 200
    rule = created.json()["routing_rule"]
    assert rule["pattern"] == "github.com"

    updated = api.patch(
        f"/api/routing-rules/{rule['id']}",
        headers=headers,
        json={"enabled": False, "priority": 10},
    )
    assert updated.status_code == 200
    assert updated.json()["routing_rule"]["enabled"] is False
    assert updated.json()["routing_rule"]["priority"] == 10

    unsafe = api.post(
        "/api/routing-rules",
        headers=headers,
        json={
            "name": "Unsafe",
            "rule_type": "keyword",
            "pattern": "authorization bearer",
            "target_knowledge_base_id": target["id"],
        },
    )
    assert unsafe.status_code == 422

    default_rule = api.post(
        "/api/routing-rules",
        headers=headers,
        json={
            "name": "Default",
            "rule_type": "default",
            "pattern": "*",
            "target_knowledge_base_id": target["id"],
        },
    )
    assert default_rule.status_code == 422
    assert "default routing is handled" in default_rule.json()["detail"]

    deleted = api.delete(f"/api/routing-rules/{rule['id']}", headers=headers)
    assert deleted.status_code == 200
    assert api.get(f"/api/routing-rules/{rule['id']}", headers=headers).status_code == 404


def test_routing_preview_api_uses_rules_without_writing_decision(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    target = api.post(
        "/api/knowledge-bases",
        headers=headers,
        json={"name": "Images", "ragflow_dataset_id": "dataset-images"},
    ).json()["knowledge_base"]
    rule = api.post(
        "/api/routing-rules",
        headers=headers,
        json={
            "name": "Image files",
            "rule_type": "mime_type",
            "pattern": "image/*",
            "target_knowledge_base_id": target["id"],
        },
    ).json()["routing_rule"]

    response = api.post(
        "/api/routing/preview",
        headers=headers,
        json={"source_type": "image", "mime_type": "image/png", "filename": "demo.png"},
    )

    assert response.status_code == 200
    preview = response.json()["route_preview"]
    assert preview["knowledge_base_id"] == target["id"]
    assert preview["knowledge_base_name"] == "Images"
    assert preview["ragflow_dataset_id"] == "dataset-images"
    assert preview["decision_type"] == "rule"
    assert preview["matched_rule_id"] == rule["id"]
    assert preview["matched_rule_ids"] == [rule["id"]]
    assert "image/*" in preview["reason"]
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        decision_count = db.execute("select count(*) from clip_route_decisions").fetchone()[0]
    assert decision_count == 0


def test_ragflow_capabilities_returns_disabled_when_unconfigured(tmp_path):
    api = client(tmp_path)
    response = api.get("/api/ragflow/capabilities", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["ragflow"]["adapter_status"] == "disabled"
    assert payload["ragflow"]["configured"] is False
    assert payload["ragflow"]["capabilities"]["dataset_list"] == "not_configured"


def test_ragflow_dry_run_create_update_delete_for_knowledge_base(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    kb = api.post(
        "/api/knowledge-bases",
        headers=headers,
        json={
            "name": "Research",
            "description": "Paper clips",
            "template_key": "research_papers",
            "ragflow_dataset_id": "dataset-existing",
            "ragflow_dataset_name": "Research",
        },
    ).json()["knowledge_base"]

    create = api.post(
        f"/api/knowledge-bases/{kb['id']}/ragflow/dry-run-create",
        headers=headers,
        json={},
    )
    update = api.post(
        f"/api/knowledge-bases/{kb['id']}/ragflow/dry-run-update",
        headers=headers,
        json={"name": "Research Updated"},
    )
    delete = api.post(
        f"/api/knowledge-bases/{kb['id']}/ragflow/dry-run-delete",
        headers=headers,
        json={},
    )

    assert create.status_code == 200
    assert create.json()["ragflow"]["operation"] == "create_dataset"
    assert create.json()["ragflow"]["dry_run"] is True
    assert create.json()["ragflow"]["remote_dataset_changed"] is False
    assert create.json()["ragflow"]["name"] == "Research"
    assert create.json()["ragflow"]["template_key"] == "research_papers"
    assert update.status_code == 200
    assert update.json()["ragflow"]["operation"] == "update_dataset"
    assert update.json()["ragflow"]["dataset_id"] == "dataset-existing"
    assert update.json()["ragflow"]["name"] == "Research Updated"
    assert delete.status_code == 200
    assert delete.json()["affected_mapping"]["ragflow_dataset_id"] == "dataset-existing"
    assert delete.json()["ragflow"]["danger_level"] == "high"
    assert delete.json()["ragflow"]["remote_dataset_deleted"] is False


def test_ragflow_dry_run_api_returns_404_for_missing_knowledge_base(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}

    response = api.post("/api/knowledge-bases/missing/ragflow/dry-run-create", headers=headers, json={})

    assert response.status_code == 404


def test_ragflow_capabilities_do_not_expose_configured_api_key(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            ingest_token="secret",
            ragflow=RagflowSettings(base_url="http://127.0.0.1:18080", api_key="test-ragflow-key"),
        )
    )
    response = TestClient(app).get("/api/ragflow/capabilities", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ragflow"]["adapter_status"] == "http_skeleton"
    assert payload["ragflow"]["configured"] is True
    assert "test-ragflow-key" not in json.dumps(payload)


def test_new_api_responses_do_not_contain_server_secret_markers(tmp_path):
    api = client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    target = api.post("/api/knowledge-bases", headers=headers, json={"name": "Safe"}).json()["knowledge_base"]
    api.post(
        "/api/routing-rules",
        headers=headers,
        json={
            "name": "Safe rule",
            "rule_type": "keyword",
            "pattern": "PerClip",
            "target_knowledge_base_id": target["id"],
        },
    )

    responses = [
        api.get("/api/knowledge-bases", headers=headers).json(),
        api.get("/api/routing-rules", headers=headers).json(),
        api.post("/api/routing/preview", headers=headers, json={"title_hint": "PerClip"}).json(),
    ]
    serialized = json.dumps(responses, ensure_ascii=False)

    for marker in [
        "RAGFLOW_API_KEY",
        "BAIDU_API_KEY",
        "NAS_PASSWORD",
        "SSH_PASSWORD",
        "cloud-secret",
        "social-secret",
        "Bearer secret",
    ]:
        assert marker not in serialized
