from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .audio_asr import BAIDU_ASR_URL, BAIDU_TOKEN_URL, AudioAsrSettings

UNSAFE_INGEST_TOKENS = {
    "change-me-mobile-token",
    "change-me-wechat-connector-token",
}


@dataclass(frozen=True)
class RagflowSettings:
    base_url: str = ""
    api_key: str = ""
    enable_real_sync: bool = False
    mode: str = "index"
    sync_allow_dataset_ids: frozenset[str] = frozenset()
    index_poll_timeout_seconds: float = 30.0
    index_poll_backoff_seconds: float = 0.25

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    @property
    def real_sync_enabled(self) -> bool:
        return (
            self.effective_mode == "index"
            and self.configured
            and self.enable_real_sync
            and bool(self.sync_allow_dataset_ids)
        )

    @property
    def effective_mode(self) -> str:
        return self.mode


@dataclass(frozen=True)
class TopicEmbeddingSettings:
    enabled: bool = False
    endpoint: str = ""
    api_key: str = ""
    model: str = ""
    provider_version: str = "v1"
    threshold: float = 0.50
    timeout_seconds: float = 10.0
    retries: int = 1
    max_input_chars: int = 8_000


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    ingest_token: str
    max_file_bytes: int = 100 * 1024 * 1024
    max_request_bytes: int = 101 * 1024 * 1024
    clip_to_ragflow_dir: Path | None = None
    enable_clip_to_ragflow: bool = False
    processing_mode: str = "inline"
    asset_root: Path | None = None
    deployment_environment: str = "local"
    enable_web_fetch: bool = False
    web_fetch_max_bytes: int = 5 * 1024 * 1024
    web_fetch_timeout_seconds: float = 20.0
    web_fetch_proxy_host: str = ""
    web_fetch_proxy_port: int = 0
    connector_tokens: dict[str, str] = field(default_factory=dict)
    ragflow: RagflowSettings = field(default_factory=RagflowSettings)
    topic_embedding: TopicEmbeddingSettings = field(
        default_factory=TopicEmbeddingSettings
    )
    audio_asr: AudioAsrSettings = field(default_factory=lambda: AudioAsrSettings(enabled=False))

    def __post_init__(self) -> None:
        validate_ingest_token(self.ingest_token)
        validate_size_limits(
            max_file_bytes=self.max_file_bytes,
            max_request_bytes=self.max_request_bytes,
        )
        validate_clip_to_ragflow_config(
            enabled=self.enable_clip_to_ragflow,
            plugin_dir=self.clip_to_ragflow_dir,
        )
        if self.processing_mode not in {"inline", "worker"}:
            raise RuntimeError("PERCLIP_PROCESSING_MODE must be inline or worker")
        if not self.deployment_environment.strip():
            raise RuntimeError("PERCLIP_DEPLOYMENT_ENVIRONMENT must not be blank")
        if self.web_fetch_max_bytes <= 0:
            raise RuntimeError("PERCLIP_WEB_FETCH_MAX_BYTES must be positive")
        if self.web_fetch_timeout_seconds <= 0:
            raise RuntimeError("PERCLIP_WEB_FETCH_TIMEOUT_SECONDS must be positive")
        validate_web_fetch_proxy_config(
            self.web_fetch_proxy_host,
            self.web_fetch_proxy_port,
        )
        validate_ragflow_config(self.ragflow)
        validate_topic_embedding_config(self.topic_embedding)
        if self.enable_clip_to_ragflow and self.ragflow.enable_real_sync:
            raise RuntimeError("legacy ClipToRAGFlow archiver and real RAGFlow sync cannot be enabled together")
        if self.processing_mode == "worker" and self.enable_clip_to_ragflow:
            raise RuntimeError("worker mode cannot enable the legacy ClipToRAGFlow archiver")
        validate_connector_tokens(self.ingest_token, self.connector_tokens)
        validate_audio_asr_config(self.audio_asr)

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("PERCLIP_DATA_DIR", "data")).resolve()
        ingest_token = required_ingest_token_from_env()
        max_file_bytes = positive_int_from_env(
            "PERCLIP_MAX_FILE_BYTES",
            default=100 * 1024 * 1024,
        )
        max_request_bytes = positive_int_from_env(
            "PERCLIP_MAX_REQUEST_BYTES",
            default=max_file_bytes + 1024 * 1024,
        )
        clip_dir = os.environ.get("PERCLIP_CLIP_TO_RAGFLOW_DIR")
        enable_archiver = bool_from_env("PERCLIP_ENABLE_CLIP_TO_RAGFLOW", default=False)
        baidu_api_key = os.environ.get("BAIDU_API_KEY", "").strip()
        baidu_secret_key = os.environ.get("BAIDU_SECRET_KEY", "").strip()
        enable_audio_asr = bool_from_env(
            "PERCLIP_ENABLE_AUDIO_ASR",
            default=bool(baidu_api_key and baidu_secret_key),
        )
        return cls(
            data_dir=data_dir,
            ingest_token=ingest_token,
            max_file_bytes=max_file_bytes,
            max_request_bytes=max_request_bytes,
            clip_to_ragflow_dir=Path(clip_dir).resolve() if clip_dir else None,
            enable_clip_to_ragflow=enable_archiver,
            processing_mode=os.environ.get("PERCLIP_PROCESSING_MODE", "worker").strip().lower(),
            asset_root=Path(os.environ["PERCLIP_ASSET_ROOT"]).resolve()
            if os.environ.get("PERCLIP_ASSET_ROOT", "").strip()
            else data_dir / "PersonalClips",
            deployment_environment=os.environ.get("PERCLIP_DEPLOYMENT_ENVIRONMENT", "local").strip(),
            enable_web_fetch=bool_from_env("PERCLIP_ENABLE_WEB_FETCH", default=True),
            web_fetch_max_bytes=positive_int_from_env(
                "PERCLIP_WEB_FETCH_MAX_BYTES", default=5 * 1024 * 1024
            ),
            web_fetch_timeout_seconds=float_from_env(
                "PERCLIP_WEB_FETCH_TIMEOUT_SECONDS", default=20.0
            ),
            web_fetch_proxy_host=os.environ.get(
                "PERCLIP_WEB_FETCH_PROXY_HOST", ""
            ),
            web_fetch_proxy_port=positive_int_from_env(
                "PERCLIP_WEB_FETCH_PROXY_PORT", default=0
            ),
            connector_tokens=connector_tokens_from_env(),
            ragflow=RagflowSettings(
                base_url=os.environ.get("RAGFLOW_BASE_URL", ""),
                api_key=os.environ.get("RAGFLOW_API_KEY", ""),
                enable_real_sync=bool_from_env("PERCLIP_ENABLE_REAL_RAGFLOW_SYNC", default=False),
                mode=ragflow_mode_from_env(),
                sync_allow_dataset_ids=frozenset(csv_from_env("PERCLIP_RAGFLOW_SYNC_ALLOW_DATASET_IDS")),
                index_poll_timeout_seconds=float_from_env(
                    "PERCLIP_RAGFLOW_INDEX_POLL_TIMEOUT_SECONDS", default=30.0
                ),
                index_poll_backoff_seconds=float_from_env(
                    "PERCLIP_RAGFLOW_INDEX_POLL_BACKOFF_SECONDS", default=0.25
                ),
            ),
            topic_embedding=TopicEmbeddingSettings(
                enabled=bool_from_env(
                    "PERCLIP_ENABLE_TOPIC_EMBEDDING", default=False
                ),
                endpoint=os.environ.get("PERCLIP_TOPIC_EMBEDDING_ENDPOINT", "").strip(),
                api_key=os.environ.get("PERCLIP_TOPIC_EMBEDDING_API_KEY", "").strip(),
                model=os.environ.get("PERCLIP_TOPIC_EMBEDDING_MODEL", "").strip(),
                provider_version=os.environ.get(
                    "PERCLIP_TOPIC_EMBEDDING_PROVIDER_VERSION", "v1"
                ).strip(),
                threshold=float_from_env(
                    "PERCLIP_TOPIC_EMBEDDING_THRESHOLD", default=0.50
                ),
                timeout_seconds=float_from_env(
                    "PERCLIP_TOPIC_EMBEDDING_TIMEOUT_SECONDS", default=10.0
                ),
                retries=non_negative_int_from_env(
                    "PERCLIP_TOPIC_EMBEDDING_RETRIES", default=1
                ),
                max_input_chars=positive_int_from_env(
                    "PERCLIP_TOPIC_EMBEDDING_MAX_INPUT_CHARS", default=8_000
                ),
            ),
            audio_asr=AudioAsrSettings(
                enabled=enable_audio_asr,
                baidu_api_key=baidu_api_key,
                baidu_secret_key=baidu_secret_key,
                dev_pid=positive_int_from_env("BAIDU_ASR_DEV_PID", default=1537),
                rate=positive_int_from_env("BAIDU_ASR_RATE", default=16000),
                channel=positive_int_from_env("BAIDU_ASR_CHANNEL", default=1),
                token_url=os.environ.get("BAIDU_TOKEN_URL", "").strip() or BAIDU_TOKEN_URL,
                asr_url=os.environ.get("BAIDU_ASR_URL", "").strip() or BAIDU_ASR_URL,
                timeout_seconds=float_from_env("BAIDU_ASR_TIMEOUT_SECONDS", default=30.0),
            ),
        )


def required_ingest_token_from_env() -> str:
    token = os.environ.get("PERCLIP_INGEST_TOKEN", "").strip()
    validate_ingest_token(token, missing_message="PERCLIP_INGEST_TOKEN must be set before starting PerClip ingest API")
    return token


def validate_ingest_token(
    token: str,
    missing_message: str = "ingest_token must not be blank",
) -> None:
    if not token:
        raise RuntimeError(missing_message)
    if any(char.isspace() for char in token):
        raise RuntimeError("ingest_token must not contain spaces or newlines")
    if token in UNSAFE_INGEST_TOKENS:
        raise RuntimeError("ingest_token must be changed from the example placeholder")


def positive_int_from_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    try:
        value = int(raw_value.strip())
    except ValueError as error:
        raise RuntimeError(f"{name} must be a positive integer") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


def validate_web_fetch_proxy_config(host: str, port: int) -> None:
    if host != host.strip():
        raise RuntimeError(
            "PERCLIP_WEB_FETCH_PROXY_HOST must not contain surrounding whitespace"
        )
    if bool(host) != bool(port):
        raise RuntimeError(
            "PERCLIP_WEB_FETCH_PROXY_HOST and PERCLIP_WEB_FETCH_PROXY_PORT must be set together"
        )
    if not host:
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise RuntimeError(
            "PERCLIP_WEB_FETCH_PROXY_HOST must be a numeric loopback IP"
        ) from error
    if not address.is_loopback:
        raise RuntimeError(
            "PERCLIP_WEB_FETCH_PROXY_HOST must be a numeric loopback IP"
        )
    if not 1 <= port <= 65535:
        raise RuntimeError("PERCLIP_WEB_FETCH_PROXY_PORT must be between 1 and 65535")


def non_negative_int_from_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    try:
        value = int(raw_value.strip())
    except ValueError as error:
        raise RuntimeError(f"{name} must be a non-negative integer") from error
    if value < 0:
        raise RuntimeError(f"{name} must be a non-negative integer")
    return value


def validate_size_limits(max_file_bytes: int, max_request_bytes: int) -> None:
    if max_file_bytes <= 0:
        raise RuntimeError("max_file_bytes must be positive")
    if max_request_bytes <= 0:
        raise RuntimeError("max_request_bytes must be positive")
    if max_request_bytes < max_file_bytes:
        raise RuntimeError("max_request_bytes must be greater than or equal to max_file_bytes")


def bool_from_env(name: str, default: bool) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value.strip() == "":
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean value")


def csv_from_env(name: str) -> list[str]:
    return [value.strip() for value in os.environ.get(name, "").split(",") if value.strip()]


def ragflow_mode_from_env() -> str:
    explicit = os.environ.get("RAGFLOW_MODE", "").strip().lower()
    if explicit:
        return explicit
    return (
        "index"
        if bool_from_env("PERCLIP_ENABLE_REAL_RAGFLOW_SYNC", default=False)
        else "off"
    )


def validate_clip_to_ragflow_config(enabled: bool, plugin_dir: Path | None) -> None:
    if not enabled:
        return
    if plugin_dir is None:
        raise RuntimeError("PERCLIP_CLIP_TO_RAGFLOW_DIR must be set when ClipToRAGFlow mode is enabled")
    if not plugin_dir.is_dir():
        raise RuntimeError("PERCLIP_CLIP_TO_RAGFLOW_DIR must point to an existing directory")
    if not (plugin_dir / "clip_to_ragflow").is_dir():
        raise RuntimeError("PERCLIP_CLIP_TO_RAGFLOW_DIR must contain the clip_to_ragflow package")


def validate_ragflow_config(settings: RagflowSettings) -> None:
    if settings.effective_mode not in {"off", "index", "qa"}:
        raise RuntimeError("RAGFLOW_MODE must be off, index, or qa")
    if any(char.isspace() for char in settings.api_key):
        raise RuntimeError("RAGFLOW_API_KEY must not contain spaces or newlines")
    if any(ord(char) < 33 or ord(char) == 127 for char in settings.api_key):
        raise RuntimeError("RAGFLOW_API_KEY contains unsupported characters")
    if any(char.isspace() for char in settings.base_url):
        raise RuntimeError("RAGFLOW_BASE_URL must not contain spaces or newlines")
    if settings.index_poll_timeout_seconds <= 0:
        raise RuntimeError("PERCLIP_RAGFLOW_INDEX_POLL_TIMEOUT_SECONDS must be positive")
    if settings.index_poll_backoff_seconds <= 0:
        raise RuntimeError("PERCLIP_RAGFLOW_INDEX_POLL_BACKOFF_SECONDS must be positive")


def validate_topic_embedding_config(settings: TopicEmbeddingSettings) -> None:
    if not settings.enabled:
        return
    if not settings.endpoint or not settings.api_key or not settings.model:
        raise RuntimeError(
            "topic embedding endpoint, key, and model are required when enabled"
        )
    if any(char.isspace() for char in settings.api_key):
        raise RuntimeError("PERCLIP_TOPIC_EMBEDDING_API_KEY must not contain spaces")
    if not settings.provider_version or len(settings.provider_version) > 64:
        raise RuntimeError("invalid topic embedding provider version")
    if not 0 < settings.threshold <= 1:
        raise RuntimeError("PERCLIP_TOPIC_EMBEDDING_THRESHOLD must be between 0 and 1")
    if settings.timeout_seconds <= 0:
        raise RuntimeError("PERCLIP_TOPIC_EMBEDDING_TIMEOUT_SECONDS must be positive")
    if not 0 <= settings.retries <= 3:
        raise RuntimeError("PERCLIP_TOPIC_EMBEDDING_RETRIES must be between 0 and 3")
    if not 256 <= settings.max_input_chars <= 8_000:
        raise RuntimeError(
            "PERCLIP_TOPIC_EMBEDDING_MAX_INPUT_CHARS must be between 256 and 8000"
        )


def float_from_env(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    try:
        value = float(raw_value.strip())
    except ValueError as error:
        raise RuntimeError(f"{name} must be a positive number") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive number")
    return value


def validate_audio_asr_config(settings: AudioAsrSettings) -> None:
    if not settings.enabled:
        return
    if not settings.baidu_api_key:
        raise RuntimeError("BAIDU_API_KEY must be set when audio ASR is enabled")
    if not settings.baidu_secret_key:
        raise RuntimeError("BAIDU_SECRET_KEY must be set when audio ASR is enabled")
    if settings.rate not in {8000, 16000}:
        raise RuntimeError("BAIDU_ASR_RATE must be 8000 or 16000")
    if settings.channel != 1:
        raise RuntimeError("BAIDU_ASR_CHANNEL must be 1")


def connector_tokens_from_env() -> dict[str, str]:
    raw = os.environ.get("PERCLIP_CONNECTOR_TOKENS_JSON", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError("PERCLIP_CONNECTOR_TOKENS_JSON must be a JSON object") from error
    if not isinstance(payload, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in payload.items()):
        raise RuntimeError("PERCLIP_CONNECTOR_TOKENS_JSON must map adapters to tokens")
    return {key.strip(): value.strip() for key, value in payload.items()}


def validate_connector_tokens(primary_token: str, connector_tokens: dict[str, str]) -> None:
    supported = {"api", "wechat_bot", "webhook", "import"}
    if set(connector_tokens) - supported:
        raise RuntimeError("connector token adapter is unsupported")
    values: list[str] = []
    for adapter, token in connector_tokens.items():
        validate_ingest_token(token, missing_message=f"connector token for {adapter} must not be blank")
        if token == primary_token:
            raise RuntimeError("connector token must differ from the mobile/admin token")
        values.append(token)
    if len(values) != len(set(values)):
        raise RuntimeError("connector tokens must be unique per adapter")
