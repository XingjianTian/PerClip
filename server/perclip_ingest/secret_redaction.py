from __future__ import annotations

import re


REDACTED_VALUE = "[redacted]"

_SECRET_KEY = r"(?:api[_-]?key|token|password|passwd|secret|credential|cookie)"
_KEY_ASSIGNMENT_RE = re.compile(
    rf"(?i)(?P<prefix>(?<![\w-])(?P<key_quote>[\"']?){_SECRET_KEY}"
    rf"(?P=key_quote)\s*[:=]\s*(?P<value_quote>[\"']?))"
    rf"(?P<value>\[redacted\]|[^\"'\s,;}}\]]+)(?P<suffix>(?P=value_quote))"
)
_AUTHORIZATION_RE = re.compile(
    r"(?i)(?P<prefix>(?<![\w-])(?P<key_quote>[\"']?)authorization"
    r"(?P=key_quote)\s*[:=]\s*(?P<value_quote>[\"']?)"
    r"(?P<scheme>bearer|basic|token|apikey)\s+)"
    r"(?P<value>\[redacted\]|[^\"'\s,;}}\]]+)(?P<suffix>(?P=value_quote))"
)


def redact_structured_secret_values(value: str) -> str:
    """Redact only high-confidence assigned/header values while preserving syntax."""

    def replace(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}{REDACTED_VALUE}{match.group('suffix')}"

    redacted = _AUTHORIZATION_RE.sub(replace, str(value or ""))
    return _KEY_ASSIGNMENT_RE.sub(replace, redacted)


def text_without_structured_secret_assignments(value: str) -> str:
    """Remove recognized assignments for content-emptiness checks, not display redaction."""

    redacted = redact_structured_secret_values(value)
    without_headers = _AUTHORIZATION_RE.sub("", redacted)
    return _KEY_ASSIGNMENT_RE.sub("", without_headers)
