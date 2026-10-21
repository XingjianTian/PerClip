from __future__ import annotations

import re


REDACTED_PATH = "[redacted-path]"
HTTP_URL_RE = re.compile(r"(?i)https?://[^\s<>'\"]+")
PRIVATE_PATH_RE = re.compile(
    r"(?ix)"
    r"(?:"
    r"file://(?:localhost)?/(?:[^\s<>'\"]*)"
    r"|smb://[^\s<>'\"]+"
    r"|\\\\[^\\/\s<>'\"]+[\\/][^\\/\s<>'\"]+(?:[\\/][^\s<>'\"]*)?"
    r"|(?<![A-Za-z0-9])[A-Z]:[\\/][^\s<>'\"]+"
    r"|/(?:Users|home)/[^/\s<>'\"]+(?:/[^\s<>'\"]*)?"
    r"|/(?:mnt|nas|volume\d+|Volumes|opt|srv|root|app|data|tmp)(?:/[^\s<>'\"]*)?"
    r"|/var/lib(?:/[^\s<>'\"]*)?"
    r")"
)


def _outside_http_urls(value: str):
    cursor = 0
    for match in HTTP_URL_RE.finditer(value):
        yield value[cursor : match.start()], False
        yield match.group(0), True
        cursor = match.end()
    yield value[cursor:], False


def redact_private_paths(value: object) -> str:
    """Redact absolute private locations while preserving ordinary URLs and relative paths."""
    parts: list[str] = []
    for segment, is_http_url in _outside_http_urls(str(value or "")):
        parts.append(segment if is_http_url else PRIVATE_PATH_RE.sub(REDACTED_PATH, segment))
    return "".join(parts)


def contains_private_path(value: object) -> bool:
    return any(
        PRIVATE_PATH_RE.search(segment) is not None
        for segment, is_http_url in _outside_http_urls(str(value or ""))
        if not is_http_url
    )
