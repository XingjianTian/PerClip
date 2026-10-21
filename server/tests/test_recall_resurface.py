import base64
import json
import re
from test_recall import HEADERS, client, public_id, save_clip
from fastapi.testclient import TestClient
from perclip_ingest.config import Settings
from perclip_ingest.main import create_app
from perclip_ingest.recall import topic_id
from perclip_ingest.storage import ClipStore
from datetime import datetime, timezone


def add_event(api, *, event_id, action, clip_id, occurred_at=None):
    event_time = occurred_at or datetime.now(timezone.utc).isoformat()
    return api.post("/api/recall/interactions", headers=HEADERS, json={"client_event_id": event_id, "surface": "resurface", "action": action, "clip_id": str(clip_id), "node_id": f"clip:{clip_id}", "occurred_at": event_time})


def test_resurface_uses_snapshot_bound_cursor_and_real_scores(tmp_path):
    api = client(tmp_path)
    for number, label in enumerate(("Alpha", "Beta", "Gamma"), 1):
        save_clip(tmp_path, api, request_id=f"surface-{number}", title=label, text="body", tags=[label])
    first = api.get("/api/recall/resurface?limit=1", headers=HEADERS)
    assert first.status_code == 200
    payload = first.json()
    assert payload["items"] and payload["next_cursor"] and payload["items"][0]["score"] >= 0
    assert isinstance(payload["items"][0]["reason_codes"], list)
    second = api.get(f"/api/recall/resurface?limit=1&cursor={payload['next_cursor']}", headers=HEADERS)
    assert second.status_code == 200
    assert second.json()["items"][0]["clip_id"] != payload["items"][0]["clip_id"]
    assert api.get("/api/recall/resurface?cursor=not-a-cursor", headers=HEADERS).status_code == 422
    save_clip(tmp_path, api, request_id="surface-new", title="New", text="body", tags=["Delta"])
    assert api.get(f"/api/recall/resurface?cursor={payload['next_cursor']}", headers=HEADERS).status_code == 409


def test_domain_and_resurface_custom_range_share_the_exact_timezone_window(tmp_path):
    api = client(tmp_path)
    query = "days=5&start=2026-07-01&end=2026-07-05&timezone=Asia%2FShanghai"
    domain = api.get(f"/api/recall/domain?{query}", headers=HEADERS)
    resurface = api.get(f"/api/recall/resurface?{query}", headers=HEADERS)
    assert domain.status_code == 200
    assert resurface.status_code == 200
    assert domain.json()["window"] == resurface.json()["window"]
    assert domain.json()["window"] == {
        "days": 5,
        "start": "2026-06-30T16:00:00+00:00",
        "end": "2026-07-05T16:00:00+00:00",
    }
    assert api.get(
        "/api/recall/domain?days=4&start=2026-07-01&end=2026-07-05&timezone=Asia%2FShanghai",
        headers=HEADERS,
    ).status_code == 422


def test_resurface_balances_topics_and_uses_viewed_not_any_action_for_last_viewed(tmp_path):
    api = client(tmp_path)
    alpha = [public_id(api, save_clip(tmp_path, api, request_id=f"alpha-{i}", title="Alpha", text="body", tags=["Alpha"])) for i in range(3)]
    beta = save_clip(tmp_path, api, request_id="beta", title="Beta", text="body", tags=["Beta"])
    assert add_event(api, event_id="deferred", action="defer", clip_id=alpha[0]).status_code == 200
    page = api.get("/api/recall/resurface?limit=3", headers=HEADERS).json()
    labels = [item["topic_label"] for item in page["items"]]
    assert labels == ["待归类", "待归类", "待归类"]
    deferred = next(item for item in api.get("/api/recall/resurface?limit=20", headers=HEADERS).json()["items"] if item["clip_id"] == alpha[0])
    assert deferred["last_viewed_at"] == "" and "recently_deferred" in deferred["reason_codes"]


def test_resurface_respects_preferred_muted_topic_and_exclusions(tmp_path):
    api = client(tmp_path)
    alpha = public_id(api, save_clip(tmp_path, api, request_id="res-alpha", title="Alpha", text="body", tags=["Alpha"]))
    beta = save_clip(tmp_path, api, request_id="res-beta", title="Beta", text="body", tags=["Beta"])
    assert api.patch("/api/recall/preferences", headers=HEADERS, json={"muted_topic_ids": ["unclassified"]}).status_code == 200
    payload = api.get(f"/api/recall/resurface?limit=20&exclude_clip_ids={alpha}", headers=HEADERS).json()
    assert not payload["items"]
    filtered = api.get("/api/recall/resurface?topic_id=unclassified", headers=HEADERS).json()
    assert filtered["items"] == []


def test_suppress_restore_are_persistent_idempotent_and_distinct_from_defer(tmp_path):
    api = client(tmp_path)
    internal_id = save_clip(
        tmp_path,
        api,
        request_id="persistent-suppress",
        title="Recoverable",
        text="body",
        tags=["Fixture"],
    )
    clip_id = public_id(api, internal_id)

    assert add_event(
        api, event_id="temporary-defer", action="defer", clip_id=clip_id
    ).status_code == 200
    assert clip_id in {
        item["clip_id"]
        for item in api.get("/api/recall/resurface?limit=20", headers=HEADERS).json()["items"]
    }

    event_time = datetime.now(timezone.utc).isoformat()
    assert add_event(
        api, event_id="persistent-hide", action="suppress", clip_id=clip_id,
        occurred_at=event_time,
    ).status_code == 200
    replayed = add_event(
        api, event_id="persistent-hide", action="suppress", clip_id=clip_id,
        occurred_at=event_time,
    )
    assert replayed.status_code == 200
    assert replayed.json()["replayed"] is True
    assert clip_id not in {
        item["clip_id"]
        for item in api.get("/api/recall/resurface?limit=20", headers=HEADERS).json()["items"]
    }
    assert clip_id not in str(
        api.get("/api/memory-planet?window=week", headers=HEADERS).json()
    )

    restarted = client(tmp_path)
    suppression_list = restarted.get("/api/recall/suppressions", headers=HEADERS).json()
    assert [item["clip_id"] for item in suppression_list["items"]] == [clip_id]
    assert "internal_clip_id" not in str(suppression_list)

    restore_time = datetime.now(timezone.utc).isoformat()
    assert add_event(
        restarted, event_id="persistent-restore", action="restore", clip_id=clip_id,
        occurred_at=restore_time,
    ).status_code == 200
    restore_replay = add_event(
        restarted, event_id="persistent-restore", action="restore", clip_id=clip_id,
        occurred_at=restore_time,
    )
    assert restore_replay.status_code == 200
    assert restore_replay.json()["replayed"] is True
    assert restarted.get("/api/recall/suppressions", headers=HEADERS).json()["items"] == []
    stale_suppress_replay = add_event(
        restarted, event_id="persistent-hide", action="suppress", clip_id=clip_id,
        occurred_at=event_time,
    )
    assert stale_suppress_replay.status_code == 200
    assert stale_suppress_replay.json()["replayed"] is True
    assert restarted.get("/api/recall/suppressions", headers=HEADERS).json()["items"] == []
    assert clip_id in {
        item["clip_id"]
        for item in restarted.get("/api/recall/resurface?limit=20", headers=HEADERS).json()["items"]
    }


def test_suppress_and_restore_roll_back_event_and_state_then_same_id_retries(tmp_path):
    bootstrap = client(tmp_path)
    internal_id = save_clip(
        tmp_path,
        bootstrap,
        request_id="atomic-suppression",
        title="Atomic",
        text="body",
        tags=["Fixture"],
    )
    clip_id = public_id(bootstrap, internal_id)
    failures_remaining = 1

    def fail_once():
        nonlocal failures_remaining
        if failures_remaining:
            failures_remaining -= 1
            raise RuntimeError("injected after event insert")

    faulting = TestClient(
        create_app(
            Settings(data_dir=tmp_path, ingest_token="secret"),
            recall_fault_after_event_insert=fail_once,
        ),
        raise_server_exceptions=False,
    )
    event_time = datetime.now(timezone.utc).isoformat()
    failed = add_event(
        faulting,
        event_id="atomic-suppress",
        action="suppress",
        clip_id=clip_id,
        occurred_at=event_time,
    )
    assert failed.status_code == 500
    with ClipStore(tmp_path).connect() as db:
        assert db.execute(
            "select 1 from recall_surface_events where client_event_id='atomic-suppress'"
        ).fetchone() is None
        assert db.execute(
            "select 1 from recall_suppressions where clip_id=?", (str(internal_id),)
        ).fetchone() is None

    retried = add_event(
        faulting,
        event_id="atomic-suppress",
        action="suppress",
        clip_id=clip_id,
        occurred_at=event_time,
    )
    assert retried.status_code == 200
    assert retried.json()["replayed"] is False
    assert [item["clip_id"] for item in faulting.get(
        "/api/recall/suppressions", headers=HEADERS
    ).json()["items"]] == [clip_id]

    restore_failures = 1

    def fail_restore_once():
        nonlocal restore_failures
        if restore_failures:
            restore_failures -= 1
            raise RuntimeError("injected after restore event insert")

    restore_client = TestClient(
        create_app(
            Settings(data_dir=tmp_path, ingest_token="secret"),
            recall_fault_after_event_insert=fail_restore_once,
        ),
        raise_server_exceptions=False,
    )
    restore_time = datetime.now(timezone.utc).isoformat()
    failed_restore = add_event(
        restore_client,
        event_id="atomic-restore",
        action="restore",
        clip_id=clip_id,
        occurred_at=restore_time,
    )
    assert failed_restore.status_code == 500
    with ClipStore(tmp_path).connect() as db:
        assert db.execute(
            "select 1 from recall_surface_events where client_event_id='atomic-restore'"
        ).fetchone() is None
    assert restore_client.get(
        "/api/recall/suppressions", headers=HEADERS
    ).json()["items"]

    retried_restore = add_event(
        restore_client,
        event_id="atomic-restore",
        action="restore",
        clip_id=clip_id,
        occurred_at=restore_time,
    )
    assert retried_restore.status_code == 200
    assert retried_restore.json()["replayed"] is False
    assert restore_client.get(
        "/api/recall/suppressions", headers=HEADERS
    ).json()["items"] == []


def test_suppression_recovery_is_bounded_and_cursor_paginated(tmp_path):
    api = client(tmp_path)
    clip_ids = []
    for index in range(7):
        internal_id = save_clip(
            tmp_path,
            api,
            request_id=f"suppression-page-{index}",
            title=f"Recoverable {index}",
            text="body",
            tags=["Fixture"],
        )
        clip_id = public_id(api, internal_id)
        clip_ids.append(clip_id)
        response = add_event(
            api,
            event_id=f"suppression-page-{index}",
            action="suppress",
            clip_id=clip_id,
        )
        assert response.status_code == 200

    first = api.get("/api/recall/suppressions?limit=5", headers=HEADERS)
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["items"]) == 5
    assert first_body["next_cursor"].startswith("kc_")
    encoded_cursor = first_body["next_cursor"][3:]
    cursor_payload = json.loads(
        base64.urlsafe_b64decode(
            encoded_cursor + "=" * (-len(encoded_cursor) % 4)
        ).decode()
    )
    assert set(cursor_payload) == {
        "v",
        "direction",
        "updated_at",
        "public_clip_id",
    }
    assert cursor_payload["v"] == 2
    assert cursor_payload["direction"] == "next"
    assert re.fullmatch(r"pc_[0-9a-f]{32}", cursor_payload["public_clip_id"])
    assert all(
        not str(value).isdigit()
        for key, value in cursor_payload.items()
        if key != "v"
    )
    second = api.get(
        f"/api/recall/suppressions?limit=5&cursor={first_body['next_cursor']}",
        headers=HEADERS,
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["previous_cursor"].startswith("kc_")
    recovered_ids = {
        item["clip_id"] for item in first_body["items"] + second_body["items"]
    }
    assert recovered_ids == set(clip_ids)
    assert second_body["next_cursor"] == ""
    previous = api.get(
        f"/api/recall/suppressions?limit=5&cursor={second_body['previous_cursor']}",
        headers=HEADERS,
    )
    assert previous.status_code == 200
    assert [item["clip_id"] for item in previous.json()["items"]] == [
        item["clip_id"] for item in first_body["items"]
    ]
    assert previous.json()["previous_cursor"] == ""
    assert previous.json()["next_cursor"]
    assert api.get("/api/recall/suppressions?limit=101", headers=HEADERS).status_code == 422


def test_all_501_suppressions_are_pageable_restorable_and_refreshable(tmp_path):
    api = client(tmp_path)
    for index in range(501):
        internal_id = save_clip(
            tmp_path,
            api,
            request_id=f"suppression-501-{index:03d}",
            title=f"Suppression {index:03d}",
            text="synthetic paging fixture",
            tags=["Fixture"],
        )
        ClipStore(tmp_path).set_recall_suppressed(str(internal_id), True)

    pages = []
    cursor = ""
    seen = set()
    while True:
        response = api.get(
            "/api/recall/suppressions",
            params={"limit": 50, "cursor": cursor},
            headers=HEADERS,
        )
        assert response.status_code == 200
        page = response.json()
        page_ids = [item["clip_id"] for item in page["items"]]
        assert not (seen & set(page_ids))
        seen.update(page_ids)
        pages.append(page)
        cursor = page["next_cursor"]
        if not cursor:
            break

    assert len(seen) == 501
    assert len(pages) == 11
    assert len(pages[-1]["items"]) == 1
    assert pages[-1]["previous_cursor"]
    assert pages[-1]["next_cursor"] == ""

    last_item = pages[-1]["items"][0]
    restored = add_event(
        api,
        event_id="restore-item-501",
        action="restore",
        clip_id=last_item["clip_id"],
    )
    assert restored.status_code == 200

    previous = api.get(
        "/api/recall/suppressions",
        params={"limit": 50, "cursor": pages[-1]["previous_cursor"]},
        headers=HEADERS,
    )
    assert previous.status_code == 200
    previous_body = previous.json()
    assert len(previous_body["items"]) == 50
    assert len({item["clip_id"] for item in previous_body["items"]}) == 50
    assert previous_body["next_cursor"] == ""

    refreshed = api.get(
        "/api/recall/suppressions",
        params={"limit": 50},
        headers=HEADERS,
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["cursor"] == ""
    assert refreshed.json()["previous_cursor"] == ""
    assert len(refreshed.json()["items"]) == 50
