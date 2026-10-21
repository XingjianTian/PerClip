from test_recall import HEADERS, client, public_id, save_clip
from perclip_ingest.recall import topic_id


def test_legacy_recall_and_mobile_contracts_keep_ids_order_limits_and_safe_fields(tmp_path):
    api = client(tmp_path)
    first = save_clip(tmp_path, api, request_id="legacy-a", title="Alpha", text="body", tags=["Alpha"])
    second = save_clip(tmp_path, api, request_id="legacy-b", title="Beta", text="body", tags=["Beta"])
    first_public = public_id(api, first)
    second_public = public_id(api, second)
    overview = api.get("/api/recall/overview", headers=HEADERS)
    assert overview.status_code == 200
    graph = overview.json()["graph"]
    assert graph["nodes"] == api.get("/api/recall/overview", headers=HEADERS).json()["graph"]["nodes"]
    assert {node["color_slot"] for node in graph["nodes"]} <= {0, 1, 2, 3}
    topic = api.get("/api/recall/topics/unclassified", headers=HEADERS).json()
    assert topic["topic"]["id"] == "unclassified"
    assert {item["clip_id"] for item in topic["items"]} == {first_public, second_public}
    session = api.post("/api/recall/sessions", headers=HEADERS, json={"limit": 2}).json()
    assert len(session["items"]) == 2 and {item["clip_id"] for item in session["items"]} == {first_public, second_public}
    weekly = api.get("/api/recall/weekly-review", headers=HEADERS).json()
    assert len(weekly["top_topics"]) <= 10 and len(weekly["suggested_items"]) <= 10
    clip = api.get(f"/api/recall/clips/{first}", headers=HEADERS)
    # save_clip itself exercises the unchanged POST /api/mobile-clips contract;
    # it must remain a write endpoint, not a new list projection.
    assert clip.status_code == 200
    assert "original_path" not in str(clip.json()) and "ragflow_document_id" not in str(clip.json())
