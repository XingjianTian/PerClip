from __future__ import annotations

from perclip_ingest.metadata_contract import (
    CONTRACT_VERSION,
    NormalizedMetadataInput,
    build_normalized_metadata,
    dumps_normalized_metadata,
    loads_normalized_metadata,
)


def input_payload(**overrides) -> NormalizedMetadataInput:
    values = {
        "source_type": "text",
        "title_hint": "Title",
        "note": "note",
        "text": "body",
        "url": "",
        "mime_type": "text/plain",
        "device_name": "Pixel PerClip",
        "source_app": "Browser",
        "captured_at": "2026-07-09T10:00:00Z",
        "client_request_id": "clip-1:",
        "filename": "clip.txt",
        "has_file": False,
        "size_bytes": 4,
        "content_hash": "abc123",
        "storage_uri": "/tmp/personal/clip.txt",
        "received_at": "2026-07-09T10:00:01Z",
        "archive_status": "local",
        "ragflow_document_id": "",
    }
    values.update(overrides)
    return NormalizedMetadataInput(**values)


def test_text_clip_normalized_metadata():
    metadata = build_normalized_metadata(
        input_payload(
            filename="",
            client_request_id="text-1:",
            text="PerClip text",
            url="",
            note="",
            size_bytes=len("PerClip text".encode()),
        )
    )

    assert metadata["contract_version"] == CONTRACT_VERSION
    assert metadata["clip"]["clip_id"] == "text-1"
    assert metadata["clip"]["source_type"] == "text"
    assert metadata["clip"]["text"] == "PerClip text"
    assert metadata["provenance"]["launcher_type"] == "android"
    assert metadata["provenance"]["capture_method"] == "share_sheet"
    assert metadata["assets"][0]["role"] == "original"
    assert metadata["assets"][0]["text"] == "PerClip text"
    assert metadata["processing"]["archive_status"] == "local"
    assert metadata["security"]["auth_context"] == {
        "method": "mobile_ingest_token",
        "verified": True,
    }


def test_provenance_preserves_non_android_adapter_identity():
    metadata = build_normalized_metadata(
        input_payload(
            source_adapter="wechat_bot",
            source_client_id="langbot-main",
            source_event_id="event-42",
            source_app="WeChat",
        )
    )

    assert metadata["provenance"]["launcher_type"] == "wechat_bot"
    assert metadata["provenance"]["launcher_id"] == "langbot-main"
    assert metadata["provenance"]["source_message_id"] == "event-42"
    assert metadata["security"]["auth_context"]["method"] == "connector_ingest_token"


def test_url_clip_normalized_metadata():
    metadata = build_normalized_metadata(
        input_payload(
            source_type="url",
            filename="",
            client_request_id="url-1:",
            text="Example title",
            url="https://example.com/a",
            size_bytes=len("Example title".encode()),
        )
    )

    assert metadata["clip"]["source_type"] == "url"
    assert metadata["clip"]["url"] == "https://example.com/a"
    assert metadata["provenance"]["source_url"] == "https://example.com/a"
    assert metadata["assets"][0]["text"] == "Example title"


def test_file_upload_normalized_metadata():
    metadata = build_normalized_metadata(
        input_payload(
            source_type="file",
            filename="demo.pdf",
            has_file=True,
            mime_type="application/pdf",
            size_bytes=11,
            text="",
            note="",
            content_hash="f" * 64,
            storage_uri="/personalclips/demo.pdf",
        )
    )

    asset = metadata["assets"][0]
    assert asset["role"] == "original"
    assert asset["filename"] == "demo.pdf"
    assert asset["mime_type"] == "application/pdf"
    assert asset["size_bytes"] == 11
    assert asset["content_hash"] == "f" * 64
    assert asset["storage_uri"] == "/personalclips/demo.pdf"
    assert asset["text"] == ""


def test_screen_clip_normalized_metadata():
    metadata = build_normalized_metadata(
        input_payload(
            source_type="screen_clip",
            filename="",
            text="来源：Example App\nscreen body",
            source_app="Example App",
        )
    )

    assert metadata["clip"]["source_type"] == "screen_clip"
    assert metadata["provenance"]["capture_method"] == "accessibility"
    assert metadata["assets"][0]["role"] == "screenshot"
    assert metadata["assets"][0]["text"] == "来源：Example App\nscreen body"


def test_clip_to_ragflow_metadata_uses_capability_label_not_secret():
    metadata = build_normalized_metadata(
        input_payload(
            archive_status="clip_to_ragflow",
            ragflow_document_id="doc-1",
            storage_uri="/personalclips/doc.md",
        )
    )

    assert metadata["processing"]["ragflow_document_id"] == "doc-1"
    assert metadata["security"]["credential_scope"] == ["ragflow:personalclips"]


def test_metadata_serialization_is_stable_and_secret_free():
    metadata = build_normalized_metadata(input_payload(note=""))
    encoded = dumps_normalized_metadata(metadata)
    decoded = loads_normalized_metadata(encoded)

    assert decoded == metadata
    assert encoded == dumps_normalized_metadata(metadata)
    assert "secret-mobile-token" not in encoded
    assert "fake-asr-secret-value" not in encoded
    assert "change-me-server-side-ragflow-key" not in encoded


def test_capture_section_is_safe_deterministic_and_old_metadata_still_loads():
    metadata = build_normalized_metadata(
        input_payload(
            filename="../../private/report.pdf",
            client_batch_id="batch-1",
            parent_client_request_id="parent-1:",
            part_index=1,
            part_count=3,
            part_role="file",
            source_intent="share",
            captured_timezone="Asia/Shanghai",
            content_fingerprint="a" * 64,
        )
    )
    assert metadata["capture"] == {
        "client_batch_id": "batch-1", "parent_client_request_id": "parent-1:",
        "part_index": 1, "part_count": 3, "part_role": "file",
        "original_filename": "report.pdf", "original_mime_type": "text/plain",
        "source_intent": "share", "captured_timezone": "Asia/Shanghai",
        "content_fingerprint": "a" * 64,
    }
    assert dumps_normalized_metadata(metadata) == dumps_normalized_metadata(metadata)
    legacy = {key: value for key, value in metadata.items() if key != "capture"}
    assert loads_normalized_metadata(dumps_normalized_metadata(legacy)) == legacy


def test_invalid_capture_section_is_rejected_and_unknown_fingerprint_is_normalized():
    metadata = build_normalized_metadata(input_payload(content_fingerprint="/Users/local/secret"))
    assert metadata["capture"]["content_fingerprint"] == ""
    invalid = build_normalized_metadata(input_payload())
    invalid["capture"] = {"part_index": 2, "part_count": 1}
    try:
        loads_normalized_metadata(dumps_normalized_metadata(invalid))
    except ValueError as error:
        assert "part index/count" in str(error)
    else:
        raise AssertionError("invalid capture section must be rejected")
