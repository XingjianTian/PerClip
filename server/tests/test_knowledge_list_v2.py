from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from time import monotonic

import pytest
from fastapi.testclient import TestClient

from perclip_ingest.config import RagflowSettings, Settings
from perclip_ingest.knowledge_list_store import CONTRACT_VERSION, KnowledgeListStore
from perclip_ingest.main import create_app
from perclip_ingest.pipeline_store import PipelineStore


HEADERS = {"Authorization": "Bearer secret"}
CLIP_COLUMNS = """id,client_request_id,source_type,title_hint,note,text,url,mime_type,
device_name,source_app,captured_at,filename,size_bytes,original_path,content_hash,
ragflow_document_id,archive_status,capture_client_batch_id,capture_parent_client_request_id,
capture_part_index,capture_part_count,capture_part_role,created_at"""


def api(tmp_path) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))


def add_kb(db: sqlite3.Connection, identifier: str, name: str | None = None) -> None:
    now = "2026-01-01T00:00:00Z"
    db.execute(
        """insert or ignore into knowledge_bases(
        id,name,description,icon,color,is_default,is_archived,ragflow_dataset_id,
        ragflow_dataset_name,template_key,created_at,updated_at,deleted_at)
        values(?,?, '', '', '',0,0,'','','general',?,?,'')""",
        (identifier, name or identifier, now, now),
    )


def seed_clips(tmp_path, count: int, *, knowledge_base_id: str = "kb_default", same_time: bool = False) -> None:
    if count == 0:
        return
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    add_kb(db, knowledge_base_id)
    clips = []
    identities = []
    associations = []
    for index in range(count):
        clip_id = index + 1
        public_id = f"pc_{clip_id:032x}"
        captured = "2026-01-15T12:00:00Z" if same_time else f"2026-01-{(index % 28) + 1:02d}T12:{index % 60:02d}:00Z"
        clips.append((clip_id, f"request-{clip_id}", "text", f"标题 {index}", "", f"正文 {index}", "", "text/plain", "", "测试来源", captured, "", 0, f"/archive/{clip_id}.md", f"hash-{clip_id}", "", "ready", "", "", 0, 1, "single", captured))
        identities.append((clip_id, public_id, captured))
        associations.append((clip_id, knowledge_base_id, "imported", None, "", captured))
    db.executemany(f"insert into clips({CLIP_COLUMNS}) values ({','.join('?' for _ in range(23))})", clips)
    db.executemany("insert into clip_identities(clip_id,public_id,created_at) values(?,?,?)", identities)
    db.executemany("insert into clip_knowledge_bases(clip_id,knowledge_base_id,association_type,route_decision_id,association_intent_id,created_at) values(?,?,?,?,?,?)", associations)
    db.commit()
    db.close()


def insert_clip(db: sqlite3.Connection, clip_id: int, *, knowledge_base_id: str = "kb_default") -> None:
    captured = f"2026-02-{clip_id:02d}T00:00:00Z"
    values = (clip_id, f"request-{clip_id}", "text", f"标题 {clip_id}", "", f"正文 {clip_id}", "", "text/plain", "", "测试来源", captured, "", 0, f"/archive/{clip_id}.md", f"hash-{clip_id}", "", "ready", "", "", 0, 1, "single", captured)
    db.execute(f"insert into clips({CLIP_COLUMNS}) values ({','.join('?' for _ in range(23))})", values)
    db.execute("insert into clip_identities(clip_id,public_id,created_at) values(?,?,?)", (clip_id, f"pc_{clip_id:032x}", captured))
    db.execute("insert into clip_knowledge_bases(clip_id,knowledge_base_id,association_type,route_decision_id,association_intent_id,created_at) values(?,?,?,?,?,?)", (clip_id, knowledge_base_id, "imported", None, "", captured))


def list_page(client: TestClient, **params):
    response = client.get("/api/knowledge/clips", headers=HEADERS, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_route_auth_contract_capability_and_limits(tmp_path):
    client = api(tmp_path)
    assert client.get("/api/knowledge/clips").status_code == 401
    assert client.get("/api/knowledge/summary").status_code == 401
    assert client.get("/api/knowledge/changes").status_code == 401
    assert client.post("/api/knowledge/bootstrap").status_code == 401
    for limit in (0, 101):
        assert client.get("/api/knowledge/clips", headers=HEADERS, params={"limit": limit}).status_code == 422
    for limit in (1, 50, 100):
        assert list_page(client, limit=limit)["contract_version"] == CONTRACT_VERSION
    capabilities = client.get("/api/app-capabilities", headers=HEADERS).json()
    assert capabilities["features"]["knowledge_list_v2"] is True
    assert capabilities["contracts"]["knowledge_list"] == CONTRACT_VERSION
    assert capabilities["knowledge_list_bootstrap"]["status"] == "pending"


def test_global_and_single_scope_traverse_all_501_with_stable_ties(tmp_path):
    client = api(tmp_path)
    seed_clips(tmp_path, 501, same_time=True)
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    add_kb(db, "kb-b")
    db.execute("insert into clip_knowledge_bases values(1,'kb-b','manual',null,'','2026-01-15T12:00:00Z')")
    db.commit(); db.close()

    cursor = ""
    seen: list[str] = []
    while True:
        page = list_page(client, limit=100, cursor=cursor)
        seen.extend(item["public_clip_id"] for item in page["items"])
        assert page["summary"]["total_count"] == 501
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 501
    assert seen == sorted(seen, reverse=True)
    first = list_page(client, knowledge_base_id="kb-b")
    assert [item["public_clip_id"] for item in first["items"]] == [f"pc_{1:032x}"]
    assert first["items"][0]["knowledge_base_ids"] == ["kb-b", "kb_default"]


def test_cursor_is_scope_filter_bound_and_tamper_closed(tmp_path):
    client = api(tmp_path); seed_clips(tmp_path, 60)
    page = list_page(client, limit=10)
    cursor = page["next_cursor"]
    assert cursor.startswith("kl_") and "captured_at" not in cursor and "internal" not in cursor
    assert client.get("/api/knowledge/clips", headers=HEADERS, params={"cursor": cursor, "query": "different"}).status_code == 422
    assert client.get("/api/knowledge/clips", headers=HEADERS, params={"cursor": cursor, "knowledge_base_id": "missing"}).status_code == 404
    tampered = cursor[:-2] + ("AA" if cursor[-2:] != "AA" else "BB")
    assert client.get("/api/knowledge/clips", headers=HEADERS, params={"cursor": tampered}).status_code == 422
    assert client.get("/api/knowledge/clips", headers=HEADERS, params={"cursor": "kl_not-base64"}).status_code == 422


def test_all_filters_literal_search_and_authoritative_matching_count(tmp_path):
    client = api(tmp_path); seed_clips(tmp_path, 6)
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    db.execute("update clips set title_hint='中文 100%_精确 & 空格',source_app='微信',source_type='url',url='https://example.com',captured_at='2026-02-01T00:00:00Z' where id=1")
    db.execute("update clips set source_type='file',filename='report.pdf',mime_type='application/pdf',captured_at='2026-02-02T00:00:00Z' where id=2")
    db.execute("update clips set source_type='image',filename='photo.png',mime_type='image/png',captured_at='2026-02-03T00:00:00Z' where id=3")
    db.execute("update clips set source_type='screen_clip',filename='',mime_type='text/plain',captured_at='2026-02-04T00:00:00Z' where id=4")
    db.execute("insert into clip_enrichments(clip_id,engine,status,title,summary,created_at,updated_at) values('5','test','completed','富化标题','特殊 摘要','2026-02-05T00:00:00Z','2026-02-06T00:00:00Z')")
    db.commit(); db.close()
    for query in ("中文", "100%_", "& 空格", "特殊 摘要"):
        payload = list_page(client, query=query)
        assert payload["summary"]["matching_count"] == 1
        assert len(payload["items"]) == 1
    assert list_page(client, query="%_")["summary"]["matching_count"] == 1
    assert list_page(client, source="微信")["summary"]["matching_count"] == 1
    assert list_page(client, source_type="file")["summary"]["matching_count"] == 1
    assert list_page(client, attachment="with")["summary"]["matching_count"] == 2
    without = list_page(client, attachment="without")
    assert without["summary"]["matching_count"] == 4
    assert all(not item["has_attachment"] for item in without["items"])
    combo = list_page(client, source_type="file", attachment="with", captured_after="2026-02-01T00:00:00Z", captured_before="2026-02-03T00:00:00Z")
    assert combo["summary"]["total_count"] == 6
    assert combo["summary"]["matching_count"] == 1
    assert client.get("/api/knowledge/clips", headers=HEADERS, params={"source_type": "bad"}).status_code == 422
    assert client.get("/api/knowledge/clips", headers=HEADERS, params={"captured_after": "2026-01-01"}).status_code == 422


def test_core_memory_projection_prefers_source_identity_and_explicit_data_states(tmp_path):
    client = api(tmp_path); seed_clips(tmp_path, 3)
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    now = "2026-02-10T00:00:00Z"
    metadata = lambda author, author_state, content, content_state: json.dumps(
        {
            "processing": {
                "active_projection": {
                    "structured_metadata": {
                    "author": {"value": author, "resolution_state": author_state},
                    "core_content": {"value": content, "resolution_state": content_state},
                    }
                }
            }
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    db.executemany(
        """insert into clip_metadata(clip_id,client_request_id,contract_version,metadata_json,created_at)
        values(?,?,?,?,?)""",
        [
            (1, "request-1", "perclip.metadata.v1", metadata("真实发布者", "resolved", "", "resolved"), now),
            (2, "request-2", "perclip.metadata.v1", metadata("不应展示的矛盾值", "explicit_unknown", "", "resolved"), now),
            (3, "request-3", "perclip.metadata.v1", metadata("", "explicit_unknown", "不应展示的矛盾正文", "explicit_unavailable"), now),
        ],
    )
    db.execute("insert into clip_enrichments(clip_id,engine,status,title,summary,created_at,updated_at) values('1','test','completed','真实标题','真实摘要',?,?)", (now, now))
    db.execute("insert into clip_enrichments(clip_id,engine,status,title,summary,created_at,updated_at) values('3','test','completed','受限标题','不应展示的矛盾摘要',?,?)", (now, now))
    db.commit(); db.close()

    items = {item["public_clip_id"]: item for item in list_page(client, limit=10)["items"]}
    assert items[f"pc_{1:032x}"]["source"] == "真实发布者"
    assert items[f"pc_{1:032x}"]["summary"] == "真实摘要"
    assert items[f"pc_{2:032x}"]["source"] == "未明确来源"
    assert items[f"pc_{3:032x}"]["source"] == "未明确来源"
    assert items[f"pc_{3:032x}"]["summary"] == "内容暂不可用"


def test_compact_item_uses_bounded_shared_mobile_safety_projection(tmp_path):
    client = api(tmp_path); seed_clips(tmp_path, 7)
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    db.execute(
        "update clips set url=?,client_request_id=? where id=1",
        ("https://user:pass@example.com/path", "valid.capture:request-1"),
    )
    db.execute(
        "update clips set url=? where id=2",
        ("https://Example.com/path?keep=yes&token=secret&utm_source=test#private",),
    )
    db.execute(
        "update clips set url=? where id=3",
        (
            "https://example.com/path?access_token=secret&authorization=secret"
            "&session=secret&password=secret&api_key=secret&ref=tracking",
        ),
    )
    db.execute("update clips set url='file:///private/archive.txt' where id=4")
    db.execute("update clips set url='/private/archive.txt',source_app='/private/source' where id=5")
    db.execute(
        "update clips set title_hint=?,client_request_id=? where id=6",
        ("标题" * 200, "token:secret-value"),
    )
    db.execute(
        "update clips set title_hint='正常中文标题',source_app='中文来源',client_request_id=? where id=7",
        ("x" * 129,),
    )
    db.execute(
        "insert into clip_enrichments(clip_id,engine,status,title,summary,created_at,updated_at) values(6,'test','completed','',?,'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')",
        ("摘要" * 300,),
    )
    db.execute(
        "insert into clip_enrichments(clip_id,engine,status,title,summary,created_at,updated_at) values(7,'test','completed','正常中文标题','正常中文摘要','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
    )
    db.commit(); db.close()

    items = {item["public_clip_id"]: item for item in list_page(client, limit=20)["items"]}
    assert items[f"pc_{1:032x}"]["safe_display_url"] == ""
    assert items[f"pc_{1:032x}"]["correlation_identity"] == "valid.capture:request-1"
    assert items[f"pc_{2:032x}"]["safe_display_url"] == "https://example.com/path?keep=yes"
    assert items[f"pc_{3:032x}"]["safe_display_url"] == "https://example.com/path"
    assert items[f"pc_{4:032x}"]["safe_display_url"] == ""
    assert items[f"pc_{5:032x}"]["safe_display_url"] == ""
    assert "/private/" not in items[f"pc_{5:032x}"]["source"]
    assert len(items[f"pc_{6:032x}"]["title"]) == 160
    assert len(items[f"pc_{6:032x}"]["summary"]) == 320
    assert items[f"pc_{6:032x}"]["correlation_identity"] == ""
    assert items[f"pc_{7:032x}"]["title"] == "正常中文标题"
    assert items[f"pc_{7:032x}"]["summary"] == "正常中文摘要"
    assert items[f"pc_{7:032x}"]["correlation_identity"] == ""


def test_captured_filters_normalize_to_utc_and_cursor_accepts_equivalent_offsets(tmp_path):
    client = api(tmp_path); seed_clips(tmp_path, 3)
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    db.execute("update clips set captured_at='2026-01-01T00:00:00Z' where id=1")
    db.execute("update clips set captured_at='2026-01-01T00:00:01Z' where id=2")
    db.execute("update clips set captured_at='2025-12-31T23:59:59Z' where id=3")
    db.commit(); db.close()

    positive = list_page(
        client,
        limit=1,
        captured_after="2026-01-01T08:00:00+08:00",
        captured_before="2026-01-01T08:00:01+08:00",
    )
    assert positive["summary"]["matching_count"] == 2
    continued = list_page(
        client,
        limit=1,
        cursor=positive["next_cursor"],
        captured_after="2026-01-01T00:00:00Z",
        captured_before="2026-01-01T00:00:01Z",
    )
    assert len(continued["items"]) == 1
    negative = list_page(
        client,
        captured_after="2025-12-31T18:59:59-05:00",
        captured_before="2025-12-31T19:00:00-05:00",
    )
    assert negative["summary"]["matching_count"] == 2
    assert client.get(
        "/api/knowledge/clips",
        headers=HEADERS,
        params={"captured_after": "2026-01-01T00:00:01Z", "captured_before": "2026-01-01T00:00:00Z"},
    ).status_code == 422


def test_multi_membership_detach_keeps_global_item_and_single_scope_removes(tmp_path):
    client = api(tmp_path); seed_clips(tmp_path, 1)
    db = sqlite3.connect(tmp_path / "perclip.sqlite3"); add_kb(db, "kb-b"); db.commit()
    before = db.execute("select coalesce(max(revision),0) from knowledge_change_events").fetchone()[0]
    db.close()
    associated = client.post(f"/api/clips/pc_{1:032x}/knowledge-bases/kb-b", headers=HEADERS)
    assert associated.status_code == 200, associated.text
    replayed_association = client.post(f"/api/clips/pc_{1:032x}/knowledge-bases/kb-b", headers=HEADERS)
    assert replayed_association.status_code == 200
    assert len([item for item in replayed_association.json()["knowledge_bases"] if item["knowledge_base_id"] == "kb-b"]) == 1
    response = client.delete(f"/api/clips/pc_{1:032x}/knowledge-bases/kb-b", headers=HEADERS)
    assert response.status_code == 200, response.text
    global_changes = client.get("/api/knowledge/changes", headers=HEADERS, params={"after_revision": before}).json()["changes"]
    assert global_changes[-1]["source_operation"] == "remove"
    assert global_changes[-1]["operation"] == "upsert"
    assert global_changes[-1]["item"]["knowledge_base_ids"] == ["kb_default"]
    scoped = client.get("/api/knowledge/changes", headers=HEADERS, params=[("after_revision", before), ("knowledge_base_id", "kb-b")]).json()["changes"]
    assert scoped[-1]["operation"] == "remove" and "item" not in scoped[-1]


def test_move_reuses_full_detach_semantics_preserves_intent_and_rolls_back(tmp_path):
    client = api(tmp_path); seed_clips(tmp_path, 3)
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    add_kb(db, "kb-target")
    add_kb(db, "kb-failure")
    now = "2026-01-01T00:00:00Z"
    operation_only_key = "a" * 64
    ordinary_key = "b" * 64
    rollback_key = "c" * 64
    attempts = (
        (operation_only_key, 2, "kb-target"),
        (ordinary_key, 1, "kb_default"),
        (rollback_key, 3, "kb_default"),
    )
    for operation_key, clip_id, knowledge_base_id in attempts:
        db.execute(
            """insert into index_attempts(
            operation_key,clip_id,knowledge_base_id,index_provider,dataset_id,
            association_intent_id,generation_id,document_id,content_hash,status,
            remote_status,chunk_count,vector_count,metadata_json,created_at,updated_at)
            values(?,?,?,'ragflow','dataset','','gen','document','hash','indexed_verified',
            'done',1,1,'{}',?,?)""",
            (operation_key, clip_id, knowledge_base_id, now, now),
        )
    db.execute(
        """insert into active_indexes values(
        1,'kb_default','ragflow','dataset',?,'document','gen','hash',?)""",
        (operation_only_key, now),
    )
    db.execute(
        """insert into active_indexes values(
        3,'kb_default','ragflow','dataset',?,'document','gen','hash',?)""",
        (rollback_key, now),
    )
    for clip_id in (1, 3):
        db.execute(
            """insert into index_documents values(
            ?,'kb_default','ragflow','dataset','document','hash','indexed_verified',?,?)""",
            (clip_id, now, now),
        )
    before_revision = db.execute(
        "select coalesce(max(revision),0) from knowledge_change_events"
    ).fetchone()[0]
    db.commit(); db.close()
    pipeline = PipelineStore(tmp_path)

    pipeline.move_knowledge_base_association(
        clip_id=1,
        previous_knowledge_base_id="kb_default",
        knowledge_base_id="kb-target",
        route_decision_id=1,
    )
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    db.row_factory = sqlite3.Row
    assert db.execute(
        "select status from index_attempts where operation_key=?", (operation_only_key,)
    ).fetchone()["status"] == "detached_pending_cleanup"
    assert db.execute(
        "select status from index_attempts where operation_key=?", (ordinary_key,)
    ).fetchone()["status"] == "detached_pending_cleanup"
    assert db.execute(
        "select count(*) from active_indexes where clip_id=1 and knowledge_base_id='kb_default'"
    ).fetchone()[0] == 0
    assert db.execute(
        "select status from index_documents where clip_id=1 and knowledge_base_id='kb_default'"
    ).fetchone()["status"] == "detached_pending_cleanup"
    association = db.execute(
        "select association_intent_id from clip_knowledge_bases where clip_id=1 and knowledge_base_id='kb-target'"
    ).fetchone()
    intent = str(association["association_intent_id"])
    assert intent.startswith("assoc_") and len(intent) > len("assoc_")
    event_rows = db.execute(
        "select operation from knowledge_change_events where revision>? order by revision",
        (before_revision,),
    ).fetchall()
    assert [row["operation"] for row in event_rows] == ["remove", "upsert"]
    db.close()
    pipeline.move_knowledge_base_association(
        clip_id=1,
        previous_knowledge_base_id="kb_default",
        knowledge_base_id="kb-target",
        route_decision_id=2,
    )
    assert pipeline.list_knowledge_base_associations(clip_id=1)[0]["association_intent_id"] == intent
    new_attempt = pipeline.ensure_index_attempt(
        operation_key="d" * 64,
        clip_id=1,
        knowledge_base_id="kb-target",
        index_provider="ragflow",
        dataset_id="dataset-target",
        association_intent_id=intent,
        generation_id="gen-target",
        content_hash="hash-target",
        metadata_json="{}",
        status="planned",
    )
    assert new_attempt["association_intent_id"] == intent
    assert "association_intent" not in json.dumps(list_page(client))

    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    rollback_revision = db.execute(
        "select coalesce(max(revision),0) from knowledge_change_events"
    ).fetchone()[0]
    db.execute(
        """create trigger fail_move_target before insert on clip_knowledge_bases
        when new.knowledge_base_id='kb-failure' begin
          select raise(abort, 'forced move failure');
        end"""
    )
    db.commit(); db.close()
    with pytest.raises(sqlite3.IntegrityError, match="forced move failure"):
        pipeline.move_knowledge_base_association(
            clip_id=3,
            previous_knowledge_base_id="kb_default",
            knowledge_base_id="kb-failure",
            route_decision_id=3,
        )
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    assert db.execute(
        "select count(*) from clip_knowledge_bases where clip_id=3 and knowledge_base_id='kb_default'"
    ).fetchone()[0] == 1
    assert db.execute(
        "select status from index_attempts where operation_key=?", (rollback_key,)
    ).fetchone()[0] == "indexed_verified"
    assert db.execute(
        "select count(*) from active_indexes where clip_id=3 and knowledge_base_id='kb_default'"
    ).fetchone()[0] == 1
    assert db.execute(
        "select status from index_documents where clip_id=3 and knowledge_base_id='kb_default'"
    ).fetchone()[0] == "indexed_verified"
    assert db.execute(
        "select coalesce(max(revision),0) from knowledge_change_events"
    ).fetchone()[0] == rollback_revision
    db.close()


def test_remove_association_still_uses_full_detach_helper(tmp_path):
    api(tmp_path); seed_clips(tmp_path, 1)
    pipeline = PipelineStore(tmp_path)
    now = "2026-01-01T00:00:00Z"
    key = "e" * 64
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    db.execute(
        """insert into index_attempts(
        operation_key,clip_id,knowledge_base_id,index_provider,dataset_id,
        association_intent_id,generation_id,document_id,content_hash,status,
        remote_status,chunk_count,vector_count,metadata_json,created_at,updated_at)
        values(?,1,'kb_default','ragflow','dataset','','gen','document','hash',
        'indexed_verified','done',1,1,'{}',?,?)""",
        (key, now, now),
    )
    db.execute(
        "insert into active_indexes values(1,'kb_default','ragflow','dataset',?,'document','gen','hash',?)",
        (key, now),
    )
    db.execute(
        "insert into index_documents values(1,'kb_default','ragflow','dataset','document','hash','indexed_verified',?,?)",
        (now, now),
    )
    db.commit(); db.close()
    assert pipeline.remove_knowledge_base_association(
        clip_id=1, knowledge_base_id="kb_default"
    ) is True
    assert pipeline.find_index_attempt(operation_key=key)["status"] == "detached_pending_cleanup"


def test_change_events_cover_move_enrichment_projection_topic_archive_delete_and_replay(tmp_path):
    client = api(tmp_path); seed_clips(tmp_path, 1)
    db = sqlite3.connect(tmp_path / "perclip.sqlite3"); add_kb(db, "kb-b")
    now = "2026-01-01T00:00:00Z"
    db.execute("""insert into clip_route_decisions(clip_id,client_request_id,knowledge_base_id,decision_type,reason,created_at)
                  values('1','request-1','kb_default','manual','seed',?)""", (now,))
    db.commit(); db.close()
    start = client.get("/api/knowledge/changes", headers=HEADERS).json()["current_revision"]
    moved = client.post(f"/api/clips/pc_{1:032x}/move", headers=HEADERS, json={"target_knowledge_base_id": "kb-b"})
    assert moved.status_code == 200, moved.text
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    db.execute("insert into clip_enrichments(clip_id,engine,status,title,summary,created_at,updated_at) values('1','test','completed','new title','new summary',?,?)", (now, now))
    metadata = json.loads(db.execute("select metadata_json from clip_metadata where clip_id=1").fetchone()[0])
    processing = metadata.setdefault("processing", {})
    processing["active_enrichment_id"] = 1
    processing["active_projection"] = {"extraction_status": "completed", "recall_eligible": True, "index_eligible": True}
    db.execute("update clip_metadata set metadata_json=? where clip_id=1", (json.dumps(metadata),))
    db.commit(); db.close()
    topic_set = client.put(f"/api/clips/pc_{1:032x}/topic-assignment", headers=HEADERS, json={"topic_id": "work_projects"})
    assert topic_set.status_code == 200, topic_set.text
    topic_clear = client.delete(f"/api/clips/pc_{1:032x}/topic-assignment", headers=HEADERS)
    assert topic_clear.status_code == 200, topic_clear.text
    assert list_page(client, knowledge_base_id="kb-b")["items"][0]["title"] == "new title"
    assert client.post("/api/knowledge-bases/kb-b/archive", headers=HEADERS).status_code == 200
    changes = client.get("/api/knowledge/changes", headers=HEADERS, params={"after_revision": start, "limit": 100}).json()["changes"]
    reasons = {item["reason"] for item in changes}
    assert {"association_remove", "association_upsert", "enrichment_update", "active_projection_update", "topic_update", "knowledge_base_visibility"} <= reasons
    revisions = [item["revision"] for item in changes]
    replay = client.get("/api/knowledge/changes", headers=HEADERS, params={"after_revision": start, "limit": 100}).json()["changes"]
    assert [item["revision"] for item in replay] == revisions
    assert len(revisions) == len(set(revisions))
    before_delete = client.get("/api/knowledge/changes", headers=HEADERS).json()["current_revision"]
    assert client.delete("/api/knowledge-bases/kb-b", headers=HEADERS).status_code == 200
    deleted_changes = client.get("/api/knowledge/changes", headers=HEADERS, params={"after_revision": before_delete}).json()["changes"]
    assert deleted_changes and deleted_changes[-1]["reason"] == "knowledge_base_visibility"


def test_v2_topic_assignment_matches_quality_read_and_emits_correction(tmp_path):
    client = api(tmp_path); seed_clips(tmp_path, 2)
    now = "2026-01-01T00:00:00Z"
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    assignments = [
        ("primary", 1, "work_projects", "primary", "manual", 1),
        ("secondary-a", 1, "software_automation", "secondary", "classification", 0),
        ("secondary-a-duplicate", 1, "software_automation", "secondary", "classification", 0),
        ("secondary-b", 1, "ai_ml", "secondary", "classification", 0),
    ]
    db.executemany(
        """insert into clip_topic_assignments(
        id,clip_id,run_id,generation,topic_id,role,source,confidence,
        taxonomy_version,active,manual_override,created_at)
        values(?,?,null,'gen_000000000000000000000000',?,?,?,1.0,'topic-taxonomy.v1',1,?,?)""",
        [(identifier, clip_id, topic_id, role, source, manual, now) for identifier, clip_id, topic_id, role, source, manual in assignments],
    )
    db.execute("update topic_definitions set enabled=0 where topic_id in ('work_projects','ai_ml')")
    db.commit(); db.close()

    item = next(item for item in list_page(client)["items"] if item["public_clip_id"] == f"pc_{1:032x}")
    assignment = item["topic_assignment"]
    assert assignment["primary"] == {"topic_id": "work_projects", "display_name": "工作与项目", "source": "manual"}
    assert [topic["topic_id"] for topic in assignment["secondary"]] == ["ai_ml", "software_automation"]
    assert assignment["manual_override"] is True and assignment["topic_disabled"] is True
    assert assignment["unclassified"] is False
    unclassified = next(item for item in list_page(client)["items"] if item["public_clip_id"] == f"pc_{2:032x}")["topic_assignment"]
    assert unclassified["unclassified"] is True and unclassified["primary"]["topic_id"] == "unclassified"

    quality = client.get(f"/api/clips/pc_{1:032x}/quality", headers=HEADERS).json()["quality_read"]["topic_assignment"]
    for key in ("primary", "secondary", "unclassified", "manual_override", "topic_disabled"):
        assert assignment[key] == quality[key]

    before = client.get("/api/knowledge/changes", headers=HEADERS).json()["current_revision"]
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    db.execute("update clip_topic_assignments set topic_id='football_sports' where id='primary'")
    db.commit(); db.close()
    changes = client.get("/api/knowledge/changes", headers=HEADERS, params={"after_revision": before}).json()["changes"]
    assert changes and changes[-1]["operation"] == "upsert" and changes[-1]["reason"] == "topic_update"
    assert changes[-1]["item"]["topic_assignment"]["primary"]["topic_id"] == "football_sports"


def test_captured_at_update_reorders_filters_and_emits_replayable_upsert(tmp_path):
    client = api(tmp_path); seed_clips(tmp_path, 2)
    before_items = list_page(client)["items"]
    assert before_items[0]["public_clip_id"] == f"pc_{2:032x}"
    before_revision = client.get("/api/knowledge/changes", headers=HEADERS).json()["current_revision"]
    old_item = next(item for item in before_items if item["public_clip_id"] == f"pc_{1:032x}")

    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    db.execute("update clips set captured_at='2026-02-01T00:00:00Z' where id=1")
    db.commit(); db.close()

    reordered = list_page(client)["items"]
    assert reordered[0]["public_clip_id"] == f"pc_{1:032x}"
    assert list_page(
        client,
        captured_after="2026-01-01T00:00:00Z",
        captured_before="2026-01-31T23:59:59Z",
    )["summary"]["matching_count"] == 1
    new_window = list_page(
        client,
        captured_after="2026-02-01T00:00:00Z",
        captured_before="2026-02-01T00:00:00Z",
    )
    assert [item["public_clip_id"] for item in new_window["items"]] == [f"pc_{1:032x}"]
    changed_item = reordered[0]
    assert changed_item["item_revision"] > old_item["item_revision"]
    assert changed_item["updated_at"] != old_item["updated_at"]

    first = client.get(
        "/api/knowledge/changes",
        headers=HEADERS,
        params={"after_revision": before_revision},
    ).json()["changes"]
    assert first[-1]["operation"] == "upsert"
    assert first[-1]["reason"] == "clip_projection_update"
    assert first[-1]["item"]["captured_at"] == "2026-02-01T00:00:00Z"
    replay = client.get(
        "/api/knowledge/changes",
        headers=HEADERS,
        params={"after_revision": before_revision},
    ).json()["changes"]
    assert replay == first


def test_membership_projection_tracks_archive_unarchive_and_association_delete(tmp_path):
    client = api(tmp_path); seed_clips(tmp_path, 1)
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    add_kb(db, "kb-lifecycle")
    db.execute("insert into clip_knowledge_bases values(1,'kb-lifecycle','manual',null,'','2026-01-01T00:00:00Z')")
    db.commit(); db.close()
    assert list_page(client, knowledge_base_id="kb-lifecycle")["summary"]["total_count"] == 1

    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    db.execute("update knowledge_bases set is_archived=1 where id='kb-lifecycle'")
    assert db.execute("select count(*) from knowledge_list_membership_projection where knowledge_base_id='kb-lifecycle'").fetchone()[0] == 0
    db.execute("update knowledge_bases set is_archived=0 where id='kb-lifecycle'")
    assert db.execute("select count(*) from knowledge_list_membership_projection where knowledge_base_id='kb-lifecycle'").fetchone()[0] == 1
    db.execute("delete from clip_knowledge_bases where clip_id=1 and knowledge_base_id='kb-lifecycle'")
    assert db.execute("select count(*) from knowledge_list_membership_projection where knowledge_base_id='kb-lifecycle'").fetchone()[0] == 0
    db.commit(); db.close()


def test_bootstrap_is_explicit_once_and_changes_read_does_not_reconcile(tmp_path):
    client = api(tmp_path); seed_clips(tmp_path, 50)
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    db.execute("delete from knowledge_change_events"); db.execute("delete from knowledge_list_bootstrap_state"); db.commit(); db.close()
    assert client.get("/api/knowledge/changes", headers=HEADERS).json()["changes"] == []
    first = client.post("/api/knowledge/bootstrap", headers=HEADERS).json()["bootstrap"]
    second = client.post("/api/knowledge/bootstrap", headers=HEADERS).json()["bootstrap"]
    assert first["status"] == "completed" and first["rows_recorded"] == 50 and first["already_completed"] is False
    assert second["already_completed"] is True and second["rows_recorded"] == 50
    assert len(client.get("/api/knowledge/changes", headers=HEADERS, params={"limit": 100}).json()["changes"]) == 50


def test_bootstrap_is_concurrent_idempotent_across_independent_connections(tmp_path):
    api(tmp_path); seed_clips(tmp_path, 50)
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    db.execute("delete from knowledge_change_events")
    db.execute("delete from knowledge_list_bootstrap_state")
    db.commit(); db.close()
    stores = (KnowledgeListStore(tmp_path), KnowledgeListStore(tmp_path))
    barrier = Barrier(2)

    def run(store: KnowledgeListStore) -> dict[str, object]:
        barrier.wait()
        return store.bootstrap()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, stores))

    assert sorted(bool(result["already_completed"]) for result in results) == [False, True]
    assert {int(result["rows_recorded"]) for result in results} == {50}
    status = KnowledgeListStore(tmp_path).bootstrap_status()
    assert status["status"] == "completed" and status["rows_recorded"] == 50
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    assert db.execute(
        "select count(*) from knowledge_change_events where reason='legacy_bootstrap'"
    ).fetchone()[0] == 50
    db.close()


def test_bootstrap_failure_rolls_back_state_and_can_retry(tmp_path):
    api(tmp_path); seed_clips(tmp_path, 3)
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    db.execute("delete from knowledge_change_events")
    db.execute("delete from knowledge_list_bootstrap_state")
    db.execute(
        """create trigger fail_legacy_bootstrap before insert on knowledge_change_events
        when new.reason='legacy_bootstrap' begin
          select raise(abort, 'forced bootstrap failure');
        end"""
    )
    db.commit(); db.close()
    store = KnowledgeListStore(tmp_path)

    with pytest.raises(sqlite3.IntegrityError, match="forced bootstrap failure"):
        store.bootstrap()
    assert store.bootstrap_status()["status"] == "pending"
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    assert db.execute("select count(*) from knowledge_change_events").fetchone()[0] == 0
    db.execute("drop trigger fail_legacy_bootstrap")
    db.commit(); db.close()
    retried = store.bootstrap()
    assert retried["rows_recorded"] == 3 and retried["already_completed"] is False


@pytest.mark.parametrize("route", ["/api/knowledge/clips", "/api/knowledge/summary"])
def test_route_snapshot_watermark_cannot_skip_concurrent_writer(tmp_path, monkeypatch, route):
    client = api(tmp_path); seed_clips(tmp_path, 1)
    fixed = Event(); writer_done = Event()
    original = KnowledgeListStore._latest_revision_in

    def pause_after_watermark(db):
        revision = original(db)
        fixed.set()
        assert writer_done.wait(5)
        return revision

    monkeypatch.setattr(KnowledgeListStore, "_latest_revision_in", staticmethod(pause_after_watermark))
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(client.get, route, headers=HEADERS)
        assert fixed.wait(5)
        db = sqlite3.connect(tmp_path / "perclip.sqlite3")
        insert_clip(db, 2)
        db.commit(); db.close(); writer_done.set()
        response = pending.result(timeout=5)

    payload = response.json()
    summary = payload["summary"]
    assert summary["total_count"] == summary["matching_count"] == 1
    if route.endswith("clips"):
        assert [item["public_clip_id"] for item in payload["items"]] == [f"pc_{1:032x}"]
    changes = client.get(
        "/api/knowledge/changes", headers=HEADERS,
        params={"after_revision": summary["revision"]},
    ).json()["changes"]
    assert any(change["public_clip_id"] == f"pc_{2:032x}" for change in changes)


@pytest.mark.parametrize("route", ["/api/knowledge/clips", "/api/knowledge/summary"])
def test_route_snapshot_includes_writer_committed_before_first_read(tmp_path, route):
    client = api(tmp_path); seed_clips(tmp_path, 1)
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    insert_clip(db, 2)
    db.commit()
    writer_revision = int(db.execute("select max(revision) from knowledge_change_events").fetchone()[0])
    db.close()
    payload = client.get(route, headers=HEADERS).json()
    assert payload["summary"]["total_count"] == payload["summary"]["matching_count"] == 2
    assert payload["summary"]["revision"] >= writer_revision
    if route.endswith("clips"):
        assert {item["public_clip_id"] for item in payload["items"]} == {f"pc_{1:032x}", f"pc_{2:032x}"}


@pytest.mark.parametrize("count", [0, 1, 50, 501, 5_000, 20_000])
def test_scale_keyset_query_plan_and_route_pagination(tmp_path, count):
    client = api(tmp_path); seed_clips(tmp_path, count, same_time=True)
    started = monotonic(); payload = list_page(client, limit=100); first_elapsed = monotonic() - started
    assert payload["summary"]["total_count"] == count
    assert len(payload["items"]) == min(count, 100)
    if count:
        assert first_elapsed < 5.0
    if count in {5_000, 20_000}:
        cursor = payload["next_cursor"]
        seen = {item["public_clip_id"] for item in payload["items"]}
        while cursor:
            next_page = list_page(client, limit=100, cursor=cursor)
            ids = {item["public_clip_id"] for item in next_page["items"]}
            assert not seen.intersection(ids)
            seen.update(ids); cursor = next_page["next_cursor"]
        assert len(seen) == count
    plan = KnowledgeListStore(tmp_path).query_plan(scope=("kb_default",))
    assert any("idx_knowledge_membership_keyset" in line for line in plan)
    assert not any("USE TEMP B-TREE FOR ORDER BY" in line.upper() for line in plan)
    assert not any("OFFSET" in line.upper() for line in plan)


def test_sparse_20k_single_scope_uses_membership_index_and_traverses_exactly(tmp_path):
    client = api(tmp_path); seed_clips(tmp_path, 20_000, same_time=True)
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    add_kb(db, "kb-sparse")
    add_kb(db, "kb-random")
    created = "2026-01-15T12:00:00Z"
    sparse_ids = list(range(1, 51))
    random_ids = sorted({1 + (index * 199) % 20_000 for index in range(100)})
    db.executemany(
        "insert into clip_knowledge_bases values(?,?,'manual',null,'',?)",
        [(clip_id, "kb-sparse", created) for clip_id in sparse_ids]
        + [(clip_id, "kb-random", created) for clip_id in random_ids],
    )
    db.commit(); db.close()

    started = monotonic()
    cursor = ""
    pages = []
    seen = []
    while True:
        page = list_page(client, knowledge_base_id="kb-sparse", limit=10, cursor=cursor)
        pages.append(page)
        seen.extend(item["public_clip_id"] for item in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    elapsed = monotonic() - started
    assert len(pages) == 5 and len(seen) == len(set(seen)) == 50
    assert all(len(page["items"]) == 10 for page in (pages[0], pages[2], pages[-1]))
    assert pages[0]["has_more"] is True and pages[-1]["has_more"] is False
    assert pages[0]["summary"]["total_count"] == pages[2]["summary"]["matching_count"] == 50
    summary = client.get("/api/knowledge/summary", headers=HEADERS, params={"knowledge_base_id": "kb-sparse"}).json()["summary"]
    assert summary["total_count"] == summary["matching_count"] == 50
    matching = list_page(client, knowledge_base_id="kb-sparse", query="标题 7")
    assert matching["summary"]["total_count"] == 50
    assert matching["summary"]["matching_count"] == len(matching["items"]) == 1
    assert elapsed < 5.0

    random_seen = []
    cursor = ""
    while True:
        page = list_page(client, knowledge_base_id="kb-random", limit=17, cursor=cursor)
        random_seen.extend(item["public_clip_id"] for item in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(random_seen) == len(set(random_seen)) == 100
    multi_seen = []
    cursor = ""
    while True:
        multi = list_page(client, knowledge_base_id=["kb-sparse", "kb-random"], limit=100, cursor=cursor)
        multi_seen.extend(item["public_clip_id"] for item in multi["items"])
        cursor = multi["next_cursor"]
        if not cursor:
            break
    assert len(multi_seen) == len(set(multi_seen)) == multi["summary"]["matching_count"] == 149

    store = KnowledgeListStore(tmp_path)
    first_plan = store.query_plan(scope=("kb-sparse",))
    middle_row = pages[2]["items"][-1]
    middle_plan = store.query_plan(
        scope=("kb-sparse",), after_captured_at=middle_row["captured_at"],
        after_public_clip_id=middle_row["public_clip_id"],
    )
    last_cursor_row = pages[-2]["items"][-1]
    last_plan = store.query_plan(
        scope=("kb-sparse",), after_captured_at=last_cursor_row["captured_at"],
        after_public_clip_id=last_cursor_row["public_clip_id"],
    )
    for plan in (first_plan, middle_plan, last_plan):
        assert any("SEARCH p USING INDEX idx_knowledge_membership_keyset" in line for line in plan)
        assert not any("SCAN p" in line or "idx_knowledge_list_keyset" in line for line in plan)
        assert not any("USE TEMP B-TREE FOR ORDER BY" in line.upper() for line in plan)


@pytest.mark.parametrize("ragflow", [RagflowSettings(mode="off"), RagflowSettings(mode="index")])
def test_ragflow_off_or_unconfigured_and_response_privacy(tmp_path, ragflow):
    client = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret", ragflow=ragflow)))
    seed_clips(tmp_path, 1)
    payload = list_page(client)
    serialized = json.dumps(payload)
    assert payload["items"][0]["has_attachment"] is False
    for forbidden in ("internal_clip_id", "original_path", "/archive/", "ragflow_dataset_id", "document_id", "api_key", "token"):
        assert forbidden not in serialized


def test_clip_delete_emits_remove_and_item_revision_is_per_item(tmp_path):
    client = api(tmp_path); seed_clips(tmp_path, 2)
    db = sqlite3.connect(tmp_path / "perclip.sqlite3")
    db.execute("update clips set title_hint='changed' where id=1")
    revisions = dict(db.execute("select public_clip_id,max(revision) from knowledge_change_events group by public_clip_id").fetchall())
    start = max(revisions.values())
    db.execute("delete from clips where id=1")
    db.commit(); db.close()
    changes = client.get("/api/knowledge/changes", headers=HEADERS, params={"after_revision": start}).json()["changes"]
    assert changes[-1]["operation"] == "remove" and changes[-1]["reason"] == "clip_delete"
    remaining = list_page(client)["items"]
    assert [item["public_clip_id"] for item in remaining] == [f"pc_{2:032x}"]
    assert remaining[0]["item_revision"] == revisions[f"pc_{2:032x}"]
    assert remaining[0]["updated_at"] != "2026-01-15T12:00:00Z"


@pytest.mark.parametrize("limit", [1, 50, 100])
def test_page_database_statement_count_is_bounded_independent_of_item_count(tmp_path, limit):
    api(tmp_path); seed_clips(tmp_path, 100)
    store = KnowledgeListStore(tmp_path)
    original_connect = store.connect
    statements: list[str] = []

    def traced_connect():
        connection = original_connect()
        connection.set_trace_callback(statements.append)
        return connection

    store.connect = traced_connect  # type: ignore[method-assign]
    assert len(store.page(scope=("kb_default",), limit=limit)) == limit
    select_count = len([statement for statement in statements if statement.lstrip().lower().startswith("select")])
    assert select_count == 4
