from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from perclip_ingest.runtime_audit import RuntimeAuditError, audit_runtime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Offline, read-only PerClip/PersonalClips/RAGFlow snapshot audit; "
            "SQLite inputs must be consistent offline snapshots"
        )
    )
    parser.add_argument("--perclip-db", type=Path, required=True)
    parser.add_argument("--personalclips-db", type=Path)
    parser.add_argument("--ragflow-snapshot", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = audit_runtime(
            perclip_db=args.perclip_db,
            personalclips_db=args.personalclips_db,
            ragflow_snapshot=args.ragflow_snapshot,
        )
    except RuntimeAuditError as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
