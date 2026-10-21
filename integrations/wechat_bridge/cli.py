from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from .mapping import WechatIngestMapper
from .models import WechatTextEvent
from .outbox import WechatOutbox


def fixture() -> WechatTextEvent:
    return WechatTextEvent(event_id="fixture-001", occurred_at=datetime.fromisoformat("2026-07-12T10:00:00+08:00"),
                           timezone="Asia/Shanghai", text="fixture content")


def summary(mapped: object) -> dict[str, object]:
    envelope = mapped.envelope  # type: ignore[attr-defined]
    clip = envelope["clip"]
    return {
        "client_request_id": mapped.client_request_id,  # type: ignore[attr-defined]
        "source_type": clip["source_type"], "multipart": mapped.multipart,  # type: ignore[index,attr-defined]
        "captured_at": clip["captured_at"], "captured_timezone": clip["captured_timezone"],  # type: ignore[index]
        "content": "<redacted>", "network": False,
    }


async def run(args: argparse.Namespace) -> int:
    deployment = os.getenv("PERCLIP_WECHAT_DEPLOYMENT_ID", "fixture")
    mapper = WechatIngestMapper(deployment_id=deployment, default_kb_id="")
    mapped = mapper.map(fixture())
    if args.command in {"map-fixture", "send-fixture"}:
        print(json.dumps(summary(mapped), ensure_ascii=False, sort_keys=True))
        return 0
    path = Path(args.outbox) if args.outbox else Path(tempfile.gettempdir()) / "perclip-wechat-dry-run.sqlite3"
    outbox = WechatOutbox(path)
    records = outbox.claim(limit=args.limit) if not args.dry_run else []
    print(json.dumps({"dry_run": args.dry_run, "network": False, "claim_count": len(records)}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe PerClip WeChat bridge utilities")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("map-fixture")
    send = sub.add_parser("send-fixture"); send.add_argument("--dry-run", action="store_true", required=True)
    process = sub.add_parser("process-outbox"); process.add_argument("--dry-run", action="store_true", required=True)
    process.add_argument("--outbox", default=""); process.add_argument("--limit", type=int, default=20)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
