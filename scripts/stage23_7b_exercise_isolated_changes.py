#!/usr/bin/env python3
"""Exercise topic, move, and delete changes against a disposable Stage 23.7B fixture."""

from __future__ import annotations

import argparse
import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:18087")
    parser.add_argument("--token", default="stage23-7b-synthetic-token")
    args = parser.parse_args()

    def request(
        method: str,
        path: str,
        payload: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Authorization": f"Bearer {args.token}", "Content-Type": "application/json"}
        headers.update(extra_headers or {})
        call = urllib.request.Request(
            args.base_url.rstrip("/") + path,
            data=data,
            method=method,
            headers=headers,
        )
        with urllib.request.urlopen(call, timeout=10) as response:
            return json.load(response)

    initial = request("GET", "/api/knowledge/changes?limit=1")
    after_revision = int(initial["current_revision"])
    topic_id = "pc_" + f"{1:032x}"
    move_id = "pc_" + f"{2:032x}"
    delete_id = "pc_" + f"{3:032x}"
    concurrent_id = "pc_" + f"{4:032x}"

    search_before = request("GET", "/api/knowledge/summary?query=ALPHA-499")["summary"]["matching_count"]
    source_before = request(
        "GET", "/api/knowledge/summary?" + urllib.parse.urlencode({"source": "Synthetic Files"})
    )["summary"]["matching_count"]
    type_before = request("GET", "/api/knowledge/summary?source_type=file")["summary"]["matching_count"]
    with sqlite3.connect(args.data_dir / "perclip.sqlite3") as database:
        database.execute("update clips set title_hint='Synthetic deep-page marker removed' where id=499")
        database.execute("update clips set source_app='Synthetic Moved',source_type='url' where id=7")
    search_after = request("GET", "/api/knowledge/summary?query=ALPHA-499")["summary"]["matching_count"]
    source_after = request(
        "GET", "/api/knowledge/summary?" + urllib.parse.urlencode({"source": "Synthetic Files"})
    )["summary"]["matching_count"]
    type_after = request("GET", "/api/knowledge/summary?source_type=file")["summary"]["matching_count"]
    assert (search_before, search_after) == (1, 0)
    assert source_after == source_before - 1
    assert type_after == type_before - 1

    try:
        request(
            "GET",
            "/api/knowledge/changes?limit=1",
            extra_headers={"X-PerClip-Synthetic-Fail-Changes": "1"},
        )
    except urllib.error.HTTPError as error:
        assert error.code == 503
    else:
        raise AssertionError("synthetic changes failure was not injected")

    concurrent_page = request(
        "GET",
        "/api/knowledge/clips?limit=1",
        extra_headers={"X-PerClip-Synthetic-Insert-During-List": "1"},
    )
    page_revision = int(concurrent_page["summary"]["revision"])
    concurrent_query = urllib.parse.urlencode({"after_revision": page_revision, "limit": 100})
    concurrent_changes = request("GET", f"/api/knowledge/changes?{concurrent_query}")["changes"]
    assert any(change["public_clip_id"] == concurrent_id for change in concurrent_changes)

    request("PUT", f"/api/clips/{topic_id}/topic-assignment", {"topic_id": "work_projects"})

    with sqlite3.connect(args.data_dir / "perclip.sqlite3") as database:
        # These disposable producer-side mutations exercise the frozen
        # membership and Clip-delete trigger/outbox contracts without a worker.
        database.execute("delete from clip_knowledge_bases where clip_id=2 and knowledge_base_id='kb_default'")
        database.execute(
            """insert into clip_knowledge_bases(
                   clip_id,knowledge_base_id,association_type,route_decision_id,association_intent_id,created_at)
               values(2,'kb-secondary','manual',null,'stage23-7b-move','2026-01-01T00:00:00Z')"""
        )
        database.execute("delete from clips where id=3")
        database.execute("delete from clip_knowledge_bases where clip_id=3")
        database.execute("delete from clip_identities where clip_id=3")

    query = urllib.parse.urlencode({"after_revision": after_revision, "limit": 100})
    changes = request("GET", f"/api/knowledge/changes?{query}")["changes"]
    changed_ids = {change["public_clip_id"] for change in changes}
    assert {topic_id, move_id, delete_id} <= changed_ids
    assert any(change["public_clip_id"] == topic_id and change["reason"] == "topic_update" for change in changes)
    assert any(
        change["public_clip_id"] == move_id
        and change.get("item", {}).get("knowledge_base_ids") == ["kb-secondary"]
        for change in changes
    )
    assert any(change["public_clip_id"] == delete_id and change["operation"] == "remove" for change in changes)
    print(json.dumps({
        "change_count": len(changes),
        "search_revalidated": [search_before, search_after],
        "source_filter_revalidated": [source_before, source_after],
        "type_filter_revalidated": [type_before, type_after],
        "changes_failure_injected": True,
        "concurrent_event_after_page_revision": True,
        "has_topic_update": True,
        "has_membership_move": True,
        "has_global_remove": True,
        "next_revision": max(change["revision"] for change in changes),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
