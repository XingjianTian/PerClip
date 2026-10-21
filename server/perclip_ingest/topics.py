from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Protocol

from .secret_redaction import redact_structured_secret_values

TOPIC_ASSIGNMENT_CONTRACT = "perclip.topic-assignment.v1"
TAXONOMY_VERSION = "perclip.fixed-topics.v1"
UNCLASSIFIED_TOPIC_ID = "unclassified"
MAX_SECONDARY_TOPICS = 2
MAX_ENTITIES = 8
MAX_KEYWORDS = 12
MAX_CLASSIFICATION_MARKDOWN = 8_000
TOPIC_REGISTRY_CONTRACT = "perclip.topic-registry.v1"


@dataclass(frozen=True)
class TopicDefinition:
    topic_id: str
    display_name: str
    description: str
    positive_examples: tuple[str, ...]
    exclusions: tuple[str, ...]
    aliases: tuple[str, ...]
    enabled: bool
    sort_order: int


@dataclass(frozen=True)
class TopicAlias:
    alias_id: int
    topic_id: str
    alias: str
    alias_type: str


@dataclass(frozen=True)
class TopicRegistrySnapshot:
    taxonomy_version: str
    definitions: tuple[TopicDefinition, ...]
    aliases: tuple[TopicAlias, ...]

    @property
    def by_id(self) -> dict[str, TopicDefinition]:
        return {definition.topic_id: definition for definition in self.definitions}

    def enabled_topic(self, topic_id: str) -> TopicDefinition | None:
        definition = self.by_id.get(topic_id)
        return definition if definition is not None and definition.enabled else None


@dataclass(frozen=True)
class TopicClassificationInput:
    """Bounded, privacy-scrubbed whole-memory projection."""

    explicit_title: str = ""
    active_title: str = ""
    summary: str = ""
    markdown: str = ""
    user_tags: tuple[str, ...] = ()
    knowledge_base_name: str = ""
    source_context: str = ""

    @staticmethod
    def _safe(value: object, limit: int) -> str:
        return redact_structured_secret_values(str(value or "")).strip()[:limit]

    @classmethod
    def build(
        cls,
        *,
        explicit_title: object = "",
        active_title: object = "",
        summary: object = "",
        markdown: object = "",
        user_tags: Iterable[object] = (),
        knowledge_base_name: object = "",
        source_context: object = "",
    ) -> "TopicClassificationInput":
        return cls(
            explicit_title=cls._safe(explicit_title, 240),
            active_title=cls._safe(active_title, 240),
            summary=cls._safe(summary, 600),
            markdown=cls._safe(markdown, MAX_CLASSIFICATION_MARKDOWN),
            user_tags=tuple(
                value
                for value in (cls._safe(item, 64) for item in user_tags)
                if value
            )[:12],
            knowledge_base_name=cls._safe(knowledge_base_name, 96),
            source_context=cls._safe(source_context, 64),
        )

    @classmethod
    def from_text(cls, text: str) -> "TopicClassificationInput":
        return cls.build(markdown=text)

    def weighted_segments(self) -> tuple[tuple[str, float], ...]:
        segments = (
            (self.explicit_title, 6.0),
            (self.active_title, 5.0),
            (self.summary, 4.0),
            (" ".join(self.user_tags), 4.0),
            (self.markdown, 1.0),
            (self.knowledge_base_name, 0.5),
            (self.source_context, 0.25),
        )
        return tuple((text, weight) for text, weight in segments if text)

    def rendered(self) -> str:
        return "\n".join(text for text, _weight in self.weighted_segments())

    @property
    def input_hash(self) -> str:
        material = json.dumps(
            {
                "contract": "perclip.topic-input.v1",
                "explicit_title": self.explicit_title,
                "active_title": self.active_title,
                "summary": self.summary,
                "markdown": self.markdown,
                "user_tags": self.user_tags,
                "knowledge_base_name": self.knowledge_base_name,
                "source_context": self.source_context,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


_TOPIC_ROWS = (
    ("ai_ml", "AI与大模型", "人工智能、机器学习、生成式模型与相关应用", ("人工智能", "机器学习", "大模型", "AI", "LLM"), ("普通软件开发",), ("人工智能", "ai", "machine learning", "llm", "大模型")),
    ("digital_tech", "数码与科技", "消费电子、硬件、互联网科技与数码产品", ("手机", "电脑", "芯片", "相机"), ("纯软件工程",), ("数码", "科技", "手机", "电脑", "芯片", "camera", "smartphone", "laptop")),
    ("software_automation", "软件开发与自动化", "编程、软件工程、运维与自动化工作流", ("编程", "API", "Docker", "自动化"), ("仅讨论AI模型",), ("软件开发", "编程", "automation", "docker", "github")),
    ("education_research", "教学与科研", "课程、教学、论文、实验与学术研究", ("教学", "论文", "实验", "科研"), ("一般工作项目",), ("教育", "教学", "科研", "论文", "research")),
    ("work_projects", "工作与项目", "工作计划、协作、项目管理与交付", ("项目", "会议", "需求", "里程碑"), ("个人成长随笔",), ("工作", "项目", "会议", "project")),
    ("finance_economy", "投资与经济", "投资、市场、公司财务与宏观经济", ("股票", "基金", "通胀", "财报"), ("个人日常记账",), ("投资", "经济", "股票", "基金", "finance")),
    ("health_medical", "健康与医疗", "健康管理、疾病、医疗与运动康复", ("健康", "医学", "医院", "营养"), ("美妆护肤",), ("健康", "医疗", "医学", "营养", "health")),
    ("travel_places", "旅行与地点", "旅行计划、目的地、交通与地点记录", ("旅行", "酒店", "景点", "航班"), ("纯历史文化介绍",), ("旅行", "旅游", "酒店", "景点", "travel")),
    ("football_sports", "足球与体育", "足球及其他竞技体育赛事与训练", ("足球", "欧冠", "篮球", "比赛"), ("电子游戏电竞",), ("足球", "体育", "篮球", "欧冠", "sports")),
    ("games_entertainment", "游戏与娱乐", "电子游戏、影视、音乐与大众娱乐", ("游戏", "电影", "音乐", "剧集"), ("体育比赛",), ("游戏", "娱乐", "电影", "音乐", "game")),
    ("history_culture", "历史与文化", "历史事件、文化传统、艺术与人文", ("历史", "博物馆", "文学", "文化"), ("旅行行程",), ("历史", "文化", "艺术", "文学", "history")),
    ("relationships", "人际与关系", "家庭、亲密关系、沟通与社会交往", ("关系", "家庭", "沟通", "朋友"), ("工作协作流程",), ("人际", "关系", "家庭", "沟通", "relationship")),
    ("lifestyle", "生活方式", "居家、饮食、消费与日常生活管理", ("做饭", "家居", "收纳", "日常"), ("健康医疗建议",), ("生活", "家居", "饮食", "收纳", "lifestyle")),
    ("beauty_fashion", "美妆与穿搭", "护肤、化妆、服饰与个人造型", ("护肤", "口红", "穿搭", "服装"), ("疾病治疗",), ("美妆", "穿搭", "护肤", "时尚", "fashion")),
    ("growth_reflection", "个人成长与思考", "自我反思、习惯、价值观与个人成长", ("复盘", "习惯", "思考", "成长"), ("工作项目复盘",), ("成长", "反思", "复盘", "习惯", "reflection")),
    ("unclassified", "待归类", "没有足够证据归入固定主题的内容", ("无主题短句", "上下文不足"), (), ("待归类", "未分类", "unclassified")),
)

TOPIC_DEFINITIONS = tuple(
    TopicDefinition(topic_id, display, description, positives, exclusions, aliases, True, order)
    for order, (topic_id, display, description, positives, exclusions, aliases) in enumerate(_TOPIC_ROWS, 1)
)
TOPIC_BY_ID = {definition.topic_id: definition for definition in TOPIC_DEFINITIONS}

ENTITY_TOPIC_HINTS = {
    "ChatGPT": "ai_ml",
    "Kimi": "ai_ml",
    "Claude": "ai_ml",
    "DeepSeek": "ai_ml",
    "Codex": "ai_ml",
}


def bootstrap_snapshot() -> TopicRegistrySnapshot:
    aliases: list[TopicAlias] = []
    alias_id = 1
    for definition in TOPIC_DEFINITIONS:
        for alias in definition.aliases:
            aliases.append(TopicAlias(alias_id, definition.topic_id, alias, "exact_alias"))
            alias_id += 1
    for entity, topic_id in ENTITY_TOPIC_HINTS.items():
        aliases.append(TopicAlias(alias_id, topic_id, entity, "entity_hint"))
        alias_id += 1
    return TopicRegistrySnapshot(TAXONOMY_VERSION, TOPIC_DEFINITIONS, tuple(aliases))


@dataclass(frozen=True)
class ClassificationResult:
    primary_topic_id: str
    secondary_topic_ids: tuple[str, ...]
    entities: tuple[str, ...]
    keywords: tuple[str, ...]
    source: str
    confidence: float
    engine: str
    evidence: tuple[str, ...] = ()


class TopicClassifier(Protocol):
    def classify(
        self, value: TopicClassificationInput | str
    ) -> ClassificationResult | None: ...


class UserOverrideClassifier:
    def __init__(
        self,
        topic_id: str | None,
        registry: TopicRegistrySnapshot | None = None,
    ) -> None:
        self.topic_id = topic_id
        self.registry = registry or bootstrap_snapshot()

    def classify(
        self, value: TopicClassificationInput | str
    ) -> ClassificationResult | None:
        del value
        if self.topic_id is None or self.registry.enabled_topic(self.topic_id) is None:
            return None
        return ClassificationResult(self.topic_id, (), (), (), "manual", 1.0, "user-override")


def _contains(text: str, term: str) -> bool:
    if re.fullmatch(r"[A-Za-z0-9_+.-]+", term):
        return bool(re.search(rf"(?i)(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", text))
    return term.casefold() in text.casefold()


def extract_entities_and_keywords(
    text: str,
    registry: TopicRegistrySnapshot | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    text = redact_structured_secret_values(text)
    snapshot = registry or bootstrap_snapshot()
    entities = tuple(
        alias.alias
        for alias in snapshot.aliases
        if alias.alias_type == "entity_hint"
        and snapshot.enabled_topic(alias.topic_id) is not None
        and _contains(text, alias.alias)
    )[:MAX_ENTITIES]
    tokens = re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_+.-]{2,31}", text)
    stop = {"the", "and", "with", "from", "this", "that", "一个", "我们", "可以", "以及", "内容"}
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for token in tokens:
        normalized = token.casefold()
        if normalized in stop:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1
        display.setdefault(normalized, token)
    keywords = tuple(
        display[key] for key in sorted(counts, key=lambda key: (-counts[key], key))[:MAX_KEYWORDS]
    )
    return entities, keywords


class ExactRuleClassifier:
    """Deterministic aliases and entity hints; no network or chunk retrieval."""

    def __init__(
        self,
        user_rules: tuple[tuple[str, str], ...] = (),
        *,
        registry: TopicRegistrySnapshot | None = None,
        secondary_threshold: float = 2.0,
        secondary_margin: float = 40.0,
    ) -> None:
        self.user_rules = user_rules
        self.registry = registry or bootstrap_snapshot()
        self.secondary_threshold = secondary_threshold
        self.secondary_margin = secondary_margin

    @staticmethod
    def _input(value: TopicClassificationInput | str) -> TopicClassificationInput:
        return value if isinstance(value, TopicClassificationInput) else TopicClassificationInput.from_text(value)

    @staticmethod
    def _negated(text: str, alias: str) -> bool:
        folded = text.casefold()
        needle = alias.casefold()
        start = folded.find(needle)
        while start >= 0:
            prefix = folded[max(0, start - 14):start]
            if re.search(r"(?:不讨论|不是|并非|不涉及|无需|避免|排除|without|not\s+about)\s*$", prefix):
                return True
            start = folded.find(needle, start + max(1, len(needle)))
        return False

    def classify(
        self, value: TopicClassificationInput | str
    ) -> ClassificationResult | None:
        projection = self._input(value)
        text = projection.rendered()
        entities, keywords = extract_entities_and_keywords(text, self.registry)
        rules = [
            *self.user_rules,
            *(
                (alias.alias, alias.topic_id)
                for alias in self.registry.aliases
                if alias.alias_type == "user_rule"
            ),
        ]
        for rule, topic_id in rules:
            if self.registry.enabled_topic(topic_id) is not None and any(
                _contains(segment, rule) for segment, _weight in projection.weighted_segments()
            ):
                return ClassificationResult(
                    topic_id, (), entities, keywords, "user_rule", 1.0,
                    "exact-user-rule-v1", (rule,),
                )
        scores: dict[str, float] = {}
        evidence: dict[str, list[str]] = {}
        for alias in self.registry.aliases:
            definition = self.registry.enabled_topic(alias.topic_id)
            if (
                definition is None
                or definition.topic_id == UNCLASSIFIED_TOPIC_ID
                or alias.alias_type not in {"exact_alias", "entity_hint"}
            ):
                continue
            for segment, weight in projection.weighted_segments():
                if not _contains(segment, alias.alias) or self._negated(segment, alias.alias):
                    continue
                multiplier = 3.0 if alias.alias_type == "entity_hint" else 2.0
                scores[definition.topic_id] = scores.get(definition.topic_id, 0.0) + weight * multiplier
                evidence.setdefault(definition.topic_id, []).append(alias.alias)
        for definition in self.registry.definitions:
            if not definition.enabled or definition.topic_id == UNCLASSIFIED_TOPIC_ID:
                continue
            alias_terms = {
                alias.alias.casefold()
                for alias in self.registry.aliases
                if alias.topic_id == definition.topic_id
                and alias.alias_type in {"exact_alias", "entity_hint"}
            }
            for term in definition.positive_examples:
                if term.casefold() in alias_terms:
                    continue
                for segment, weight in projection.weighted_segments():
                    if not _contains(segment, term) or self._negated(segment, term):
                        continue
                    scores[definition.topic_id] = scores.get(definition.topic_id, 0.0) + weight
                    evidence.setdefault(definition.topic_id, []).append(term)
        for definition in self.registry.definitions:
            if definition.topic_id not in scores:
                continue
            exclusion_weight = sum(
                weight
                for segment, weight in projection.weighted_segments()
                for exclusion in definition.exclusions
                if _contains(segment, exclusion)
            )
            scores[definition.topic_id] -= min(16.0, exclusion_weight * 1.5)
        scores = {topic_id: score for topic_id, score in scores.items() if score > 0}
        if not scores:
            return None
        definitions = self.registry.by_id
        ranked = sorted(
            scores,
            key=lambda topic_id: (-scores[topic_id], definitions[topic_id].sort_order, topic_id),
        )
        primary = ranked[0]
        confidence = min(0.99, 0.68 + 0.025 * scores[primary])
        secondary = tuple(
            topic_id
            for topic_id in ranked[1:3]
            if scores[topic_id] >= self.secondary_threshold
            and scores[primary] - scores[topic_id] <= self.secondary_margin
        )
        return ClassificationResult(
            primary, secondary, entities, keywords, "exact_rule", confidence,
            "exact-alias-positive-entity-v2", tuple(dict.fromkeys(evidence.get(primary, ()))),
        )


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> tuple[float, ...]: ...


class FakeEmbeddingProvider:
    """Stable local embedding for tests/evaluation; never sends content externally."""

    dimensions = 64

    def embed(self, text: str) -> tuple[float, ...]:
        vector = [0.0] * self.dimensions
        for token in re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_+.-]+", text.casefold()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:2], "big") % self.dimensions] += 1.0 if digest[2] & 1 else -1.0
        length = math.sqrt(sum(value * value for value in vector)) or 1.0
        return tuple(value / length for value in vector)


class OpenAICompatibleEmbeddingProvider:
    """Direct server-side OpenAI-compatible embeddings with bounded retry."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 10.0,
        retries: int = 1,
        max_input_chars: int = MAX_CLASSIFICATION_MARKDOWN,
    ) -> None:
        if not endpoint.strip() or not api_key or not model.strip():
            raise ValueError("embedding_provider_not_configured")
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model = model.strip()
        self.timeout_seconds = timeout_seconds
        self.retries = max(0, min(3, int(retries)))
        self.max_input_chars = max(256, min(MAX_CLASSIFICATION_MARKDOWN, int(max_input_chars)))

    @property
    def embeddings_url(self) -> str:
        return (
            self.endpoint
            if self.endpoint.endswith("/embeddings")
            else f"{self.endpoint}/embeddings"
        )

    def embed(self, text: str) -> tuple[float, ...]:
        payload = json.dumps(
            {"model": self.model, "input": text[: self.max_input_chars]},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            self.embeddings_url,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(
                    request, timeout=self.timeout_seconds
                ) as response:
                    body = json.loads(response.read().decode("utf-8"))
                vector = body["data"][0]["embedding"]
                if (
                    not isinstance(vector, list)
                    or not vector
                    or any(
                        not isinstance(value, (int, float))
                        or isinstance(value, bool)
                        or not math.isfinite(float(value))
                        for value in vector
                    )
                ):
                    raise ValueError("embedding_response_invalid")
                return tuple(float(value) for value in vector)
            except (
                OSError,
                KeyError,
                IndexError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
                urllib.error.URLError,
            ) as error:
                last_error = error
                if attempt < self.retries:
                    time.sleep(min(0.5, 0.1 * (2**attempt)))
        raise RuntimeError("embedding_provider_failed") from last_error


class EmbeddingSimilarityClassifier:
    def __init__(
        self,
        provider: EmbeddingProvider | None = None,
        *,
        threshold: float = 0.50,
        registry: TopicRegistrySnapshot | None = None,
        engine: str = "fake-embedding-v1",
        fail_open: bool = False,
    ) -> None:
        self.provider = provider or FakeEmbeddingProvider()
        self.threshold = threshold
        self.registry = registry or bootstrap_snapshot()
        self.engine = engine
        self.fail_open = fail_open
        try:
            self._topics = {
                definition.topic_id: self.provider.embed(
                    " ".join(
                        (
                            definition.display_name,
                            definition.description,
                            *definition.positive_examples,
                            *definition.aliases,
                        )
                    )
                )
                for definition in self.registry.definitions
                if definition.enabled
                and definition.topic_id != UNCLASSIFIED_TOPIC_ID
            }
        except Exception:
            if not fail_open:
                raise
            self._topics = {}

    def classify(
        self, value: TopicClassificationInput | str
    ) -> ClassificationResult | None:
        projection = value if isinstance(value, TopicClassificationInput) else TopicClassificationInput.from_text(value)
        text = projection.rendered()
        entities, keywords = extract_entities_and_keywords(text, self.registry)
        try:
            query = self.provider.embed(text)
        except Exception:
            if self.fail_open:
                return None
            raise
        ranked = sorted(
            ((sum(a * b for a, b in zip(query, vector)), topic_id) for topic_id, vector in self._topics.items()),
            reverse=True,
        )
        if not ranked or ranked[0][0] < self.threshold:
            return None
        primary_score, primary = ranked[0]
        secondary = tuple(topic_id for score, topic_id in ranked[1:3] if score >= self.threshold)
        return ClassificationResult(
            primary, secondary, entities, keywords, "embedding",
            min(0.89, max(0.0, primary_score)), self.engine,
        )


class OptionalModelAdjudicator:
    """Default-off boundary. Real-content model calls are intentionally not implemented."""

    def classify(
        self, value: TopicClassificationInput | str
    ) -> ClassificationResult | None:
        del value
        return None


class TopicClassificationService:
    def __init__(
        self,
        store: "TopicStore",
        classifiers: tuple[TopicClassifier, ...] | None = None,
        *,
        semantic_provider: EmbeddingProvider | None = None,
        semantic_threshold: float = 0.50,
        semantic_engine: str = "embedding",
    ) -> None:
        self.store = store
        # Semantic embedding providers are opt-in. Production defaults to
        # deterministic rules plus unclassified; the fake provider exists only
        # for synthetic evaluation and boundary tests.
        self.classifiers = classifiers if classifiers is not None else ()
        self.semantic_provider = semantic_provider
        self.semantic_threshold = semantic_threshold
        self.semantic_engine = semantic_engine
        self._semantic_cache: dict[str, EmbeddingSimilarityClassifier] = {}

    def classify(
        self,
        *,
        clip_id: int,
        generation: str,
        text: str = "",
        projection: TopicClassificationInput | None = None,
    ) -> dict[str, object]:
        classification_input = projection or TopicClassificationInput.from_text(text)
        registry = self.store.snapshot()
        manual = self.store.manual_topic_id(clip_id)
        semantic_classifiers: tuple[TopicClassifier, ...] = ()
        if self.semantic_provider is not None:
            semantic = self._semantic_cache.get(registry.taxonomy_version)
            if semantic is None:
                semantic = EmbeddingSimilarityClassifier(
                    self.semantic_provider,
                    threshold=self.semantic_threshold,
                    registry=registry,
                    engine=self.semantic_engine,
                    fail_open=True,
                )
                self._semantic_cache = {registry.taxonomy_version: semantic}
            semantic_classifiers = (semantic,)
        classifier_chain: tuple[TopicClassifier, ...] = (
            UserOverrideClassifier(manual, registry),
            ExactRuleClassifier(registry=registry),
            *self.classifiers,
            *semantic_classifiers,
            OptionalModelAdjudicator(),
        )
        try:
            result = next(
                (
                    candidate
                    for classifier in classifier_chain
                    if (candidate := classifier.classify(classification_input)) is not None
                ),
                None,
            )
            if result is not None and result.source == "manual":
                entities, keywords = extract_entities_and_keywords(
                    classification_input.rendered(), registry
                )
                result = ClassificationResult(
                    result.primary_topic_id, (), entities, keywords,
                    result.source, result.confidence, result.engine, result.evidence,
                )
            if result is None:
                entities, keywords = extract_entities_and_keywords(
                    classification_input.rendered(), registry
                )
                result = ClassificationResult(
                    UNCLASSIFIED_TOPIC_ID, (), entities, keywords,
                    "unclassified", 0.0, "deterministic-fallback-v1",
                )
            return self.store.record_success(
                clip_id=clip_id,
                generation=generation,
                result=result,
                input_hash=classification_input.input_hash,
                taxonomy_version=registry.taxonomy_version,
            )
        except Exception:
            self.store.record_failure(
                clip_id=clip_id,
                generation=generation,
                safe_error_code="topic_classification_failed",
                input_hash=classification_input.input_hash,
                taxonomy_version=registry.taxonomy_version,
            )
            raise


class TopicStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.db_path = data_dir / "perclip.sqlite3"

    def connect(self) -> sqlite3.Connection:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("pragma foreign_keys=on")
        db.execute("pragma journal_mode=wal")
        return db

    def init(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                create table if not exists topic_definitions (
                    topic_id text primary key, display_name text not null,
                    description text not null, positive_examples_json text not null,
                    exclusions_json text not null, enabled integer not null,
                    sort_order integer not null, taxonomy_version text not null
                );
                create table if not exists topic_aliases (
                    id integer primary key autoincrement, topic_id text not null,
                    alias text not null, alias_type text not null,
                    taxonomy_version text not null, enabled integer not null,
                    unique(topic_id, alias, alias_type, taxonomy_version),
                    foreign key(topic_id) references topic_definitions(topic_id)
                );
                create table if not exists topic_classification_runs (
                    id text primary key, run_key text unique not null,
                    clip_id integer not null, generation text not null,
                    taxonomy_version text not null, status text not null,
                    source text not null, engine text not null,
                    confidence real not null, safe_error_code text not null,
                    result_json text not null, created_at text not null,
                    finished_at text not null
                );
                create table if not exists topic_registry_state (
                    singleton integer primary key check(singleton=1),
                    base_version text not null, revision integer not null,
                    updated_at text not null
                );
                create index if not exists idx_topic_runs_clip on topic_classification_runs(clip_id, created_at);
                create table if not exists clip_topic_assignments (
                    id text primary key, clip_id integer not null,
                    run_id text, generation text not null, topic_id text not null,
                    role text not null, source text not null, confidence real not null,
                    taxonomy_version text not null, active integer not null,
                    manual_override integer not null, created_at text not null,
                    foreign key(run_id) references topic_classification_runs(id),
                    foreign key(topic_id) references topic_definitions(topic_id)
                );
                create index if not exists idx_topic_assignment_active on clip_topic_assignments(clip_id, active, role);
                create table if not exists clip_entities (
                    id integer primary key autoincrement, clip_id integer not null,
                    run_id text not null, entity text not null, active integer not null,
                    created_at text not null, unique(clip_id, run_id, entity)
                );
                create table if not exists clip_keywords (
                    id integer primary key autoincrement, clip_id integer not null,
                    run_id text not null, keyword text not null, active integer not null,
                    created_at text not null, unique(clip_id, run_id, keyword)
                );
                """
            )
            run_columns = {
                str(row["name"])
                for row in db.execute("pragma table_info(topic_classification_runs)")
            }
            if "input_hash" not in run_columns:
                db.execute(
                    "alter table topic_classification_runs add column input_hash text not null default ''"
                )
            db.execute(
                """insert or ignore into topic_registry_state
                (singleton,base_version,revision,updated_at) values(1,?,?,?)""",
                (TAXONOMY_VERSION, 0, self._now()),
            )
            for definition in TOPIC_DEFINITIONS:
                db.execute(
                    """insert or ignore into topic_definitions values(?,?,?,?,?,?,?,?)""",
                    (
                        definition.topic_id, definition.display_name, definition.description,
                        json.dumps(definition.positive_examples, ensure_ascii=False),
                        json.dumps(definition.exclusions, ensure_ascii=False), int(definition.enabled),
                        definition.sort_order, TAXONOMY_VERSION,
                    ),
                )
                for alias in definition.aliases:
                    db.execute(
                        """insert or ignore into topic_aliases
                        (topic_id,alias,alias_type,taxonomy_version,enabled) values(?,?,?,?,1)""",
                        (definition.topic_id, alias, "exact_alias", TAXONOMY_VERSION),
                    )
            for entity, topic_id in ENTITY_TOPIC_HINTS.items():
                db.execute(
                    """insert or ignore into topic_aliases
                    (topic_id,alias,alias_type,taxonomy_version,enabled) values(?,?,?,?,1)""",
                    (topic_id, entity, "entity_hint", TAXONOMY_VERSION),
                )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def manual_topic_id(self, clip_id: int) -> str | None:
        with self.connect() as db:
            row = db.execute(
                """select topic_id from clip_topic_assignments where clip_id=? and active=1
                and manual_override=1 and role='primary' order by created_at desc limit 1""",
                (clip_id,),
            ).fetchone()
        return str(row["topic_id"]) if row else None

    def taxonomy_version(self, db: sqlite3.Connection | None = None) -> str:
        owns_connection = db is None
        connection = db or self.connect()
        try:
            row = connection.execute(
                "select base_version,revision from topic_registry_state where singleton=1"
            ).fetchone()
            if row is None or int(row["revision"]) == 0:
                return TAXONOMY_VERSION
            return f"{row['base_version']}.r{int(row['revision'])}"
        finally:
            if owns_connection:
                connection.close()

    def _bump_taxonomy(self, db: sqlite3.Connection) -> str:
        now = self._now()
        db.execute(
            """update topic_registry_state set revision=revision+1,updated_at=?
            where singleton=1""",
            (now,),
        )
        version = self.taxonomy_version(db)
        db.execute("update topic_definitions set taxonomy_version=?", (version,))
        return version

    @staticmethod
    def _definition_from_row(row: sqlite3.Row) -> TopicDefinition:
        positives = json.loads(str(row["positive_examples_json"]))
        exclusions = json.loads(str(row["exclusions_json"]))
        return TopicDefinition(
            topic_id=str(row["topic_id"]),
            display_name=str(row["display_name"]),
            description=str(row["description"]),
            positive_examples=tuple(str(item) for item in positives),
            exclusions=tuple(str(item) for item in exclusions),
            aliases=(),
            enabled=bool(row["enabled"]),
            sort_order=int(row["sort_order"]),
        )

    def snapshot(self) -> TopicRegistrySnapshot:
        with self.connect() as db:
            definition_rows = db.execute(
                "select * from topic_definitions order by sort_order,topic_id"
            ).fetchall()
            alias_rows = db.execute(
                """select a.id,a.topic_id,a.alias,a.alias_type
                from topic_aliases a
                join topic_definitions d on d.topic_id=a.topic_id
                where a.enabled=1
                order by a.id"""
            ).fetchall()
            version = self.taxonomy_version(db)
        aliases = tuple(
            TopicAlias(
                int(row["id"]),
                str(row["topic_id"]),
                str(row["alias"]),
                str(row["alias_type"]),
            )
            for row in alias_rows
        )
        definitions = []
        for row in definition_rows:
            definition = self._definition_from_row(row)
            definition_aliases = tuple(
                alias.alias
                for alias in aliases
                if alias.topic_id == definition.topic_id
                and alias.alias_type == "exact_alias"
            )
            definitions.append(
                TopicDefinition(
                    **{
                        **definition.__dict__,
                        "aliases": definition_aliases,
                    }
                )
            )
        return TopicRegistrySnapshot(version, tuple(definitions), aliases)

    def topic_exists_and_enabled(self, topic_id: str) -> bool:
        return self.snapshot().enabled_topic(topic_id) is not None

    def unclassified_pair(self) -> tuple[str, str]:
        definition = self.snapshot().by_id.get(UNCLASSIFIED_TOPIC_ID)
        return (
            UNCLASSIFIED_TOPIC_ID,
            definition.display_name if definition is not None else "待归类",
        )

    def user_rules(self) -> tuple[tuple[str, str], ...]:
        with self.connect() as db:
            rows = db.execute(
                """select alias,topic_id from topic_aliases where alias_type='user_rule'
                and enabled=1 order by id"""
            ).fetchall()
        return tuple((str(row["alias"]), str(row["topic_id"])) for row in rows)

    def add_user_rule(self, *, rule: str, topic_id: str) -> int:
        rule = rule.strip()
        if not rule or len(rule) > 120 or not self.topic_exists_and_enabled(topic_id):
            raise ValueError("invalid_user_rule")
        with self.connect() as db:
            version = self._bump_taxonomy(db)
            db.execute(
                """update topic_aliases set enabled=0
                where topic_id=? and alias=? and alias_type='user_rule'""",
                (topic_id, rule),
            )
            cursor = db.execute(
                """insert into topic_aliases(topic_id,alias,alias_type,taxonomy_version,enabled)
                values(?,?,?,?,1)""",
                (topic_id, rule, "user_rule", version),
            )
            return int(cursor.lastrowid)

    def registry_payload(self) -> dict[str, object]:
        snapshot = self.snapshot()
        aliases_by_topic: dict[str, list[dict[str, object]]] = {}
        for alias in snapshot.aliases:
            if alias.alias_type == "user_rule":
                continue
            aliases_by_topic.setdefault(alias.topic_id, []).append(
                {
                    "alias_id": alias.alias_id,
                    "alias": alias.alias,
                    "alias_type": alias.alias_type,
                }
            )
        return {
            "contract_version": TOPIC_REGISTRY_CONTRACT,
            "taxonomy_version": snapshot.taxonomy_version,
            "topics": [
                {
                    "topic_id": definition.topic_id,
                    "display_name": definition.display_name,
                    "description": definition.description,
                    "enabled": definition.enabled,
                    "sort_order": definition.sort_order,
                    "exclusions": list(definition.exclusions),
                    "aliases": aliases_by_topic.get(definition.topic_id, []),
                }
                for definition in snapshot.definitions
            ],
        }

    def update_topic(self, topic_id: str, changes: dict[str, object]) -> dict[str, object]:
        allowed = {"display_name", "enabled", "sort_order", "exclusions"}
        if not changes or set(changes) - allowed:
            raise ValueError("invalid_topic_patch")
        snapshot = self.snapshot()
        if topic_id not in snapshot.by_id:
            raise ValueError("unknown_topic_id")
        if topic_id == UNCLASSIFIED_TOPIC_ID and changes.get("enabled") is False:
            raise ValueError("unclassified_cannot_be_disabled")
        assignments: list[str] = []
        values: list[object] = []
        if "display_name" in changes:
            display_name = str(changes["display_name"]).strip()
            if not display_name or len(display_name) > 80:
                raise ValueError("invalid_display_name")
            assignments.append("display_name=?")
            values.append(display_name)
        if "enabled" in changes:
            if not isinstance(changes["enabled"], bool):
                raise ValueError("invalid_enabled")
            assignments.append("enabled=?")
            values.append(int(changes["enabled"]))
        if "sort_order" in changes:
            sort_order = changes["sort_order"]
            if (
                not isinstance(sort_order, int)
                or isinstance(sort_order, bool)
                or not 1 <= sort_order <= 10_000
            ):
                raise ValueError("invalid_sort_order")
            assignments.append("sort_order=?")
            values.append(sort_order)
        if "exclusions" in changes:
            exclusions = changes["exclusions"]
            if (
                not isinstance(exclusions, list)
                or len(exclusions) > 24
                or any(
                    not isinstance(item, str)
                    or not item.strip()
                    or len(item.strip()) > 120
                    for item in exclusions
                )
            ):
                raise ValueError("invalid_exclusions")
            assignments.append("exclusions_json=?")
            values.append(
                json.dumps(
                    list(dict.fromkeys(item.strip() for item in exclusions)),
                    ensure_ascii=False,
                )
            )
        with self.connect() as db:
            if set(changes) - {"display_name"}:
                self._bump_taxonomy(db)
            db.execute(
                f"update topic_definitions set {','.join(assignments)} where topic_id=?",
                (*values, topic_id),
            )
        return self.registry_payload()

    def add_alias(self, *, topic_id: str, alias: str, alias_type: str) -> int:
        alias = alias.strip()
        if (
            not self.topic_exists_and_enabled(topic_id)
            or not alias
            or len(alias) > 120
            or alias_type not in {"exact_alias", "entity_hint"}
        ):
            raise ValueError("invalid_topic_alias")
        with self.connect() as db:
            version = self._bump_taxonomy(db)
            db.execute(
                """update topic_aliases set enabled=0
                where topic_id=? and alias=? and alias_type=?""",
                (topic_id, alias, alias_type),
            )
            cursor = db.execute(
                """insert into topic_aliases
                (topic_id,alias,alias_type,taxonomy_version,enabled)
                values(?,?,?,?,1)""",
                (topic_id, alias, alias_type, version),
            )
            return int(cursor.lastrowid)

    def delete_alias(self, *, topic_id: str, alias_id: int) -> bool:
        with self.connect() as db:
            row = db.execute(
                """select id from topic_aliases where id=? and topic_id=?
                and alias_type in ('exact_alias','entity_hint') and enabled=1""",
                (alias_id, topic_id),
            ).fetchone()
            if row is None:
                return False
            self._bump_taxonomy(db)
            db.execute("update topic_aliases set enabled=0 where id=?", (alias_id,))
            return True

    def delete_user_rule(self, rule_id: int) -> bool:
        with self.connect() as db:
            row = db.execute(
                """select id from topic_aliases where id=? and alias_type='user_rule'
                and enabled=1""",
                (rule_id,),
            ).fetchone()
            if row is None:
                return False
            self._bump_taxonomy(db)
            db.execute("update topic_aliases set enabled=0 where id=?", (rule_id,))
            return True

    def clear_manual_override(self, clip_id: int) -> dict[str, object]:
        with self.connect() as db:
            manual = db.execute(
                """select run_id from clip_topic_assignments
                where clip_id=? and active=1 and manual_override=1
                order by created_at desc limit 1""",
                (clip_id,),
            ).fetchone()
            if manual is None:
                raise ValueError("manual_override_not_found")
            db.execute(
                """update clip_topic_assignments set active=0
                where clip_id=? and manual_override=1""",
                (clip_id,),
            )
            previous = db.execute(
                """select run_id,generation from clip_topic_assignments
                where clip_id=? and manual_override=0 and role='primary'
                order by created_at desc limit 1""",
                (clip_id,),
            ).fetchone()
            if previous is not None:
                run_id = str(previous["run_id"] or "")
                db.execute(
                    """update clip_topic_assignments set active=1
                    where clip_id=? and run_id=?""",
                    (clip_id, run_id),
                )
                db.execute(
                    "update clip_entities set active=(run_id=?) where clip_id=?",
                    (run_id, clip_id),
                )
                db.execute(
                    "update clip_keywords set active=(run_id=?) where clip_id=?",
                    (run_id, clip_id),
                )
        return self.assignment_payload(clip_id)

    def record_success(
        self,
        *,
        clip_id: int,
        generation: str,
        result: ClassificationResult,
        input_hash: str = "",
        taxonomy_version: str | None = None,
    ) -> dict[str, object]:
        version = taxonomy_version or self.taxonomy_version()
        snapshot = self.snapshot()
        if snapshot.enabled_topic(result.primary_topic_id) is None:
            raise ValueError("topic_disabled")
        secondary_ids = tuple(
            topic_id
            for topic_id in result.secondary_topic_ids
            if snapshot.enabled_topic(topic_id) is not None
            and topic_id != result.primary_topic_id
        )[:MAX_SECONDARY_TOPICS]
        result_json = json.dumps(
            {
                "primary_topic_id": result.primary_topic_id,
                "secondary_topic_ids": list(secondary_ids),
                "entities": list(result.entities[:MAX_ENTITIES]),
                "keywords": list(result.keywords[:MAX_KEYWORDS]),
                "evidence": list(result.evidence),
            },
            ensure_ascii=False, sort_keys=True,
        )
        run_key = hashlib.sha256(
            f"{clip_id}\0{generation}\0{version}\0{input_hash}\0{result.source}\0{result_json}".encode()
        ).hexdigest()
        run_id = "tcr_" + run_key[:32]
        now = self._now()
        with self.connect() as db:
            existing = db.execute("select id from topic_classification_runs where run_key=?", (run_key,)).fetchone()
            if existing:
                return self.assignment_payload(clip_id, current_generation=generation)
            db.execute(
                """insert into topic_classification_runs
                (id,run_key,clip_id,generation,taxonomy_version,status,source,engine,
                 confidence,safe_error_code,result_json,created_at,finished_at,input_hash)
                values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    run_key,
                    clip_id,
                    generation,
                    version,
                    "succeeded",
                    result.source,
                    result.engine,
                    result.confidence,
                    "",
                    result_json,
                    now,
                    now,
                    input_hash,
                ),
            )
            manual = db.execute(
                """select topic_id from clip_topic_assignments where clip_id=? and active=1
                and manual_override=1 and role='primary' limit 1""", (clip_id,)
            ).fetchone()
            if manual and result.source != "manual":
                return self.assignment_payload(clip_id, current_generation=generation)
            db.execute("update clip_topic_assignments set active=0 where clip_id=?", (clip_id,))
            db.execute("update clip_entities set active=0 where clip_id=?", (clip_id,))
            db.execute("update clip_keywords set active=0 where clip_id=?", (clip_id,))
            topic_roles = [
                (result.primary_topic_id, "primary"),
                *((topic_id, "secondary") for topic_id in secondary_ids),
            ]
            for index, (topic_id, role) in enumerate(topic_roles):
                assignment_id = "ta_" + hashlib.sha256(f"{run_id}:{role}:{index}:{topic_id}".encode()).hexdigest()[:32]
                db.execute(
                    """insert into clip_topic_assignments values(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        assignment_id,
                        clip_id,
                        run_id,
                        generation,
                        topic_id,
                        role,
                        result.source,
                        result.confidence,
                        version,
                        1,
                        int(result.source == "manual"),
                        now,
                    ),
                )
            for entity in result.entities[:MAX_ENTITIES]:
                db.execute("insert into clip_entities(clip_id,run_id,entity,active,created_at) values(?,?,?,?,?)", (clip_id, run_id, entity, 1, now))
            for keyword in result.keywords[:MAX_KEYWORDS]:
                db.execute("insert into clip_keywords(clip_id,run_id,keyword,active,created_at) values(?,?,?,?,?)", (clip_id, run_id, keyword, 1, now))
        return self.assignment_payload(clip_id, current_generation=generation)

    def record_failure(
        self,
        *,
        clip_id: int,
        generation: str,
        safe_error_code: str,
        input_hash: str = "",
        taxonomy_version: str | None = None,
    ) -> None:
        version = taxonomy_version or self.taxonomy_version()
        run_key = hashlib.sha256(
            f"{clip_id}\0{generation}\0{version}\0{input_hash}\0failed".encode()
        ).hexdigest()
        now = self._now()
        with self.connect() as db:
            db.execute(
                """insert or ignore into topic_classification_runs
                (id,run_key,clip_id,generation,taxonomy_version,status,source,engine,
                 confidence,safe_error_code,result_json,created_at,finished_at,input_hash)
                values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "tcr_" + run_key[:32],
                    run_key,
                    clip_id,
                    generation,
                    version,
                    "failed",
                    "",
                    "",
                    0.0,
                    safe_error_code,
                    "{}",
                    now,
                    now,
                    input_hash,
                ),
            )

    def set_manual_override(self, *, clip_id: int, generation: str, topic_id: str) -> dict[str, object]:
        if not self.topic_exists_and_enabled(topic_id):
            raise ValueError("unknown_or_disabled_topic_id")
        current = self.assignment_payload(clip_id, current_generation=generation)
        return self.record_success(
            clip_id=clip_id, generation=generation,
            result=ClassificationResult(
                topic_id, (), tuple(current["entities"]), tuple(current["keywords"]),
                "manual", 1.0, "user-override",
            ),
            taxonomy_version=self.taxonomy_version(),
        )

    def active_topic_ids(self, clip_id: int) -> list[str]:
        with self.connect() as db:
            rows = db.execute(
                """select topic_id from clip_topic_assignments where clip_id=? and active=1
                order by case role when 'primary' then 0 else 1 end, created_at""", (clip_id,)
            ).fetchall()
        return [str(row["topic_id"]) for row in rows]

    def active_index_provenance(self, clip_id: int) -> dict[str, object]:
        with self.connect() as db:
            rows = db.execute(
                """select id,topic_id,generation,taxonomy_version,manual_override
                from clip_topic_assignments where clip_id=? and active=1
                order by case role when 'primary' then 0 else 1 end,created_at""",
                (clip_id,),
            ).fetchall()
        return {
            "topic_ids": [str(row["topic_id"]) for row in rows],
            "taxonomy_version": self.taxonomy_version(),
            "assignment_generation": (
                "tag_"
                + hashlib.sha256(
                    f"{rows[0]['id']}\0{rows[0]['taxonomy_version']}".encode()
                ).hexdigest()[:24]
                if rows
                else ""
            ),
            "manual_override": bool(rows and rows[0]["manual_override"]),
        }

    def active_topic_pairs(self, clip_id: int) -> list[tuple[str, str]]:
        with self.connect() as db:
            rows = db.execute(
                """select a.topic_id,d.display_name from clip_topic_assignments a
                join topic_definitions d on d.topic_id=a.topic_id
                where a.clip_id=? and a.active=1
                order by case a.role when 'primary' then 0 else 1 end,d.sort_order""",
                (clip_id,),
            ).fetchall()
        return [(str(row["topic_id"]), str(row["display_name"])) for row in rows]

    def assignment_payload(self, clip_id: int, *, current_generation: str = "") -> dict[str, object]:
        with self.connect() as db:
            rows = db.execute(
                """select a.*,d.display_name,d.enabled from clip_topic_assignments a
                join topic_definitions d on d.topic_id=a.topic_id
                where a.clip_id=? and a.active=1
                order by case a.role when 'primary' then 0 else 1 end,
                         d.sort_order,a.created_at,a.id""",
                (clip_id,),
            ).fetchall()
            entities = db.execute("select entity from clip_entities where clip_id=? and active=1 order by id limit ?", (clip_id, MAX_ENTITIES)).fetchall()
            keywords = db.execute("select keyword from clip_keywords where clip_id=? and active=1 order by id limit ?", (clip_id, MAX_KEYWORDS)).fetchall()
            latest = db.execute(
                """select generation,taxonomy_version,status,source,safe_error_code
                from topic_classification_runs where clip_id=?
                order by created_at desc,id desc limit 1""",
                (clip_id,),
            ).fetchone()
        primary = next((row for row in rows if row["role"] == "primary"), None)
        seen_topic_ids = {str(primary["topic_id"])} if primary else set()
        secondary = []
        for row in rows:
            topic_id = str(row["topic_id"])
            if row["role"] != "secondary" or topic_id in seen_topic_ids:
                continue
            seen_topic_ids.add(topic_id)
            secondary.append(row)
            if len(secondary) == MAX_SECONDARY_TOPICS:
                break
        generation = str(primary["generation"]) if primary else ""
        active_taxonomy_version = (
            str(primary["taxonomy_version"]) if primary else ""
        )
        current_taxonomy_version = self.taxonomy_version()
        assignment_generation = (
            "tag_"
            + hashlib.sha256(
                f"{primary['id']}\0{primary['taxonomy_version']}".encode()
            ).hexdigest()[:24]
            if primary
            else ""
        )
        unclassified_id, unclassified_label = self.unclassified_pair()
        return {
            "contract_version": TOPIC_ASSIGNMENT_CONTRACT,
            "primary": {
                "topic_id": str(primary["topic_id"]) if primary else unclassified_id,
                "display_name": str(primary["display_name"]) if primary else unclassified_label,
                "source": str(primary["source"]) if primary else "unclassified",
            },
            "secondary": [
                {"topic_id": str(row["topic_id"]), "display_name": str(row["display_name"])}
                for row in secondary
            ],
            "entities": [str(row["entity"]) for row in entities],
            "keywords": [str(row["keyword"]) for row in keywords],
            "unclassified": not primary or str(primary["topic_id"]) == unclassified_id,
            "stale": bool(
                (
                    current_generation
                    and (not primary or not generation or generation != current_generation)
                )
                or (
                    primary
                    and active_taxonomy_version != current_taxonomy_version
                )
            ),
            "active_generation": generation,
            "assignment_generation": assignment_generation,
            "active_taxonomy_version": active_taxonomy_version,
            "latest_attempted_status": str(latest["status"]) if latest else "not_started",
            "latest_attempted_generation": str(latest["generation"]) if latest else "",
            "latest_safe_error": str(latest["safe_error_code"]) if latest else "",
            "topic_disabled": bool(primary and not bool(primary["enabled"])),
            "manual_override": bool(primary and primary["manual_override"]),
            "classifier_source": str(primary["source"]) if primary else "unclassified",
        }
