from __future__ import annotations

import json
import os
import socket
import struct
import sys


SCHEMA = "perclip-ragflow-operator-evidence.v1"
MAX_MESSAGE_BYTES = 64 * 1024


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise RuntimeError("operator proxy response ended early")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _exchange(socket_path: str, request: bytes) -> bytes:
    if not request or len(request) > MAX_MESSAGE_BYTES:
        raise RuntimeError("operator request size is invalid")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(
            float(os.environ.get("PERCLIP_OPERATOR_SOCKET_TIMEOUT_SECONDS", "90"))
        )
        connection.connect(socket_path)
        connection.sendall(struct.pack("!I", len(request)) + request)
        response_size = struct.unpack("!I", _receive_exact(connection, 4))[0]
        if not 0 < response_size <= MAX_MESSAGE_BYTES:
            raise RuntimeError("operator proxy response size is invalid")
        return _receive_exact(connection, response_size)


def main() -> int:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict) or request.get("schema") != SCHEMA:
            raise RuntimeError("operator request schema is invalid")
        dataset_id = str(request.get("dataset_id") or "").strip()
        document_id = str(request.get("document_id") or "").strip()
        allowed_dataset_id = os.environ.get(
            "PERCLIP_OPERATOR_ALLOW_DATASET_ID", ""
        ).strip()
        if (
            not dataset_id
            or not document_id
            or not allowed_dataset_id
            or dataset_id != allowed_dataset_id
        ):
            raise RuntimeError("operator request scope is invalid")
        socket_path = os.environ.get("PERCLIP_OPERATOR_SOCKET_PATH", "").strip()
        if not socket_path:
            raise RuntimeError("operator socket is not configured")
        encoded = json.dumps(request, separators=(",", ":")).encode("utf-8")
        payload = json.loads(_exchange(socket_path, encoded).decode("utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != SCHEMA
            or payload.get("safe_error_code")
        ):
            raise RuntimeError("operator proxy rejected the request")
        print(json.dumps(payload, separators=(",", ":")))
        return 0
    except Exception:
        print(
            json.dumps(
                {"schema": SCHEMA, "safe_error_code": "operator_transport_failed"},
                separators=(",", ":"),
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
