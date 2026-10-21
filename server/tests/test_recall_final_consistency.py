from datetime import datetime, timezone

from perclip_ingest.recall import topic_id
from test_recall import HEADERS, client, public_id, save_clip


def test_legacy_topic_label_matches_canonical_label(tmp_path):
    api = client(tmp_path)
    for index, label in enumerate(("AI Agent", "ai agent", "AI agent")):
        save_clip(tmp_path, api, request_id=f"label-{index}", title=label, text="body", tags=[label])
    identifier = "unclassified"
    domain = api.get("/api/recall/domain", headers=HEADERS).json()
    label = next(item["label"] for item in domain["topics"] if item["id"] == identifier)
    assert api.get(f"/api/recall/topics/{identifier}", headers=HEADERS).json()["topic"]["label"] == label


def test_interaction_target_normalization_and_real_diversity(tmp_path):
    api = client(tmp_path)
    one = public_id(api, save_clip(tmp_path, api, request_id="one", title="One", text="body", tags=["One"]))
    two = public_id(api, save_clip(tmp_path, api, request_id="two", title="Two", text="body", tags=["Two"]))
    base = {"client_event_id":"bad", "surface":"resurface", "action":"viewed"}
    assert api.post("/api/recall/interactions", headers=HEADERS, json={**base,"node_id":"clip:notnumeric"}).status_code == 422
    assert api.post("/api/recall/interactions", headers=HEADERS, json={**base,"client_event_id":"mismatch","node_id":f"clip:{one}","clip_id":two}).status_code == 422
    valid = api.post("/api/recall/interactions", headers=HEADERS, json={**base,"client_event_id":"valid","node_id":f"clip:{one}"})
    assert valid.status_code == 200 and valid.json()["target"]["clip_id"] == one
    page = api.get("/api/recall/resurface?limit=2", headers=HEADERS).json()["items"]
    assert all("topic_diversity" not in item["reason_codes"] for item in page)
    filtered = api.get("/api/recall/resurface?limit=2&topic_id=unclassified", headers=HEADERS).json()["items"]
    assert all("topic_diversity" not in item["reason_codes"] for item in filtered)
