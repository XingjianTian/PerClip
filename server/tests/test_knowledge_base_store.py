import sqlite3

import pytest

from perclip_ingest.knowledge_base_store import (
    DEFAULT_KNOWLEDGE_BASE_NAME,
    KnowledgeBaseConflictError,
    KnowledgeBaseError,
    KnowledgeBaseNotFoundError,
    KnowledgeBaseStore,
)


def store_for(tmp_path) -> KnowledgeBaseStore:
    store = KnowledgeBaseStore(tmp_path)
    store.init()
    return store


def test_init_creates_default_knowledge_base(tmp_path):
    store = store_for(tmp_path)

    default = store.get_default_knowledge_base()

    assert default is not None
    assert default.name == DEFAULT_KNOWLEDGE_BASE_NAME
    assert default.is_default is True
    assert default.is_archived is False


def test_init_is_idempotent_for_default_knowledge_base(tmp_path):
    first = store_for(tmp_path)
    first_default = first.get_default_knowledge_base()
    assert first_default is not None

    second = store_for(tmp_path)
    defaults = [kb for kb in second.list_knowledge_bases() if kb.is_default]

    assert len(defaults) == 1
    assert defaults[0].id == first_default.id


def test_create_knowledge_base_rejects_active_name_conflict(tmp_path):
    store = store_for(tmp_path)
    store.create_knowledge_base(name="Research")

    with pytest.raises(KnowledgeBaseConflictError):
        store.create_knowledge_base(name="research")


def test_update_knowledge_base_fields(tmp_path):
    store = store_for(tmp_path)
    kb = store.create_knowledge_base(name="Research")

    updated = store.update_knowledge_base(
        kb.id,
        name="Papers",
        description="PDF inbox",
        icon="article",
        color="blue",
    )

    assert updated.name == "Papers"
    assert updated.description == "PDF inbox"
    assert updated.icon == "article"
    assert updated.color == "blue"


def test_set_default_unsets_previous_default(tmp_path):
    store = store_for(tmp_path)
    kb = store.create_knowledge_base(name="Research")

    updated = store.set_default_knowledge_base(kb.id)
    defaults = [item for item in store.list_knowledge_bases() if item.is_default]

    assert updated.id == kb.id
    assert len(defaults) == 1
    assert defaults[0].id == kb.id


def test_archive_knowledge_base(tmp_path):
    store = store_for(tmp_path)
    kb = store.create_knowledge_base(name="Archive me")

    archived = store.archive_knowledge_base(kb.id)

    assert archived.is_archived is True


def test_delete_non_default_knowledge_base_soft_deletes(tmp_path):
    store = store_for(tmp_path)
    kb = store.create_knowledge_base(name="Old")

    deleted = store.delete_knowledge_base(kb.id)

    assert deleted.deleted_at
    assert store.get_knowledge_base(kb.id) is None
    assert store.get_knowledge_base(kb.id, include_deleted=True) is not None


def test_delete_default_knowledge_base_is_rejected(tmp_path):
    store = store_for(tmp_path)
    default = store.get_default_knowledge_base()
    assert default is not None

    with pytest.raises(KnowledgeBaseConflictError):
        store.delete_knowledge_base(default.id)


def test_archived_and_deleted_knowledge_bases_cannot_be_rule_targets(tmp_path):
    store = store_for(tmp_path)
    archived = store.archive_knowledge_base(store.create_knowledge_base(name="Archived").id)
    deleted = store.delete_knowledge_base(store.create_knowledge_base(name="Deleted").id)

    with pytest.raises(KnowledgeBaseConflictError):
        store.create_routing_rule(
            name="Archived target",
            rule_type="keyword",
            pattern="archived",
            target_knowledge_base_id=archived.id,
        )
    with pytest.raises(KnowledgeBaseNotFoundError):
        store.create_routing_rule(
            name="Deleted target",
            rule_type="keyword",
            pattern="deleted",
            target_knowledge_base_id=deleted.id,
        )


@pytest.mark.parametrize(
    ("rule_type", "pattern"),
    [
        ("source_app", "Chrome"),
        ("mime_type", "application/pdf"),
        ("file_extension", ".pdf"),
        ("url_domain", "github.com"),
        ("keyword", "PerClip"),
    ],
)
def test_create_supported_routing_rules(tmp_path, rule_type, pattern):
    store = store_for(tmp_path)
    target = store.create_knowledge_base(name=f"Target {rule_type}")

    rule = store.create_routing_rule(
        name=f"{rule_type} rule",
        rule_type=rule_type,
        pattern=pattern,
        target_knowledge_base_id=target.id,
        priority=10,
    )

    assert rule.rule_type == rule_type
    assert rule.pattern == pattern
    assert rule.target_knowledge_base_id == target.id
    assert rule.priority == 10


def test_default_routing_rule_type_is_rejected(tmp_path):
    store = store_for(tmp_path)
    target = store.create_knowledge_base(name="Target")

    with pytest.raises(KnowledgeBaseError, match="default routing is handled"):
        store.create_routing_rule(
            name="Default rule",
            rule_type="default",
            pattern="*",
            target_knowledge_base_id=target.id,
        )


def test_update_disable_and_delete_routing_rule(tmp_path):
    store = store_for(tmp_path)
    target = store.create_knowledge_base(name="Target")
    other = store.create_knowledge_base(name="Other")
    rule = store.create_routing_rule(
        name="Old",
        rule_type="keyword",
        pattern="old",
        target_knowledge_base_id=target.id,
    )

    updated = store.update_routing_rule(
        rule.id,
        name="New",
        enabled=False,
        pattern="new",
        target_knowledge_base_id=other.id,
        priority=5,
    )
    deleted = store.delete_routing_rule(rule.id)

    assert updated.name == "New"
    assert updated.enabled is False
    assert updated.pattern == "new"
    assert updated.target_knowledge_base_id == other.id
    assert updated.priority == 5
    assert deleted.id == rule.id
    assert store.get_routing_rule(rule.id) is None


@pytest.mark.parametrize("pattern", ["token=abc", "api_key: value", "password123", "secret", "cookie", "authorization"])
def test_rule_pattern_rejects_credential_like_terms(tmp_path, pattern):
    store = store_for(tmp_path)
    target = store.create_knowledge_base(name="Target")

    with pytest.raises(KnowledgeBaseError):
        store.create_routing_rule(
            name="Unsafe",
            rule_type="keyword",
            pattern=pattern,
            target_knowledge_base_id=target.id,
        )


def test_save_and_read_route_decision(tmp_path):
    store = store_for(tmp_path)
    target = store.create_knowledge_base(name="Target", ragflow_dataset_id="dataset-ref")

    saved = store.save_route_decision(
        clip_id=42,
        client_request_id="request-42",
        knowledge_base_id=target.id,
        ragflow_dataset_id=target.ragflow_dataset_id,
        decision_type="rule",
        matched_rule_id="rule-1",
        matched_rule_ids=["rule-1", "rule-2"],
        confidence=0.9,
        manual_override=False,
        reason='rule keyword matched "PerClip" -> "Target"',
        previous_knowledge_base_id="old-kb",
        reindex_status="required",
        lineage_id="lineage-1",
    )
    by_clip = store.find_latest_route_decision_by_clip_id(42)
    by_request = store.find_route_decision_by_request_id("request-42")

    assert saved.matched_rule_ids == ["rule-1", "rule-2"]
    assert by_clip is not None
    assert by_clip.id == saved.id
    assert by_request is not None
    assert by_request.id == saved.id
    assert by_request.ragflow_dataset_id == "dataset-ref"
    assert by_request.reindex_status == "required"


def test_route_decision_reason_must_be_explanatory(tmp_path):
    store = store_for(tmp_path)
    target = store.create_knowledge_base(name="Target")

    with pytest.raises(KnowledgeBaseError):
        store.save_route_decision(
            clip_id=1,
            client_request_id="request",
            knowledge_base_id=target.id,
            decision_type="rule",
            confidence=0.1,
            manual_override=False,
            reason="auto",
        )


def test_init_migrates_existing_clip_database_without_manual_steps(tmp_path):
    db_path = tmp_path / "perclip.sqlite3"
    tmp_path.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as db:
        db.execute("create table clips (id integer primary key autoincrement)")

    store = KnowledgeBaseStore(tmp_path)
    store.init()

    assert store.get_default_knowledge_base() is not None
    with sqlite3.connect(db_path) as db:
        tables = {row[0] for row in db.execute("select name from sqlite_master where type = 'table'")}
    assert {"knowledge_bases", "routing_rules", "clip_route_decisions"}.issubset(tables)
