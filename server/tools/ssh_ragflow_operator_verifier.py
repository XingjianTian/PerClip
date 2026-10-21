from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


SAFE_TARGET = re.compile(r"^[A-Za-z0-9_.-]+$")
BOOTSTRAP = (
    "import base64,io,json,sys;"
    "e=json.load(sys.stdin);"
    "sys.stdin=io.StringIO(json.dumps(e['request']));"
    "exec(compile(base64.b64decode(e['script']),"
    "'ragflow_es_operator_verifier.py','exec'))"
)


def _required_safe_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or not SAFE_TARGET.fullmatch(value):
        raise RuntimeError(f"{name} must be a safe non-empty target name")
    return value


def main() -> int:
    try:
        request = json.load(sys.stdin)
        allow_dataset_id = os.environ[
            "PERCLIP_OPERATOR_ALLOW_DATASET_ID"
        ].strip()
        if not allow_dataset_id:
            raise RuntimeError("operator dataset allowlist is empty")
        request["allow_dataset_id"] = allow_dataset_id

        ssh_alias = _required_safe_env("PERCLIP_OPERATOR_SSH_ALIAS")
        container = _required_safe_env("PERCLIP_OPERATOR_RAGFLOW_CONTAINER")
        verifier = Path(__file__).with_name(
            "ragflow_es_operator_verifier.py"
        ).read_bytes()
        envelope = json.dumps(
            {
                "script": base64.b64encode(verifier).decode("ascii"),
                "request": request,
            },
            separators=(",", ":"),
        )
        result = subprocess.run(
            [
                "ssh",
                ssh_alias,
                shlex.join(
                    [
                        "docker",
                        "exec",
                        "-i",
                        container,
                        "python",
                        "-c",
                        BOOTSTRAP,
                    ]
                ),
            ],
            input=envelope,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError("remote operator verifier failed")
        payload = json.loads(result.stdout)
        if payload.get("schema") != request.get("schema"):
            raise RuntimeError("remote operator verifier schema mismatch")
        print(json.dumps(payload, separators=(",", ":")))
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "schema": "perclip-ragflow-operator-evidence.v1",
                    "safe_error_code": "operator_transport_failed",
                },
                separators=(",", ":"),
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
