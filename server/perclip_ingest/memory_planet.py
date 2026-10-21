from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable

from .recall import RecallCandidate, parse_utc
from .topics import UNCLASSIFIED_TOPIC_ID


MEMORY_PLANET_CONTRACT = "perclip.memory-planet.v1"


def _tokens(candidate: RecallCandidate) -> set[str]:
    return set(re.findall(r"[\u4e00-\u9fff]{2,8}|[a-z][a-z0-9_+-]{2,}", f"{candidate.title} {candidate.summary}".casefold()))


def _near_duplicate(left: RecallCandidate, right: RecallCandidate) -> bool:
    a, b = _tokens(left), _tokens(right)
    return bool(a and b and len(a & b) / len(a | b) >= 0.9)


def _safe_time(value: object) -> datetime | None:
    return parse_utc(str(value or ""))


def _score(
    candidate: RecallCandidate,
    *,
    topic_count: int,
    newest: datetime,
    oldest: datetime,
    stats: dict[str, object],
    preferred: set[str],
) -> float:
    captured = _safe_time(candidate.captured_at) or oldest
    span = max(1.0, (newest - oldest).total_seconds())
    recency = max(0.0, min(1.0, (captured - oldest).total_seconds() / span))
    not_recently_surfaced = 1.0 if not stats.get("last_viewed_at") else 0.0
    coverage = min(1.0, topic_count / 5.0)
    user_priority = 1.0 if candidate.topics and candidate.topics[0][0] in preferred else 0.0
    internal_diversity = min(1.0, len(set(candidate.tags)) / 3.0)
    return round(
        0.40 * coverage
        + 0.25 * recency
        + 0.20 * not_recently_surfaced
        + 0.10 * user_priority
        + 0.05 * internal_diversity,
        6,
    )


def _representative_order(items: list[tuple[RecallCandidate, float]]) -> list[RecallCandidate]:
    ordered = sorted(items, key=lambda item: (-item[1], item[0].clip_id))
    return [candidate for candidate, _score_value in ordered]


def _select_topic_memories(
    items: list[tuple[RecallCandidate, float]],
    stats: dict[str, dict[str, object]],
) -> list[RecallCandidate]:
    newest = [
        candidate for candidate, _ in sorted(
            items, key=lambda item: (item[0].captured_at, item[0].clip_id), reverse=True
        )[:2]
    ]
    representative = _representative_order(items)
    longest_not_surfaced = sorted(
        (
            candidate for candidate, _ in items
            if not stats.get(candidate.internal_clip_id, {}).get("last_viewed_at")
        ),
        key=lambda candidate: (len(candidate.reveal_text), candidate.captured_at, candidate.clip_id),
        reverse=True,
    )[:1]
    selected: list[RecallCandidate] = []

    def add_from(values: Iterable[RecallCandidate], limit: int) -> None:
        added = 0
        for candidate in values:
            if candidate.clip_id in {item.clip_id for item in selected}:
                continue
            if any(_near_duplicate(candidate, item) for item in selected):
                continue
            selected.append(candidate)
            added += 1
            if added == limit or len(selected) == 5:
                return

    add_from(newest, 2)
    add_from(representative, 2)
    add_from(longest_not_surfaced, 1)
    return selected


def build_memory_planet(
    candidates: Iterable[RecallCandidate],
    *,
    window: dict[str, object],
    stats: dict[str, dict[str, object]] | None = None,
    preferred_topic_ids: Iterable[str] = (),
) -> dict[str, object]:
    stats = stats or {}
    preferred = set(preferred_topic_ids)
    eligible = [
        candidate for candidate in candidates
        if candidate.topics
        and not stats.get(candidate.internal_clip_id, {}).get("suppressed", False)
    ]
    if not eligible:
        return {
            "contract_version": MEMORY_PLANET_CONTRACT,
            "window": window,
            "topics": [],
            "unclassified_count": 0,
            "unclassified_preview": [],
            "has_more_unclassified": False,
        }
    by_topic: dict[str, list[RecallCandidate]] = defaultdict(list)
    labels: dict[str, str] = {}
    for candidate in eligible:
        topic_id, label = candidate.topics[0]
        by_topic[topic_id].append(candidate)
        labels[topic_id] = label
    unclassified_count = len(by_topic.get(UNCLASSIFIED_TOPIC_ID, ()))
    small_unclassified = bool(
        unclassified_count
        and unclassified_count < 3
        and unclassified_count / len(eligible) < 0.2
    )
    if small_unclassified:
        by_topic.pop(UNCLASSIFIED_TOPIC_ID, None)
    oldest = min((_safe_time(candidate.captured_at) for candidate in eligible), default=None)
    newest = max((_safe_time(candidate.captured_at) for candidate in eligible), default=None)
    now = datetime.now(timezone.utc)
    oldest = oldest or now
    newest = newest or now
    scored_topics: list[tuple[float, str, list[tuple[RecallCandidate, float]]]] = []
    for topic_id, topic_candidates in by_topic.items():
        scored = [
            (
                candidate,
                _score(
                    candidate, topic_count=len(topic_candidates), newest=newest, oldest=oldest,
                    stats=stats.get(candidate.internal_clip_id, {}), preferred=preferred,
                ),
            )
            for candidate in topic_candidates
        ]
        topic_score = sum(score for _candidate, score in scored) / len(scored)
        scored_topics.append((topic_score, topic_id, scored))
    scored_topics.sort(key=lambda item: (-item[0], item[1]))
    topics = []
    for _topic_score, topic_id, scored in scored_topics[:5]:
        selected = _select_topic_memories(scored, stats)
        topics.append(
            {
                "topic_id": topic_id,
                "display_name": labels[topic_id],
                "memory_count": len(scored),
                "memories": [
                    {
                        "clip_id": candidate.clip_id,
                        "title": candidate.title,
                        "summary": candidate.summary,
                        "captured_at": candidate.captured_at,
                        "source": candidate.source_app or candidate.source_type,
                    }
                    for candidate in selected
                ],
            }
        )
    unclassified_preview = sorted(
        (
            candidate
            for candidate in eligible
            if candidate.topics[0][0] == UNCLASSIFIED_TOPIC_ID
        ),
        key=lambda candidate: (candidate.captured_at, candidate.clip_id),
        reverse=True,
    )[:3]
    return {
        "contract_version": MEMORY_PLANET_CONTRACT,
        "window": window,
        "topics": topics,
        "unclassified_count": unclassified_count,
        "unclassified_preview": [
            {
                "clip_id": candidate.clip_id,
                "title": candidate.title,
                "summary": candidate.summary,
                "captured_at": candidate.captured_at,
                "source": candidate.source_app or candidate.source_type,
            }
            for candidate in unclassified_preview
        ],
        "has_more_unclassified": unclassified_count > len(unclassified_preview),
    }
