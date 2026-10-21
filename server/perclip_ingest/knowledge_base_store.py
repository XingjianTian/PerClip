from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_KNOWLEDGE_BASE_ID = "kb_default"
DEFAULT_KNOWLEDGE_BASE_NAME = "个人收藏"
SUPPORTED_RULE_TYPES = {"source_app", "mime_type", "file_extension", "url_domain", "keyword"}
SENSITIVE_PATTERN_RE = re.compile(r"(token|api[_-]?key|password|secret|cookie|authorization)", re.IGNORECASE)


class KnowledgeBaseError(ValueError):
    pass


class KnowledgeBaseNotFoundError(KnowledgeBaseError):
    pass


class KnowledgeBaseConflictError(KnowledgeBaseError):
    pass


@dataclass(frozen=True)
class KnowledgeBase:
    id: str
    name: str
    description: str
    icon: str
    color: str
    is_default: bool
    is_archived: bool
    ragflow_dataset_id: str
    ragflow_dataset_name: str
    template_key: str
    created_at: str
    updated_at: str
    deleted_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "color": self.color,
            "is_default": self.is_default,
            "is_archived": self.is_archived,
            "ragflow_dataset_id": self.ragflow_dataset_id,
            "ragflow_dataset_name": self.ragflow_dataset_name,
            "template_key": self.template_key,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


@dataclass(frozen=True)
class KnowledgeBaseTopicSummary:
    id: str
    label: str
    clip_count: int

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "clip_count": self.clip_count}


@dataclass(frozen=True)
class RoutingRule:
    id: str
    name: str
    enabled: bool
    rule_type: str
    pattern: str
    target_knowledge_base_id: str
    priority: int
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "rule_type": self.rule_type,
            "pattern": self.pattern,
            "target_knowledge_base_id": self.target_knowledge_base_id,
            "priority": self.priority,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class ClipRouteDecision:
    id: int
    clip_id: str
    client_request_id: str
    knowledge_base_id: str
    ragflow_dataset_id: str
    decision_type: str
    matched_rule_id: str
    matched_rule_ids: list[str]
    confidence: float
    manual_override: bool
    reason: str
    created_at: str
    previous_knowledge_base_id: str
    reindex_status: str
    lineage_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "clip_id": self.clip_id,
            "client_request_id": self.client_request_id,
            "knowledge_base_id": self.knowledge_base_id,
            "ragflow_dataset_id": self.ragflow_dataset_id,
            "decision_type": self.decision_type,
            "matched_rule_id": self.matched_rule_id,
            "matched_rule_ids": self.matched_rule_ids,
            "confidence": self.confidence,
            "manual_override": self.manual_override,
            "reason": self.reason,
            "created_at": self.created_at,
            "previous_knowledge_base_id": self.previous_knowledge_base_id,
            "reindex_status": self.reindex_status,
            "lineage_id": self.lineage_id,
        }


class KnowledgeBaseStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.db_path = data_dir / "perclip.sqlite3"

    def init(self) -> None:
        with self.connect() as db:
            db.execute(
                """
                create table if not exists knowledge_bases (
                    id text primary key,
                    name text not null,
                    description text not null default '',
                    icon text not null default '',
                    color text not null default '',
                    is_default integer not null default 0,
                    is_archived integer not null default 0,
                    ragflow_dataset_id text not null default '',
                    ragflow_dataset_name text not null default '',
                    template_key text not null default 'general',
                    created_at text not null,
                    updated_at text not null,
                    deleted_at text not null default ''
                )
                """
            )
            db.execute(
                """
                create index if not exists idx_knowledge_bases_active_name
                on knowledge_bases(name, deleted_at)
                """
            )
            db.execute(
                """
                create table if not exists routing_rules (
                    id text primary key,
                    name text not null,
                    enabled integer not null default 1,
                    rule_type text not null,
                    pattern text not null,
                    target_knowledge_base_id text not null,
                    priority integer not null default 100,
                    created_at text not null,
                    updated_at text not null,
                    foreign key (target_knowledge_base_id) references knowledge_bases(id)
                )
                """
            )
            db.execute(
                """
                create index if not exists idx_routing_rules_type_priority
                on routing_rules(rule_type, priority)
                """
            )
            db.execute(
                """
                create table if not exists clip_route_decisions (
                    id integer primary key autoincrement,
                    clip_id text not null,
                    client_request_id text not null default '',
                    knowledge_base_id text not null,
                    ragflow_dataset_id text not null default '',
                    decision_type text not null,
                    matched_rule_id text not null default '',
                    matched_rule_ids_json text not null default '[]',
                    confidence real not null default 0,
                    manual_override integer not null default 0,
                    reason text not null,
                    created_at text not null,
                    previous_knowledge_base_id text not null default '',
                    reindex_status text not null default 'not_required',
                    lineage_id text not null default '',
                    foreign key (knowledge_base_id) references knowledge_bases(id)
                )
                """
            )
            db.execute(
                """
                create index if not exists idx_clip_route_decisions_clip_id
                on clip_route_decisions(clip_id, id)
                """
            )
            db.execute(
                """
                create index if not exists idx_clip_route_decisions_client_request_id
                on clip_route_decisions(client_request_id, id)
                """
            )
        self.ensure_default_knowledge_base()

    def connect(self) -> sqlite3.Connection:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    def ensure_default_knowledge_base(self) -> KnowledgeBase:
        existing_default = self.get_default_knowledge_base()
        if existing_default is not None:
            return existing_default

        now = utc_now()
        with self.connect() as db:
            reusable = db.execute(
                """
                select * from knowledge_bases
                where deleted_at = '' and lower(name) = lower(?)
                order by created_at asc
                limit 1
                """,
                (DEFAULT_KNOWLEDGE_BASE_NAME,),
            ).fetchone()
            if reusable is not None:
                db.execute("update knowledge_bases set is_default = 0 where deleted_at = ''")
                db.execute(
                    "update knowledge_bases set is_default = 1, is_archived = 0, updated_at = ? where id = ?",
                    (now, str(reusable["id"])),
                )
                row = db.execute("select * from knowledge_bases where id = ?", (str(reusable["id"]),)).fetchone()
                return row_to_knowledge_base(row)

            db.execute("update knowledge_bases set is_default = 0 where deleted_at = ''")
            db.execute(
                """
                insert into knowledge_bases (
                    id, name, description, icon, color, is_default, is_archived,
                    ragflow_dataset_id, ragflow_dataset_name, template_key,
                    created_at, updated_at, deleted_at
                )
                values (?, ?, ?, ?, ?, 1, 0, '', '', 'general', ?, ?, '')
                """,
                (
                    DEFAULT_KNOWLEDGE_BASE_ID,
                    DEFAULT_KNOWLEDGE_BASE_NAME,
                    "默认知识库",
                    "inbox",
                    "yellow",
                    now,
                    now,
                ),
            )
            row = db.execute("select * from knowledge_bases where id = ?", (DEFAULT_KNOWLEDGE_BASE_ID,)).fetchone()
        return row_to_knowledge_base(row)

    def list_knowledge_bases(self, include_deleted: bool = False) -> list[KnowledgeBase]:
        where = "" if include_deleted else "where deleted_at = ''"
        with self.connect() as db:
            rows = db.execute(
                f"""
                select * from knowledge_bases
                {where}
                order by is_default desc, is_archived asc, updated_at desc, name asc
                """
            ).fetchall()
        return [row_to_knowledge_base(row) for row in rows]

    def top_topics_by_knowledge_base(self, limit: int = 3) -> dict[str, list[KnowledgeBaseTopicSummary]]:
        if limit <= 0:
            return {}
        with self.connect() as db:
            required_tables = {
                "clip_knowledge_bases",
                "clip_topic_assignments",
                "topic_definitions",
            }
            existing_tables = {
                str(row["name"])
                for row in db.execute(
                    "select name from sqlite_master where type = 'table' and name in (?, ?, ?)",
                    tuple(required_tables),
                ).fetchall()
            }
            if existing_tables != required_tables:
                return {}
            rows = db.execute(
                """
                select ckb.knowledge_base_id,
                       assignment.topic_id,
                       definition.display_name,
                       definition.sort_order,
                       count(distinct ckb.clip_id) as clip_count
                from clip_knowledge_bases ckb
                join clip_topic_assignments assignment
                  on assignment.clip_id = ckb.clip_id
                 and assignment.active = 1
                 and assignment.role = 'primary'
                 and assignment.topic_id <> 'unclassified'
                join topic_definitions definition
                  on definition.topic_id = assignment.topic_id
                group by ckb.knowledge_base_id,
                         assignment.topic_id,
                         definition.display_name,
                         definition.sort_order
                order by ckb.knowledge_base_id asc,
                         clip_count desc,
                         definition.sort_order asc,
                         assignment.topic_id asc
                """
            ).fetchall()

        result: dict[str, list[KnowledgeBaseTopicSummary]] = {}
        for row in rows:
            knowledge_base_id = str(row["knowledge_base_id"])
            summaries = result.setdefault(knowledge_base_id, [])
            if len(summaries) >= limit:
                continue
            summaries.append(
                KnowledgeBaseTopicSummary(
                    id=str(row["topic_id"]),
                    label=str(row["display_name"]),
                    clip_count=int(row["clip_count"]),
                )
            )
        return result

    def get_knowledge_base(self, knowledge_base_id: str, include_deleted: bool = False) -> KnowledgeBase | None:
        where_deleted = "" if include_deleted else "and deleted_at = ''"
        with self.connect() as db:
            row = db.execute(
                f"select * from knowledge_bases where id = ? {where_deleted}",
                (knowledge_base_id,),
            ).fetchone()
        return row_to_knowledge_base(row) if row else None

    def require_active_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        knowledge_base = self.get_knowledge_base(knowledge_base_id)
        if knowledge_base is None:
            raise KnowledgeBaseNotFoundError("knowledge base not found")
        if knowledge_base.is_archived:
            raise KnowledgeBaseConflictError("knowledge base is archived")
        return knowledge_base

    def get_default_knowledge_base(self) -> KnowledgeBase | None:
        with self.connect() as db:
            row = db.execute(
                """
                select * from knowledge_bases
                where deleted_at = '' and is_default = 1 and is_archived = 0
                order by updated_at desc
                limit 1
                """
            ).fetchone()
        return row_to_knowledge_base(row) if row else None

    def create_knowledge_base(
        self,
        *,
        name: str,
        description: str = "",
        icon: str = "",
        color: str = "",
        is_default: bool = False,
        ragflow_dataset_id: str = "",
        ragflow_dataset_name: str = "",
        template_key: str = "general",
    ) -> KnowledgeBase:
        normalized_name = require_nonblank(name, "name")
        self._reject_active_name_conflict(normalized_name)
        now = utc_now()
        knowledge_base_id = f"kb_{uuid.uuid4().hex}"
        with self.connect() as db:
            if is_default:
                db.execute("update knowledge_bases set is_default = 0 where deleted_at = ''")
            db.execute(
                """
                insert into knowledge_bases (
                    id, name, description, icon, color, is_default, is_archived,
                    ragflow_dataset_id, ragflow_dataset_name, template_key,
                    created_at, updated_at, deleted_at
                )
                values (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, '')
                """,
                (
                    knowledge_base_id,
                    normalized_name,
                    description.strip(),
                    icon.strip(),
                    color.strip(),
                    1 if is_default else 0,
                    ragflow_dataset_id.strip(),
                    ragflow_dataset_name.strip(),
                    template_key.strip() or "general",
                    now,
                    now,
                ),
            )
            row = db.execute("select * from knowledge_bases where id = ?", (knowledge_base_id,)).fetchone()
        return row_to_knowledge_base(row)

    def update_knowledge_base(
        self,
        knowledge_base_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        icon: str | None = None,
        color: str | None = None,
        ragflow_dataset_id: str | None = None,
        ragflow_dataset_name: str | None = None,
    ) -> KnowledgeBase:
        current = self.get_knowledge_base(knowledge_base_id)
        if current is None:
            raise KnowledgeBaseNotFoundError("knowledge base not found")
        next_name = current.name if name is None else require_nonblank(name, "name")
        if next_name.lower() != current.name.lower():
            self._reject_active_name_conflict(next_name, exclude_id=knowledge_base_id)
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """
                update knowledge_bases
                set name = ?, description = ?, icon = ?, color = ?,
                    ragflow_dataset_id = ?, ragflow_dataset_name = ?, updated_at = ?
                where id = ? and deleted_at = ''
                """,
                (
                    next_name,
                    current.description if description is None else description.strip(),
                    current.icon if icon is None else icon.strip(),
                    current.color if color is None else color.strip(),
                    current.ragflow_dataset_id if ragflow_dataset_id is None else ragflow_dataset_id.strip(),
                    current.ragflow_dataset_name if ragflow_dataset_name is None else ragflow_dataset_name.strip(),
                    now,
                    knowledge_base_id,
                ),
            )
            row = db.execute("select * from knowledge_bases where id = ?", (knowledge_base_id,)).fetchone()
        return row_to_knowledge_base(row)

    def set_default_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        knowledge_base = self.require_active_knowledge_base(knowledge_base_id)
        now = utc_now()
        with self.connect() as db:
            db.execute("update knowledge_bases set is_default = 0 where deleted_at = ''")
            db.execute(
                "update knowledge_bases set is_default = 1, updated_at = ? where id = ?",
                (now, knowledge_base.id),
            )
            row = db.execute("select * from knowledge_bases where id = ?", (knowledge_base.id,)).fetchone()
        return row_to_knowledge_base(row)

    def archive_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        knowledge_base = self.get_knowledge_base(knowledge_base_id)
        if knowledge_base is None:
            raise KnowledgeBaseNotFoundError("knowledge base not found")
        if knowledge_base.is_default:
            raise KnowledgeBaseConflictError("default knowledge base cannot be archived")
        now = utc_now()
        with self.connect() as db:
            db.execute(
                "update knowledge_bases set is_archived = 1, updated_at = ? where id = ? and deleted_at = ''",
                (now, knowledge_base_id),
            )
            row = db.execute("select * from knowledge_bases where id = ?", (knowledge_base_id,)).fetchone()
        return row_to_knowledge_base(row)

    def delete_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        knowledge_base = self.get_knowledge_base(knowledge_base_id)
        if knowledge_base is None:
            raise KnowledgeBaseNotFoundError("knowledge base not found")
        if knowledge_base.is_default:
            raise KnowledgeBaseConflictError("default knowledge base cannot be deleted")
        now = utc_now()
        with self.connect() as db:
            db.execute(
                "update knowledge_bases set deleted_at = ?, updated_at = ?, is_default = 0 where id = ? and deleted_at = ''",
                (now, now, knowledge_base_id),
            )
            row = db.execute("select * from knowledge_bases where id = ?", (knowledge_base_id,)).fetchone()
        return row_to_knowledge_base(row)

    def create_routing_rule(
        self,
        *,
        name: str,
        rule_type: str,
        pattern: str,
        target_knowledge_base_id: str,
        priority: int = 100,
        enabled: bool = True,
    ) -> RoutingRule:
        normalized_rule_type = validate_rule_type(rule_type)
        normalized_pattern = validate_rule_pattern(pattern)
        target = self.require_active_knowledge_base(target_knowledge_base_id)
        now = utc_now()
        rule_id = f"rule_{uuid.uuid4().hex}"
        with self.connect() as db:
            db.execute(
                """
                insert into routing_rules (
                    id, name, enabled, rule_type, pattern, target_knowledge_base_id,
                    priority, created_at, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule_id,
                    require_nonblank(name, "name"),
                    1 if enabled else 0,
                    normalized_rule_type,
                    normalized_pattern,
                    target.id,
                    int(priority),
                    now,
                    now,
                ),
            )
            row = db.execute("select * from routing_rules where id = ?", (rule_id,)).fetchone()
        return row_to_routing_rule(row)

    def list_routing_rules(self) -> list[RoutingRule]:
        with self.connect() as db:
            rows = db.execute(
                """
                select * from routing_rules
                order by rule_type asc, priority asc, created_at asc
                """
            ).fetchall()
        return [row_to_routing_rule(row) for row in rows]

    def list_enabled_routing_rules(self) -> list[RoutingRule]:
        with self.connect() as db:
            rows = db.execute(
                """
                select * from routing_rules
                where enabled = 1
                order by priority asc, created_at asc
                """
            ).fetchall()
        return [row_to_routing_rule(row) for row in rows]

    def get_routing_rule(self, rule_id: str) -> RoutingRule | None:
        with self.connect() as db:
            row = db.execute("select * from routing_rules where id = ?", (rule_id,)).fetchone()
        return row_to_routing_rule(row) if row else None

    def update_routing_rule(
        self,
        rule_id: str,
        *,
        name: str | None = None,
        enabled: bool | None = None,
        rule_type: str | None = None,
        pattern: str | None = None,
        target_knowledge_base_id: str | None = None,
        priority: int | None = None,
    ) -> RoutingRule:
        current = self.get_routing_rule(rule_id)
        if current is None:
            raise KnowledgeBaseNotFoundError("routing rule not found")
        next_rule_type = current.rule_type if rule_type is None else validate_rule_type(rule_type)
        next_pattern = current.pattern if pattern is None else validate_rule_pattern(pattern)
        next_target_id = current.target_knowledge_base_id if target_knowledge_base_id is None else target_knowledge_base_id
        self.require_active_knowledge_base(next_target_id)
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """
                update routing_rules
                set name = ?, enabled = ?, rule_type = ?, pattern = ?,
                    target_knowledge_base_id = ?, priority = ?, updated_at = ?
                where id = ?
                """,
                (
                    current.name if name is None else require_nonblank(name, "name"),
                    1 if (current.enabled if enabled is None else enabled) else 0,
                    next_rule_type,
                    next_pattern,
                    next_target_id,
                    current.priority if priority is None else int(priority),
                    now,
                    rule_id,
                ),
            )
            row = db.execute("select * from routing_rules where id = ?", (rule_id,)).fetchone()
        return row_to_routing_rule(row)

    def delete_routing_rule(self, rule_id: str) -> RoutingRule:
        current = self.get_routing_rule(rule_id)
        if current is None:
            raise KnowledgeBaseNotFoundError("routing rule not found")
        with self.connect() as db:
            db.execute("delete from routing_rules where id = ?", (rule_id,))
        return current

    def save_route_decision(
        self,
        *,
        clip_id: str | int,
        client_request_id: str,
        knowledge_base_id: str,
        ragflow_dataset_id: str = "",
        decision_type: str,
        matched_rule_id: str = "",
        matched_rule_ids: list[str] | None = None,
        confidence: float,
        manual_override: bool,
        reason: str,
        previous_knowledge_base_id: str = "",
        reindex_status: str = "not_required",
        lineage_id: str = "",
    ) -> ClipRouteDecision:
        self.require_active_knowledge_base(knowledge_base_id)
        readable_reason = require_nonblank(reason, "reason")
        if readable_reason.lower() in {"auto", "matched"}:
            raise KnowledgeBaseError("route decision reason must be explanatory")
        created_at = utc_now()
        with self.connect() as db:
            cursor = db.execute(
                """
                insert into clip_route_decisions (
                    clip_id, client_request_id, knowledge_base_id, ragflow_dataset_id,
                    decision_type, matched_rule_id, matched_rule_ids_json, confidence,
                    manual_override, reason, created_at, previous_knowledge_base_id,
                    reindex_status, lineage_id
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(clip_id),
                    client_request_id.strip(),
                    knowledge_base_id,
                    ragflow_dataset_id.strip(),
                    require_nonblank(decision_type, "decision_type"),
                    matched_rule_id.strip(),
                    json.dumps(matched_rule_ids or [], ensure_ascii=False, sort_keys=True),
                    float(confidence),
                    1 if manual_override else 0,
                    readable_reason,
                    created_at,
                    previous_knowledge_base_id.strip(),
                    reindex_status.strip() or "not_required",
                    lineage_id.strip(),
                ),
            )
            row = db.execute("select * from clip_route_decisions where id = ?", (int(cursor.lastrowid),)).fetchone()
        return row_to_route_decision(row)

    def find_latest_route_decision_by_clip_id(self, clip_id: str | int) -> ClipRouteDecision | None:
        with self.connect() as db:
            row = db.execute(
                """
                select * from clip_route_decisions
                where clip_id = ?
                order by id desc
                limit 1
                """,
                (str(clip_id),),
            ).fetchone()
        return row_to_route_decision(row) if row else None

    def find_route_decision_by_request_id(self, client_request_id: str) -> ClipRouteDecision | None:
        with self.connect() as db:
            row = db.execute(
                """
                select * from clip_route_decisions
                where client_request_id = ?
                order by id desc
                limit 1
                """,
                (client_request_id.strip(),),
            ).fetchone()
        return row_to_route_decision(row) if row else None

    def _reject_active_name_conflict(self, name: str, exclude_id: str = "") -> None:
        with self.connect() as db:
            row = db.execute(
                """
                select id from knowledge_bases
                where deleted_at = '' and lower(name) = lower(?) and id != ?
                limit 1
                """,
                (name, exclude_id),
            ).fetchone()
        if row is not None:
            raise KnowledgeBaseConflictError("active knowledge base name already exists")


def validate_rule_type(rule_type: str) -> str:
    normalized = rule_type.strip()
    if normalized == "default":
        raise KnowledgeBaseError("default routing is handled by the default knowledge base fallback")
    if normalized not in SUPPORTED_RULE_TYPES:
        raise KnowledgeBaseError("unsupported routing rule type")
    return normalized


def validate_rule_pattern(pattern: str) -> str:
    normalized = require_nonblank(pattern, "pattern")
    if SENSITIVE_PATTERN_RE.search(normalized):
        raise KnowledgeBaseError("routing rule pattern must not contain credential-like fields")
    return normalized


def require_nonblank(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise KnowledgeBaseError(f"{field_name} must not be blank")
    return normalized


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def row_to_knowledge_base(row: sqlite3.Row) -> KnowledgeBase:
    return KnowledgeBase(
        id=str(row["id"]),
        name=str(row["name"]),
        description=str(row["description"]),
        icon=str(row["icon"]),
        color=str(row["color"]),
        is_default=bool(row["is_default"]),
        is_archived=bool(row["is_archived"]),
        ragflow_dataset_id=str(row["ragflow_dataset_id"]),
        ragflow_dataset_name=str(row["ragflow_dataset_name"]),
        template_key=str(row["template_key"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        deleted_at=str(row["deleted_at"]),
    )


def row_to_routing_rule(row: sqlite3.Row) -> RoutingRule:
    return RoutingRule(
        id=str(row["id"]),
        name=str(row["name"]),
        enabled=bool(row["enabled"]),
        rule_type=str(row["rule_type"]),
        pattern=str(row["pattern"]),
        target_knowledge_base_id=str(row["target_knowledge_base_id"]),
        priority=int(row["priority"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def row_to_route_decision(row: sqlite3.Row) -> ClipRouteDecision:
    matched_rule_ids = json.loads(str(row["matched_rule_ids_json"]))
    if not isinstance(matched_rule_ids, list):
        matched_rule_ids = []
    return ClipRouteDecision(
        id=int(row["id"]),
        clip_id=str(row["clip_id"]),
        client_request_id=str(row["client_request_id"]),
        knowledge_base_id=str(row["knowledge_base_id"]),
        ragflow_dataset_id=str(row["ragflow_dataset_id"]),
        decision_type=str(row["decision_type"]),
        matched_rule_id=str(row["matched_rule_id"]),
        matched_rule_ids=[str(rule_id) for rule_id in matched_rule_ids],
        confidence=float(row["confidence"]),
        manual_override=bool(row["manual_override"]),
        reason=str(row["reason"]),
        created_at=str(row["created_at"]),
        previous_knowledge_base_id=str(row["previous_knowledge_base_id"]),
        reindex_status=str(row["reindex_status"]),
        lineage_id=str(row["lineage_id"]),
    )
