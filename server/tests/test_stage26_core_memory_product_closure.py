from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient

from perclip_ingest.config import Settings
from perclip_ingest.main import create_app


HEADERS = {"Authorization": "Bearer secret"}
ROOT = Path(__file__).resolve().parents[2]
CORE_RECALL_PLAN = ROOT / "docs/quality/candidates/stage25-3-core-recall-gap-plan-v1.json"
CLIP_COLUMNS = """id,client_request_id,source_type,title_hint,note,text,url,mime_type,
device_name,source_app,captured_at,filename,size_bytes,original_path,content_hash,
ragflow_document_id,archive_status,capture_client_batch_id,capture_parent_client_request_id,
capture_part_index,capture_part_count,capture_part_role,created_at"""


def _client(data_dir: Path) -> TestClient:
    return TestClient(create_app(Settings(data_dir=data_dir, ingest_token="secret")))


def _seed_core_memory_fixture(data_dir: Path) -> list[dict[str, object]]:
    plan = json.loads(CORE_RECALL_PLAN.read_text(encoding="utf-8"))
    cases = list(plan["cases"])
    assert len(cases) == 60
    assert Counter(str(item["source_platform"]) for item in cases) == {
        "bilibili": 10,
        "douyin": 10,
        "wechat_official_account": 10,
        "xiaohongshu": 10,
        "web": 10,
        "zhihu": 10,
    }

    db = sqlite3.connect(data_dir / "perclip.sqlite3")
    now = "2026-08-25T00:00:00Z"
    db.execute(
        """insert or ignore into knowledge_bases(
        id,name,description,icon,color,is_default,is_archived,ragflow_dataset_id,
        ragflow_dataset_name,template_key,created_at,updated_at,deleted_at)
        values('kb_default','个人收藏','','','',1,0,'','','general',?,?,'')""",
        (now, now),
    )
    for index, case in enumerate(cases, start=1):
        sample_id = str(case["sample_id"])
        platform = str(case["source_platform"])
        title = f"Core Memory {sample_id}"
        captured = f"2026-08-{(index % 25) + 1:02d}T{index % 24:02d}:00:00Z"
        values = (
            index,
            f"stage26:{sample_id}",
            "url",
            title,
            "",
            "",
            "",
            "text/plain",
            "",
            platform,
            captured,
            "",
            0,
            "",
            f"stage26-safe-{index}",
            "",
            "ready",
            "",
            "",
            0,
            1,
            "single",
            captured,
        )
        db.execute(
            f"insert into clips({CLIP_COLUMNS}) values ({','.join('?' for _ in range(23))})",
            values,
        )
        public_id = f"pc_{index:032x}"
        db.execute(
            "insert into clip_identities(clip_id,public_id,created_at) values(?,?,?)",
            (index, public_id, captured),
        )
        db.execute(
            """insert into clip_knowledge_bases(
            clip_id,knowledge_base_id,association_type,route_decision_id,association_intent_id,created_at)
            values(?,'kb_default','imported',null,'',?)""",
            (index, captured),
        )

        states = dict(case["availability_states"])
        author_state = str(states["source_identity"])
        content_state = str(states["core_content"])
        author = f"发布者 {platform}" if author_state == "resolved" else "矛盾来源值"
        metadata = {
            "processing": {
                "active_projection": {
                    "structured_metadata": {
                        "author": {"value": author, "resolution_state": author_state},
                        "core_content": {
                            "value": "矛盾正文值" if content_state == "explicit_unavailable" else "",
                            "resolution_state": content_state,
                        },
                    }
                }
            }
        }
        db.execute(
            """insert into clip_metadata(
            clip_id,client_request_id,contract_version,metadata_json,created_at)
            values(?,?,?,?,?)""",
            (index, f"stage26:{sample_id}", "perclip.clip.v1", json.dumps(metadata, ensure_ascii=False), captured),
        )
        if content_state == "resolved":
            db.execute(
                """insert into clip_enrichments(
                clip_id,engine,status,title,summary,created_at,updated_at)
                values(?,'stage26.fixture','completed',?,?,?,?)""",
                (str(index), title, f"核心内容 {sample_id}", captured, captured),
            )
    db.commit()
    db.close()
    return cases


def _all_items(client: TestClient) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    cursor = ""
    while True:
        response = client.get(
            "/api/knowledge/clips",
            headers=HEADERS,
            params={"limit": 50, "cursor": cursor},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        items.extend(payload["items"])
        cursor = str(payload["next_cursor"])
        if not cursor:
            assert payload["summary"]["total_count"] == 60
            break
    return items


def test_full_60_core_memories_persist_and_each_title_keyword_matches(tmp_path):
    client = _client(tmp_path)
    cases = _seed_core_memory_fixture(tmp_path)

    initial = _all_items(client)
    assert len(initial) == len({item["public_clip_id"] for item in initial}) == 60

    restarted = _client(tmp_path)
    persisted = _all_items(restarted)
    assert [item["public_clip_id"] for item in persisted] == [item["public_clip_id"] for item in initial]

    for case in cases:
        sample_id = str(case["sample_id"])
        response = restarted.get(
            "/api/knowledge/clips",
            headers=HEADERS,
            params={"query": sample_id},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["summary"]["matching_count"] == 1
        assert [item["title"] for item in payload["items"]] == [f"Core Memory {sample_id}"]

    cleared = restarted.get("/api/knowledge/clips", headers=HEADERS, params={"query": ""}).json()
    assert cleared["summary"]["matching_count"] == 60


def test_full_60_list_and_detail_states_stay_source_faithful(tmp_path):
    client = _client(tmp_path)
    cases = _seed_core_memory_fixture(tmp_path)
    items = {item["title"].removeprefix("Core Memory "): item for item in _all_items(client)}

    unknown = unavailable = 0
    for case in cases:
        sample_id = str(case["sample_id"])
        states = dict(case["availability_states"])
        item = items[sample_id]
        if states["source_identity"] == "explicit_unknown":
            unknown += 1
            assert item["source"] == "未明确来源"
        else:
            assert item["source"].startswith("发布者 ")
        if states["core_content"] == "explicit_unavailable":
            unavailable += 1
            assert item["summary"] == "内容暂不可用"
        else:
            assert item["summary"] == f"核心内容 {sample_id}"

    assert unknown == 12
    assert unavailable == 10
