from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import uuid
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


proxy_module = _load(
    "perclip_ragflow_operator_proxy",
    ROOT / "deploy" / "perclip-ragflow-operator-proxy.py",
)
client_module = _load(
    "unix_ragflow_operator_verifier",
    ROOT / "server" / "tools" / "unix_ragflow_operator_verifier.py",
)
STAGE23_3B_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "staging"
    / "perclip_stage23_3b_synthetic_v1.json"
)


def _alias(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _environment(tmp_path: Path, *, sync_allowlist: str = "dataset-test") -> Path:
    path = tmp_path / "private.env"
    path.write_text(
        "\n".join(
            [
                f"PERCLIP_RAGFLOW_SYNC_ALLOW_DATASET_IDS={sync_allowlist}",
                "PERCLIP_OPERATOR_ALLOW_DATASET_ID=dataset-test",
                "PERCLIP_OPERATOR_RAGFLOW_CONTAINER=ragflow-server",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_proxy_requires_one_matching_exact_dataset_allowlist(tmp_path):
    environment = _environment(tmp_path)

    assert proxy_module.load_operator_scope(environment) == (
        "dataset-test",
        "ragflow-server",
    )

    for invalid in ("dataset-test,dataset-other", "dataset-other", ""):
        environment = _environment(tmp_path, sync_allowlist=invalid)
        with pytest.raises(proxy_module.ProxyConfigurationError):
            proxy_module.load_operator_scope(environment)


def test_stage23_3b_fixture_is_versioned_bounded_synthetic_and_replayable():
    fixture = json.loads(STAGE23_3B_FIXTURE.read_text(encoding="utf-8"))
    items = fixture["items"]
    request_ids = [item["request_id"] for item in items]

    assert fixture["schema"] == "perclip.stage23-3b-synthetic.v1"
    assert fixture["label"] == "Stage 23.3B Synthetic v1"
    assert len(items) == 6
    assert len(set(request_ids)) == len(items)
    assert all("synthetic" in (item["title"] + item["text"]).lower() for item in items)
    replay = fixture["exact_replay"]
    replay_item = next(item for item in items if item["key"] == replay["item_key"])
    assert replay["request_id"] == replay_item["request_id"]
    heading_item = next(
        item for item in items if item["scenario"] == "markdown_heading_retrieval"
    )
    assert heading_item["text"].count("\n## ") >= 6
    assert "STAGE23_3B_ATLAS_MIDDLE" in heading_item["text"]
    assert "STAGE23_3B_ATLAS_LAST" in heading_item["text"]
    multichunk_item = next(
        item for item in items if item["scenario"] == "markdown_verified_multichunk"
    )
    assert len(multichunk_item["text"].encode("utf-8")) >= 8_000
    assert multichunk_item["text"].count("\n## ") >= 12
    assert "STAGE23_3B_AIRSHIP_FIRST" in multichunk_item["text"]
    assert "STAGE23_3B_AIRSHIP_MIDDLE" in multichunk_item["text"]
    assert "STAGE23_3B_AIRSHIP_LAST" in multichunk_item["text"]


def test_runtime_packages_and_starts_operator_worker_as_a_module():
    dockerfile = (ROOT / "deploy" / "perclip-runtime.Dockerfile").read_text()
    unit = (
        ROOT / "deploy" / "perclip-worker-operator-container.service.in"
    ).read_text()

    assert "server/tools/__init__.py" in dockerfile
    assert "python -m tools.run_operator_verified_worker" in unit
    assert "python /opt/perclip/server/tools/run_operator_verified_worker.py" not in unit


def test_control_helper_binds_hashed_candidate_to_installed_runtime_paths():
    helper = (ROOT / "deploy" / "perclip-stage23-3b-control.sh").read_text()

    assert '"--env-file $INSTALLED_ENV "' in helper
    assert '"$INSTALLED_OPERATOR_PROXY --environment-file $INSTALLED_ENV "' in helper
    assert '"--verifier-script $INSTALLED_OPERATOR_VERIFIER "' in helper
    assert '"python -m tools.run_operator_verified_worker"' in helper


def test_proxy_rejects_non_target_requests_and_untrusted_evidence():
    valid = {
        "schema": proxy_module.SCHEMA,
        "dataset_id": "dataset-test",
        "document_id": "document-test",
    }

    assert proxy_module.validate_request(
        valid, allowed_dataset_id="dataset-test"
    )["allow_dataset_id"] == "dataset-test"
    with pytest.raises(ValueError):
        proxy_module.validate_request(
            {**valid, "dataset_id": "dataset-other"},
            allowed_dataset_id="dataset-test",
        )

    evidence = {
        "schema": proxy_module.SCHEMA,
        "dataset_alias": _alias("dataset-test"),
        "document_alias": _alias("document-test"),
        "chunk_count": 2,
        "vector_count": 2,
        "covered_chunk_count": 2,
        "evidence_type": proxy_module.EVIDENCE_TYPE,
    }
    assert proxy_module.validate_evidence(
        evidence, dataset_id="dataset-test", document_id="document-test"
    ) == evidence
    with pytest.raises(ValueError):
        proxy_module.validate_evidence(
            {**evidence, "vector_count": 1, "document_alias": _alias("other")},
            dataset_id="dataset-test",
            document_id="document-test",
        )


def test_proxy_executes_only_the_configured_container_and_returns_safe_evidence(
    tmp_path, monkeypatch
):
    observed: dict[str, object] = {}

    def run(command, **kwargs):
        observed["command"] = command
        envelope = json.loads(kwargs["input"])
        observed["request"] = envelope["request"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "schema": proxy_module.SCHEMA,
                    "dataset_alias": _alias("dataset-test"),
                    "document_alias": _alias("document-test"),
                    "chunk_count": 3,
                    "vector_count": 3,
                    "covered_chunk_count": 3,
                    "evidence_type": proxy_module.EVIDENCE_TYPE,
                }
            ),
            stderr="private upstream warning",
        )

    monkeypatch.setattr(proxy_module.subprocess, "run", run)
    proxy = proxy_module.OperatorProxy(
        socket_path=tmp_path / "operator.sock",
        docker_binary="/usr/bin/docker",
        ragflow_container="ragflow-server",
        allowed_dataset_id="dataset-test",
        verifier_script=b"print('unused')",
    )
    evidence = proxy.inspect(
        json.dumps(
            {
                "schema": proxy_module.SCHEMA,
                "dataset_id": "dataset-test",
                "document_id": "document-test",
            }
        ).encode()
    )

    assert observed["command"][:4] == [
        "/usr/bin/docker",
        "exec",
        "-i",
        "ragflow-server",
    ]
    assert observed["request"]["allow_dataset_id"] == "dataset-test"
    assert evidence["vector_count"] == evidence["chunk_count"] == 3
    assert "private upstream warning" not in json.dumps(evidence)


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    result = b""
    while len(result) < size:
        result += connection.recv(size - len(result))
    return result


def test_unix_client_double_checks_allowlist_and_transports_bounded_evidence(
    tmp_path, monkeypatch, capsys
):
    socket_path = Path(tempfile.gettempdir()) / f"perclip-{uuid.uuid4().hex}.sock"
    ready = threading.Event()

    def server() -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(socket_path))
            listener.listen(1)
            ready.set()
            connection, _ = listener.accept()
            with connection:
                size = struct.unpack("!I", _receive_exact(connection, 4))[0]
                request = json.loads(_receive_exact(connection, size))
                assert request["dataset_id"] == "dataset-test"
                response = json.dumps(
                    {
                        "schema": proxy_module.SCHEMA,
                        "dataset_alias": _alias("dataset-test"),
                        "document_alias": _alias("document-test"),
                        "chunk_count": 1,
                        "vector_count": 1,
                        "covered_chunk_count": 1,
                        "evidence_type": proxy_module.EVIDENCE_TYPE,
                    },
                    separators=(",", ":"),
                ).encode()
                connection.sendall(struct.pack("!I", len(response)) + response)

    thread = threading.Thread(target=server)
    thread.start()
    assert ready.wait(2)
    monkeypatch.setenv("PERCLIP_OPERATOR_SOCKET_PATH", str(socket_path))
    monkeypatch.setenv("PERCLIP_OPERATOR_ALLOW_DATASET_ID", "dataset-test")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "schema": proxy_module.SCHEMA,
                    "dataset_id": "dataset-test",
                    "document_id": "document-test",
                }
            )
        ),
    )

    assert client_module.main() == 0
    thread.join(timeout=2)
    payload = json.loads(capsys.readouterr().out)
    assert payload["vector_count"] == payload["chunk_count"] == 1

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "schema": proxy_module.SCHEMA,
                    "dataset_id": "dataset-other",
                    "document_id": "document-test",
                }
            )
        ),
    )
    assert client_module.main() == 1
    assert json.loads(capsys.readouterr().out)["safe_error_code"] == (
        "operator_transport_failed"
    )
    socket_path.unlink(missing_ok=True)


def test_proxy_socket_is_private_and_owned_by_configured_worker(
    tmp_path, monkeypatch
):
    socket_path = Path(tempfile.gettempdir()) / f"perclip-{uuid.uuid4().hex}.sock"
    observed: list[tuple[Path, int, int]] = []
    real_chown = proxy_module.os.chown

    def chown(path, uid, gid):
        observed.append((Path(path), uid, gid))
        real_chown(path, uid, gid)

    monkeypatch.setattr(proxy_module.os, "chown", chown)
    proxy = proxy_module.OperatorProxy(
        socket_path=socket_path,
        docker_binary="/usr/bin/docker",
        ragflow_container="ragflow-server",
        allowed_dataset_id="dataset-test",
        verifier_script=b"print('unused')",
        socket_uid=proxy_module.os.getuid(),
        socket_gid=proxy_module.os.getgid(),
    )
    thread = threading.Thread(target=proxy.serve)
    thread.start()

    assert proxy.ready_event.wait(2)
    assert socket_path.exists()
    assert stat.S_IMODE(socket_path.stat().st_mode) == 0o600
    assert observed == [
        (socket_path, proxy_module.os.getuid(), proxy_module.os.getgid())
    ]
    proxy.stop()
    thread.join(timeout=2)
    proxy.cleanup()


def test_expected_shutdown_does_not_report_proxy_exit_as_unexpected():
    worker = Mock()
    worker.poll.side_effect = [None, 0]
    proxy_thread = Mock()
    proxy_thread.is_alive.return_value = False
    shutdown_requested = threading.Event()
    shutdown_requested.set()

    assert (
        proxy_module._wait_for_worker(
            worker,
            proxy_thread,
            shutdown_requested,
            wait_seconds=0,
        )
        == 0
    )
    worker.terminate.assert_not_called()
    worker.wait.assert_not_called()


def test_unexpected_proxy_exit_terminates_worker_and_fails_closed():
    worker = Mock()
    worker.poll.return_value = None
    proxy_thread = Mock()
    proxy_thread.is_alive.return_value = False
    shutdown_requested = threading.Event()

    with pytest.raises(RuntimeError, match="operator proxy stopped unexpectedly"):
        proxy_module._wait_for_worker(
            worker,
            proxy_thread,
            shutdown_requested,
            wait_seconds=0,
        )

    worker.terminate.assert_called_once_with()
    worker.wait.assert_called_once_with()
