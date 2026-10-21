#!/usr/bin/env python3
"""Render the optional gateway from explicit environment; preserve Nginx variables."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render(source: Path, target: Path, env: dict[str, str]) -> None:
    source, target = source.resolve(), target.resolve()
    if target == source or source in target.parents:
        raise ValueError("Generated gateway must be outside the reference directory")
    for key in ("PERCLIP_PUBLIC_HOST", "PERCLIP_UPSTREAM_HOST"):
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", env.get(key, "")):
            raise ValueError(f"Invalid or missing gateway host variable: {key}")
    port = env.get("PERCLIP_PORT", "")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("Invalid or missing PERCLIP_PORT")
    for key in ("PERCLIP_TLS_CERT", "PERCLIP_TLS_KEY"):
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", env.get(key, "")):
            raise ValueError(f"Invalid or missing TLS path variable: {key}")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    for path in source.glob("*.conf"):
        content = path.read_text()
        for key in ("PERCLIP_PUBLIC_HOST", "PERCLIP_UPSTREAM_HOST", "PERCLIP_PORT",
                    "PERCLIP_TLS_CERT", "PERCLIP_TLS_KEY"):
            content = content.replace("${" + key + "}", env[key])
        with tempfile.NamedTemporaryFile(mode="w", dir=target, delete=False) as output:
            output.write(content)
        os.replace(output.name, target / path.name)


if __name__ == "__main__":
    render(ROOT / "deploy/openresty-manager", ROOT / "deploy/generated/openresty", dict(os.environ))
    print("Private gateway rendered; deployment values are not printed.")
