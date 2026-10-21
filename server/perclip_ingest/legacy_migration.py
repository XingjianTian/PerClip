from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .knowledge_base_store import KnowledgeBaseStore
from .metadata_contract import NormalizedMetadataInput, build_normalized_metadata, dumps_normalized_metadata
from .pipeline_store import PipelineStore
from .storage import ClipStore


REQUIRED_COLUMNS = {
    "id", "created_at", "launcher_id", "message_id", "source_type", "platform",
    "title", "markdown_path", "original_path", "source_url", "ragflow_document_id",
    "status", "metadata_json",
}
APPLY_CONFIRMATION = "IMPORT_LEGACY_READ_ONLY_COPY"


def now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class LegacyItem:
    id: int
    created_at: str
    launcher_id: str
    message_id: str
    source_type: str
    platform: str
    title: str
    markdown_path: str
    original_path: str
    source_url: str
    ragflow_document_id: str
    status: str
    metadata_json: str


class LegacyMigrationError(ValueError):
    pass


class LegacyImporter:
    def __init__(self, *, legacy_db: Path, data_dir: Path, dataset_id: str = "") -> None:
        self.legacy_db = legacy_db.resolve()
        self.data_dir = data_dir.resolve()
        self.dataset_id = dataset_id.strip()

    def read_items(self) -> list[LegacyItem]:
        if not self.legacy_db.is_file():
            raise LegacyMigrationError("legacy database not found")
        uri = f"file:{self.legacy_db.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            db.row_factory = sqlite3.Row
            columns = {str(row[1]) for row in db.execute("pragma table_info(items)").fetchall()}
            if not REQUIRED_COLUMNS.issubset(columns):
                raise LegacyMigrationError("legacy items schema is unsupported")
            rows = db.execute("select * from items order by id asc").fetchall()
        return [
            LegacyItem(
                id=int(row["id"]),
                created_at=str(row["created_at"] or ""),
                launcher_id=str(row["launcher_id"] or ""),
                message_id=str(row["message_id"] or ""),
                source_type=str(row["source_type"] or "text"),
                platform=str(row["platform"] or ""),
                title=str(row["title"] or "未命名收藏"),
                markdown_path=str(row["markdown_path"] or ""),
                original_path=str(row["original_path"] or ""),
                source_url=str(row["source_url"] or ""),
                ragflow_document_id=str(row["ragflow_document_id"] or ""),
                status=str(row["status"] or "unknown"),
                metadata_json=str(row["metadata_json"] or "{}"),
            )
            for row in rows
        ]

    def audit(self) -> dict[str, object]:
        items = self.read_items()
        status_counts: dict[str, int] = {}
        for item in items:
            status_counts[item.status] = status_counts.get(item.status, 0) + 1
        active = [item for item in items if item.status == "active"]
        missing_markdown = sum(1 for item in active if not Path(item.markdown_path).is_file())
        missing_original = sum(
            1 for item in active if item.original_path and not Path(item.original_path).is_file()
        )
        duplicate_documents = len(active) - len(
            {item.ragflow_document_id for item in active if item.ragflow_document_id}
        ) - sum(1 for item in active if not item.ragflow_document_id)
        current_maps = 0
        destination = self.data_dir / "perclip.sqlite3"
        if destination.is_file():
            uri = f"file:{destination.as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as db:
                exists = db.execute(
                    "select 1 from sqlite_master where type='table' and name='legacy_import_map'"
                ).fetchone()
                if exists:
                    current_maps = int(
                        db.execute(
                            "select count(*) from legacy_import_map where legacy_system='cliptoragflow'"
                        ).fetchone()[0]
                    )
        return {
            "mode": "dry_run",
            "legacy_items": len(items),
            "status_counts": status_counts,
            "active_candidates": len(active),
            "missing_markdown_files": missing_markdown,
            "missing_original_files": missing_original,
            "duplicate_nonempty_document_ids": max(0, duplicate_documents),
            "existing_import_maps": current_maps,
            "dataset_mapping_configured": bool(self.dataset_id),
            "legacy_database_mutated": False,
            "ragflow_mutated": False,
        }

    def apply(self, *, confirmation: str, backup_dir: Path) -> dict[str, object]:
        if confirmation != APPLY_CONFIRMATION:
            raise LegacyMigrationError("explicit import confirmation is required")
        items = self.read_items()
        active_with_documents = any(
            item.status == "active" and item.ragflow_document_id for item in items
        )
        if active_with_documents and not self.dataset_id:
            raise LegacyMigrationError("legacy dataset mapping is required before import")

        self._backup_destination(backup_dir)
        store = ClipStore(self.data_dir)
        store.init()
        knowledge = KnowledgeBaseStore(self.data_dir)
        knowledge.init()
        pipeline = PipelineStore(self.data_dir)
        pipeline.init()
        default_kb = knowledge.get_default_knowledge_base()
        if default_kb is None:
            raise LegacyMigrationError("default knowledge base is unavailable")

        imported = 0
        mapped_inactive = 0
        skipped_missing = 0
        for item in items:
            if self._already_mapped(item.id):
                continue
            if item.status != "active":
                self._record_inactive_map(item)
                mapped_inactive += 1
                continue
            markdown_path = Path(item.markdown_path)
            if not markdown_path.is_file():
                self._record_missing_map(item)
                skipped_missing += 1
                continue
            self._import_active(item, default_kb.id)
            imported += 1
        return {
            "mode": "apply",
            "imported_active": imported,
            "mapped_inactive": mapped_inactive,
            "skipped_missing": skipped_missing,
            "legacy_database_mutated": False,
            "ragflow_mutated": False,
        }

    def _backup_destination(self, backup_dir: Path) -> None:
        backup_dir = backup_dir.resolve()
        backup_dir.mkdir(parents=True, exist_ok=True)
        destination = self.data_dir / "perclip.sqlite3"
        if not destination.is_file():
            raise LegacyMigrationError("destination database is unavailable for backup")
        backup = backup_dir / (
            f"perclip-before-legacy-import-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
            f"-{uuid.uuid4().hex[:8]}.sqlite3"
        )
        with sqlite3.connect(destination) as source_db, sqlite3.connect(backup) as backup_db:
            source_db.backup(backup_db)

    def _already_mapped(self, legacy_id: int) -> bool:
        with sqlite3.connect(self.data_dir / "perclip.sqlite3") as db:
            row = db.execute(
                "select 1 from legacy_import_map where legacy_system='cliptoragflow' and legacy_item_id=?",
                (str(legacy_id),),
            ).fetchone()
        return row is not None

    def _record_inactive_map(self, item: LegacyItem) -> None:
        self._upsert_map(item, clip_id=None, import_status=f"legacy_{item.status}")

    def _record_missing_map(self, item: LegacyItem) -> None:
        self._upsert_map(item, clip_id=None, import_status="missing_markdown")

    def _upsert_map(self, item: LegacyItem, *, clip_id: int | None, import_status: str) -> None:
        now = now_text()
        with sqlite3.connect(self.data_dir / "perclip.sqlite3") as db:
            db.execute(
                """
                insert into legacy_import_map(
                    legacy_system, legacy_item_id, clip_id, source_url, source_path_hash,
                    content_hash, index_provider, dataset_id, document_id, import_status,
                    evidence_json, created_at, updated_at
                ) values ('cliptoragflow', ?, ?, ?, ?, ?, 'ragflow', ?, ?, ?, ?, ?, ?)
                on conflict(legacy_system, legacy_item_id) do nothing
                """,
                (
                    str(item.id), clip_id, item.source_url,
                    hashlib.sha256(item.markdown_path.encode()).hexdigest(), "",
                    self.dataset_id, item.ragflow_document_id, import_status,
                    json.dumps({"legacy_status": item.status}, sort_keys=True), now, now,
                ),
            )

    def _import_active(self, item: LegacyItem, knowledge_base_id: str) -> None:
        markdown_path = Path(item.markdown_path)
        markdown_bytes = markdown_path.read_bytes()
        content_hash = hashlib.sha256(markdown_bytes).hexdigest()
        try:
            text = markdown_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = markdown_bytes.decode("utf-8", errors="replace")
        created_at = self._safe_created_at(item.created_at)
        client_request_id = f"legacy:cliptoragflow:{item.id}"
        source_type = item.source_type if item.source_type in {"text", "url", "image", "file"} else "file"
        storage_path = Path(item.original_path) if item.original_path and Path(item.original_path).is_file() else markdown_path
        now = now_text()
        public_id = f"pc_{uuid.uuid4().hex}"
        asset_id = f"asset_{hashlib.sha256(f'legacy:{item.id}:{content_hash}'.encode()).hexdigest()[:24]}"
        event_key = f"import:cliptoragflow:{item.id}"
        source_event_id = f"se_{hashlib.sha256(event_key.encode()).hexdigest()[:24]}"
        metadata = build_normalized_metadata(
            NormalizedMetadataInput(
                source_type=source_type,
                title_hint=item.title,
                note="",
                text=text,
                url=item.source_url,
                mime_type="text/markdown",
                device_name="",
                source_app=item.platform,
                captured_at=created_at,
                client_request_id=client_request_id,
                filename=markdown_path.name,
                has_file=True,
                size_bytes=len(markdown_bytes),
                content_hash=content_hash,
                storage_uri=str(markdown_path),
                received_at=now,
                archive_status="archived",
                ragflow_document_id=item.ragflow_document_id,
                source_adapter="import",
                source_client_id="cliptoragflow",
                source_event_id=str(item.id),
                source_intent="unknown",
                content_fingerprint=content_hash,
            )
        )
        metadata["routing"] = {
            "knowledge_base_id": knowledge_base_id,
            "knowledge_base_name": "",
            "ragflow_dataset_id": self.dataset_id,
            "decision_type": "import",
            "matched_rule_ids": [],
            "reason": "legacy import mapping",
            "manual_override": False,
            "routed_at": now,
        }
        with sqlite3.connect(self.data_dir / "perclip.sqlite3") as db:
            db.execute("pragma foreign_keys=on")
            db.execute("begin immediate")
            cursor = db.execute(
                """
                insert into clips(
                    client_request_id, source_type, title_hint, note, text, url, mime_type,
                    device_name, source_app, captured_at, filename, size_bytes, original_path,
                    content_hash, ragflow_document_id, archive_status, created_at
                ) values (?, ?, ?, '', ?, ?, 'text/markdown', '', ?, ?, ?, ?, ?, ?, ?, 'archived', ?)
                """,
                (
                    client_request_id, source_type, item.title, text, item.source_url,
                    item.platform, created_at, markdown_path.name, len(markdown_bytes),
                    str(storage_path), content_hash, item.ragflow_document_id, now,
                ),
            )
            clip_id = int(cursor.lastrowid)
            route = db.execute(
                """
                insert into clip_route_decisions(
                    clip_id, client_request_id, knowledge_base_id, ragflow_dataset_id,
                    decision_type, matched_rule_id, matched_rule_ids_json, confidence,
                    manual_override, reason, created_at, lineage_id
                ) values (?, ?, ?, ?, 'import', '', '[]', 1, 0,
                    'legacy ClipToRAGFlow import', ?, ?)
                """,
                (
                    str(clip_id), client_request_id, knowledge_base_id, self.dataset_id,
                    now, f"clip:{clip_id}",
                ),
            )
            route_id = int(route.lastrowid)
            db.execute(
                """
                insert into clip_metadata(
                    clip_id, client_request_id, contract_version, metadata_json, created_at
                ) values (?, ?, 'perclip.clip.v1', ?, ?)
                """,
                (clip_id, client_request_id, dumps_normalized_metadata(metadata), now),
            )
            db.execute(
                "insert into clip_identities(clip_id, public_id, created_at) values (?, ?, ?)",
                (clip_id, public_id, now),
            )
            db.execute(
                """
                insert into source_events(
                    id, event_key, clip_id, adapter, client_id, event_id, source_app,
                    occurred_at, deployment_environment, created_at
                ) values (?, ?, ?, 'import', 'cliptoragflow', ?, ?, ?, 'legacy-import', ?)
                """,
                (source_event_id, event_key, clip_id, str(item.id), item.platform, created_at, now),
            )
            db.execute(
                """
                insert into assets(
                    id, clip_id, role, filename, mime_type, size_bytes, content_hash,
                    storage_uri, engine, engine_version, created_at
                ) values (?, ?, 'legacy_markdown', ?, 'text/markdown', ?, ?, ?,
                    'cliptoragflow', 'legacy', ?)
                """,
                (asset_id, clip_id, markdown_path.name, len(markdown_bytes), content_hash, str(markdown_path), now),
            )
            db.execute(
                """
                insert into clip_knowledge_bases(
                    clip_id, knowledge_base_id, association_type, route_decision_id,
                    association_intent_id, created_at
                ) values (?, ?, 'imported', ?, ?, ?)
                """,
                (clip_id, knowledge_base_id, route_id, "assoc_" + uuid.uuid4().hex, now),
            )
            if item.ragflow_document_id:
                db.execute(
                    """
                    insert into index_documents(
                        clip_id, knowledge_base_id, index_provider, dataset_id,
                        document_id, content_hash, status, created_at, updated_at
                    ) values (?, ?, 'ragflow', ?, ?, ?, 'legacy_existing', ?, ?)
                    """,
                    (
                        clip_id, knowledge_base_id, self.dataset_id,
                        item.ragflow_document_id, content_hash, now, now,
                    ),
                )
            db.execute(
                """
                insert into legacy_import_map(
                    legacy_system, legacy_item_id, clip_id, source_url, source_path_hash,
                    content_hash, index_provider, dataset_id, document_id, import_status,
                    evidence_json, created_at, updated_at
                ) values ('cliptoragflow', ?, ?, ?, ?, ?, 'ragflow', ?, ?, 'imported', ?, ?, ?)
                """,
                (
                    str(item.id), clip_id, item.source_url,
                    hashlib.sha256(item.markdown_path.encode()).hexdigest(), content_hash,
                    self.dataset_id, item.ragflow_document_id,
                    json.dumps({"legacy_status": item.status, "asset_readable": True}, sort_keys=True),
                    now, now,
                ),
            )

    @staticmethod
    def _safe_created_at(value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return now_text()
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit or import the legacy ClipToRAGFlow metadata database")
    parser.add_argument("--legacy-db", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--dataset-id-env", default="PERSONAL_CLIPS_DATASET_ID")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args(argv)
    importer = LegacyImporter(
        legacy_db=args.legacy_db,
        data_dir=args.data_dir,
        dataset_id=os.environ.get(args.dataset_id_env, ""),
    )
    try:
        if args.apply:
            if args.backup_dir is None:
                raise LegacyMigrationError("--backup-dir is required for apply")
            report = importer.apply(confirmation=args.confirm, backup_dir=args.backup_dir)
        else:
            report = importer.audit()
    except LegacyMigrationError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
