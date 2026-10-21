from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .knowledge_base_store import ClipRouteDecision
from .mobile_safety import redact_private_paths
from .secret_redaction import redact_structured_secret_values
from .storage import StoredClipRawFields
from .topics import TOPIC_DEFINITIONS, UNCLASSIFIED_TOPIC_ID


ENGINE_DETERMINISTIC_V1 = "deterministic.v1"
ENGINE_DETERMINISTIC_V2 = "deterministic.v2"
ENGINE_DETERMINISTIC_V3 = "deterministic.v3"
ENGINE_DETERMINISTIC_V4 = "deterministic.v4"
ENGINE_DETERMINISTIC_V5 = "deterministic.v5"
ENGINE_DETERMINISTIC_V6 = "deterministic.v6"
ENGINE_DETERMINISTIC_V7 = "deterministic.v7"
ENRICHMENT_STATUSES = {"pending", "running", "completed", "failed", "skipped"}
SECRET_LIKE_RE = re.compile(
    r"(?i)(\b(?:token|api[_-]?key|password|passwd|secret|credential|cookie)\b\s*[:=]\s*)"
    r"(?!\[redacted\])([^\s,;]+)"
)
CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
ENGLISH_RE = re.compile(r"[A-Za-z]")
CONTENT_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,12}|[A-Za-z][A-Za-z0-9_-]{3,31}")
SENTENCE_BOUNDARY_RE = re.compile(
    r"(?<=[。！？])\s*|(?<=[.!?])(?:\s+|(?=[\u4e00-\u9fff]))|[\r\n]+"
)
SEMANTIC_CHAR_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9]")
CONTENT_STOP_WORDS = {
    "about", "after", "before", "could", "from", "have", "into", "more",
    "that", "their", "there", "these", "this", "with", "would",
}

# High-signal terms are ordered by usefulness within each fixed topic.  The
# remaining registry vocabulary is appended by ``_semantic_terms_for_topic``
# so runtime stays useful across every enabled topic without arbitrary token
# slicing.  Every emitted tag must still occur in the source projection.
SEMANTIC_TAG_TERMS: dict[str, tuple[str, ...]] = {
    "ai_ml": ("大模型", "推理", "机器学习", "人工智能", "LLM", "AI"),
    "digital_tech": ("芯片", "相机", "手机", "电脑", "硬件", "数码"),
    "software_automation": ("Docker", "GitHub", "API", "编程", "自动化"),
    "education_research": ("课程", "实验", "教学", "论文", "科研", "研究"),
    "work_projects": ("项目", "里程碑", "需求", "交付", "会议", "协作"),
    "finance_economy": ("股票", "基金", "财报", "通胀", "投资", "经济"),
    "health_medical": ("医学", "医院", "营养", "康复", "健康", "医疗"),
    "travel_places": ("西湖", "旅行", "酒店", "景点", "航班", "旅游"),
    "football_sports": ("欧冠", "比赛", "足球", "篮球", "体育"),
    "games_entertainment": ("游戏", "电影", "音乐", "剧集", "娱乐", "影视"),
    "history_culture": ("博物馆", "文学", "历史", "文化", "艺术", "人文"),
    "relationships": ("家庭", "沟通", "朋友", "关系", "亲密关系", "人际"),
    "lifestyle": ("做饭", "家居", "收纳", "饮食", "日常", "生活"),
    "beauty_fashion": ("护肤", "口红", "穿搭", "服装", "美妆", "时尚"),
    "growth_reflection": ("复盘", "习惯", "思考", "成长", "反思", "价值观"),
}


@dataclass(frozen=True)
class EnrichmentInputProjection:
    """Latest successful processed view used by enrichment and read models."""

    text: str
    title: str = ""
    resolved_url: str = ""
    canonical_url: str = ""
    extraction_status: str = "raw_fallback"
    quality_score: float | None = None
    source_asset_id: str = ""
    source_asset_role: str = "raw"
    safe_error_code: str = ""
    quality_reason: str = ""
    recall_eligible: bool = True
    raw_fallback_used: bool = False
    structured_metadata: dict[str, object] | None = None

    @property
    def index_eligible(self) -> bool:
        return self.extraction_status == "completed" or (
            self.extraction_status == "partial"
            and self.recall_eligible
            and not self.raw_fallback_used
        )

    @property
    def index_reason(self) -> str:
        if self.index_eligible:
            return "completed_projection" if self.extraction_status == "completed" else "usable_partial_projection"
        if self.raw_fallback_used or self.extraction_status == "raw_fallback":
            return "raw_fallback_ineligible"
        return f"{self.extraction_status or 'unknown'}_projection_ineligible"

    def to_metadata(self) -> dict[str, object]:
        return {
            "source_asset_id": self.source_asset_id,
            "source_asset_role": self.source_asset_role,
            "title": safe_short_text(self.title),
            "resolved_url": self.resolved_url,
            "canonical_url": self.canonical_url,
            "extraction_status": self.extraction_status,
            "quality_score": self.quality_score,
            "safe_error_code": self.safe_error_code,
            "quality_reason": self.quality_reason,
            "recall_eligible": self.recall_eligible,
            "raw_fallback_used": self.raw_fallback_used,
            "index_eligible": self.index_eligible,
            "index_reason": self.index_reason,
            "structured_metadata": dict(self.structured_metadata or {}),
        }


@dataclass(frozen=True)
class EnrichmentResult:
    engine: str
    status: str
    title: str
    summary: str
    tags: list[str]
    key_points: list[str]
    language: str
    extracted_text: str
    error_code: str = ""
    error_message: str = ""

    def tags_json(self) -> str:
        return json.dumps(self.tags, ensure_ascii=False, sort_keys=True)

    def to_metadata(self) -> dict[str, object]:
        return {
            "engine": self.engine,
            "status": self.status,
            "title": self.title,
            "summary": self.summary,
            "tags": self.tags,
            "key_points": self.key_points,
            "language": self.language,
            "extracted_text": self.extracted_text,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


def deterministic_enrich(
    raw: StoredClipRawFields,
    route_decision: ClipRouteDecision | None,
    metadata: dict[str, object],
    projection: EnrichmentInputProjection | None = None,
) -> EnrichmentResult:
    del metadata
    projected_text = projection.text if projection is not None else build_extracted_text(raw)
    extracted_text = safe_extracted_text(projected_text)
    projected_title = projection.title if projection is not None else ""
    if projection is not None and not projected_title:
        projected_title = title_from_processed_text(extracted_text)
    explicit_title = explicit_title_hint(raw)
    title = safe_short_text(explicit_title or projected_title or title_for(raw), fallback="未命名收藏")
    summary = safe_summary(
        extracted_text if projection is not None and extracted_text else summary_for(raw, extracted_text)
    )
    language = language_for(" ".join([extracted_text, title]))
    tags = (
        semantic_tags_for(title, extracted_text)
        if projection is not None
        else tags_for(raw, route_decision)
    )
    key_points = deterministic_key_points(extracted_text) if projection is not None else []
    status = status_for(raw, summary, extracted_text)
    error_code = ""
    if projection is not None and projection.extraction_status == "failed":
        status = "failed"
        error_code = projection.safe_error_code or "extraction_failed"
    elif projection is not None and not projection.recall_eligible:
        error_code = f"recall_ineligible:{projection.quality_reason or 'insufficient_content'}"

    return EnrichmentResult(
        engine=ENGINE_DETERMINISTIC_V7 if projection is not None else ENGINE_DETERMINISTIC_V2,
        status=status,
        title=title,
        summary=summary,
        tags=tags,
        key_points=key_points,
        language=language,
        extracted_text=extracted_text,
        error_code=error_code,
    )


def deterministic_key_points(text: str, *, limit: int = 3) -> list[str]:
    """Return ordered, bounded, redacted source sentences as key points."""

    source_text = text.strip()
    if limit <= 0 or _semantic_length(source_text) < 12:
        return []
    points: list[str] = []
    seen: set[str] = set()
    for candidate in SENTENCE_BOUNDARY_RE.split(source_text):
        safe_candidate = redact_private_paths(redact_structured_secret_values(candidate))
        point = " ".join(safe_candidate.split()).strip()
        normalized = point.casefold()
        if _semantic_length(point) < 8 or normalized in seen:
            continue
        seen.add(normalized)
        points.append(point[:240].rstrip())
        if len(points) == limit:
            break
    return points


def _semantic_length(value: str) -> int:
    return len(SEMANTIC_CHAR_RE.findall(value))


def build_extracted_text(raw: StoredClipRawFields) -> str:
    if raw.source_type in {"text", "url", "note", "screen_clip"}:
        parts = [raw.text.strip(), raw.note.strip(), raw.url.strip()]
        return "\n".join(part for part in parts if part)
    if raw.source_type in {"file", "image", "audio"}:
        return raw.filename.strip()
    return ""


def title_for(raw: StoredClipRawFields) -> str:
    explicit = explicit_title_hint(raw)
    if explicit:
        return explicit
    # URL archive filenames contain capture timestamps and are not source
    # titles. Prefer the stable source domain when extraction has no title.
    if raw.source_type == "url":
        domain = domain_for(raw.url)
        if domain:
            return domain
    if raw.filename.strip():
        return raw.filename.strip()
    domain = domain_for(raw.url)
    if domain:
        return domain
    return "未命名收藏"


def explicit_title_hint(raw: StoredClipRawFields) -> str:
    value = raw.title_hint.strip()
    if value in {"", "未命名收藏", "未命名闪记", "闪记"}:
        return ""
    if raw.source_type in {"file", "image", "audio"} and value == raw.filename.strip():
        return ""
    return value


def summary_for(raw: StoredClipRawFields, extracted_text: str) -> str:
    if raw.source_type in {"file", "image", "audio"} and raw.filename.strip():
        mime = raw.mime_type.strip()
        suffix = f" ({mime})" if mime else ""
        return f"File: {raw.filename.strip()}{suffix}"
    if raw.source_type == "url" and raw.url.strip():
        return f"URL: {raw.url.strip()}"
    return extracted_text[:120]


def status_for(raw: StoredClipRawFields, summary: str, extracted_text: str) -> str:
    if summary or extracted_text:
        return "completed"
    if raw.original_path or raw.filename or raw.size_bytes > 0:
        return "completed"
    return "skipped"


def language_for(text: str) -> str:
    if CHINESE_RE.search(text):
        return "zh-CN"
    if ENGLISH_RE.search(text):
        return "en"
    return ""


def tags_for(
    raw: StoredClipRawFields,
    route_decision: ClipRouteDecision | None,
    processed_text: str = "",
) -> list[str]:
    tags: list[str] = []
    source_tag = source_type_tag(raw.source_type)
    if source_tag:
        tags.append(source_tag)
    if route_decision is not None and route_decision.knowledge_base_id:
        tags.append("knowledge-base")
    mime_tag = mime_type_tag(raw.mime_type, raw.filename)
    if mime_tag:
        tags.append(mime_tag)
    tags.extend(content_tags_for(processed_text))
    return dedupe_tags(tags)[:8]


def title_from_processed_text(text: str) -> str:
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split()).strip("# -*\t")
        if 4 <= len(line) <= 120:
            return line
    return ""


def content_tags_for(text: str) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for match in CONTENT_TOKEN_RE.finditer(text[:4000]):
        token = match.group(0).strip("_- ")
        normalized = token.casefold()
        if normalized in CONTENT_STOP_WORDS or normalized in seen:
            continue
        safe = SECRET_LIKE_RE.sub("", token).strip()
        if not safe:
            continue
        seen.add(normalized)
        tags.append(safe.lower() if safe.isascii() else safe)
        if len(tags) >= 3:
            break
    return tags


def semantic_tags_for(title: str, text: str, *, limit: int = 2) -> list[str]:
    """Return concise, source-grounded concepts from the fixed topic registry.

    The title is weighted above body mentions when choosing one topic. Tags are
    then selected from the complete title/body projection, which retains useful
    body evidence without letting an incidental mention switch the topic. The
    function emits at most two terms from a bounded topic vocabulary, and only
    when the source contains them; transport, storage, MIME and arbitrary CJK
    slices are never promoted to user-visible tags.
    """

    if limit <= 0:
        return []
    safe_title = redact_structured_secret_values(title).strip()
    safe_text = redact_structured_secret_values(text).strip()
    candidates = _semantic_topic_matches(safe_title, safe_text)
    if not candidates:
        return []
    _score, _topic_order, topic_id = max(
        candidates,
        key=lambda candidate: (candidate[0], -candidate[1]),
    )
    source = "\n".join((safe_title, safe_text))
    return [
        term
        for term in _semantic_terms_for_topic(topic_id)
        if _contains_semantic_term(source, term)
    ][:limit]


def _semantic_topic_matches(title: str, text: str) -> list[tuple[int, int, str]]:
    matches: list[tuple[int, int, str]] = []
    for definition in TOPIC_DEFINITIONS:
        if definition.topic_id == UNCLASSIFIED_TOPIC_ID or not definition.enabled:
            continue
        terms = _semantic_terms_for_topic(definition.topic_id)
        title_hits = sum(_contains_semantic_term(title, term) for term in terms)
        body_hits = sum(_contains_semantic_term(text, term) for term in terms)
        score = title_hits * 3 + body_hits
        if score:
            matches.append((score, definition.sort_order, definition.topic_id))
    return matches


def _semantic_terms_for_topic(topic_id: str) -> list[str]:
    definition = next(
        (item for item in TOPIC_DEFINITIONS if item.topic_id == topic_id),
        None,
    )
    if definition is None:
        return []
    return _dedupe_semantic_tags(
        [
            *SEMANTIC_TAG_TERMS.get(topic_id, ()),
            *definition.positive_examples,
            *definition.aliases,
        ]
    )


def _dedupe_semantic_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        safe_tag = SECRET_LIKE_RE.sub("", tag).strip()
        normalized = safe_tag.casefold()
        if not safe_tag or normalized in seen:
            continue
        seen.add(normalized)
        result.append(safe_tag)
    return result


def _contains_semantic_term(value: str, term: str) -> bool:
    if term.isascii():
        return bool(
            re.search(
                rf"(?i)(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])",
                value,
            )
        )
    return term.casefold() in value.casefold()


def source_type_tag(source_type: str) -> str:
    if source_type in {"text", "url", "file", "image", "screen_clip", "audio"}:
        return source_type
    return ""


def mime_type_tag(mime_type: str, filename: str) -> str:
    normalized = mime_type.lower().strip()
    lower_filename = filename.lower().strip()
    if normalized == "application/pdf" or lower_filename.endswith(".pdf"):
        return "pdf"
    if normalized.startswith("image/"):
        return "image"
    if normalized.startswith("audio/"):
        return "audio"
    if normalized.startswith("text/"):
        return "text"
    return ""


def dedupe_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        safe_tag = SECRET_LIKE_RE.sub("", tag).strip()
        if not safe_tag or safe_tag in seen:
            continue
        seen.add(safe_tag)
        result.append(safe_tag)
    return result


def domain_for(url: str) -> str:
    parsed = urlparse(url.strip())
    return parsed.netloc.lower()


def safe_short_text(value: str, *, fallback: str = "") -> str:
    redacted = redact_structured_secret_values(value).strip()
    return redacted[:160] or fallback


def safe_summary(value: str) -> str:
    return safe_short_text(value)[:120]


def safe_extracted_text(value: str) -> str:
    return redact_structured_secret_values(value).strip()
