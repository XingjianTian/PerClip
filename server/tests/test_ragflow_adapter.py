import json

import pytest

import perclip_ingest.ragflow_adapter as ragflow_adapter_module
from perclip_ingest.config import RagflowSettings
from perclip_ingest.ragflow_adapter import (
    CAPABILITY_KEYS,
    DisabledRagflowAdapter,
    DryRunRagflowAdapter,
    HttpRagflowAdapter,
    RagflowAdapterError,
    RagflowUnsupportedError,
    UrlLibRagflowHttpClient,
    build_ragflow_adapter,
)


def test_disabled_adapter_reports_not_configured_capabilities():
    adapter = DisabledRagflowAdapter()
    report = adapter.capability_report()

    assert report.adapter_status == "disabled"
    assert report.configured is False
    assert set(report.capabilities) == set(CAPABILITY_KEYS)
    assert set(report.capabilities.values()) == {"not_configured"}


def test_build_adapter_without_ragflow_config_returns_disabled_adapter():
    adapter = build_ragflow_adapter(RagflowSettings())

    assert adapter.capability_report().adapter_status == "disabled"


def test_dry_run_list_datasets_does_not_require_network():
    adapter = DryRunRagflowAdapter(configured=True)

    assert adapter.list_datasets() == []


def test_dry_run_create_dataset_returns_planned_operation():
    adapter = DryRunRagflowAdapter(configured=True)

    plan = adapter.create_dataset("Research", "Papers", "research_papers")

    assert plan["operation"] == "create_dataset"
    assert plan["dry_run"] is True
    assert plan["remote_dataset_changed"] is False
    assert plan["name"] == "Research"
    assert plan["template_key"] == "research_papers"
    assert plan["dataset_id"].startswith("dry-run-dataset:")


def test_dry_run_update_dataset_returns_planned_operation():
    adapter = DryRunRagflowAdapter(configured=True)

    plan = adapter.update_dataset("dataset-1", name="Updated", description="Next")

    assert plan["operation"] == "update_dataset"
    assert plan["dataset_id"] == "dataset-1"
    assert plan["name"] == "Updated"
    assert plan["description"] == "Next"
    assert plan["remote_dataset_changed"] is False


def test_dry_run_delete_dataset_is_high_danger_and_does_not_delete():
    adapter = DryRunRagflowAdapter(configured=True)

    plan = adapter.delete_dataset("dataset-1")

    assert plan["operation"] == "delete_dataset"
    assert plan["danger_level"] == "high"
    assert plan["requires_confirmation"] is True
    assert plan["remote_dataset_deleted"] is False


def test_delete_dataset_without_dry_run_requires_confirmation_and_still_refuses_remote_delete():
    adapter = DryRunRagflowAdapter(configured=True)

    with pytest.raises(RagflowAdapterError, match="Stage 14B safety gate"):
        adapter.delete_dataset("dataset-1", dry_run=False)
    with pytest.raises(RagflowAdapterError, match="Stage 14B safety gate"):
        adapter.delete_dataset("dataset-1", dry_run=False, confirm_name="Research")


def test_non_dry_run_document_mutations_are_disabled_in_stage14a():
    adapter = DryRunRagflowAdapter(configured=True)

    with pytest.raises(RagflowAdapterError, match="Stage 14B safety gate"):
        adapter.create_dataset("Research", "Papers", "research_papers", dry_run=False)
    with pytest.raises(RagflowAdapterError, match="Stage 14B safety gate"):
        adapter.update_dataset("dataset-1", name="Research", dry_run=False)
    with pytest.raises(RagflowAdapterError, match="Stage 14B safety gate"):
        adapter.upload_document("dataset-1", "demo.md", "/tmp/demo.md", dry_run=False)
    with pytest.raises(RagflowAdapterError, match="Stage 14B safety gate"):
        adapter.update_document_meta("dataset-1", "doc-1", {}, dry_run=False)
    with pytest.raises(RagflowAdapterError, match="Stage 14B safety gate"):
        adapter.disable_or_delete_document("dataset-1", "doc-1", "disable", dry_run=False)


def test_upload_document_dry_run_returns_planned_document_ref():
    adapter = DryRunRagflowAdapter(configured=True)

    ref = adapter.upload_document(
        dataset_id="dataset-1",
        name="demo.md",
        content_or_path="/tmp/demo.md",
        meta_fields={"knowledge_base_id": "kb-1"},
    )

    assert ref.dataset_id == "dataset-1"
    assert ref.name == "demo.md"
    assert ref.document_id.startswith("dry-run:")
    assert ref.meta_fields == {"knowledge_base_id": "kb-1"}
    assert ref.dry_run is True


def test_update_document_meta_dry_run_returns_planned_meta_fields():
    adapter = DryRunRagflowAdapter(configured=True)

    plan = adapter.update_document_meta("dataset-1", "doc-1", {"route": "manual"})

    assert plan["operation"] == "update_document_meta"
    assert plan["dataset_id"] == "dataset-1"
    assert plan["document_id"] == "doc-1"
    assert plan["configured"] is True
    assert plan["planned_meta_fields"] == {"route": "manual"}


def test_disable_or_delete_document_dry_run_returns_planned_operation():
    adapter = DryRunRagflowAdapter(configured=True)

    disabled = adapter.disable_or_delete_document("dataset-1", "doc-1", "disable")
    deleted = adapter.disable_or_delete_document("dataset-1", "doc-1", "delete")

    assert disabled["mode"] == "disable"
    assert disabled["configured"] is True
    assert disabled["remote_document_changed"] is False
    assert deleted["mode"] == "delete"
    assert deleted["remote_document_changed"] is False


def test_disable_or_delete_document_rejects_unknown_mode():
    adapter = DryRunRagflowAdapter(configured=True)

    with pytest.raises(RagflowAdapterError, match="disable or delete"):
        adapter.disable_or_delete_document("dataset-1", "doc-1", "move")


def test_http_skeleton_capability_report_does_not_expose_api_key():
    adapter = build_ragflow_adapter(RagflowSettings(base_url="http://127.0.0.1:18080", api_key="test-ragflow-key"))

    payload = adapter.capability_report().to_dict()

    assert payload["adapter_status"] == "http_skeleton"
    assert payload["configured"] is True
    assert set(payload["capabilities"]) == set(CAPABILITY_KEYS)
    assert payload["capabilities"]["dataset_list"] == "unknown"
    assert payload["capabilities"]["document_upload"] == "disabled"
    assert payload["capabilities"]["document_meta_fields"] == "disabled"
    assert "test-ragflow-key" not in str(payload)


class FakeRagflowClient:
    def __init__(self):
        self.uploads = []
        self.meta_updates = []
        self.parse_requests = []
        self.deletes = []
        self.documents = []
        self.chunks = []
        self.chunk_total = None
        self.total_only = False

    def upload_document(self, base_url, api_key, dataset_id, name, content):
        self.uploads.append((base_url, api_key, dataset_id, name, content))
        return {"data": [{"id": "doc-created"}]}

    def update_document_meta(self, base_url, api_key, dataset_id, document_id, meta_fields):
        self.meta_updates.append((base_url, api_key, dataset_id, document_id, meta_fields))
        return {"data": {"id": document_id}}

    def find_documents(self, base_url, api_key, dataset_id, operation_key):
        return {"data": {"docs": self.documents, "total": len(self.documents)}}

    def request_parse(self, base_url, api_key, dataset_id, document_id):
        self.parse_requests.append((dataset_id, document_id))
        return {"code": 0}

    def get_document(self, base_url, api_key, dataset_id, document_id):
        rows = [item for item in self.documents if item["id"] == document_id]
        return {"data": {"docs": rows, "total": len(rows)}}

    def get_chunks(
        self, base_url, api_key, dataset_id, document_id, page, page_size
    ):
        total = len(self.chunks) if self.chunk_total is None else self.chunk_total
        rows = [] if self.total_only else self.chunks[(page - 1) * page_size : page * page_size]
        return {"data": {"chunks": rows, "total": total}}

    def delete_document(self, base_url, api_key, dataset_id, document_id):
        self.deletes.append((dataset_id, document_id))
        self.documents = [item for item in self.documents if item["id"] != document_id]
        self.chunks = []
        return {"code": 0}


def test_real_sync_requires_both_explicit_safety_gates():
    client = FakeRagflowClient()
    adapter = HttpRagflowAdapter(RagflowSettings(base_url="http://ragflow", api_key="key"), client)

    with pytest.raises(RagflowAdapterError, match="PERCLIP_ENABLE_REAL_RAGFLOW_SYNC"):
        adapter.upload_document("dataset-test", "clip.md", "body", dry_run=False)

    assert client.uploads == []


def test_real_sync_rejects_dataset_outside_allowlist():
    settings = RagflowSettings(base_url="http://ragflow", api_key="key", enable_real_sync=True, sync_allow_dataset_ids=frozenset({"dataset-test"}))
    adapter = HttpRagflowAdapter(settings, FakeRagflowClient())

    with pytest.raises(RagflowAdapterError, match="not allowlisted"):
        adapter.upload_document("dataset-other", "clip.md", "body", dry_run=False)


def test_real_sync_uploads_one_document_then_writes_meta_fields():
    client = FakeRagflowClient()
    settings = RagflowSettings(base_url="http://ragflow", api_key="key", enable_real_sync=True, sync_allow_dataset_ids=frozenset({"dataset-test"}))
    adapter = HttpRagflowAdapter(settings, client)

    document = adapter.upload_document("dataset-test", "clip.md", "body", {"language": "en"}, dry_run=False)
    result = adapter.update_document_meta("dataset-test", document.document_id, {"language": "en"}, dry_run=False)

    assert document.document_id == "doc-created"
    assert document.dry_run is False
    assert client.uploads == [("http://ragflow", "key", "dataset-test", "clip.md", b"body")]
    assert client.meta_updates == [("http://ragflow", "key", "dataset-test", "doc-created", {"language": "en"})]
    assert result["remote_document_changed"] is True


def test_real_sync_reads_document_path_instead_of_uploading_path_text(tmp_path):
    document_path = tmp_path / "clip.md"
    document_path.write_text("actual document body", encoding="utf-8")
    client = FakeRagflowClient()
    settings = RagflowSettings(
        base_url="http://ragflow",
        api_key="key",
        enable_real_sync=True,
        sync_allow_dataset_ids=frozenset({"dataset-test"}),
    )
    adapter = HttpRagflowAdapter(settings, client)

    adapter.upload_document("dataset-test", "clip.md", str(document_path), dry_run=False)

    assert client.uploads[0][-1] == b"actual document body"
    assert str(document_path).encode() not in client.uploads[0][-1]


def test_real_sync_adapter_exposes_parse_status_chunk_vector_and_delete_contract():
    client = FakeRagflowClient()
    client.documents = [
        {
            "id": "doc-created",
            "run": 3,
            "meta_fields": {"operation_key": "operation", "content_hash": "hash"},
        },
        {
            "id": "doc-other",
            "run": "running",
            "meta_fields": {"operation_key": "other"},
        },
    ]
    client.chunks = [{"id": "chunk-1", "has_vector": True}]
    settings = RagflowSettings(
        base_url="http://ragflow",
        api_key="key",
        enable_real_sync=True,
        sync_allow_dataset_ids=frozenset({"dataset-test"}),
    )
    adapter = HttpRagflowAdapter(settings, client)

    matches = adapter.find_document_by_operation_key("dataset-test", "operation")
    adapter.request_parse("dataset-test", "doc-created")
    status = adapter.get_document_status("dataset-test", "doc-created")
    chunks = adapter.get_chunk_summary("dataset-test", "doc-created")
    vectors = adapter.get_vector_evidence("dataset-test", "doc-created")

    assert [match.document_id for match in matches] == ["doc-created"]
    assert status.status == "done"
    assert chunks.chunk_count == 1
    assert vectors.vector_count == 1
    assert client.parse_requests == [("dataset-test", "doc-created")]

    adapter.request_delete("dataset-test", "doc-created")
    deleted_status, deleted_chunks, deleted_vectors = adapter.verify_deleted(
        "dataset-test", "doc-created"
    )
    assert deleted_status.status == "missing"
    assert deleted_chunks.chunk_count == 0
    assert deleted_vectors.vector_count == 0


def test_available_is_not_vector_evidence_and_public_api_fails_closed():
    client = FakeRagflowClient()
    client.chunks = [{"id": "chunk-1", "available": True}]
    settings = RagflowSettings(
        base_url="http://ragflow",
        api_key="key",
        enable_real_sync=True,
        sync_allow_dataset_ids=frozenset({"dataset-test"}),
    )
    adapter = HttpRagflowAdapter(settings, client)

    assert adapter.get_chunk_summary("dataset-test", "doc-created").chunk_count == 1
    with pytest.raises(RagflowUnsupportedError, match="explicit vector evidence"):
        adapter.get_vector_evidence("dataset-test", "doc-created")


def test_vector_evidence_paginates_every_chunk():
    client = FakeRagflowClient()
    client.chunks = [
        {"id": f"chunk-{index}", "has_vector": True} for index in range(101)
    ]
    settings = RagflowSettings(
        base_url="http://ragflow",
        api_key="key",
        enable_real_sync=True,
        sync_allow_dataset_ids=frozenset({"dataset-test"}),
    )
    adapter = HttpRagflowAdapter(settings, client)

    evidence = adapter.get_vector_evidence("dataset-test", "doc-created")
    assert evidence.vector_count == evidence.covered_chunk_count == 101


def test_total_only_or_first_page_only_chunk_api_is_not_complete_evidence():
    settings = RagflowSettings(
        base_url="http://ragflow",
        api_key="key",
        enable_real_sync=True,
        sync_allow_dataset_ids=frozenset({"dataset-test"}),
    )
    total_only = FakeRagflowClient()
    total_only.chunk_total = 10
    total_only.total_only = True
    with pytest.raises(RagflowUnsupportedError, match="pagination"):
        HttpRagflowAdapter(settings, total_only).get_vector_evidence(
            "dataset-test", "doc-created"
        )

    first_page_only = FakeRagflowClient()
    first_page_only.chunk_total = 101
    first_page_only.chunks = [
        {"id": f"chunk-{index}", "has_vector": True} for index in range(100)
    ]
    with pytest.raises(RagflowUnsupportedError, match="pagination"):
        HttpRagflowAdapter(settings, first_page_only).get_vector_evidence(
            "dataset-test", "doc-created"
        )


def test_document_status_preserves_numeric_zero_as_unstart():
    client = FakeRagflowClient()
    client.documents = [{"id": "doc-zero", "run": 0, "meta_fields": {}}]
    settings = RagflowSettings(
        base_url="http://ragflow",
        api_key="key",
        enable_real_sync=True,
        sync_allow_dataset_ids=frozenset({"dataset-test"}),
    )
    adapter = HttpRagflowAdapter(settings, client)

    assert adapter.get_document_status("dataset-test", "doc-zero").status == "unstart"


def test_exact_document_not_found_response_maps_to_missing_only_for_status_lookup(
    monkeypatch,
):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {"code": 102, "message": "You don't own the document doc-gone."}
            ).encode()

    monkeypatch.setattr(
        ragflow_adapter_module, "urlopen", lambda *_args, **_kwargs: Response()
    )
    client = UrlLibRagflowHttpClient()

    assert client.get_document(
        "http://ragflow", "key", "dataset-test", "doc-gone"
    ) == {"data": {"docs": [], "total": 0}}
    with pytest.raises(RagflowAdapterError, match="rejected"):
        client.find_documents(
            "http://ragflow", "key", "dataset-test", "operation"
        )


def test_repeated_delete_treats_exact_document_not_found_as_idempotent(
    monkeypatch,
):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {
                    "code": 102,
                    "message": (
                        "These documents do not belong to dataset dataset-test "
                        "or Document not found: doc-gone"
                    ),
                }
            ).encode()

    monkeypatch.setattr(
        ragflow_adapter_module, "urlopen", lambda *_args, **_kwargs: Response()
    )

    assert UrlLibRagflowHttpClient().delete_document(
        "http://ragflow", "key", "dataset-test", "doc-gone"
    ) == {"code": 0, "data": None}
