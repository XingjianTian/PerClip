from __future__ import annotations

import argparse
import json
import sys

from .config import Settings
from .pipeline_store import PipelineStore


RETRY_CONFIRMATION = "RETRY_FAILED_PIPELINE_JOB"
PROMOTE_CONFIRMATION = "PROMOTE_PLANNED_RAGFLOW_REAL_SYNC"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply guarded local control-plane actions to PerClip pipeline jobs"
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    retry = subparsers.add_parser("retry-failed", help="reopen one terminal failed job")
    retry.add_argument("--job-id", type=int, required=True)
    retry.add_argument("--request-id", required=True)
    retry.add_argument("--confirm", required=True)
    retry.add_argument("--additional-attempts", type=int, default=5)

    promote = subparsers.add_parser(
        "promote-real-sync", help="promote one clip's planned index to a real-sync job"
    )
    promote.add_argument("--clip-id", type=int, required=True)
    promote.add_argument("--request-id", required=True)
    promote.add_argument("--confirm", required=True)

    args = parser.parse_args(argv)
    settings = Settings.from_env()
    store = PipelineStore(settings.data_dir)
    store.init()

    try:
        if args.action == "retry-failed":
            if args.confirm != RETRY_CONFIRMATION:
                raise ValueError("exact retry confirmation required")
            job, changed = store.retry_failed_job(
                job_id=args.job_id,
                request_id=args.request_id,
                authorized=True,
                additional_attempts=args.additional_attempts,
            )
        else:
            if args.confirm != PROMOTE_CONFIRMATION:
                raise ValueError("exact real-sync promotion confirmation required")
            if not settings.ragflow.real_sync_enabled:
                raise ValueError("real RAGFlow sync safety gates are not enabled")
            job, changed = store.promote_planned_index(
                clip_id=args.clip_id,
                request_id=args.request_id,
                authorized=True,
            )
    except ValueError as error:
        parser.error(str(error))

    print(
        json.dumps(
            {
                "ok": True,
                "changed": changed,
                "job_id": job.id,
                "clip_id": job.clip_id,
                "stage": job.stage,
                "status": job.status,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
