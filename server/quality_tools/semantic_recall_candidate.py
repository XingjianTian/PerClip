from __future__ import annotations

from dataclasses import dataclass

from perclip_ingest.enrichment import _contains_semantic_term
from perclip_ingest.topics import TOPIC_DEFINITIONS, UNCLASSIFIED_TOPIC_ID


@dataclass(frozen=True)
class CandidateTopic:
    topic_id: str
    score: int


# Offline-only vocabulary used to measure whether a small, explicit set of
# high-signal source terms can close Q3 recall without arbitrary token slicing.
# Every emitted tag must still occur verbatim in the title or body.
CANDIDATE_TAG_TERMS: dict[str, tuple[str, ...]] = {
    "ai_ml": ("大模型", "推理", "机器学习", "人工智能", "LLM", "AI"),
    "software_automation": ("Docker", "GitHub", "API", "编程", "自动化"),
    "education_research": ("课程", "实验", "教学", "论文", "科研", "研究"),
    "travel_places": ("西湖", "旅行", "酒店", "景点", "航班", "旅游"),
    "football_sports": ("欧冠", "比赛", "足球", "篮球", "体育"),
}


def candidate_primary_topic(title: str, text: str) -> str:
    """Measure fixed-topic matching when positive examples are usable evidence."""

    ranked: list[CandidateTopic] = []
    for definition in TOPIC_DEFINITIONS:
        if definition.topic_id == UNCLASSIFIED_TOPIC_ID or not definition.enabled:
            continue
        terms = (*definition.positive_examples, *definition.aliases)
        title_hits = sum(_contains_semantic_term(title, term) for term in terms)
        body_hits = sum(_contains_semantic_term(text, term) for term in terms)
        score = title_hits * 3 + body_hits
        if score:
            ranked.append(CandidateTopic(definition.topic_id, score))
    if not ranked:
        return UNCLASSIFIED_TOPIC_ID
    order = {definition.topic_id: definition.sort_order for definition in TOPIC_DEFINITIONS}
    return min(ranked, key=lambda item: (-item.score, order[item.topic_id])).topic_id


def candidate_semantic_tags(title: str, text: str, *, limit: int = 2) -> list[str]:
    """Return bounded, source-grounded high-signal terms for offline evaluation."""

    if limit <= 0:
        return []
    topic_id = candidate_primary_topic(title, text)
    source = "\n".join((title, text))
    return [
        term
        for term in CANDIDATE_TAG_TERMS.get(topic_id, ())
        if _contains_semantic_term(source, term)
    ][:limit]


__all__ = ["candidate_primary_topic", "candidate_semantic_tags"]
