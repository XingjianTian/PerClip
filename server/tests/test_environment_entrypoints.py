from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_api_uses_explicit_bind_configuration(monkeypatch):
    monkeypatch.setenv("PERCLIP_HOST", "127.0.0.2")
    monkeypatch.setenv("PERCLIP_PORT", "18999")
    result = module("run_service").command(["api"])
    assert result[-4:] == ["--host", "127.0.0.2", "--port", "18999"]
    assert "--factory" in result


def test_worker_forwards_bounded_arguments():
    result = module("run_service").command(["worker", "--once", "--limit", "1"])
    assert result[2:] == ["perclip_ingest.worker", "--once", "--limit", "1"]


def test_gateway_preserves_nginx_variables_and_private_file_mode(tmp_path):
    source = ROOT / "deploy/openresty-manager"
    target = tmp_path / "private"
    env = {"PERCLIP_PUBLIC_HOST": "capture.example.com", "PERCLIP_UPSTREAM_HOST": "127.0.0.2",
           "PERCLIP_PORT": "18999", "PERCLIP_TLS_CERT": "certs/example.crt",
           "PERCLIP_TLS_KEY": "certs/example.key", "RAGFLOW_API_KEY": "unused-fictional-value"}
    module("render_gateway").render(source, target, env)
    body = (target / "perclip.example.com.conf").read_text()
    assert "capture.example.com" in body and "$host" in body
    assert "unused-fictional-value" not in body and "${PERCLIP_" not in body
    assert "127.0.0.2:18999" in (target / "perclip-upstream.conf").read_text()
    assert os.stat(target / "perclip.example.com.conf").st_mode & 0o777 == 0o600


@pytest.mark.parametrize("key,value", [("PERCLIP_PUBLIC_HOST", "example.com; inject"),
                                       ("PERCLIP_PORT", "70000"),
                                       ("PERCLIP_TLS_KEY", "key; inject")])
def test_gateway_rejects_configuration_injection(tmp_path, key, value):
    env = {"PERCLIP_PUBLIC_HOST": "capture.example.com", "PERCLIP_UPSTREAM_HOST": "127.0.0.1",
           "PERCLIP_PORT": "18081", "PERCLIP_TLS_CERT": "example.crt",
           "PERCLIP_TLS_KEY": "example.key"}
    env[key] = value
    with pytest.raises(ValueError):
        module("render_gateway").render(ROOT / "deploy/openresty-manager", tmp_path / "out", env)


def test_public_url_matrix_is_explicitly_fictional():
    import json
    from urllib.parse import urlsplit

    path = ROOT / "tests/fixtures/stage24/public_url_matrix_v1.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 60
    for row in rows:
        assert row["synthetic"] and row["network_calls"] == 0
        assert urlsplit(row["url"]).hostname == "example.invalid"
        assert row["title"].startswith("Synthetic PerClip case ")
        assert row["author"] == "Fictional fixture author"
