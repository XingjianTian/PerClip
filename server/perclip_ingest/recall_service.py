"""Shared immutable inputs for Recall projections; it introduces no new identity source."""
from __future__ import annotations
from dataclasses import dataclass
from .recall import RecallCandidate
from .recall_domain import RecallDomainSnapshot

@dataclass(frozen=True)
class RecallContext:
    days: int
    window_start: str
    window_end: str
    candidates: list[RecallCandidate]
    previous_topic_ids: set[str]
    recall_counts: dict[str, dict[str, object]]
    interaction_stats: dict[str, dict[str, object]]
    domain: RecallDomainSnapshot
