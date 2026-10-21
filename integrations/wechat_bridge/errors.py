"""Stable, non-sensitive bridge error categories."""


class BridgeError(Exception):
    code = "bridge_error"


class ConfigurationError(BridgeError):
    code = "configuration_error"


class MappingError(BridgeError):
    code = "invalid_event"


class UnsupportedEventError(BridgeError):
    code = "unsupported"


class MediaError(BridgeError):
    code = "media_error"


class RetryableIngestError(BridgeError):
    code = "upstream_retryable"


class TerminalIngestError(BridgeError):
    code = "upstream_terminal"


class IngestConflictError(TerminalIngestError):
    code = "content_conflict"


class LeaseLostError(BridgeError):
    code = "lease_lost"
