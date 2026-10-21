from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient

from perclip_ingest.config import Settings
from perclip_ingest.knowledge_base_store import KnowledgeBaseStore
from perclip_ingest.main import create_app
from perclip_ingest.mobile_safety import contains_private_path, redact_private_paths
from perclip_ingest.pipeline_store import PipelineStore
from perclip_ingest.quality_read_model import QUALITY_READ_CONTRACT_VERSION, audit_quality_payload
from perclip_ingest.storage import ClipStore


HEADERS = {"Authorization": "Bearer secret"}


def seeded_clip(tmp_path, *, title: str = "Captured title", text: str = "Captured body"):
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))
    response = api.post(
        "/api/mobile-clips",
        headers=HEADERS,
        data={
            "source_type": "text",
            "title_hint": title,
            "text": text,
            "source_app": "Fixture App",
            "client_request_id": f"quality-read-{title.lower().replace(' ', '-')}",
        },
    )
    assert response.status_code == 200
    clip_id = int(response.json()["clip_id"])
    store = ClipStore(tmp_path)
    raw = store.find_raw_fields_by_clip_id(clip_id)
    assert raw is not None
    knowledge = KnowledgeBaseStore(tmp_path)
    route = knowledge.find_latest_route_decision_by_clip_id(clip_id)
    assert route is not None
    pipeline = PipelineStore(tmp_path)
    pipeline.associate_knowledge_base(
        clip_id=clip_id,
        knowledge_base_id=route.knowledge_base_id,
        association_type="manual" if route.manual_override else "automatic",
        route_decision_id=route.id,
    )
    return api, store, pipeline, knowledge, raw, route


def projection(
    identifier: str,
    *,
    state: str = "completed",
    recall_eligible: bool = True,
    index_eligible: bool = True,
    safe_error: str = "",
    reason: str = "completed_projection",
    url: str = "https://example.test/active",
):
    return {
        "source_asset_id": identifier,
        "source_asset_role": "clean_markdown",
        "extraction_status": state,
        "quality_reason": reason,
        "safe_error_code": safe_error,
        "recall_eligible": recall_eligible,
        "index_eligible": index_eligible,
        "index_reason": reason,
        "raw_fallback_used": False,
        "canonical_url": url,
        "resolved_url": url,
        "structured_metadata": {
            "title": {
                "source": "user.title_hint",
                "engine": "builtin-extractor",
                "engine_version": "v3",
            },
            "canonical_url": {
                "source": "fetch.resolved_url",
                "engine": "builtin-extractor",
                "engine_version": "v3",
            },
        },
    }


def with_core_memory_states(
    value: dict[str, object],
    *,
    author: str,
    author_state: str,
    content_state: str,
) -> dict[str, object]:
    result = dict(value)
    structured = dict(result["structured_metadata"])
    structured["author"] = {"value": author, "resolution_state": author_state}
    structured["core_content"] = {
        "value": "不应直接采用的正文值",
        "resolution_state": content_state,
    }
    result["structured_metadata"] = structured
    return result


def save_enrichment(store, raw, route, *, status="completed", title="Active title", summary="Active summary", text="Active body", key_points=None):
    return store.save_enrichment(
        clip_id=raw.id,
        client_request_id=raw.client_request_id,
        knowledge_base_id=route.knowledge_base_id,
        route_decision_id=route.id,
        engine="deterministic.v4",
        status=status,
        title=title,
        summary=summary,
        tags=["quality"],
        key_points=[] if key_points is None else key_points,
        language="en",
        extracted_text=text,
        error_code="recall_ineligible:failed" if status == "failed" else "",
    )


def save_processing(store, raw, *, active, active_projection, latest=None, latest_projection=None, active_index=None, latest_index=None):
    stored = store.find_normalized_metadata_by_clip_id(raw.id)
    assert stored is not None
    metadata = dict(stored.metadata)
    processing = dict(metadata.get("processing", {}))
    processing.update(
        {
            "active_enrichment_id": active.id,
            "active_projection": active_projection,
            "latest_successful_projection": active_projection,
            "latest_attempted_enrichment_id": (latest or active).id,
            "latest_attempted_projection": latest_projection or active_projection,
            "active_index": active_index
            or {
                "status": "indexed",
                "projection_id": active_projection["source_asset_id"],
                "reason": "completed_projection",
                "updated_at": "2026-07-22T00:00:00+00:00",
            },
            "latest_index_attempt": latest_index
            or {
                "status": "completed",
                "projection_id": active_projection["source_asset_id"],
                "reason": "completed_projection",
                "attempted_at": "2026-07-22T00:00:00+00:00",
            },
        }
    )
    metadata["processing"] = processing
    metadata["projection"] = active_projection
    metadata["clip"] = {
        **dict(metadata.get("clip", {})),
        "title_hint": active.title,
        "text": active.extracted_text,
        "url": active_projection.get("canonical_url", ""),
    }
    store.save_normalized_metadata(
        clip_id=raw.id, client_request_id=raw.client_request_id, metadata=metadata
    )


def quality(api, clip_id: int | str):
    response = api.get(f"/api/clips/{clip_id}/quality", headers=HEADERS)
    assert response.status_code == 200
    return response.json()["quality_read"]


def test_active_completed_quality_knowledge_and_recall_share_content(tmp_path):
    api, store, _pipeline, _knowledge, raw, route = seeded_clip(tmp_path)
    active = save_enrichment(store, raw, route, key_points=["Active body explains durable quality."])
    save_processing(store, raw, active=active, active_projection=projection("asset-active"))

    detail = quality(api, raw.id)
    recall = api.get(f"/api/recall/clips/{raw.id}", headers=HEADERS)
    listing = api.get(f"/api/knowledge-bases/{route.knowledge_base_id}/clips", headers=HEADERS)

    assert detail["contract_version"] == QUALITY_READ_CONTRACT_VERSION
    assert detail["user_status"] == "ready"
    assert detail["active_content"]["title"] == "Active title"
    assert detail["active_content"]["original_text"] == "Captured body"
    assert detail["active_content"]["key_points"] == ["Active body explains durable quality."]
    assert detail["quality"] == {
        "state": "completed",
        "quality_reason": "completed_projection",
        "recall_eligible": True,
        "index_eligible": True,
        "raw_fallback_used": False,
    }
    assert recall.status_code == 200
    assert recall.json()["clip"]["title"] == detail["active_content"]["title"]
    assert recall.json()["clip"]["summary"] == detail["active_content"]["summary"]
    assert recall.json()["clip"]["safe_text"] == detail["active_content"]["text_preview"]
    assert recall.json()["clip"]["url"] == detail["active_content"]["safe_display_url"]
    assert listing.status_code == 200
    assert listing.json()["items"][0]["title"] == detail["active_content"]["title"]
    generation = listing.json()["items"][0]["active_generation"]
    assert generation.startswith("gen_")
    assert generation != str(active.id)
    assert detail["index"]["active_index"]["generation"] == generation
    assert detail["index"]["latest_index_attempt"]["generation"] == generation


def test_saved_screen_clip_exposes_safe_original_text_only_in_detail(tmp_path):
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))
    original = (
        "来源：Chrome\n包名：com.android.chrome\nExample Domain\n"
        "正文保存在 /Users/alice/private.md\nAuthorization: Bearer synthetic-secret"
    )
    created = api.post(
        "/api/mobile-clips", headers=HEADERS,
        data={"source_type": "screen_clip", "title_hint": "Example Domain", "text": original,
              "source_app": "Chrome · com.android.chrome", "client_request_id": "stage29-screen-detail",
              "routing_mode": "default_only"},
    )
    assert created.status_code == 200, created.text
    listing = api.get("/api/knowledge/clips", headers=HEADERS).json()
    assert "original_text" not in json.dumps(listing)
    assert "text_preview" not in json.dumps(listing)

    public_id = PipelineStore(tmp_path).public_id_for(int(created.json()["clip_id"]))
    detail = quality(api, public_id)
    displayed = detail["active_content"]["original_text"]
    assert displayed.startswith("来源：Chrome 包名：com.android.chrome Example Domain")
    assert "[redacted-path]" in displayed and "[redacted]" in displayed
    assert "/Users/alice" not in displayed and "synthetic-secret" not in displayed
    assert detail["active_content"]["text_preview"] == ""
    audit_quality_payload(detail)


def test_saved_url_original_text_is_bounded_and_restart_durable(tmp_path):
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))
    original = "URL 页面核心文本 " + ("甲" * 5_000)
    created = api.post(
        "/api/mobile-clips", headers=HEADERS,
        data={"source_type": "url", "title_hint": "Stage 29 URL", "text": original,
              "url": "https://example.test/stage29", "client_request_id": "stage29-url-detail",
              "routing_mode": "default_only"},
    )
    assert created.status_code == 200, created.text
    restarted = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))
    detail = restarted.get(f"/api/clips/{created.json()['clip_id']}/quality", headers=HEADERS).json()["quality_read"]
    assert detail["active_content"]["original_text"].startswith("URL 页面核心文本")
    assert len(detail["active_content"]["original_text"]) == 4_000


def test_saved_detail_strips_credential_url_userinfo_and_remains_readable(tmp_path):
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))
    created = api.post(
        "/api/mobile-clips", headers=HEADERS,
        data={"source_type": "screen_clip", "title_hint": "Credential URL safety",
              "text": "参考 https://stage29-user:stage29-password@example.test/private 的核心内容",
              "source_app": "Chrome · com.android.chrome",
              "client_request_id": "stage29-credential-url-detail", "routing_mode": "default_only"},
    )
    assert created.status_code == 200, created.text

    public_id = PipelineStore(tmp_path).public_id_for(int(created.json()["clip_id"]))
    detail = quality(api, public_id)
    displayed = detail["active_content"]["original_text"]
    assert "https://example.test/private" in displayed
    assert "stage29-user" not in displayed and "stage29-password" not in displayed
    assert "://[redacted]:[redacted]@" not in displayed
    audit_quality_payload(detail)


def test_quality_detail_uses_core_memory_source_and_unavailable_states(tmp_path):
    api, store, _pipeline, _knowledge, raw, route = seeded_clip(tmp_path)
    active = save_enrichment(store, raw, route, summary="不应展示的矛盾摘要")
    active_projection = with_core_memory_states(
        projection("asset-core-memory"),
        author="不应展示的矛盾来源",
        author_state="explicit_unknown",
        content_state="explicit_unavailable",
    )
    save_processing(store, raw, active=active, active_projection=active_projection)

    detail = quality(api, raw.id)
    assert detail["active_content"]["source"] == "未明确来源"
    assert detail["active_content"]["summary"] == "内容暂不可用"


def test_hard_gate_mobile_contract_exposes_internal_clip_id(tmp_path):
    api, store, pipeline, _knowledge, raw, route = seeded_clip(tmp_path, title="Public identity")
    active = save_enrichment(store, raw, route)
    save_processing(store, raw, active=active, active_projection=projection("asset-public"))

    public_id = pipeline.public_id_for(raw.id)
    numeric = quality(api, raw.id)
    public = quality(api, public_id)
    restarted = PipelineStore(tmp_path).public_id_for(raw.id)

    assert numeric == public
    assert numeric["clip_id"] == public_id == restarted
    assert public_id.startswith("pc_")
    serialized = json.dumps(public)
    assert '"clip_id": "1"' not in serialized


def test_hard_gate_mobile_contract_exposes_internal_enrichment_id(tmp_path):
    api, store, _pipeline, _knowledge, raw, route = seeded_clip(tmp_path, title="Generation")
    active = save_enrichment(store, raw, route)
    save_processing(store, raw, active=active, active_projection=projection("asset-generation"))

    payload = quality(api, raw.id)
    serialized = json.dumps(payload)
    assert "enrichment_id" not in serialized
    assert payload["processing"]["active_generation"].startswith("gen_")
    assert payload["processing"]["latest_attempt_generation"].startswith("gen_")


def test_public_generation_changes_only_when_active_content_changes(tmp_path):
    api, store, _pipeline, _knowledge, raw, route = seeded_clip(tmp_path, title="Generation lifecycle")
    first = save_enrichment(store, raw, route, title="First")
    save_processing(store, raw, active=first, active_projection=projection("asset-first"))
    first_view = quality(api, raw.id)
    restarted = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))
    assert quality(restarted, raw.id)["processing"]["active_generation"] == first_view["processing"]["active_generation"]

    second = save_enrichment(store, raw, route, title="Second")
    save_processing(store, raw, active=second, active_projection=projection("asset-second"))
    second_view = quality(api, raw.id)
    assert second_view["processing"]["active_generation"].startswith("gen_")
    assert second_view["processing"]["active_generation"] != first_view["processing"]["active_generation"]
    serialized = json.dumps(second_view)
    for forbidden in ("source_asset_id", "projection_id", "active_projection_id", "asset-first", "asset-second"):
        assert forbidden not in serialized


def test_hard_gate_knowledge_cursor_exposes_internal_row_id(tmp_path):
    first_api, *_first, first_raw, first_route = seeded_clip(tmp_path, title="Cursor one")
    seeded_clip(tmp_path, title="Cursor two")
    seeded_clip(tmp_path, title="Cursor three")
    path = f"/api/knowledge-bases/{first_route.knowledge_base_id}/clips"

    first = first_api.get(path, headers=HEADERS, params={"limit": 1})
    assert first.status_code == 200
    cursor = first.json()["next_cursor"]
    assert cursor.startswith("kc_")
    assert cursor != str(first_raw.id)
    assert cursor != f"kc_{first_raw.id}"
    assert "next_after_id" not in first.json()

    restarted_api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))
    second = restarted_api.get(path, headers=HEADERS, params={"limit": 1, "cursor": cursor})
    third = restarted_api.get(
        path,
        headers=HEADERS,
        params={"limit": 1, "cursor": second.json()["next_cursor"]},
    )
    ids = [
        first.json()["items"][0]["clip_id"],
        second.json()["items"][0]["clip_id"],
        third.json()["items"][0]["clip_id"],
    ]
    assert len(set(ids)) == 3
    assert all(identifier.startswith("pc_") for identifier in ids)
    assert third.json()["next_cursor"] is None
    assert restarted_api.get(path, headers=HEADERS, params={"after_id": 1}).status_code == 422


def test_knowledge_cursor_expires_is_scope_bound_and_cleanup_preserves_valid_cursor(tmp_path):
    api, *_rest, _raw, route = seeded_clip(tmp_path, title="Expiring cursor")
    seeded_clip(tmp_path, title="Cursor follower")
    path = f"/api/knowledge-bases/{route.knowledge_base_id}/clips"
    expired = api.get(path, headers=HEADERS, params={"limit": 1}).json()["next_cursor"]
    assert expired.startswith("kc_")

    created = api.post(
        "/api/knowledge-bases",
        headers=HEADERS,
        json={"name": "Other cursor scope", "template_key": "general"},
    )
    assert created.status_code == 200
    other_id = created.json()["knowledge_base"]["id"]
    assert api.get(f"/api/knowledge-bases/{other_id}/clips", headers=HEADERS, params={"cursor": expired}).status_code == 422

    pipeline = PipelineStore(tmp_path)
    valid = pipeline.create_knowledge_read_cursor(
        knowledge_base_id=route.knowledge_base_id, after_internal_id=1
    )
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.execute(
            "update knowledge_read_cursors set created_at=? where token=?",
            ("2000-01-01T00:00:00+00:00", expired),
        )
    assert api.get(path, headers=HEADERS, params={"cursor": expired}).status_code == 422
    assert pipeline.resolve_knowledge_read_cursor(
        knowledge_base_id=route.knowledge_base_id, token=valid
    ) == 1
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        assert db.execute("select 1 from knowledge_read_cursors where token=?", (expired,)).fetchone() is None


def test_saved_and_processing_user_statuses_are_not_quality_states(tmp_path):
    api, _store, pipeline, _knowledge, raw, _route = seeded_clip(tmp_path, title="Pending")

    saved = quality(api, raw.id)
    assert saved["user_status"] == "saved"
    assert saved["quality"]["state"] == "not_started"

    pipeline.enqueue(
        clip_id=raw.id,
        stage="extract",
        engine="builtin-extractor",
        engine_version="v3",
        input_hash="quality-read-pending",
    )
    processing = quality(api, raw.id)
    assert processing["user_status"] == "processing"
    assert processing["quality"]["state"] == "not_started"
    assert processing["processing"]["in_progress"] is True
    assert processing["processing"]["current_stage"] == "extract"


def test_hard_gate_active_reprocess_not_exposed_as_processing(tmp_path):
    api, store, pipeline, _knowledge, raw, route = seeded_clip(tmp_path, title="Reprocess")
    active = save_enrichment(store, raw, route, title="Stable title", text="Stable body")
    save_processing(store, raw, active=active, active_projection=projection("asset-stable"))
    pipeline.enqueue(
        clip_id=raw.id,
        stage="extract",
        engine="builtin-extractor",
        engine_version="v3",
        input_hash="active-reprocess",
    )

    payload = quality(api, raw.id)
    assert payload["user_status"] == "processing"
    assert payload["active_content"]["title"] == "Stable title"
    assert payload["active_content"]["text_preview"] == "Stable body"


def test_hard_gate_index_only_job_blocks_ready_content(tmp_path):
    api, store, pipeline, _knowledge, raw, route = seeded_clip(tmp_path, title="Index only")
    active = save_enrichment(store, raw, route)
    save_processing(store, raw, active=active, active_projection=projection("asset-index"))
    pipeline.enqueue(
        clip_id=raw.id,
        stage="index",
        engine="ragflow",
        engine_version="v1",
        input_hash="index-only",
    )

    payload = quality(api, raw.id)
    assert payload["user_status"] == "ready"
    assert payload["processing"]["in_progress"] is False
    assert payload["processing"]["current_stage"] == ""


def test_hard_gate_active_content_disappears_while_processing(tmp_path):
    api, store, pipeline, _knowledge, raw, route = seeded_clip(tmp_path, title="Retry content")
    active = save_enrichment(store, raw, route, title="Prior title", summary="Prior summary")
    save_processing(store, raw, active=active, active_projection=projection("asset-prior"))
    job = pipeline.enqueue(
        clip_id=raw.id,
        stage="enrich",
        engine="deterministic",
        engine_version="v4",
        input_hash="retry-enrich",
    )
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.execute("update outbox_jobs set status='retry' where id=?", (job.id,))

    payload = quality(api, raw.id)
    assert payload["user_status"] == "processing"
    assert payload["processing"]["current_stage"] == "enrich"
    assert payload["active_content"]["title"] == "Prior title"
    assert payload["active_content"]["summary"] == "Prior summary"


def test_running_clean_stage_is_processing(tmp_path):
    api, _store, pipeline, _knowledge, raw, _route = seeded_clip(
        tmp_path, title="Running clean"
    )
    job = pipeline.enqueue(
        clip_id=raw.id,
        stage="clean",
        engine="cleaner",
        engine_version="v2",
        input_hash="running-clean",
    )
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.execute("update outbox_jobs set status='running' where id=?", (job.id,))

    payload = quality(api, raw.id)
    assert payload["user_status"] == "processing"
    assert payload["processing"]["in_progress"] is True
    assert payload["processing"]["current_stage"] == "clean"


def test_active_usable_partial_is_ready_and_eligible(tmp_path):
    api, store, _pipeline, _knowledge, raw, route = seeded_clip(tmp_path, title="Partial")
    active = save_enrichment(store, raw, route, title="Partial title")
    partial = projection(
        "asset-partial", state="partial", reason="usable_partial_projection"
    )
    save_processing(store, raw, active=active, active_projection=partial)

    detail = quality(api, raw.id)
    assert detail["user_status"] == "ready"
    assert detail["quality"]["state"] == "partial"
    assert detail["quality"]["recall_eligible"] is True
    assert detail["quality"]["index_eligible"] is True


def test_latest_failed_and_unusable_partial_do_not_replace_active_success(tmp_path):
    api, store, _pipeline, _knowledge, raw, route = seeded_clip(tmp_path, title="Lifecycle")
    active = save_enrichment(store, raw, route, title="Stable title", summary="Stable summary", text="Stable body")
    active_projection = projection("asset-stable")
    failed = save_enrichment(store, raw, route, status="failed", title="Failed attempt", summary="", text="")
    failed_projection = projection(
        "asset-failed", state="failed", recall_eligible=False, index_eligible=False,
        safe_error="web_fetch_failed", reason="failed_projection_ineligible",
    )
    save_processing(
        store,
        raw,
        active=active,
        active_projection=active_projection,
        latest=failed,
        latest_projection=failed_projection,
        latest_index={
            "status": "skipped_no_new_projection",
            "projection_id": "asset-failed",
            "reason": "no_new_eligible_projection",
            "attempted_at": "2026-07-22T01:00:00+00:00",
        },
    )

    failed_view = quality(api, raw.id)
    stable_generation = failed_view["processing"]["active_generation"]
    assert failed_view["active_content"]["title"] == "Stable title"
    assert failed_view["processing"]["latest_attempt"]["state"] == "failed"
    assert failed_view["user_status"] == "ready"
    assert failed_view["actions"]["needs_attention"] is True
    assert failed_view["index"]["active_index"]["generation"] == stable_generation
    assert failed_view["index"]["latest_index_attempt"]["generation"] == failed_view["processing"]["latest_attempt_generation"]
    assert failed_view["processing"]["latest_attempt_generation"] != stable_generation
    assert api.get(f"/api/recall/clips/{raw.id}", headers=HEADERS).json()["clip"]["title"] == "Stable title"

    partial = save_enrichment(store, raw, route, title="Unusable shell", summary="", text="Loading")
    partial_projection = projection(
        "asset-shell", state="partial", recall_eligible=False, index_eligible=False,
        reason="client_render_shell",
    )
    save_processing(
        store,
        raw,
        active=active,
        active_projection=active_projection,
        latest=partial,
        latest_projection=partial_projection,
    )
    partial_view = quality(api, raw.id)
    assert partial_view["active_content"]["title"] == "Stable title"
    assert partial_view["processing"]["latest_attempt"]["state"] == "partial"
    assert partial_view["processing"]["latest_attempt"]["recall_eligible"] is False
    assert partial_view["processing"]["active_generation"] == stable_generation
    assert api.get(f"/api/recall/clips/{raw.id}", headers=HEADERS).json()["clip"]["title"] == "Stable title"


def test_pointerless_legacy_uses_latest_completed_not_latest_failed(tmp_path):
    api, store, _pipeline, _knowledge, raw, route = seeded_clip(tmp_path, title="Legacy")
    completed = save_enrichment(store, raw, route, title="Legacy completed")
    failed = save_enrichment(store, raw, route, status="failed", title="Later failed")
    active_projection = projection("legacy-asset")
    save_processing(
        store,
        raw,
        active=completed,
        active_projection=active_projection,
        latest=failed,
        latest_projection=projection(
            "failed-asset", state="failed", recall_eligible=False, index_eligible=False,
            safe_error="web_fetch_failed", reason="failed_projection_ineligible",
        ),
    )
    stored = store.find_normalized_metadata_by_clip_id(raw.id)
    metadata = dict(stored.metadata)
    processing = dict(metadata["processing"])
    processing.pop("active_enrichment_id")
    metadata["processing"] = processing
    store.save_normalized_metadata(clip_id=raw.id, client_request_id=raw.client_request_id, metadata=metadata)

    detail = quality(api, raw.id)
    assert detail["processing"]["resolution_mode"] == "legacy_latest_completed"
    assert detail["active_content"]["title"] == "Legacy completed"
    enrichment = api.get(f"/api/clips/{raw.id}/enrichment", headers=HEADERS)
    assert enrichment.status_code == 200
    assert enrichment.json()["enrichment"]["title"] == "Legacy completed"


def test_invalid_pointer_fails_closed_without_fallback(tmp_path):
    api, store, _pipeline, _knowledge, raw, route = seeded_clip(tmp_path, title="Invalid")
    completed = save_enrichment(store, raw, route, title="Must not leak")
    save_processing(store, raw, active=completed, active_projection=projection("asset-old"))
    stored = store.find_normalized_metadata_by_clip_id(raw.id)
    metadata = dict(stored.metadata)
    metadata["processing"] = {**dict(metadata["processing"]), "active_enrichment_id": 999999}
    store.save_normalized_metadata(clip_id=raw.id, client_request_id=raw.client_request_id, metadata=metadata)

    detail = quality(api, raw.id)
    assert detail["processing"]["resolution_mode"] == "invalid_active_pointer"
    assert detail["user_status"] == "needs_attention"
    assert detail["active_content"]["title"] != "Must not leak"
    assert detail["quality"]["recall_eligible"] is False
    assert api.get(f"/api/recall/clips/{raw.id}", headers=HEADERS).status_code == 404
    assert api.get(f"/api/clips/{raw.id}/enrichment", headers=HEADERS).status_code == 409


def test_cross_clip_active_pointer_is_invalid_and_never_falls_back(tmp_path):
    api, store, _pipeline, _knowledge, raw, route = seeded_clip(tmp_path, title="Owner")
    owner_enrichment = save_enrichment(store, raw, route, title="Owner completed")
    save_processing(store, raw, active=owner_enrichment, active_projection=projection("owner-asset"))

    _api2, store2, _pipeline2, _knowledge2, other_raw, other_route = seeded_clip(
        tmp_path, title="Other"
    )
    other_enrichment = save_enrichment(
        store2, other_raw, other_route, title="Cross clip content"
    )
    stored = store.find_normalized_metadata_by_clip_id(raw.id)
    metadata = dict(stored.metadata)
    metadata["processing"] = {
        **dict(metadata["processing"]),
        "active_enrichment_id": other_enrichment.id,
    }
    store.save_normalized_metadata(
        clip_id=raw.id, client_request_id=raw.client_request_id, metadata=metadata
    )

    detail = quality(api, raw.id)
    assert detail["processing"]["resolution_mode"] == "invalid_active_pointer"
    assert detail["active_content"]["title"] not in {
        "Owner completed",
        "Cross clip content",
    }
    assert api.get(f"/api/recall/clips/{raw.id}", headers=HEADERS).status_code == 404


def test_failed_only_ragflow_failure_and_no_dataset_are_distinct(tmp_path):
    api, store, _pipeline, _knowledge, raw, route = seeded_clip(tmp_path, title="States")
    failed = save_enrichment(store, raw, route, status="failed", title="Explicit title")
    failed_projection = projection(
        "asset-failed-only", state="failed", recall_eligible=False, index_eligible=False,
        safe_error="unsupported_media_type", reason="failed_projection_ineligible",
    )
    save_processing(store, raw, active=failed, active_projection=failed_projection)
    failed_view = quality(api, raw.id)
    assert failed_view["user_status"] == "needs_attention"
    assert failed_view["quality"]["state"] == "failed"

    active = save_enrichment(store, raw, route, title="Ready content")
    active_projection = projection("asset-ready")
    save_processing(
        store,
        raw,
        active=active,
        active_projection=active_projection,
        latest_index={
            "status": "failed",
            "projection_id": "asset-ready",
            "reason": "ragflow_index_failed",
            "attempted_at": "2026-07-22T02:00:00+00:00",
        },
    )
    ragflow_failure = quality(api, raw.id)
    assert ragflow_failure["user_status"] == "ready"
    assert ragflow_failure["actions"]["can_retry_index"] is True
    assert ragflow_failure["actions"]["needs_attention"] is True

    save_processing(
        store,
        raw,
        active=active,
        active_projection=active_projection,
        active_index={
            "status": "not_indexed",
            "projection_id": "asset-ready",
            "reason": "no_dataset_mapping",
            "updated_at": "2026-07-22T03:00:00+00:00",
        },
        latest_index={
            "status": "skipped_no_dataset_mapping",
            "projection_id": "asset-ready",
            "reason": "no_dataset_mapping",
            "attempted_at": "2026-07-22T03:00:00+00:00",
        },
    )
    no_dataset = quality(api, raw.id)
    assert no_dataset["user_status"] == "ready"
    assert no_dataset["index"]["active_index"]["status"] == "not_indexed"
    assert no_dataset["actions"]["can_retry_index"] is False
    serialized_no_dataset = json.dumps(no_dataset).lower()
    assert "dataset_id" not in serialized_no_dataset
    assert "document_id" not in serialized_no_dataset


def test_quality_serialization_redacts_values_and_private_paths(tmp_path):
    api, store, _pipeline, _knowledge, raw, route = seeded_clip(tmp_path, title="Privacy")
    active = save_enrichment(
        store,
        raw,
        route,
        title='"token": "synthetic-secret"',
        summary="Authorization: Bearer synthetic-bearer",
        text="PASSWORD=synthetic-password /mnt/private/archive.md",
        key_points=["Authorization: Bearer synthetic-point /Users/alice/private.md"],
    )
    save_processing(store, raw, active=active, active_projection=projection("asset-private"))

    payload = quality(api, raw.id)
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    audit_quality_payload(payload)
    assert "synthetic-secret" not in serialized
    assert "synthetic-bearer" not in serialized
    assert "synthetic-password" not in serialized
    assert "synthetic-point" not in serialized
    assert "/mnt/private" not in serialized
    for forbidden in (
        "storage_uri",
        "original_path",
        "ragflow_dataset_id",
        "ragflow_document_id",
        "traceback",
    ):
        assert forbidden not in serialized


def test_cross_platform_private_paths_are_redacted_without_harming_safe_paths():
    private_values = (
        "/Users/alice/notes/a.md",
        "/home/alice/notes/a.md",
        "/mnt/archive/a.md",
        "/nas/private/a.md",
        "/volume1/private/a.md",
        r"C:\Users\alice\notes.txt",
        r"D:\Data\notes.txt",
        r"\\server\share\notes.txt",
        "file:///Users/alice/notes.txt",
        "smb://server/share/notes.txt",
        "/Volumes/External/notes.txt",
        "/opt/perclip/notes.txt",
        "/srv/perclip/notes.txt",
        "/var/lib/perclip/notes.txt",
        "/root/notes.txt",
        "/app/notes.txt",
        "/data/notes.txt",
        "/tmp/notes.txt",
    )
    for value in private_values:
        assert redact_private_paths(f"before {value} after") == "before [redacted-path] after"
        assert contains_private_path(value)

    safe_values = (
        "docs/notes/a.md",
        "package.module.symbol",
        "https://example.test/Users/alice/notes",
        "https://example.test/home/alice/notes",
    )
    assert [redact_private_paths(value) for value in safe_values] == list(safe_values)
    assert not any(contains_private_path(value) for value in safe_values)


def test_hard_gates_windows_linux_and_unc_private_paths_are_not_exposed(tmp_path):
    api, store, _pipeline, _knowledge, raw, route = seeded_clip(tmp_path, title="Privacy matrix")
    active = save_enrichment(
        store,
        raw,
        route,
        title=r"Title C:\Users\alice\private.txt",
        summary="Summary /home/alice/private.txt",
        text=r"Preview \\server\share\private.txt and safe docs/readme.md",
    )
    active = store.find_enrichment_by_id(active.id)
    assert active is not None
    with sqlite3.connect(tmp_path / "perclip.sqlite3") as db:
        db.execute(
            "update clip_enrichments set tags_json=? where id=?",
            (json.dumps(["/volume1/private", "safe-tag"]), active.id),
        )
        db.execute(
            "update clip_route_decisions set reason=? where id=?",
            ("route file:///Users/alice/private", route.id),
        )
    active = store.find_enrichment_by_id(active.id)
    assert active is not None
    private_projection = projection(
        "asset-private-matrix",
        safe_error=r"D:\Data\exception.log",
        reason="quality /mnt/private/reason.txt",
    )
    save_processing(store, raw, active=active, active_projection=private_projection)

    quality_payload = quality(api, raw.id)
    recall_payload = api.get(f"/api/recall/clips/{raw.id}", headers=HEADERS).json()
    serialized = json.dumps([quality_payload, recall_payload], ensure_ascii=False)
    for gate, forbidden in (
        ("windows_private_path_exposed", r"C:\Users"),
        ("linux_home_path_exposed", "/home/alice"),
        ("unc_or_file_path_exposed", r"\\server\share"),
        ("unc_or_file_path_exposed", "file:///"),
    ):
        assert forbidden not in serialized, gate
    assert "[redacted-path]" in serialized
    assert "docs/readme.md" in serialized
    assert "safe-tag" in serialized


def test_ordinary_mobile_knowledge_responses_hide_connector_ids(tmp_path):
    api = TestClient(create_app(Settings(data_dir=tmp_path, ingest_token="secret")))
    created = api.post(
        "/api/knowledge-bases",
        headers=HEADERS,
        json={
            "name": "Private mapping",
            "ragflow_dataset_id": "dataset-private",
            "ragflow_dataset_name": "Private dataset",
        },
    )
    assert created.status_code == 200
    knowledge_base_id = created.json()["knowledge_base"]["id"]
    assert created.json()["knowledge_base"]["ragflow_dataset_id"] == ""
    assert created.json()["knowledge_base"]["ragflow_dataset_name"] == ""

    detail = api.get(f"/api/knowledge-bases/{knowledge_base_id}", headers=HEADERS)
    listing = api.get("/api/knowledge-bases", headers=HEADERS)
    assert detail.json()["knowledge_base"]["ragflow_dataset_id"] == ""
    listed = next(
        item
        for item in listing.json()["knowledge_bases"]
        if item["id"] == knowledge_base_id
    )
    assert listed["ragflow_dataset_id"] == ""
    assert "dataset-private" not in json.dumps([created.json(), detail.json(), listing.json()])

    patched = api.patch(
        f"/api/knowledge-bases/{knowledge_base_id}",
        headers=HEADERS,
        json={
            "ragflow_dataset_id": "dataset-operator-updated",
            "ragflow_dataset_name": "Operator updated",
        },
    )
    assert patched.status_code == 200
    assert patched.json()["knowledge_base"]["ragflow_dataset_id"] == ""
    operator_check = api.post(
        f"/api/knowledge-bases/{knowledge_base_id}/ragflow/dry-run-update",
        headers=HEADERS,
        json={},
    )
    assert operator_check.status_code == 200
    assert operator_check.json()["ragflow"]["dataset_id"] == "dataset-operator-updated"
    mobile_check = api.get(f"/api/knowledge-bases/{knowledge_base_id}", headers=HEADERS)
    assert mobile_check.json()["knowledge_base"]["ragflow_dataset_id"] == ""
    assert mobile_check.json()["knowledge_base"]["ragflow_dataset_name"] == ""

    unmapped = api.post(
        "/api/knowledge-bases",
        headers=HEADERS,
        json={"name": "Missing operator mapping"},
    ).json()["knowledge_base"]
    missing_diagnostic = api.post(
        f"/api/knowledge-bases/{unmapped['id']}/ragflow/dry-run-update",
        headers=HEADERS,
        json={},
    )
    assert missing_diagnostic.status_code == 422
