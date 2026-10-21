from __future__ import annotations

import pytest

from perclip_ingest.config import RagflowSettings, Settings, TopicEmbeddingSettings


def test_from_env_requires_explicit_ingest_token(monkeypatch):
    monkeypatch.delenv("PERCLIP_INGEST_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="PERCLIP_INGEST_TOKEN must be set"):
        Settings.from_env()


def test_from_env_rejects_whitespace_inside_ingest_token(monkeypatch):
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "bad token")

    with pytest.raises(RuntimeError, match="must not contain spaces"):
        Settings.from_env()


def test_from_env_rejects_example_placeholder_ingest_token(monkeypatch):
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "change-me-mobile-token")

    with pytest.raises(RuntimeError, match="changed from the example placeholder"):
        Settings.from_env()


def test_from_env_trims_surrounding_ingest_token_whitespace(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "  secret  ")

    settings = Settings.from_env()

    assert settings.ingest_token == "secret"


def test_settings_constructor_rejects_blank_ingest_token(tmp_path):
    with pytest.raises(RuntimeError, match="must not be blank"):
        Settings(data_dir=tmp_path, ingest_token="")


def test_settings_constructor_rejects_whitespace_ingest_token(tmp_path):
    with pytest.raises(RuntimeError, match="must not contain spaces"):
        Settings(data_dir=tmp_path, ingest_token="bad token")


def test_settings_constructor_rejects_example_placeholder_ingest_token(tmp_path):
    with pytest.raises(RuntimeError, match="changed from the example placeholder"):
        Settings(data_dir=tmp_path, ingest_token="change-me-mobile-token")


def test_worker_mode_rejects_legacy_archiver_and_connector_tokens_are_isolated(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "clip_to_ragflow").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="worker mode cannot enable"):
        Settings(
            data_dir=tmp_path,
            ingest_token="admin",
            processing_mode="worker",
            enable_clip_to_ragflow=True,
            clip_to_ragflow_dir=plugin,
        )
    with pytest.raises(RuntimeError, match="must differ"):
        Settings(
            data_dir=tmp_path,
            ingest_token="same",
            connector_tokens={"wechat_bot": "same"},
        )
    with pytest.raises(RuntimeError, match="unique"):
        Settings(
            data_dir=tmp_path,
            ingest_token="admin",
            connector_tokens={"wechat_bot": "shared", "webhook": "shared"},
        )


def test_from_env_rejects_non_integer_size_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("PERCLIP_MAX_FILE_BYTES", "ten-megabytes")

    with pytest.raises(RuntimeError, match="PERCLIP_MAX_FILE_BYTES must be a positive integer"):
        Settings.from_env()


def test_from_env_rejects_non_positive_size_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("PERCLIP_MAX_REQUEST_BYTES", "0")

    with pytest.raises(RuntimeError, match="PERCLIP_MAX_REQUEST_BYTES must be a positive integer"):
        Settings.from_env()


def test_from_env_rejects_request_limit_smaller_than_file_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("PERCLIP_MAX_FILE_BYTES", "1024")
    monkeypatch.setenv("PERCLIP_MAX_REQUEST_BYTES", "512")

    with pytest.raises(RuntimeError, match="max_request_bytes must be greater than or equal"):
        Settings.from_env()


def test_settings_constructor_rejects_invalid_size_limits(tmp_path):
    with pytest.raises(RuntimeError, match="max_file_bytes must be positive"):
        Settings(data_dir=tmp_path, ingest_token="secret", max_file_bytes=0)

    with pytest.raises(RuntimeError, match="max_request_bytes must be greater than or equal"):
        Settings(
            data_dir=tmp_path,
            ingest_token="secret",
            max_file_bytes=1024,
            max_request_bytes=512,
        )


def test_web_fetch_proxy_defaults_off_and_reads_explicit_loopback_pair(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.delenv("PERCLIP_WEB_FETCH_PROXY_HOST", raising=False)
    monkeypatch.delenv("PERCLIP_WEB_FETCH_PROXY_PORT", raising=False)

    direct = Settings.from_env()
    assert direct.web_fetch_proxy_host == ""
    assert direct.web_fetch_proxy_port == 0

    monkeypatch.setenv("PERCLIP_WEB_FETCH_PROXY_HOST", "127.0.0.1")
    monkeypatch.setenv("PERCLIP_WEB_FETCH_PROXY_PORT", "7890")
    proxied = Settings.from_env()
    assert proxied.web_fetch_proxy_host == "127.0.0.1"
    assert proxied.web_fetch_proxy_port == 7890


@pytest.mark.parametrize(
    ("host", "port", "message"),
    [
        ("127.0.0.1", 0, "must be set together"),
        ("", 7890, "must be set together"),
        ("localhost", 7890, "numeric loopback IP"),
        ("192.0.2.10", 7890, "numeric loopback IP"),
        (" 127.0.0.1", 7890, "surrounding whitespace"),
        ("127.0.0.1", 65536, "between 1 and 65535"),
    ],
)
def test_web_fetch_proxy_rejects_partial_non_loopback_or_invalid_config(
    tmp_path, host, port, message
):
    with pytest.raises(RuntimeError, match=message):
        Settings(
            data_dir=tmp_path,
            ingest_token="secret",
            web_fetch_proxy_host=host,
            web_fetch_proxy_port=port,
        )


def test_web_fetch_proxy_rejects_whitespace_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("PERCLIP_WEB_FETCH_PROXY_HOST", " 127.0.0.1")
    monkeypatch.setenv("PERCLIP_WEB_FETCH_PROXY_PORT", "7890")

    with pytest.raises(RuntimeError, match="surrounding whitespace"):
        Settings.from_env()


def test_topic_embedding_is_default_off_and_requires_server_only_config(tmp_path):
    settings = Settings(data_dir=tmp_path, ingest_token="secret")
    assert settings.topic_embedding.enabled is False
    with pytest.raises(RuntimeError, match="endpoint, key, and model"):
        Settings(
            data_dir=tmp_path,
            ingest_token="secret",
            topic_embedding=TopicEmbeddingSettings(enabled=True),
        )
    configured = Settings(
        data_dir=tmp_path,
        ingest_token="secret",
        topic_embedding=TopicEmbeddingSettings(
            enabled=True,
            endpoint="http://embedding.invalid/v1",
            api_key="server-key",
            model="fixture-model",
        ),
    )
    assert configured.topic_embedding.model == "fixture-model"


def test_from_env_rejects_invalid_clip_to_ragflow_boolean(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("PERCLIP_ENABLE_CLIP_TO_RAGFLOW", "treu")

    with pytest.raises(RuntimeError, match="PERCLIP_ENABLE_CLIP_TO_RAGFLOW must be a boolean value"):
        Settings.from_env()


def test_from_env_requires_plugin_dir_when_clip_to_ragflow_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("PERCLIP_ENABLE_CLIP_TO_RAGFLOW", "true")
    monkeypatch.delenv("PERCLIP_CLIP_TO_RAGFLOW_DIR", raising=False)

    with pytest.raises(RuntimeError, match="PERCLIP_CLIP_TO_RAGFLOW_DIR must be set"):
        Settings.from_env()


def test_from_env_rejects_missing_clip_to_ragflow_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("PERCLIP_ENABLE_CLIP_TO_RAGFLOW", "1")
    monkeypatch.setenv("PERCLIP_CLIP_TO_RAGFLOW_DIR", str(tmp_path / "missing-plugin"))

    with pytest.raises(RuntimeError, match="must point to an existing directory"):
        Settings.from_env()


def test_from_env_rejects_clip_to_ragflow_dir_without_package(monkeypatch, tmp_path):
    plugin_dir = tmp_path / "ClipToRAGFlow"
    plugin_dir.mkdir()
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("PERCLIP_ENABLE_CLIP_TO_RAGFLOW", "1")
    monkeypatch.setenv("PERCLIP_CLIP_TO_RAGFLOW_DIR", str(plugin_dir))

    with pytest.raises(RuntimeError, match="must contain the clip_to_ragflow package"):
        Settings.from_env()


def test_from_env_accepts_existing_clip_to_ragflow_dir_when_enabled(monkeypatch, tmp_path):
    plugin_dir = tmp_path / "ClipToRAGFlow"
    (plugin_dir / "clip_to_ragflow").mkdir(parents=True)
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("PERCLIP_ENABLE_CLIP_TO_RAGFLOW", "yes")
    monkeypatch.setenv("PERCLIP_CLIP_TO_RAGFLOW_DIR", str(plugin_dir))
    monkeypatch.setenv("PERCLIP_PROCESSING_MODE", "inline")

    settings = Settings.from_env()

    assert settings.enable_clip_to_ragflow is True
    assert settings.clip_to_ragflow_dir == plugin_dir.resolve()


def test_from_env_reads_ragflow_settings_from_server_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("RAGFLOW_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("RAGFLOW_API_KEY", "test-ragflow-key")

    settings = Settings.from_env()

    assert settings.ragflow.base_url == "http://127.0.0.1:18080"
    assert settings.ragflow.api_key == "test-ragflow-key"
    assert settings.ragflow.configured is True
    assert settings.ragflow.real_sync_enabled is False
    assert settings.ragflow.effective_mode == "off"


def test_from_env_enables_real_ragflow_sync_only_with_allowlisted_dataset(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("RAGFLOW_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("RAGFLOW_API_KEY", "test-ragflow-key")
    monkeypatch.setenv("PERCLIP_ENABLE_REAL_RAGFLOW_SYNC", "true")
    monkeypatch.setenv("PERCLIP_RAGFLOW_SYNC_ALLOW_DATASET_IDS", " dataset-test , dataset-second ")

    settings = Settings.from_env()

    assert settings.ragflow.real_sync_enabled is True
    assert settings.ragflow.effective_mode == "index"
    assert settings.ragflow.sync_allow_dataset_ids == frozenset({"dataset-test", "dataset-second"})


@pytest.mark.parametrize("mode", ["off", "index", "qa"])
def test_from_env_accepts_explicit_ragflow_modes(monkeypatch, tmp_path, mode):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("RAGFLOW_MODE", mode)

    assert Settings.from_env().ragflow.effective_mode == mode


def test_from_env_rejects_unknown_ragflow_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("RAGFLOW_MODE", "assistant")

    with pytest.raises(RuntimeError, match="RAGFLOW_MODE"):
        Settings.from_env()


def test_from_env_rejects_ragflow_api_key_with_whitespace(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("RAGFLOW_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("RAGFLOW_API_KEY", "bad key")

    with pytest.raises(RuntimeError, match="RAGFLOW_API_KEY must not contain spaces"):
        Settings.from_env()


def test_from_env_rejects_ragflow_api_key_with_surrounding_newline(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("RAGFLOW_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("RAGFLOW_API_KEY", "test-ragflow-key\n")

    with pytest.raises(RuntimeError, match="RAGFLOW_API_KEY must not contain spaces"):
        Settings.from_env()


def test_from_env_rejects_ragflow_api_key_with_control_character(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("RAGFLOW_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("RAGFLOW_API_KEY", "test-ragflow-key\x7f")

    with pytest.raises(RuntimeError, match="RAGFLOW_API_KEY contains unsupported characters"):
        Settings.from_env()


def test_audio_asr_defaults_disabled_without_baidu_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.delenv("BAIDU_API_KEY", raising=False)
    monkeypatch.delenv("BAIDU_SECRET_KEY", raising=False)
    monkeypatch.delenv("PERCLIP_ENABLE_AUDIO_ASR", raising=False)

    settings = Settings.from_env()

    assert settings.audio_asr.enabled is False


def test_audio_asr_defaults_enabled_when_baidu_credentials_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("BAIDU_API_KEY", "api")
    monkeypatch.setenv("BAIDU_SECRET_KEY", "secret-key")
    monkeypatch.setenv("BAIDU_ASR_DEV_PID", "1537")
    monkeypatch.setenv("BAIDU_ASR_RATE", "16000")

    settings = Settings.from_env()

    assert settings.audio_asr.enabled is True
    assert settings.audio_asr.baidu_api_key == "api"
    assert settings.audio_asr.baidu_secret_key == "secret-key"
    assert settings.audio_asr.dev_pid == 1537
    assert settings.audio_asr.rate == 16000


def test_audio_asr_rejects_enabled_without_baidu_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("PERCLIP_ENABLE_AUDIO_ASR", "1")
    monkeypatch.delenv("BAIDU_API_KEY", raising=False)
    monkeypatch.delenv("BAIDU_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="BAIDU_API_KEY must be set"):
        Settings.from_env()


def test_audio_asr_rejects_unsupported_sample_rate(monkeypatch, tmp_path):
    monkeypatch.setenv("PERCLIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PERCLIP_INGEST_TOKEN", "secret")
    monkeypatch.setenv("BAIDU_API_KEY", "api")
    monkeypatch.setenv("BAIDU_SECRET_KEY", "secret-key")
    monkeypatch.setenv("BAIDU_ASR_RATE", "44100")

    with pytest.raises(RuntimeError, match="BAIDU_ASR_RATE must be 8000 or 16000"):
        Settings.from_env()


def test_rejects_legacy_archiver_and_real_ragflow_sync_together(tmp_path):
    plugin_dir = tmp_path / "legacy"
    (plugin_dir / "clip_to_ragflow").mkdir(parents=True)

    with pytest.raises(RuntimeError, match="legacy ClipToRAGFlow archiver and real RAGFlow sync cannot be enabled together"):
        Settings(
            data_dir=tmp_path / "data",
            ingest_token="secret",
            clip_to_ragflow_dir=plugin_dir,
            enable_clip_to_ragflow=True,
            ragflow=RagflowSettings(base_url="http://ragflow.test", api_key="key", enable_real_sync=True),
        )
