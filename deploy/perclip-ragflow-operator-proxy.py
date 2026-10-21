from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
from typing import Any


SCHEMA = "perclip-ragflow-operator-evidence.v1"
EVIDENCE_TYPE = "operator_es_exact_document"
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
SAFE_CONTAINER = re.compile(r"^[A-Za-z0-9_.-]+$")
MAX_MESSAGE_BYTES = 64 * 1024
BOOTSTRAP = (
    "import base64,io,json,sys;"
    "e=json.load(sys.stdin);"
    "sys.stdin=io.StringIO(json.dumps(e['request']));"
    "exec(compile(base64.b64decode(e['script']),"
    "'ragflow_es_operator_verifier.py','exec'))"
)


class ProxyConfigurationError(RuntimeError):
    pass


def _alias(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _parse_private_environment(path: Path) -> dict[str, str]:
    required = {
        "PERCLIP_OPERATOR_ALLOW_DATASET_ID",
        "PERCLIP_OPERATOR_RAGFLOW_CONTAINER",
        "PERCLIP_RAGFLOW_SYNC_ALLOW_DATASET_IDS",
    }
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key not in required:
            continue
        if key in values:
            raise ProxyConfigurationError("operator environment contains duplicates")
        try:
            parsed = shlex.split(raw_value, comments=True, posix=True)
        except ValueError as error:
            raise ProxyConfigurationError(
                "operator environment is malformed"
            ) from error
        if len(parsed) != 1:
            raise ProxyConfigurationError("operator environment value is invalid")
        values[key] = parsed[0]
    if set(values) != required:
        raise ProxyConfigurationError("operator environment is incomplete")
    return values


def load_operator_scope(environment_file: Path) -> tuple[str, str]:
    values = _parse_private_environment(environment_file)
    allowed = [
        item.strip()
        for item in values["PERCLIP_RAGFLOW_SYNC_ALLOW_DATASET_IDS"].split(",")
        if item.strip()
    ]
    operator_allowed = values["PERCLIP_OPERATOR_ALLOW_DATASET_ID"].strip()
    container = values["PERCLIP_OPERATOR_RAGFLOW_CONTAINER"].strip()
    if (
        len(allowed) != 1
        or not SAFE_ID.fullmatch(allowed[0])
        or operator_allowed != allowed[0]
    ):
        raise ProxyConfigurationError("operator Dataset scope is not exact")
    if not SAFE_CONTAINER.fullmatch(container):
        raise ProxyConfigurationError("operator container is invalid")
    return allowed[0], container


def validate_request(payload: Any, *, allowed_dataset_id: str) -> dict[str, str]:
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("operator request schema is invalid")
    dataset_id = str(payload.get("dataset_id") or "").strip()
    document_id = str(payload.get("document_id") or "").strip()
    if (
        dataset_id != allowed_dataset_id
        or not SAFE_ID.fullmatch(dataset_id)
        or not SAFE_ID.fullmatch(document_id)
    ):
        raise ValueError("operator request scope is invalid")
    return {
        "schema": SCHEMA,
        "dataset_id": dataset_id,
        "document_id": document_id,
        "allow_dataset_id": allowed_dataset_id,
    }


def validate_evidence(
    payload: Any, *, dataset_id: str, document_id: str
) -> dict[str, object]:
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("operator evidence schema is invalid")
    if payload.get("dataset_alias") != _alias(dataset_id):
        raise ValueError("operator evidence Dataset identity is invalid")
    if payload.get("document_alias") != _alias(document_id):
        raise ValueError("operator evidence Document identity is invalid")
    counts: dict[str, int] = {}
    for key in ("chunk_count", "vector_count", "covered_chunk_count"):
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("operator evidence count is invalid")
        counts[key] = value
    if payload.get("evidence_type") != EVIDENCE_TYPE:
        raise ValueError("operator evidence type is invalid")
    return {
        "schema": SCHEMA,
        "dataset_alias": _alias(dataset_id),
        "document_alias": _alias(document_id),
        **counts,
        "evidence_type": EVIDENCE_TYPE,
    }


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise RuntimeError("operator request ended early")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class OperatorProxy:
    def __init__(
        self,
        *,
        socket_path: Path,
        docker_binary: str,
        ragflow_container: str,
        allowed_dataset_id: str,
        verifier_script: bytes,
        socket_uid: int | None = None,
        socket_gid: int | None = None,
        timeout_seconds: float = 75.0,
    ) -> None:
        self.socket_path = socket_path
        self.docker_binary = docker_binary
        self.ragflow_container = ragflow_container
        self.allowed_dataset_id = allowed_dataset_id
        self.verifier_script = base64.b64encode(verifier_script).decode("ascii")
        self.socket_uid = socket_uid
        self.socket_gid = socket_gid
        self.timeout_seconds = timeout_seconds
        self.server: socket.socket | None = None
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()

    def inspect(self, encoded_request: bytes) -> dict[str, object]:
        request = validate_request(
            json.loads(encoded_request.decode("utf-8")),
            allowed_dataset_id=self.allowed_dataset_id,
        )
        envelope = json.dumps(
            {"script": self.verifier_script, "request": request},
            separators=(",", ":"),
        )
        result = subprocess.run(
            [
                self.docker_binary,
                "exec",
                "-i",
                self.ragflow_container,
                "python",
                "-c",
                BOOTSTRAP,
            ],
            input=envelope,
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError("operator verifier failed safely")
        return validate_evidence(
            json.loads(result.stdout),
            dataset_id=request["dataset_id"],
            document_id=request["document_id"],
        )

    def _safe_error(self) -> dict[str, str]:
        return {"schema": SCHEMA, "safe_error_code": "operator_verification_failed"}

    def _serve_connection(self, connection: socket.socket) -> None:
        try:
            request_size = struct.unpack("!I", _receive_exact(connection, 4))[0]
            if not 0 < request_size <= MAX_MESSAGE_BYTES:
                raise RuntimeError("operator request size is invalid")
            response = self.inspect(_receive_exact(connection, request_size))
        except Exception:
            response = self._safe_error()
        encoded = json.dumps(response, separators=(",", ":")).encode("utf-8")
        connection.sendall(struct.pack("!I", len(encoded)) + encoded)

    def serve(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            mode = self.socket_path.stat().st_mode
            if not stat.S_ISSOCK(mode):
                raise ProxyConfigurationError("operator socket path is unsafe")
            self.socket_path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server = server
        server.bind(str(self.socket_path))
        if self.socket_uid is not None or self.socket_gid is not None:
            os.chown(
                self.socket_path,
                -1 if self.socket_uid is None else self.socket_uid,
                -1 if self.socket_gid is None else self.socket_gid,
            )
        os.chmod(self.socket_path, 0o600)
        server.listen(4)
        server.settimeout(0.5)
        self.ready_event.set()
        while not self.stop_event.is_set():
            try:
                connection, _ = server.accept()
            except TimeoutError:
                continue
            except OSError:
                if self.stop_event.is_set():
                    break
                raise
            with connection:
                connection.settimeout(self.timeout_seconds)
                self._serve_connection(connection)

    def stop(self) -> None:
        self.stop_event.set()
        if self.server is not None:
            self.server.close()

    def cleanup(self) -> None:
        if self.socket_path.exists() and stat.S_ISSOCK(
            self.socket_path.stat().st_mode
        ):
            self.socket_path.unlink()


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment-file", type=Path, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--verifier-script", type=Path, required=True)
    parser.add_argument("--docker", required=True)
    parser.add_argument("--socket-uid", type=int)
    parser.add_argument("--socket-gid", type=int)
    parser.add_argument("worker_command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.worker_command[:1] == ["--"]:
        args.worker_command = args.worker_command[1:]
    if not args.worker_command:
        parser.error("worker command is required")
    return args


def _wait_for_worker(
    worker: subprocess.Popen[bytes],
    proxy_thread: threading.Thread,
    shutdown_requested: threading.Event,
    *,
    wait_seconds: float = 0.25,
) -> int:
    while worker.poll() is None:
        if not proxy_thread.is_alive() and not shutdown_requested.is_set():
            worker.terminate()
            worker.wait()
            raise RuntimeError("operator proxy stopped unexpectedly")
        threading.Event().wait(wait_seconds)
    return 0 if shutdown_requested.is_set() else worker.returncode


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    allowed_dataset_id, ragflow_container = load_operator_scope(
        args.environment_file
    )
    proxy = OperatorProxy(
        socket_path=args.socket,
        docker_binary=args.docker,
        ragflow_container=ragflow_container,
        allowed_dataset_id=allowed_dataset_id,
        verifier_script=args.verifier_script.read_bytes(),
        socket_uid=args.socket_uid,
        socket_gid=args.socket_gid,
    )
    thread = threading.Thread(target=proxy.serve, daemon=True)
    thread.start()
    for _ in range(100):
        if proxy.ready_event.is_set():
            break
        if not thread.is_alive():
            raise RuntimeError("operator proxy failed to start")
        threading.Event().wait(0.02)
    if not proxy.ready_event.is_set():
        raise RuntimeError("operator proxy did not become ready")

    worker = subprocess.Popen(args.worker_command)
    shutdown_requested = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        shutdown_requested.set()
        proxy.stop()
        if worker.poll() is None:
            worker.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        return _wait_for_worker(worker, thread, shutdown_requested)
    finally:
        proxy.stop()
        thread.join(timeout=2)
        proxy.cleanup()


if __name__ == "__main__":
    sys.exit(main())
