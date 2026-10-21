#!/usr/bin/env python3
"""Launch API or Worker using the explicitly loaded private environment."""
from __future__ import annotations

import os
import sys


def command(args: list[str]) -> list[str]:
    if args and args[0] == "api":
        return [sys.executable, "-m", "uvicorn", "perclip_ingest.main:create_app", "--factory",
                "--host", os.environ.get("PERCLIP_HOST", "127.0.0.1"),
                "--port", os.environ.get("PERCLIP_PORT", "18081"), *args[1:]]
    if args and args[0] == "worker":
        return [sys.executable, "-m", "perclip_ingest.worker", *args[1:]]
    raise SystemExit("usage: run_service.py api|worker [arguments]")


if __name__ == "__main__":
    argv = command(sys.argv[1:])
    os.execv(argv[0], argv)
