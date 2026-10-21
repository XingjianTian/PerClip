from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

from .mobile_safety import redact_private_paths
from .secret_redaction import (
    redact_structured_secret_values,
    text_without_structured_secret_assignments,
)
from .web_extraction import WebFetchError, canonicalize_url


GENERIC_TAGS = {"text", "url", "image", "file", "screen_clip", "knowledge-base", "unknown", "clip"}
MAX_TOPICS_PER_CLIP = 3
MAX_LABEL_LENGTH = 64
URL_CREDENTIAL_RE = re.compile(r"(?i)(https?://)([^\s/@:]+):([^\s/@]+)@")
WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class RecallCandidate:
    internal_clip_id: str
    clip_id: str
    client_request_id: str
    title: str
    summary: str
    reveal_text: str
    source_type: str
    source_app: str
    url: str
    filename: str
    captured_at: str
    knowledge_base_name: str
    tags: list[str]
    topics: list[tuple[str, str]]
    score: int
    recall_count: int = 0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def normalized_label(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value.strip()).casefold()


def topic_id(label: str) -> str:
    normalized = normalized_label(label)
    return "topic:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def safe_text(value: str, *, limit: int = 400) -> str:
    value = redact_structured_secret_values(str(value or ""))
    value = URL_CREDENTIAL_RE.sub(r"\1[redacted]:[redacted]@", value)
    value = redact_private_paths(value)
    return WHITESPACE_RE.sub(" ", value).strip()[:limit]


def has_displayable_text(values: Iterable[object]) -> bool:
    return any(
        safe_text(text_without_structured_secret_assignments(str(value or "")))
        not in {"", "[redacted]"}
        for value in values
    )


def displayable_title_hint(value: object) -> str:
    title = safe_text(str(value or ""), limit=160)
    return "" if title in {"未命名收藏", "未命名闪记", "闪记"} else title


def display_title(row: object, enrichment: object | None) -> str:
    candidates = [
        getattr(enrichment, "title", "") if enrichment else "",
        getattr(row, "title_hint", ""),
        getattr(row, "filename", "") if str(getattr(row, "source_type", "")) in {"file", "image", "audio"} else "",
    ]
    for value in candidates:
        text = displayable_title_hint(value)
        if text:
            return text
    return {
        "url": "网页闪记", "text": "文字闪记", "image": "图片闪记", "file": "文件闪记",
    }.get(str(getattr(row, "source_type", "")), "闪记")


def topic_labels(*, tags: Iterable[str], knowledge_base_name: str, source_app: str, source_type: str) -> list[tuple[str, str]]:
    labels: list[str] = []
    for tag in tags:
        cleaned = safe_text(tag, limit=MAX_LABEL_LENGTH)
        normalized = normalized_label(cleaned)
        if cleaned and normalized not in GENERIC_TAGS and len(cleaned) <= MAX_LABEL_LENGTH:
            labels.append(cleaned)
    if not labels and safe_text(knowledge_base_name, limit=MAX_LABEL_LENGTH):
        labels.append(safe_text(knowledge_base_name, limit=MAX_LABEL_LENGTH))
    if not labels and safe_text(source_app, limit=MAX_LABEL_LENGTH):
        labels.append(safe_text(source_app, limit=MAX_LABEL_LENGTH))
    if not labels:
        labels.append({"url": "网页", "text": "文字", "image": "图片", "file": "文件"}.get(source_type, "闪记"))
    unique: dict[str, str] = {}
    for label in labels:
        unique.setdefault(normalized_label(label), label)
        if len(unique) == MAX_TOPICS_PER_CLIP:
            break
    return [(topic_id(label), label) for label in unique.values()]


def candidate_from_row(
    row: object,
    enrichment: object | None,
    knowledge_base_name: str,
    *,
    public_clip_id: str | None = None,
) -> RecallCandidate | None:
    if bool(getattr(row, "active_enrichment_invalid", False)):
        return None
    captured = parse_utc(str(getattr(row, "captured_at", ""))) or parse_utc(str(getattr(row, "created_at", "")))
    if captured is None:
        return None
    source_type = str(getattr(row, "source_type", ""))
    archive_status = str(getattr(row, "archive_status", ""))
    explicit_title = displayable_title_hint(getattr(row, "title_hint", ""))
    minimal_url_title = explicit_title if source_type == "url" else ""
    if enrichment is not None:
        enrichment_failed = getattr(enrichment, "status", "") == "failed"
        explicitly_ineligible = str(getattr(enrichment, "error_code", "")).startswith("recall_ineligible:")
        # A source-faithful Share title is already a useful minimal memory. Rich
        # enrichment and topic classification remain additive and must not hide it.
        if (enrichment_failed or explicitly_ineligible) and not minimal_url_title:
            return None
    elif source_type in {"url", "file", "image", "audio"} and archive_status in {
        "accepted", "archived", "local",
    }:
        return None
    raw_summary = getattr(enrichment, "summary", "") if enrichment else ""
    raw_text = getattr(enrichment, "extracted_text", "") if enrichment else ""
    raw_enrichment_title = getattr(enrichment, "title", "") if enrichment else ""
    filename = getattr(row, "filename", "") if source_type in {"file", "image", "audio"} else ""
    if not has_displayable_text((displayable_title_hint(raw_enrichment_title), raw_summary, raw_text, displayable_title_hint(getattr(row, "title_hint", "")), filename, getattr(row, "note", ""), getattr(row, "text", ""), getattr(row, "url", ""))):
        return None
    title = display_title(row, enrichment)
    fallback = " ".join(
        str(value or "")
        for value in (
            getattr(row, "note", ""), getattr(row, "text", ""), minimal_url_title,
            getattr(row, "url", ""),
        )
    )
    reveal = safe_text(raw_text or fallback, limit=1000)
    summary = safe_text(raw_summary or reveal, limit=240)
    if not title and not summary and not reveal:
        return None
    tags = list(getattr(enrichment, "tags", []) if enrichment and getattr(enrichment, "status", "") == "completed" else [])
    topics = topic_labels(tags=tags, knowledge_base_name=knowledge_base_name, source_app=str(getattr(row, "source_app", "")), source_type=str(getattr(row, "source_type", "")))
    richness = 0
    richness += 40 if enrichment and getattr(enrichment, "status", "") == "completed" else 0
    richness += 20 if safe_text(str(raw_enrichment_title or getattr(row, "title_hint", "")), limit=160) else 0
    richness += 10 if safe_text(str(raw_summary), limit=240) else 0
    richness += 5 if reveal else 0
    richness += min(len(tags), MAX_TOPICS_PER_CLIP) * 3
    active_url = str(getattr(row, "active_url", "") or "")
    if not active_url:
        try:
            active_url = canonicalize_url(str(getattr(row, "url", "")))
        except WebFetchError:
            active_url = ""
    return RecallCandidate(
        internal_clip_id=str(getattr(row, "id")),
        clip_id=public_clip_id or str(getattr(row, "id")), client_request_id=str(getattr(row, "client_request_id", "")), title=title, summary=summary, reveal_text=reveal,
        source_type=str(getattr(row, "source_type", "")), source_app=safe_text(str(getattr(row, "source_app", "")), limit=80),
        url=safe_text(active_url, limit=300), filename=safe_text(str(getattr(row, "filename", "")), limit=120), captured_at=captured.isoformat(),
        knowledge_base_name=safe_text(knowledge_base_name, limit=80), tags=[safe_text(tag, limit=64) for tag in tags], topics=topics,
        score=richness,
    )


def recent_candidates(
    rows: Iterable[tuple[object, object | None, str]],
    *,
    days: int,
    now: datetime | None = None,
    recall_counts: dict[str, int] | None = None,
    public_id_for: Callable[[int], str] | None = None,
) -> list[RecallCandidate]:
    current = now or utc_now()
    start = (current.astimezone(timezone.utc).date() - timedelta(days=days - 1))
    candidates = []; recall_counts = recall_counts or {}
    for row, enrichment, kb_name in rows:
        public_clip_id = public_id_for(int(getattr(row, "id"))) if public_id_for else None
        candidate = candidate_from_row(row, enrichment, kb_name, public_clip_id=public_clip_id)
        captured = parse_utc(candidate.captured_at) if candidate else None
        if candidate and captured and start <= captured.date() <= current.date():
            age_days = max(0, (current.date() - captured.date()).days)
            recalled = recall_counts.get(candidate.internal_clip_id, 0)
            candidates.append(replace(candidate, recall_count=recalled, score=candidate.score + max(0, days - age_days) + (24 if recalled == 0 else 0) - min(recalled, 8) * 4))
    return sorted(candidates, key=lambda item: (-item.score, item.clip_id))


def graph_for(candidates: Iterable[RecallCandidate], *, topic_id_filter: str = "") -> dict[str, list[dict[str, object]]]:
    # Legacy projection only: canonical identities and contains edges come from the
    # same domain snapshot used by UI-independent consumers.
    from .recall_domain import build_recall_domain
    candidate_list = list(candidates)
    snapshot = build_recall_domain(candidate_list, days=1, window_start="", window_end="")
    topic_counts = {topic.id: topic.clip_count for topic in snapshot.topics}
    labels = {topic.id: topic.label for topic in snapshot.topics}
    topic_ids = [topic.id for topic in snapshot.topics]
    if topic_id_filter:
        topic_ids = [topic_id_filter] + [identifier for identifier in topic_ids if identifier != topic_id_filter][:5]
    else:
        topic_ids = topic_ids[:6]
    allowed_topics = set(topic_ids)
    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    for index, identifier in enumerate(topic_ids):
        nodes.append({"id": identifier, "type": "topic", "label": labels[identifier], "weight": topic_counts[identifier], "color_slot": index % 4, "topic_id": identifier, "clip_id": ""})
    included = 0
    memories = {memory.clip_id: memory for memory in snapshot.memories}
    for candidate in sorted(candidate_list, key=lambda item: (-item.score, item.clip_id)):
        if included >= 12:
            break
        primary = candidate.topics[0][0] if candidate.topics else ""
        primary = next((identifier for identifier, _ in candidate.topics if identifier in allowed_topics), "")
        if not primary:
            continue
        included += 1
        memory = memories[candidate.clip_id]
        nodes.append({"id": memory.id, "type": "clip", "label": memory.label, "weight": 1, "color_slot": topic_ids.index(primary) % 4, "topic_id": primary, "clip_id": memory.clip_id})
        for relation in snapshot.relations:
            if relation.type == "contains" and relation.target == memory.id and relation.source in allowed_topics and len(edges) < 36:
                edges.append({"source": relation.source, "target": relation.target, "type": relation.type, "weight": relation.weight})
    return {"nodes": nodes[:18], "edges": edges[:36]}


def balanced_select(candidates: Iterable[RecallCandidate], *, limit: int, recalled_clip_ids: set[str]) -> list[RecallCandidate]:
    buckets: dict[str, list[RecallCandidate]] = defaultdict(list)
    for candidate in candidates:
        if candidate.internal_clip_id in recalled_clip_ids:
            continue
        for identifier, _ in candidate.topics[:1]:
            buckets[identifier].append(candidate)
    for values in buckets.values():
        values.sort(key=lambda item: (item.score, item.captured_at, item.clip_id), reverse=True)
    selected: list[RecallCandidate] = []
    while buckets and len(selected) < limit:
        for identifier in sorted(list(buckets)):
            if len(selected) >= limit:
                break
            values = buckets[identifier]
            if values:
                selected.append(values.pop(0))
            if not values:
                del buckets[identifier]
    return selected


def candidate_payload(candidate: RecallCandidate) -> dict[str, object]:
    return {"clip_id": candidate.clip_id, "client_request_id": candidate.client_request_id, "title": candidate.title, "summary": candidate.summary, "reveal_text": candidate.reveal_text, "safe_text": candidate.reveal_text, "source_type": candidate.source_type, "source_label": candidate.source_app or candidate.source_type, "source_app": candidate.source_app, "url": candidate.url, "filename": candidate.filename, "captured_at": candidate.captured_at, "knowledge_base_name": candidate.knowledge_base_name, "tags": candidate.tags, "topic_ids": [identifier for identifier, _ in candidate.topics]}
