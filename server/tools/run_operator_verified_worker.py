from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

from perclip_ingest.config import Settings
from perclip_ingest.ragflow_adapter import RagflowAdapterError
from perclip_ingest.ragflow_operator_verifier import (
    ExternalCommandEvidenceProvider,
    OperatorVerifiedRagflowAdapter,
)
from perclip_ingest.worker import PipelineWorker


def _command_from_env() -> list[str]:
    raw = os.environ.get(
        "PERCLIP_RAGFLOW_OPERATOR_VERIFIER_COMMAND_JSON", ""
    ).strip()
    if not raw:
        raise RuntimeError(
            "PERCLIP_RAGFLOW_OPERATOR_VERIFIER_COMMAND_JSON must be set"
        )
    try:
        command = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "PERCLIP_RAGFLOW_OPERATOR_VERIFIER_COMMAND_JSON must be a JSON array"
        ) from error
    if not isinstance(command, list) or not all(
        isinstance(item, str) and item.strip() for item in command
    ):
        raise RuntimeError(
            "PERCLIP_RAGFLOW_OPERATOR_VERIFIER_COMMAND_JSON must be a JSON string array"
        )
    return command


class FaultAfterUploadOnceAdapter(OperatorVerifiedRagflowAdapter):
    """Synthetic staging fault: remote upload succeeds, local call reports unknown."""

    def __init__(self, *args, marker_path: Path, **kwargs):
        super().__init__(*args, **kwargs)
        self.marker_path = marker_path

    def upload_document(
        self,
        dataset_id: str,
        name: str,
        content_or_path: str,
        meta_fields: dict[str, object] | None = None,
        dry_run: bool = True,
    ):
        reference = super().upload_document(
            dataset_id,
            name,
            content_or_path,
            meta_fields=meta_fields,
            dry_run=dry_run,
        )
        if not dry_run and not self.marker_path.exists():
            self.marker_path.parent.mkdir(parents=True, exist_ok=True)
            self.marker_path.write_text("fault-injected\n", encoding="utf-8")
            raise RagflowAdapterError("synthetic_unknown_upload_outcome")
        return reference


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the isolated staging worker with operator vector evidence"
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if settings.ragflow.effective_mode != "index":
        raise RuntimeError("operator-verified worker requires RAGFLOW_MODE=index")
    if not settings.ragflow.real_sync_enabled:
        raise RuntimeError("operator-verified worker requires real sync safety gates")

    provider = ExternalCommandEvidenceProvider(
        _command_from_env(),
        timeout_seconds=float(
            os.environ.get(
                "PERCLIP_RAGFLOW_OPERATOR_VERIFIER_TIMEOUT_SECONDS", "90"
            )
        ),
    )
    marker = os.environ.get(
        "PERCLIP_STAGING_FAULT_AFTER_UPLOAD_ONCE_MARKER", ""
    ).strip()
    adapter = (
        FaultAfterUploadOnceAdapter(
            settings.ragflow, provider, marker_path=Path(marker).resolve()
        )
        if marker
        else OperatorVerifiedRagflowAdapter(settings.ragflow, provider)
    )
    worker = PipelineWorker(settings, ragflow_adapter_override=adapter)
    while True:
        processed = worker.run_once(limit=max(1, args.limit))
        if args.once:
            return 0
        if processed == 0:
            time.sleep(max(0.1, args.poll_seconds))


if __name__ == "__main__":
    sys.exit(main())
