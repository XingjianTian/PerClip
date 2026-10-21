from __future__ import annotations

import hashlib
import json
import re
import sys

from api.db.services.knowledgebase_service import KnowledgebaseService
from api.db.services.document_service import DocumentService
from common import settings
from common.doc_store.doc_store_base import OrderByExpr
from rag.nlp import search


SCHEMA = "perclip-ragflow-operator-evidence.v1"
VECTOR_FIELD = re.compile(r"^q_[1-9][0-9]*_vec$")
MAX_CHUNKS = 10_000


def _alias(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _has_vector(chunk: dict[str, object]) -> bool:
    vectors = [
        value for key, value in chunk.items() if VECTOR_FIELD.fullmatch(str(key))
    ]
    return len(vectors) == 1 and isinstance(vectors[0], list) and bool(vectors[0])


def main() -> int:
    try:
        settings.init_settings()
        request = json.load(sys.stdin)
        dataset_id = str(request["dataset_id"])
        allow_dataset_id = str(request["allow_dataset_id"])
        if request.get("schema") != SCHEMA or dataset_id != allow_dataset_id:
            raise ValueError("scope")

        found, dataset = KnowledgebaseService.get_by_id(dataset_id)
        if not found:
            raise ValueError("dataset")
        index_name = search.index_name(dataset.tenant_id)
        if request.get("scope") == "dataset":
            documents = DocumentService.query(kb_id=dataset_id)
            document_ids = {str(document.id) for document in documents}
            result = settings.docStoreConn.search(
                select_fields=[],
                highlight_fields=[],
                condition={},
                match_expressions=[],
                order_by=OrderByExpr(),
                offset=0,
                limit=MAX_CHUNKS,
                index_names=index_name,
                knowledgebase_ids=[dataset_id],
            )
            total = int(settings.docStoreConn.get_total(result))
            chunk_ids = settings.docStoreConn.get_doc_ids(result)
            if total > MAX_CHUNKS or len(chunk_ids) != total:
                raise ValueError("coverage")
            vector_count = 0
            orphan_count = 0
            for chunk_id in chunk_ids:
                chunk = settings.docStoreConn.get(
                    chunk_id, index_name, [dataset_id]
                )
                if (
                    not isinstance(chunk, dict)
                    or str(chunk.get("kb_id") or "") != dataset_id
                ):
                    raise ValueError("identity")
                vector_count += int(_has_vector(chunk))
                orphan_count += int(
                    str(chunk.get("doc_id") or "") not in document_ids
                )
            print(
                json.dumps(
                    {
                        "schema": SCHEMA,
                        "dataset_alias": _alias(dataset_id),
                        "document_count": len(document_ids),
                        "chunk_count": total,
                        "vector_count": vector_count,
                        "covered_chunk_count": len(chunk_ids),
                        "orphan_chunk_count": orphan_count,
                        "evidence_type": "operator_es_exact_dataset",
                    },
                    separators=(",", ":"),
                )
            )
            return 0

        document_id = str(request["document_id"])
        result = settings.docStoreConn.search(
            select_fields=[],
            highlight_fields=[],
            condition={"doc_id": document_id},
            match_expressions=[],
            order_by=OrderByExpr(),
            offset=0,
            limit=MAX_CHUNKS,
            index_names=index_name,
            knowledgebase_ids=[dataset_id],
        )
        total = int(settings.docStoreConn.get_total(result))
        chunk_ids = settings.docStoreConn.get_doc_ids(result)
        if total > MAX_CHUNKS or len(chunk_ids) != total:
            raise ValueError("coverage")

        vector_count = 0
        for chunk_id in chunk_ids:
            chunk = settings.docStoreConn.get(
                chunk_id, index_name, [dataset_id]
            )
            if (
                not isinstance(chunk, dict)
                or str(chunk.get("doc_id") or "") != document_id
                or str(chunk.get("kb_id") or "") != dataset_id
            ):
                raise ValueError("identity")
            vector_count += int(_has_vector(chunk))

        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "dataset_alias": _alias(dataset_id),
                    "document_alias": _alias(document_id),
                    "chunk_count": total,
                    "vector_count": vector_count,
                    "covered_chunk_count": len(chunk_ids),
                    "evidence_type": "operator_es_exact_document",
                },
                separators=(",", ":"),
            )
        )
        return 0
    except Exception:
        print(
            json.dumps(
                {"schema": SCHEMA, "safe_error_code": "operator_verification_failed"},
                separators=(",", ":"),
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
