from __future__ import annotations

import re

from .recall import safe_text
from .web_extraction import WebFetchError, canonicalize_url


CORRELATION_IDENTITY_MAX_LENGTH = 128
_CORRELATION_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_SENSITIVE_IDENTITY_SEGMENTS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "passwd",
    "secret",
    "session",
    "sessionid",
    "token",
}
_URL_CREDENTIAL_RE = re.compile(r"(?i)(https?://)([^\s/@:]+):([^\s/@]+)@")


def safe_mobile_text(value: object, *, limit: int) -> str:
    """Return the common bounded, redacted mobile display projection."""
    candidate = str(value or "").strip()
    if (
        (candidate.startswith("/") and not any(char.isspace() for char in candidate))
        or candidate.casefold().startswith(("file://", "smb://"))
        or re.match(r"^[A-Za-z]:[\\/]", candidate) is not None
        or candidate.startswith("\\\\")
    ):
        return ""
    # Public mobile text may preserve the useful host/path, but never the
    # credential-bearing userinfo shape.  The shared safe_text placeholder
    # intentionally keeps that shape for internal Recall semantics, while the
    # Quality payload audit correctly rejects it at the public boundary.
    candidate = _URL_CREDENTIAL_RE.sub(r"\1", candidate)
    return safe_text(candidate, limit=limit)


def safe_mobile_url(value: object) -> str:
    """Return a canonical public URL with credentials and tracking removed."""
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    try:
        return canonicalize_url(candidate)
    except WebFetchError:
        return ""


def safe_correlation_identity(value: object) -> str:
    """Allow only bounded opaque capture/client request identifiers."""
    candidate = str(value or "").strip()
    if (
        not candidate
        or len(candidate) > CORRELATION_IDENTITY_MAX_LENGTH
        or _CORRELATION_IDENTITY_RE.fullmatch(candidate) is None
    ):
        return ""
    segments = {segment.casefold() for segment in re.split(r"[.:_-]+", candidate)}
    if segments & _SENSITIVE_IDENTITY_SEGMENTS:
        return ""
    return candidate
