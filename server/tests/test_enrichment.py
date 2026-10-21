from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient

from perclip_ingest.config import Settings
from perclip_ingest.main import create_app
from perclip_ingest.storage import ClipStore
from perclip_ingest.enrichment import (
    EnrichmentInputProjection,
    deterministic_enrich,
    deterministic_key_points,
    semantic_tags_for,
)


def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, ingest_token="secret"))
    return TestClient(app)


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer secret"}


def clip_id_for_request(tmp_path, client_request_id: str) -> int:
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        return int(
            db.execute(
                "select id from clips where client_request_id = ?",
                (client_request_id,),
            ).fetchone()[0]
        )


def metadata_for_request(tmp_path, client_request_id: str) -> dict[str, object]:
    metadata = ClipStore(tmp_path).find_normalized_metadata_by_request_id(client_request_id)
    assert metadata is not None
    return metadata.metadata


def test_explicit_user_title_precedes_structured_extractor_title():
    raw = SimpleNamespace(
        id=1,
        client_request_id="title-priority",
        source_type="url",
        title_hint="User title",
        filename="",
        url="https://example.test/article",
        mime_type="text/html",
        original_path="",
        size_bytes=0,
    )
    result = deterministic_enrich(
        raw,
        None,
        {},
        EnrichmentInputProjection(
            text="Useful article body",
            title="JSON-LD title",
            extraction_status="completed",
        ),
    )

    assert result.title == "User title"


def test_projected_enrichment_emits_only_title_grounded_semantic_tags():
    raw = SimpleNamespace(
        id=1,
        client_request_id="semantic-tags",
        source_type="url",
        title_hint="",
        filename="",
        url="https://example.test/article",
        mime_type="text/html",
        original_path="",
        size_bytes=0,
    )

    result = deterministic_enrich(
        raw,
        SimpleNamespace(knowledge_base_id="kb-test"),
        {},
        EnrichmentInputProjection(
            title="欧冠比赛复盘",
            text="欧冠比赛通过高位逼抢改变节奏，正文还提到 Docker 作为无关示例。",
            extraction_status="completed",
        ),
    )

    assert result.engine == "deterministic.v7"
    assert result.tags == ["欧冠", "比赛"]
    assert result.key_points == ["欧冠比赛通过高位逼抢改变节奏，正文还提到 Docker 作为无关示例。"]
    assert not {"url", "knowledge-base", "text", "docker"}.intersection(result.tags)
    assert all(tag.casefold() in "欧冠比赛复盘".casefold() for tag in result.tags)


def test_projected_key_points_are_bounded_redacted_and_source_ordered():
    points = deterministic_key_points(
        "第一条完整事实包含 token=synthetic-secret。"
        "第二条完整事实位于 /Users/alice/private.md。"
        "第三条完整事实用于确认顺序。第四条完整事实不应进入结果。"
    )

    assert points == [
        "第一条完整事实包含 token=[redacted]",
        "第二条完整事实位于 [redacted-path]",
        "第三条完整事实用于确认顺序。",
    ]
    assert all(len(point) <= 240 for point in points)
    assert "synthetic-secret" not in json.dumps(points)
    assert "/Users/" not in json.dumps(points)


def test_projected_key_points_redact_dotted_private_path_before_sentence_split():
    points = deterministic_key_points(
        "配置保存在 /Users/alice/.config/perclip/session.token 并仅供本机读取。"
        "下一条事实确认脱敏后仍保持原始顺序。"
    )

    assert points == [
        "配置保存在 [redacted-path] 并仅供本机读取。",
        "下一条事实确认脱敏后仍保持原始顺序。",
    ]
    serialized = json.dumps(points, ensure_ascii=False)
    assert "/Users/" not in serialized
    assert ".config" not in serialized
    assert "session.token" not in serialized


def test_projected_key_points_keep_url_version_decimal_and_normal_sentence_boundaries():
    points = deterministic_key_points(
        "Release v1.2.3 keeps https://example.com/v1.2/docs and score 3.14 stable. "
        "Second English sentence remains ordered.中文句子无需空格也会切分。"
    )

    assert points == [
        "Release v1.2.3 keeps https://example.com/v1.2/docs and score 3.14 stable.",
        "Second English sentence remains ordered.",
        "中文句子无需空格也会切分。",
    ]


def test_projected_enrichment_uses_body_evidence_only_without_title_evidence():
    raw = SimpleNamespace(
        id=1,
        client_request_id="body-semantic-tags",
        source_type="url",
        title_hint="",
        filename="",
        url="https://example.test/article",
        mime_type="text/html",
        original_path="",
        size_bytes=0,
    )

    result = deterministic_enrich(
        raw,
        None,
        {},
        EnrichmentInputProjection(
            title="交付清单",
            text="Docker 与 GitHub 自动化构建需要稳定回滚。",
            extraction_status="completed",
        ),
    )

    assert result.tags == ["Docker", "GitHub"]
    assert all(tag.casefold() in "Docker 与 GitHub 自动化构建需要稳定回滚。".casefold() for tag in result.tags)


def test_projected_enrichment_weights_title_topic_then_uses_grounded_body_terms():
    raw = SimpleNamespace(
        id=1,
        client_request_id="weighted-semantic-tags",
        source_type="url",
        title_hint="",
        filename="",
        url="https://example.test/article",
        mime_type="text/html",
        original_path="",
        size_bytes=0,
    )

    result = deterministic_enrich(
        raw,
        None,
        {},
        EnrichmentInputProjection(
            title="欧冠比赛复盘",
            text="欧冠比赛改变了节奏，Docker 只是正文中的无关示例。",
            extraction_status="completed",
        ),
    )

    assert result.tags == ["欧冠", "比赛"]
    assert len(result.tags) <= 2


def test_projected_semantic_tags_cover_registry_topics_without_source_pollution():
    cases = (
        ("芯片相机评测", "手机硬件对比。", ["芯片", "相机"]),
        ("基金财报分析", "股票市场数据。", ["股票", "基金"]),
        ("家庭沟通记录", "朋友之间的关系。", ["家庭", "沟通"]),
        ("护肤穿搭清单", "服装与美妆建议。", ["护肤", "穿搭"]),
    )
    for title, text, expected in cases:
        tags = semantic_tags_for(title, text)
        assert tags == expected
        assert len(tags) <= 2
        source = f"{title}\n{text}".casefold()
        assert all(tag.casefold() in source for tag in tags)


def test_projected_semantic_tags_reject_unknown_and_non_positive_limit():
    assert semantic_tags_for("普通提醒", "稍后再看。") == []
    assert semantic_tags_for("欧冠比赛", "足球复盘", limit=0) == []


def test_projected_enrichment_returns_no_tags_without_semantic_evidence():
    raw = SimpleNamespace(
        id=1,
        client_request_id="short-semantic-tags",
        source_type="url",
        title_hint="",
        filename="",
        url="https://example.test/article",
        mime_type="text/html",
        original_path="",
        size_bytes=0,
    )

    result = deterministic_enrich(
        raw,
        SimpleNamespace(knowledge_base_id="kb-test"),
        {},
        EnrichmentInputProjection(
            title="没有足够上下文",
            text="稍后再看。",
            extraction_status="completed",
        ),
    )

    assert result.tags == []


def test_enrich_clip_requires_token(tmp_path):
    response = client(tmp_path).post("/api/clips/1/enrich")

    assert response.status_code == 401


def test_run_pending_enrichment_requires_token(tmp_path):
    response = client(tmp_path).post("/api/enrichment/run-pending", json={"limit": 1})

    assert response.status_code == 401


def test_run_pending_enrichment_rejects_invalid_limit(tmp_path):
    api = client(tmp_path)

    bad_type = api.post("/api/enrichment/run-pending", headers=auth_headers(), json={"limit": "many"})
    too_large = api.post("/api/enrichment/run-pending", headers=auth_headers(), json={"limit": 101})
    zero = api.post("/api/enrichment/run-pending", headers=auth_headers(), json={"limit": 0})

    assert bad_type.status_code == 422
    assert too_large.status_code == 422
    assert zero.status_code == 422


def test_run_pending_enrichment_respects_limit_and_does_not_repeat_existing(tmp_path):
    api = client(tmp_path)
    for index in range(3):
        uploaded = api.post(
            "/api/mobile-clips",
            headers=auth_headers(),
            data={
                "source_type": "text",
                "title_hint": f"Pending {index}",
                "text": f"pending body {index}",
                "client_request_id": f"pending-enrich-{index}",
            },
        )
        assert uploaded.status_code == 200

    first = api.post("/api/enrichment/run-pending", headers=auth_headers(), json={"limit": 2})
    second = api.post("/api/enrichment/run-pending", headers=auth_headers(), json={"limit": 20})
    third = api.post("/api/enrichment/run-pending", headers=auth_headers(), json={"limit": 20})

    assert first.status_code == 200
    assert first.json()["processed"] == 2
    assert [item["client_request_id"] for item in first.json()["items"]] == [
        "pending-enrich-0",
        "pending-enrich-1",
    ]
    assert second.status_code == 200
    assert second.json()["processed"] == 1
    assert second.json()["items"][0]["client_request_id"] == "pending-enrich-2"
    assert third.status_code == 200
    assert third.json()["processed"] == 0
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        count = db.execute("select count(*) from clip_enrichments").fetchone()[0]
    assert count == 3


def test_run_pending_enrichment_handles_text_url_and_file_and_preserves_metadata_sections(tmp_path):
    api = client(tmp_path)
    target = api.post(
        "/api/knowledge-bases",
        headers=auth_headers(),
        json={"name": "Batch KB", "ragflow_dataset_id": "dataset-batch"},
    ).json()["knowledge_base"]
    text_upload = api.post(
        "/api/mobile-clips",
        headers=auth_headers(),
        data={
            "source_type": "text",
            "text": "batch text",
            "client_request_id": "batch-text",
            "target_knowledge_base_id": target["id"],
        },
    )
    url_upload = api.post(
        "/api/mobile-clips",
        headers=auth_headers(),
        data={
            "source_type": "url",
            "url": "https://example.com/batch",
            "client_request_id": "batch-url",
            "target_knowledge_base_id": target["id"],
        },
    )
    file_upload = api.post(
        "/api/mobile-clips",
        headers=auth_headers(),
        data={
            "source_type": "file",
            "client_request_id": "batch-file",
            "target_knowledge_base_id": target["id"],
        },
        files={"file": ("batch.pdf", b"%PDF", "application/pdf")},
    )
    assert text_upload.status_code == 200
    assert url_upload.status_code == 200
    assert file_upload.status_code == 200

    response = api.post("/api/enrichment/run-pending", headers=auth_headers(), json={"limit": 10})

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed"] == 3
    assert payload["failed"] == 0
    assert {item["client_request_id"] for item in payload["items"]} == {"batch-text", "batch-url", "batch-file"}
    for request_id in ["batch-text", "batch-url", "batch-file"]:
        metadata = metadata_for_request(tmp_path, request_id)
        assert metadata["enrichment"]["engine"] == "deterministic.v2"
        assert metadata["routing"]["knowledge_base_id"] == target["id"]
        assert "processing" in metadata
        assert "security" in metadata


def test_enrich_text_clip_saves_deterministic_result_and_updates_metadata(tmp_path):
    api = client(tmp_path)
    target = api.post(
        "/api/knowledge-bases",
        headers=auth_headers(),
        json={"name": "课程资料", "ragflow_dataset_id": "dataset-teaching"},
    ).json()["knowledge_base"]
    uploaded = api.post(
        "/api/mobile-clips",
        headers=auth_headers(),
        data={
            "source_type": "text",
            "title_hint": "AI办公培训",
            "text": "这是一段用于确定性 enrichment 的中文内容，会生成摘要和语言。",
            "client_request_id": "enrich-text:",
            "target_knowledge_base_id": target["id"],
        },
    )
    assert uploaded.status_code == 200
    clip_id = clip_id_for_request(tmp_path, "enrich-text:")

    response = api.post(f"/api/clips/{clip_id}/enrich", headers=auth_headers())

    assert response.status_code == 200
    payload = response.json()
    enrichment = payload["enrichment"]
    assert payload["ok"] is True
    assert enrichment["clip_id"] == str(clip_id)
    assert enrichment["client_request_id"] == "enrich-text:"
    assert enrichment["knowledge_base_id"] == target["id"]
    assert enrichment["engine"] == "deterministic.v2"
    assert enrichment["status"] == "completed"
    assert enrichment["title"] == "AI办公培训"
    assert enrichment["summary"] == "这是一段用于确定性 enrichment 的中文内容，会生成摘要和语言。"
    assert enrichment["language"] == "zh-CN"
    assert enrichment["tags"] == ["text", "knowledge-base"]
    assert enrichment["key_points"] == []
    assert enrichment["error_code"] == ""
    assert enrichment["error_message"] == ""

    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        row = db.execute(
            """
            select clip_id, client_request_id, knowledge_base_id, engine, status, tags_json
            from clip_enrichments
            where client_request_id = ?
            """,
            ("enrich-text:",),
        ).fetchone()
    assert row[:5] == (str(clip_id), "enrich-text:", target["id"], "deterministic.v2", "completed")
    assert isinstance(json.loads(row[5]), list)
    assert json.loads(row[5]) == ["text", "knowledge-base"]

    metadata = metadata_for_request(tmp_path, "enrich-text:")
    assert metadata["enrichment"]["engine"] == "deterministic.v2"
    assert metadata["enrichment"]["tags"] == ["text", "knowledge-base"]
    assert metadata["enrichment"]["key_points"] == []
    assert metadata["processing"]["extraction_status"] == "completed"
    assert metadata["routing"]["knowledge_base_id"] == target["id"]
    store = ClipStore(tmp_path)
    by_clip_id = store.find_latest_enrichment_by_clip_id(clip_id)
    by_request_id = store.find_latest_enrichment_by_request_id("enrich-text:")
    assert by_clip_id is not None
    assert by_request_id is not None
    assert by_clip_id.id == by_request_id.id
    assert by_request_id.summary == enrichment["summary"]


def test_get_enrichment_returns_latest_result_by_numeric_or_prefix_clip_id(tmp_path):
    api = client(tmp_path)
    uploaded = api.post(
        "/api/mobile-clips",
        headers=auth_headers(),
        data={
            "source_type": "text",
            "title_hint": "First title",
            "text": "first deterministic body",
            "client_request_id": "latest-enrichment:",
        },
    )
    assert uploaded.status_code == 200
    clip_id = clip_id_for_request(tmp_path, "latest-enrichment:")

    first = api.post(f"/api/clips/{clip_id}/enrich", headers=auth_headers())
    second = api.post("/api/clips/latest-enrichment/enrich", headers=auth_headers())
    numeric_get = api.get(f"/api/clips/{clip_id}/enrichment", headers=auth_headers())
    prefix_get = api.get("/api/clips/latest-enrichment/enrichment", headers=auth_headers())

    assert first.status_code == 200
    assert second.status_code == 200
    assert numeric_get.status_code == 200
    assert prefix_get.status_code == 200
    assert numeric_get.json()["enrichment"]["created_at"] == second.json()["enrichment"]["created_at"]
    assert prefix_get.json()["enrichment"]["created_at"] == second.json()["enrichment"]["created_at"]
    assert numeric_get.json()["enrichment"]["title"] == "First title"


def test_get_enrichment_returns_404_when_clip_has_no_enrichment(tmp_path):
    api = client(tmp_path)
    uploaded = api.post(
        "/api/mobile-clips",
        headers=auth_headers(),
        data={
            "source_type": "text",
            "text": "not enriched yet",
            "client_request_id": "no-enrichment-yet:",
        },
    )
    assert uploaded.status_code == 200

    response = api.get("/api/clips/no-enrichment-yet/enrichment", headers=auth_headers())

    assert response.status_code == 404
    assert response.json()["detail"] == "enrichment not found"


def test_get_enrichment_rejects_ambiguous_android_clip_id_prefix(tmp_path):
    api = client(tmp_path)
    for index in [1, 2]:
        uploaded = api.post(
            "/api/mobile-clips",
            headers=auth_headers(),
            data={
                "source_type": "file",
                "client_request_id": f"get-multi-prefix:{index}:file.txt",
            },
            files={"file": (f"part-{index}.txt", b"part", "text/plain")},
        )
        assert uploaded.status_code == 200

    response = api.get("/api/clips/get-multi-prefix/enrichment", headers=auth_headers())

    assert response.status_code == 409
    assert response.json()["detail"] == "multiple clip parts require batch enrichment"


def test_enrich_file_clip_uses_file_summary_without_parsing_payload(tmp_path):
    api = client(tmp_path)
    uploaded = api.post(
        "/api/mobile-clips",
        headers=auth_headers(),
        data={
            "source_type": "file",
            "client_request_id": "enrich-file:",
        },
        files={"file": ("paper.pdf", b"%PDF sample", "application/pdf")},
    )
    assert uploaded.status_code == 200

    response = api.post("/api/clips/enrich-file:/enrich", headers=auth_headers())

    assert response.status_code == 200
    enrichment = response.json()["enrichment"]
    assert enrichment["status"] == "completed"
    assert enrichment["summary"] == "File: paper.pdf (application/pdf)"
    assert enrichment["extracted_text"] == "paper.pdf"
    assert enrichment["tags"] == ["file", "knowledge-base", "pdf"]
    assert "%PDF sample" not in enrichment["summary"]


def test_enrich_accepts_android_clip_id_prefix_for_single_part(tmp_path):
    api = client(tmp_path)
    uploaded = api.post(
        "/api/mobile-clips",
        headers=auth_headers(),
        data={
            "source_type": "url",
            "url": "https://example.com/article",
            "client_request_id": "android-prefix:",
        },
    )
    assert uploaded.status_code == 200

    response = api.post("/api/clips/android-prefix/enrich", headers=auth_headers())

    assert response.status_code == 200
    assert response.json()["enrichment"]["client_request_id"] == "android-prefix:"
    assert response.json()["enrichment"]["summary"] == "URL: https://example.com/article"


def test_enrich_rejects_ambiguous_android_clip_id_prefix_without_writing_result(tmp_path):
    api = client(tmp_path)
    for index in [1, 2]:
        uploaded = api.post(
            "/api/mobile-clips",
            headers=auth_headers(),
            data={
                "source_type": "file",
                "client_request_id": f"multi-prefix:{index}:file.txt",
            },
            files={"file": (f"part-{index}.txt", b"part", "text/plain")},
        )
        assert uploaded.status_code == 200

    response = api.post("/api/clips/multi-prefix/enrich", headers=auth_headers())

    assert response.status_code == 409
    assert response.json()["detail"] == "multiple clip parts require batch enrichment"
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        count = db.execute("select count(*) from clip_enrichments").fetchone()[0]
    assert count == 0


def test_enrich_redacts_credential_like_strings_from_all_enrichment_outputs(tmp_path):
    api = client(tmp_path)
    uploaded = api.post(
        "/api/mobile-clips",
        headers=auth_headers(),
        data={
            "source_type": "text",
            "title_hint": "Credential note",
            "text": (
                'token=synthetic-assigned password: synthetic-password '
                '"api_key": "synthetic-json-key" '
                "'secret': 'synthetic-single-quoted' "
                "Authorization: Basic c3ludGhldGljLWJhc2lj "
                "OAuth token rotation policy; Basic authentication security; JSON 中 token 字段的设计"
            ),
            "client_request_id": "enrich-redact:",
        },
    )
    assert uploaded.status_code == 200

    response = api.post("/api/clips/enrich-redact:/enrich", headers=auth_headers())

    assert response.status_code == 200
    enrichment = response.json()["enrichment"]
    response_payload = json.dumps(
        {
            "summary": enrichment["summary"],
            "tags": enrichment["tags"],
            "extracted_text": enrichment["extracted_text"],
            "error": enrichment["error_message"],
        },
        ensure_ascii=False,
    ).lower()
    for synthetic_value in (
        "synthetic-assigned",
        "synthetic-password",
        "synthetic-json-key",
        "synthetic-single-quoted",
        "c3ludghldgljlwjhc2lj",
    ):
        assert synthetic_value not in response_payload
    assert "token=[redacted]" in response_payload
    assert "password: [redacted]" in response_payload
    extracted_text = enrichment["extracted_text"].lower()
    assert '"api_key": "[redacted]"' in extracted_text
    assert "'secret': '[redacted]'" in extracted_text
    assert "authorization: basic [redacted]" in response_payload
    assert "oauth token rotation policy" in response_payload
    assert "basic authentication security" in response_payload
    assert "json 中 token 字段的设计" in response_payload
    assert "[redacted]" in enrichment["summary"]
    assert "[redacted]" in enrichment["extracted_text"]

    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        row = db.execute(
            """
            select summary, extracted_text
            from clip_enrichments
            where client_request_id = ?
            order by id desc
            limit 1
            """,
            ("enrich-redact:",),
        ).fetchone()
    sqlite_payload = json.dumps({"summary": row[0], "extracted_text": row[1]}, ensure_ascii=False).lower()
    assert "synthetic-json-key" not in sqlite_payload
    assert "synthetic-password" not in sqlite_payload
    assert "[redacted]" in row[0]
    assert "[redacted]" in row[1]

    metadata = metadata_for_request(tmp_path, "enrich-redact:")
    metadata_payload = json.dumps(metadata["enrichment"], ensure_ascii=False).lower()
    assert "synthetic-json-key" not in metadata_payload
    assert "synthetic-password" not in metadata_payload
    assert "[redacted]" in metadata["enrichment"]["summary"]
    assert "[redacted]" in metadata["enrichment"]["extracted_text"]

    latest = api.get("/api/clips/enrich-redact:/enrichment", headers=auth_headers())
    assert latest.status_code == 200
    latest_payload = json.dumps(latest.json()["enrichment"], ensure_ascii=False).lower()
    assert "synthetic-json-key" not in latest_payload
    assert "synthetic-password" not in latest_payload
    assert "[redacted]" in latest.json()["enrichment"]["extracted_text"]


def test_enrichment_table_is_created_when_migrating_old_database(tmp_path):
    store = ClipStore(tmp_path)
    store.init()

    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        tables = {row[0] for row in db.execute("select name from sqlite_master where type = 'table'")}
        tags_default = db.execute(
            """
            select dflt_value from pragma_table_info('clip_enrichments')
            where name = 'tags_json'
            """
        ).fetchone()[0]
        key_points_default = db.execute(
            """
            select dflt_value from pragma_table_info('clip_enrichments')
            where name = 'key_points_json'
            """
        ).fetchone()[0]

    assert "clip_enrichments" in tables
    assert tags_default == "'[]'"
    assert key_points_default == "'[]'"


def test_existing_enrichment_table_migrates_key_points_idempotently(tmp_path):
    database = tmp_path / "perclip.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute(
            """
            create table clip_enrichments (
                id integer primary key autoincrement,
                clip_id text not null,
                client_request_id text not null default '',
                knowledge_base_id text not null default '',
                route_decision_id integer,
                engine text not null,
                status text not null,
                title text not null default '',
                summary text not null default '',
                tags_json text not null default '[]',
                language text not null default '',
                extracted_text text not null default '',
                error_code text not null default '',
                error_message text not null default '',
                created_at text not null,
                updated_at text not null
            )
            """
        )
        db.execute(
            """
            insert into clip_enrichments (
                clip_id, engine, status, title, summary, created_at, updated_at
            ) values ('7', 'deterministic.v2', 'completed', 'Legacy', 'Legacy summary', 'now', 'now')
            """
        )

    store = ClipStore(tmp_path)
    store.init()
    store.init()

    legacy = store.find_latest_enrichment_by_clip_id("7")
    assert legacy is not None
    assert legacy.key_points == []
    with sqlite3.connect(database) as db:
        columns = [row[1] for row in db.execute("pragma table_info('clip_enrichments')")]
        stored = db.execute(
            "select key_points_json from clip_enrichments where clip_id='7'"
        ).fetchone()[0]
    assert columns.count("key_points_json") == 1
    assert stored == "[]"
