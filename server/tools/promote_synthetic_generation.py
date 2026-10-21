from __future__ import annotations

import json
import os
import sys

from perclip_ingest.config import Settings
from perclip_ingest.enrichment import (
    EnrichmentInputProjection,
    deterministic_enrich,
)
from perclip_ingest.ragflow_index import safe_hash_alias
from perclip_ingest.worker import PipelineWorker, STAGE_ENGINE


def main() -> int:
    if os.environ.get("PERCLIP_STAGING_SYNTHETIC_RUN", "") != "1":
        raise RuntimeError("synthetic generation promotion is staging-only")
    request = json.load(sys.stdin)
    public_id = str(request.get("clip_public_id") or "")
    replacement_text = str(request.get("replacement_text") or "")
    topic_ids = request.get("topic_ids", [])
    if (
        not public_id.startswith("pc_")
        or "PERCLIP_SYNTHETIC_ANCHOR_" not in replacement_text
        or not isinstance(topic_ids, list)
    ):
        raise ValueError("invalid synthetic generation request")

    worker = PipelineWorker(Settings.from_env())
    clip_id = worker.pipeline.clip_id_for_public_id(public_id)
    raw = worker.store.find_raw_fields_by_clip_id(clip_id or 0)
    if raw is None:
        raise ValueError("synthetic clip not found")

    asset_id = worker._write_derived_text(
        raw,
        role="clean_markdown",
        text=replacement_text,
        engine="perclip-staging-synthetic-generation",
        engine_version="v1",
        metadata={
            "extraction": {
                "status": "completed",
                "safe_error_code": "",
                "quality_reason": "synthetic_generation_fixture",
                "recall_eligible": True,
                "raw_fallback_used": False,
            }
        },
    )
    route = worker.knowledge_store.find_latest_route_decision_by_clip_id(raw.id)
    projection = EnrichmentInputProjection(
        text=replacement_text,
        title="Synthetic generation replacement",
        extraction_status="completed",
        source_asset_id=asset_id,
        source_asset_role="clean_markdown",
        quality_reason="synthetic_generation_fixture",
        recall_eligible=True,
        raw_fallback_used=False,
    )
    existing = worker.store.find_normalized_metadata_by_clip_id(raw.id)
    enrichment = deterministic_enrich(
        raw,
        route,
        existing.metadata if existing else {},
        projection,
    )
    saved = worker.store.save_enrichment(
        clip_id=raw.id,
        client_request_id=raw.client_request_id,
        knowledge_base_id=route.knowledge_base_id if route else "",
        route_decision_id=route.id if route else None,
        engine=enrichment.engine,
        status=enrichment.status,
        title=enrichment.title,
        summary=enrichment.summary,
        tags=enrichment.tags,
        key_points=enrichment.key_points,
        language=enrichment.language,
        extracted_text=enrichment.extracted_text,
        error_code=enrichment.error_code,
        error_message="",
    )
    worker._save_projection_metadata(raw, projection, saved)
    normalized = worker.store.find_normalized_metadata_by_clip_id(raw.id)
    metadata = dict(normalized.metadata) if normalized else {}
    metadata["staging_synthetic_topic_ids"] = topic_ids
    worker.store.save_normalized_metadata(
        clip_id=raw.id,
        client_request_id=raw.client_request_id,
        metadata=metadata,
    )
    asset = worker.pipeline.find_asset(asset_id)
    if asset is None:
        raise RuntimeError("synthetic generation asset missing")
    engine, version = STAGE_ENGINE["index"]
    worker.pipeline.enqueue(
        clip_id=raw.id,
        stage="index",
        engine=engine,
        engine_version=version,
        input_hash=str(asset["content_hash"]),
        payload={"sync_mode": "real", "synthetic_generation": True},
    )
    print(
        json.dumps(
            {
                "schema": "perclip.synthetic-generation-promotion.v1",
                "clip_alias": safe_hash_alias(public_id),
                "generation_alias": safe_hash_alias(
                    worker._generation_public_id(public_id, asset_id)
                ),
                "scheduled": True,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
