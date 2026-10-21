from test_recall import HEADERS, client, public_id, save_clip
from perclip_ingest.recall import topic_id


def event(**overrides):
    value = {"client_event_id": "event-1", "surface": "resurface", "action": "viewed", "clip_id": "1", "node_id": "clip:1", "metadata": {"dwell_ms": 1}}
    value.update(overrides)
    return value


def test_interaction_is_typed_idempotent_and_returns_normalized_target(tmp_path):
    api = client(tmp_path)
    clip = public_id(api, save_clip(tmp_path, api, request_id="interaction", title="One", text="body", tags=["Topic"]))
    response = api.post("/api/recall/interactions", headers=HEADERS, json=event(clip_id=clip, node_id=f"clip:{clip}"))
    assert response.status_code == 200
    body = response.json()
    assert body["replayed"] is False and body["event_id"] == "event-1"
    assert body["target"] == {"node_id": f"clip:{clip}", "topic_id": "", "clip_id": clip}
    replay = api.post("/api/recall/interactions", headers=HEADERS, json=event(clip_id=clip, node_id=f"clip:{clip}"))
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert api.post("/api/recall/interactions", headers=HEADERS, json=event(clip_id=clip, node_id=f"clip:{clip}", metadata={"dwell_ms": 2})).status_code == 409


def test_interactions_reject_invalid_targets_metadata_and_secret_like_identifiers(tmp_path):
    api = client(tmp_path)
    bad = [
        event(action="open_topic", topic_id=""), event(action="open_original", clip_id=""),
        event(metadata={"dwell_ms": True}), event(metadata={"visible_label_count": 6}),
        event(metadata={"source": "x" * 41}), event(metadata={"source": {"nested": 1}}),
        event(metadata={"position": [1]}), event(client_event_id="token=secret"),
        event(node_id="https://user:password@example.test"), event(topic_id="topic:bad\nsecret"),
    ]
    for payload in bad:
        assert api.post("/api/recall/interactions", headers=HEADERS, json=payload).status_code == 422


def test_interaction_action_target_forms_are_normalized(tmp_path):
    api = client(tmp_path)
    clip = public_id(api, save_clip(tmp_path, api, request_id="target", title="One", text="body", tags=["Topic"]))
    identifier = topic_id("Topic")
    cases = [
        event(client_event_id="topic", action="open_topic", topic_id=identifier, clip_id="", node_id=""),
        event(client_event_id="memory", action="open_memory", clip_id=clip, node_id=f"clip:{clip}"),
        event(client_event_id="impression", action="impression", clip_id="", node_id=identifier),
    ]
    for payload in cases:
        assert api.post("/api/recall/interactions", headers=HEADERS, json=payload).status_code == 200
