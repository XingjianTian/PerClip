from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from html import unescape
from urllib.parse import urlsplit


ENGINE = "perclip-title-author-normalizer"
ENGINE_VERSION = "v1"

BILIBILI_HOSTS = frozenset({"bilibili.com", "www.bilibili.com", "m.bilibili.com"})
BILIBILI_TITLE_SUFFIXES = (
    "_哔哩哔哩_bilibili",
    " - 哔哩哔哩_bilibili",
    " | 哔哩哔哩_bilibili",
    "_哔哩哔哩",
    " - 哔哩哔哩",
    " | 哔哩哔哩",
    " - bilibili",
    " | bilibili",
)
BILIBILI_AUTHOR_PREFIXES = ("UP主：", "UP主:", "作者：", "作者:")
FORMAT_CHARACTERS = str.maketrans({"\u200b": "", "\u2060": "", "\ufeff": ""})


@dataclass(frozen=True)
class NormalizedTitleAuthor:
    title: str
    author: str
    title_changed: bool
    author_changed: bool
    engine: str = ENGINE
    engine_version: str = ENGINE_VERSION


def _mechanical_text(value: str) -> str:
    decoded = unicodedata.normalize("NFC", unescape(str(value or "")[:1200]))
    decoded = decoded.translate(FORMAT_CHARACTERS)
    return " ".join(decoded.split()).strip()


def _exact_host(base_url: str) -> str:
    try:
        return (urlsplit(base_url).hostname or "").casefold().rstrip(".")
    except ValueError:
        return ""


def _strip_suffix(value: str, suffixes: tuple[str, ...]) -> str:
    folded = value.casefold()
    for suffix in suffixes:
        if not folded.endswith(suffix.casefold()):
            continue
        candidate = value[: -len(suffix)].rstrip()
        return candidate or value
    return value


def _strip_prefix(value: str, prefixes: tuple[str, ...]) -> str:
    folded = value.casefold()
    for prefix in prefixes:
        if not folded.startswith(prefix.casefold()):
            continue
        candidate = value[len(prefix) :].lstrip()
        return candidate or value
    return value


def normalize_title_author(
    *,
    title: str,
    author: str,
    base_url: str = "",
) -> NormalizedTitleAuthor:
    """Normalize display metadata without guessing missing title or author semantics."""

    normalized_title = _mechanical_text(title)
    normalized_author = _mechanical_text(author)
    if _exact_host(base_url) in BILIBILI_HOSTS:
        normalized_title = _strip_suffix(normalized_title, BILIBILI_TITLE_SUFFIXES)
        normalized_author = _strip_prefix(normalized_author, BILIBILI_AUTHOR_PREFIXES)
    normalized_title = normalized_title[:300].strip()
    normalized_author = normalized_author[:300].strip()
    return NormalizedTitleAuthor(
        title=normalized_title,
        author=normalized_author,
        title_changed=normalized_title != title,
        author_changed=normalized_author != author,
    )
