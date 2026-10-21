from __future__ import annotations


ALLOWED_MIME_TYPES = {
    "application/epub+zip",
    "application/json",
    "application/msword",
    "application/octet-stream",
    "application/pdf",
    "application/rtf",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/vnd.oasis.opendocument.presentation",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/x-7z-compressed",
    "application/x-tar",
    "application/zip",
    "text/csv",
    "text/markdown",
    "text/plain",
}

ALLOWED_MIME_PREFIXES = (
    "audio/",
    "image/",
    "text/",
)


def normalize_mime_type(mime_type: str) -> str:
    return mime_type.split(";", 1)[0].strip().lower()


def is_allowed_mime_type(mime_type: str) -> bool:
    normalized = normalize_mime_type(mime_type)
    if not normalized:
        return True
    if normalized in ALLOWED_MIME_TYPES:
        return True
    return any(normalized.startswith(prefix) for prefix in ALLOWED_MIME_PREFIXES)
