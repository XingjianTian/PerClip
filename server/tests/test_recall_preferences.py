from test_recall import HEADERS, client, save_clip
from perclip_ingest.recall import topic_id


def test_preferences_defaults_validation_deduplication_and_overlap_policy(tmp_path):
    api = client(tmp_path)
    identifier = topic_id("Topic")
    initial = api.get("/api/recall/preferences", headers=HEADERS).json()["preferences"]
    assert initial["default_days"] == 30 and initial["include_memory_labels"] is True
    updated = api.patch("/api/recall/preferences", headers=HEADERS, json={"visible_label_count": 4, "preferred_topic_ids": [identifier, identifier], "muted_topic_ids": [identifier]} )
    assert updated.status_code == 200
    preferences = updated.json()["preferences"]
    assert preferences["preferred_topic_ids"] == []  # muted wins over preferred
    assert preferences["muted_topic_ids"] == [identifier]
    for body in ({"default_days": True}, {"preferred_topic_ids": ["bad"]}, {"unknown": 1}, {"include_memory_labels": 1}):
        assert api.patch("/api/recall/preferences", headers=HEADERS, json=body).status_code == 422


def test_new_endpoints_use_default_days_only_when_omitted_and_legacy_stays_seven(tmp_path):
    api = client(tmp_path)
    save_clip(tmp_path, api, request_id="pref", title="Topic", text="body", tags=["Topic"])
    assert api.patch("/api/recall/preferences", headers=HEADERS, json={"default_days": 11}).status_code == 200
    domain = api.get("/api/recall/domain", headers=HEADERS).json()
    explicit = api.get("/api/recall/domain?days=3", headers=HEADERS).json()
    resurface = api.get("/api/recall/resurface", headers=HEADERS).json()
    overview = api.get("/api/recall/overview", headers=HEADERS).json()
    assert domain["window"]["days"] == 11 and resurface["window"]["days"] == 11
    assert explicit["window"]["days"] == 3 and overview["days"] == 7
