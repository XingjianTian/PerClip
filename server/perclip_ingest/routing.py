from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlparse

from .knowledge_base_store import KnowledgeBase, KnowledgeBaseStore, RoutingRule


RULE_TYPE_ORDER = ["source_app", "url_domain", "mime_type", "file_extension", "keyword"]
ROUTING_MODE_DEFAULT_ONLY = "default_only"


class RoutingPreviewError(ValueError):
    pass


@dataclass(frozen=True)
class RoutingPreviewInput:
    source_type: str = ""
    title_hint: str = ""
    note: str = ""
    text: str = ""
    url: str = ""
    mime_type: str = ""
    filename: str = ""
    device_name: str = ""
    source_app: str = ""
    client_request_id: str = ""
    target_knowledge_base_id: str = ""
    routing_mode: str = ""


@dataclass(frozen=True)
class RoutePreview:
    knowledge_base_id: str
    knowledge_base_name: str
    ragflow_dataset_id: str
    decision_type: str
    matched_rule_id: str
    matched_rule_ids: list[str]
    confidence: float
    manual_override: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "knowledge_base_id": self.knowledge_base_id,
            "knowledge_base_name": self.knowledge_base_name,
            "ragflow_dataset_id": self.ragflow_dataset_id,
            "decision_type": self.decision_type,
            "matched_rule_id": self.matched_rule_id,
            "matched_rule_ids": self.matched_rule_ids,
            "confidence": self.confidence,
            "manual_override": self.manual_override,
            "reason": self.reason,
        }


def preview_route(store: KnowledgeBaseStore, payload: RoutingPreviewInput) -> RoutePreview:
    routing_mode = payload.routing_mode.strip()
    if routing_mode:
        if routing_mode != ROUTING_MODE_DEFAULT_ONLY:
            raise RoutingPreviewError("unsupported routing mode")
        capture_time_target_id = payload.target_knowledge_base_id.strip()
        if capture_time_target_id:
            capture_time_target = store.get_knowledge_base(capture_time_target_id)
            if capture_time_target is not None and not capture_time_target.is_archived:
                return preview_for_target(
                    capture_time_target,
                    decision_type="default",
                    matched_rule_id="",
                    matched_rule_ids=[],
                    confidence=1.0,
                    manual_override=False,
                    reason=f'default_only: capture-time default knowledge base -> "{capture_time_target.name}"',
                )
        default = store.get_default_knowledge_base()
        if default is None:
            raise RoutingPreviewError("default knowledge base is missing")
        reason = f'default_only: current default knowledge base -> "{default.name}"'
        if capture_time_target_id:
            reason = (
                "default_only: capture-time default knowledge base unavailable; "
                f'current default -> "{default.name}"'
            )
        return preview_for_target(
            default,
            decision_type="default",
            matched_rule_id="",
            matched_rule_ids=[],
            confidence=1.0,
            manual_override=False,
            reason=reason,
        )

    if payload.target_knowledge_base_id.strip():
        target = store.require_active_knowledge_base(payload.target_knowledge_base_id.strip())
        return preview_for_target(
            target,
            decision_type="manual",
            matched_rule_id="",
            matched_rule_ids=[],
            confidence=1.0,
            manual_override=True,
            reason=f'manual override: selected knowledge base "{target.name}"',
        )

    rules = store.list_enabled_routing_rules()
    matched_rules = [rule for rule in rules if rule_matches(rule, payload)]
    matched_rule_ids = [rule.id for rule in matched_rules]
    skipped_rule_ids: list[str] = []

    for rule_type in RULE_TYPE_ORDER:
        candidates = sorted(
            [rule for rule in matched_rules if rule.rule_type == rule_type],
            key=lambda rule: (rule.priority, rule.created_at, rule.id),
        )
        for rule in candidates:
            target = store.get_knowledge_base(rule.target_knowledge_base_id)
            if target is None or target.is_archived:
                skipped_rule_ids.append(rule.id)
                continue
            return preview_for_target(
                target,
                decision_type="rule",
                matched_rule_id=rule.id,
                matched_rule_ids=matched_rule_ids,
                confidence=0.9,
                manual_override=False,
                reason=f'rule {rule.rule_type} matched "{rule.pattern}" -> "{target.name}"',
            )

    default = store.get_default_knowledge_base()
    if default is None:
        raise RoutingPreviewError("default knowledge base is missing")

    reason = f'fallback default: no enabled routing rule matched -> "{default.name}"'
    if skipped_rule_ids:
        reason = (
            "fallback default: matched rules had archived or deleted targets "
            f"({', '.join(skipped_rule_ids)}) -> \"{default.name}\""
        )
    return preview_for_target(
        default,
        decision_type="default",
        matched_rule_id="",
        matched_rule_ids=matched_rule_ids,
        confidence=0.5,
        manual_override=False,
        reason=reason,
    )


def preview_for_target(
    target: KnowledgeBase,
    *,
    decision_type: str,
    matched_rule_id: str,
    matched_rule_ids: list[str],
    confidence: float,
    manual_override: bool,
    reason: str,
) -> RoutePreview:
    return RoutePreview(
        knowledge_base_id=target.id,
        knowledge_base_name=target.name,
        ragflow_dataset_id=target.ragflow_dataset_id,
        decision_type=decision_type,
        matched_rule_id=matched_rule_id,
        matched_rule_ids=matched_rule_ids,
        confidence=confidence,
        manual_override=manual_override,
        reason=reason,
    )


def rule_matches(rule: RoutingRule, payload: RoutingPreviewInput) -> bool:
    if rule.rule_type == "source_app":
        return contains_case_insensitive(payload.source_app, rule.pattern)
    if rule.rule_type == "url_domain":
        return domain_matches(extract_domain(payload.url), rule.pattern)
    if rule.rule_type == "mime_type":
        return mime_type_matches(payload.mime_type, rule.pattern)
    if rule.rule_type == "file_extension":
        return extension_matches(payload.filename, payload.url, rule.pattern)
    if rule.rule_type == "keyword":
        haystack = "\n".join([payload.title_hint, payload.note, payload.text, payload.url])
        return contains_case_insensitive(haystack, rule.pattern)
    return False


def contains_case_insensitive(value: str, pattern: str) -> bool:
    normalized_pattern = pattern.strip().lower()
    return bool(normalized_pattern) and normalized_pattern in value.lower()


def extract_domain(url: str) -> str:
    stripped = url.strip()
    if not stripped or any(char.isspace() for char in stripped):
        return ""
    parsed = urlparse(stripped)
    if parsed.netloc:
        return parsed.netloc.split("@")[-1].split(":")[0].lower()
    if parsed.scheme == "" and "/" not in stripped:
        return stripped.lower()
    return ""


def domain_matches(domain: str, pattern: str) -> bool:
    normalized_domain = domain.strip(".").lower()
    normalized_pattern = pattern.strip().lstrip(".").lower()
    if not normalized_domain or not normalized_pattern:
        return False
    return normalized_domain == normalized_pattern or normalized_domain.endswith(f".{normalized_pattern}")


def mime_type_matches(mime_type: str, pattern: str) -> bool:
    normalized_mime = mime_type.strip().lower()
    normalized_pattern = pattern.strip().lower()
    if not normalized_mime or not normalized_pattern:
        return False
    if normalized_pattern.endswith("/*"):
        return normalized_mime.startswith(normalized_pattern[:-1])
    return normalized_mime == normalized_pattern


def extension_matches(filename: str, url: str, pattern: str) -> bool:
    normalized_pattern = pattern.strip().lower()
    if not normalized_pattern:
        return False
    if not normalized_pattern.startswith("."):
        normalized_pattern = f".{normalized_pattern}"
    candidates = [filename.strip()]
    parsed = urlparse(url.strip())
    if parsed.path:
        candidates.append(PurePosixPath(parsed.path).name)
    return any(candidate.lower().endswith(normalized_pattern) for candidate in candidates if candidate)
