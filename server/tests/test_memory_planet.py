from __future__ import annotations

from datetime import datetime, timedelta, timezone

from perclip_ingest.memory_planet import MEMORY_PLANET_CONTRACT, build_memory_planet
from perclip_ingest.recall import RecallCandidate
from perclip_ingest.storage import ClipStore
from test_recall import HEADERS, client, public_id, save_clip


def candidate(index: int, topic_id: str, label: str, *, text: str = "") -> RecallCandidate:
    captured = datetime(2026, 7, 1, tzinfo=timezone.utc) + timedelta(days=index)
    return RecallCandidate(
        internal_clip_id=str(index),
        clip_id=f"pc_{index:032x}",
        client_request_id="",
        title=text or f"Memory {index}",
        summary=f"Summary {index}",
        reveal_text=(text or "body") * (index + 1),
        source_type="text",
        source_app="Fixture",
        url="",
        filename="",
        captured_at=captured.isoformat(),
        knowledge_base_name="",
        tags=[f"tag-{index % 3}"],
        topics=[(topic_id, label)],
        score=10,
    )


def save_clip_to_knowledge_base(tmp_path, api, *, request_id: str, title: str, knowledge_base_id: str, captured_at: str = "2026-08-04T12:00:00+00:00") -> int:
    response = api.post(
        "/api/mobile-clips",
        headers=HEADERS,
        data={
            "source_type": "text",
            "title_hint": title,
            "text": f"{title} body",
            "client_request_id": request_id,
            "captured_at": captured_at,
            "source_app": "Fixture",
            "target_knowledge_base_id": knowledge_base_id,
        },
    )
    assert response.status_code == 200, response.text
    store = ClipStore(tmp_path)
    raw = store.find_raw_fields_by_client_request_id(request_id)
    assert raw is not None
    store.save_enrichment(
        clip_id=raw.id,
        client_request_id=request_id,
        knowledge_base_id=knowledge_base_id,
        route_decision_id=None,
        engine="deterministic.v1",
        status="completed",
        title=title,
        summary=f"{title} summary",
        tags=[title],
        language="en",
        extracted_text=f"{title} body",
    )
    return raw.id


def test_planet_caps_topics_and_memories_without_fake_fill_or_duplicates():
    candidates = [
        candidate(topic * 10 + item, f"topic_{topic}", f"Topic {topic}")
        for topic in range(6) for item in range(7)
    ]
    candidates.append(candidate(100, "topic_0", "Topic 0", text="same duplicate"))
    candidates.append(candidate(101, "topic_0", "Topic 0", text="same duplicate"))
    planet = build_memory_planet(
        candidates,
        window={"kind": "month", "days": 30, "start": "", "end": ""},
    )
    assert planet["contract_version"] == MEMORY_PLANET_CONTRACT
    assert len(planet["topics"]) == 5
    assert all(1 <= len(topic["memories"]) <= 5 for topic in planet["topics"])
    for topic in planet["topics"]:
        ids = [memory["clip_id"] for memory in topic["memories"]]
        assert len(ids) == len(set(ids))
        assert all(clip_id.startswith("pc_") for clip_id in ids)


def test_unclassified_threshold_and_deferred_suppression():
    candidates = [
        candidate(1, "ai_ml", "AI与大模型"),
        candidate(2, "ai_ml", "AI与大模型"),
        candidate(3, "ai_ml", "AI与大模型"),
        candidate(4, "ai_ml", "AI与大模型"),
        candidate(5, "ai_ml", "AI与大模型"),
        candidate(6, "unclassified", "待归类"),
    ]
    hidden = build_memory_planet(candidates, window={"kind": "week", "days": 7})
    assert "unclassified" not in {topic["topic_id"] for topic in hidden["topics"]}
    assert hidden["unclassified_count"] == 1
    assert len(hidden["unclassified_preview"]) == 1
    assert hidden["has_more_unclassified"] is False

    candidates.extend(
        [candidate(7, "unclassified", "待归类"), candidate(8, "unclassified", "待归类")]
    )
    stats = {"7": {"last_deferred_at": "2026-07-20T00:00:00+00:00", "last_viewed_at": ""}}
    visible = build_memory_planet(
        candidates, window={"kind": "week", "days": 7}, stats=stats
    )
    unclassified = next(topic for topic in visible["topics"] if topic["topic_id"] == "unclassified")
    assert all(memory["clip_id"] != f"pc_{7:032x}" for memory in unclassified["memories"])
    assert "internal_clip_id" not in str(visible)


def test_small_unclassified_preview_never_consumes_five_main_topic_slots():
    candidates = [
        candidate(index + 1, f"topic_{index}", f"Topic {index}")
        for index in range(5)
    ]
    candidates.extend(
        candidate(20 + index, "topic_0", "Topic 0") for index in range(5)
    )
    candidates.extend(
        [
            candidate(40, "unclassified", "待归类"),
            candidate(41, "unclassified", "待归类"),
        ]
    )
    planet = build_memory_planet(candidates, window={"kind": "month", "days": 30})
    assert len(planet["topics"]) == 5
    assert "unclassified" not in {topic["topic_id"] for topic in planet["topics"]}
    assert planet["unclassified_count"] == 2
    assert len(planet["unclassified_preview"]) == 2
    assert planet["has_more_unclassified"] is False


def test_unclassified_is_main_topic_at_three_or_exactly_twenty_percent():
    three = [
        *(candidate(index, "ai_ml", "AI与大模型") for index in range(1, 13)),
        *(candidate(20 + index, "unclassified", "待归类") for index in range(3)),
    ]
    three_planet = build_memory_planet(three, window={"kind": "month", "days": 30})
    assert "unclassified" in {
        topic["topic_id"] for topic in three_planet["topics"]
    }
    assert three_planet["has_more_unclassified"] is False

    exact_twenty = [
        *(candidate(index, "ai_ml", "AI与大模型") for index in range(1, 5)),
        candidate(10, "unclassified", "待归类"),
    ]
    twenty_planet = build_memory_planet(
        exact_twenty, window={"kind": "week", "days": 7}
    )
    assert "unclassified" in {
        topic["topic_id"] for topic in twenty_planet["topics"]
    }


def test_unclassified_preview_ignores_temporary_defer_and_applies_persistent_suppression():
    candidates = [
        *(candidate(index, "ai_ml", "AI与大模型") for index in range(1, 8)),
        *(candidate(20 + index, "unclassified", "待归类") for index in range(5)),
    ]
    deferred_stats = {
        "21": {
            "last_deferred_at": "2026-07-20T00:00:00+00:00",
            "last_viewed_at": "",
        }
    }
    deferred = build_memory_planet(
        candidates, window={"kind": "month", "days": 30}, stats=deferred_stats
    )
    assert deferred["unclassified_count"] == 5

    suppressed = build_memory_planet(
        candidates,
        window={"kind": "month", "days": 30},
        stats={"21": {"suppressed": True}},
    )
    assert suppressed["unclassified_count"] == 4
    assert len(suppressed["unclassified_preview"]) == 3
    assert suppressed["has_more_unclassified"] is True
    serialized = str(suppressed)
    assert f"pc_{21:032x}" not in serialized
    assert "internal_clip_id" not in serialized


def test_custom_window_uses_actual_dates_timezone_and_non_fourteen_day_span(tmp_path):
    api = client(tmp_path)
    included = public_id(
        api,
        save_clip(
            tmp_path,
            api,
            request_id="custom-included",
            title="Included",
            text="body",
            tags=["Fixture"],
            captured_at="2026-07-03T12:00:00+00:00",
        ),
    )
    excluded = public_id(
        api,
        save_clip(
            tmp_path,
            api,
            request_id="custom-excluded",
            title="Excluded",
            text="body",
            tags=["Fixture"],
            captured_at="2026-07-08T12:00:00+00:00",
        ),
    )
    response = api.get(
        "/api/memory-planet?window=custom&start=2026-07-01&end=2026-07-05&timezone=Asia%2FShanghai",
        headers=HEADERS,
    )
    assert response.status_code == 200
    planet = response.json()["planet"]
    assert planet["window"]["days"] == 5
    assert planet["window"]["start_date"] == "2026-07-01"
    assert planet["window"]["end_date"] == "2026-07-05"
    assert planet["window"]["timezone"] == "Asia/Shanghai"
    assert included in str(planet)
    assert excluded not in str(planet)


def test_custom_window_rejects_format_order_span_timezone_and_legacy_days(tmp_path):
    api = client(tmp_path)
    invalid_queries = [
        "start=2026-7-01&end=2026-07-05&timezone=UTC",
        "start=2026-07-06&end=2026-07-05&timezone=UTC",
        "start=2026-01-01&end=2026-07-05&timezone=UTC",
        "start=2026-07-01&end=2026-07-05&timezone=Not%2FAZone",
        "days=14",
    ]
    for query in invalid_queries:
        assert api.get(
            f"/api/memory-planet?window=custom&{query}",
            headers=HEADERS,
        ).status_code == 422


def test_memory_planet_and_domain_scope_each_knowledge_base_independently(tmp_path):
    api = client(tmp_path)
    captured_at = datetime.now(timezone.utc).isoformat()
    target = api.post(
        "/api/knowledge-bases",
        headers=HEADERS,
        json={"name": "Development test"},
    ).json()["knowledge_base"]
    save_clip(
        tmp_path,
        api,
        request_id="planet-default-only",
        title="Default only",
        text="default body",
        tags=["Default topic"],
        captured_at=captured_at,
    )
    save_clip_to_knowledge_base(
        tmp_path,
        api,
        request_id="planet-target-only",
        title="Target only",
        knowledge_base_id=target["id"],
        captured_at=captured_at,
    )

    domain = api.get(
        f"/api/recall/domain?days=7&knowledge_base_id={target['id']}",
        headers=HEADERS,
    )
    planet = api.get(
        f"/api/memory-planet?window=week&knowledge_base_id={target['id']}",
        headers=HEADERS,
    )

    assert domain.status_code == 200, domain.text
    assert planet.status_code == 200, planet.text
    assert domain.json()["knowledge_base_id"] == target["id"]
    assert planet.json()["planet"]["window"]["knowledge_base_id"] == target["id"]
    assert "Target only" in str(domain.json())
    assert "Default only" not in str(domain.json())
    assert "Target only" in str(planet.json())
    assert "Default only" not in str(planet.json())
    assert api.get(
        "/api/memory-planet?window=week&knowledge_base_id=missing",
        headers=HEADERS,
    ).status_code == 404
