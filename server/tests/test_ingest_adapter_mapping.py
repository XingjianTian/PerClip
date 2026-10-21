from __future__ import annotations

import copy

import pytest

from perclip_ingest.ingest_adapters import (
    AdapterValidationError,
    json_envelope_to_command,
    mobile_form_to_command,
    multipart_envelope_to_command,
)


def envelope(source_type: str = "text") -> dict[str, object]:
    return {
        "contract_version": "perclip.ingest.v1",
        "client_request_id": "wechat:message:123",
        "source": {
            "adapter": "wechat_bot",
            "client_id": "bot-main",
            "event_id": "message-123",
            "source_app": "WeChat",
            "account_hint": "masked-account",
        },
        "clip": {
            "source_type": source_type,
            "title_hint": " title ",
            "note": " note ",
            "text": "body" if source_type == "text" else "",
            "url": "",
            "mime_type": "text/plain" if source_type == "text" else "image/png",
            "captured_at": "2026-07-12T10:00:00+08:00",
            "captured_timezone": "Asia/Shanghai",
            "device_name": "",
        },
        "capture": {
            "client_batch_id": "",
            "parent_client_request_id": "",
            "part_index": 0,
            "part_count": 1,
            "part_role": "single",
            "source_intent": "share",
            "content_fingerprint": "",
        },
        "routing": {"target_knowledge_base_id": "kb-personal"},
    }


def test_json_adapter_is_pure_and_maps_nested_fields():
    source = envelope()
    original = copy.deepcopy(source)

    command = json_envelope_to_command(source)

    assert source == original
    assert command.replay_policy == "strict_v1"
    assert command.source.adapter == "wechat_bot"
    assert command.source.event_id == "message-123"
    assert command.clip.title_hint == "title"
    assert command.clip.note == "note"
    assert command.clip.text == "body"
    assert command.clip.captured_timezone == "Asia/Shanghai"
    assert command.capture.source_intent == "share"
    assert command.routing.target_knowledge_base_id == "kb-personal"
    assert command.asset is None


def test_json_adapter_maps_default_only_with_capture_time_target():
    source = envelope()
    source["routing"]["mode"] = "default_only"  # type: ignore[index]

    command = json_envelope_to_command(source)

    assert command.routing.mode == "default_only"
    assert command.routing.target_knowledge_base_id == "kb-personal"


def test_json_adapter_canonicalizes_equivalent_timestamps_and_validates_timezone():
    first = envelope()
    second = envelope()
    first["clip"]["captured_at"] = "2026-07-12T10:00:00+08:00"  # type: ignore[index]
    second["clip"]["captured_at"] = "2026-07-12T02:00:00Z"  # type: ignore[index]

    first_command = json_envelope_to_command(first)
    second_command = json_envelope_to_command(second)

    assert first_command.clip.captured_at == second_command.clip.captured_at == "2026-07-12T02:00:00Z"
    invalid = envelope()
    invalid["clip"]["captured_timezone"] = "Mars/Olympus"  # type: ignore[index]
    with pytest.raises(AdapterValidationError, match="invalid captured_timezone"):
        json_envelope_to_command(invalid)


@pytest.mark.parametrize("field", ["captured_at", "captured_timezone"])
def test_strict_adapter_requires_capture_time_and_timezone(field):
    invalid = envelope()
    invalid["clip"][field] = ""  # type: ignore[index]
    with pytest.raises(AdapterValidationError, match=f"{field} is required"):
        json_envelope_to_command(invalid)


@pytest.mark.parametrize(
    "path,value",
    [
        (("unexpected",), True),
        (("source", "unexpected"), True),
        (("clip", "unexpected"), True),
        (("capture", "unexpected"), True),
        (("routing", "unexpected"), True),
    ],
)
def test_json_adapter_rejects_unknown_fields(path, value):
    source = envelope()
    target = source
    for key in path[:-1]:
        target = target[key]  # type: ignore[index,assignment]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(AdapterValidationError, match="unknown"):
        json_envelope_to_command(source)


@pytest.mark.parametrize("field", ["text", "note", "url"])
@pytest.mark.parametrize("encoded", ["data:text/plain,hello", "base64,c2VjcmV0"])
def test_json_adapter_rejects_encoded_payload(field, encoded):
    source = envelope()
    source["clip"][field] = encoded  # type: ignore[index]

    with pytest.raises(AdapterValidationError, match="encoded payload"):
        json_envelope_to_command(source)


def test_multipart_adapter_maps_filename_mime_and_bytes_without_mutating_envelope():
    source = envelope("image")
    original = copy.deepcopy(source)
    payload = b"\x89PNG\r\n"

    command = multipart_envelope_to_command(
        source, filename="../camera.png", mime_type="image/png", payload=payload
    )

    assert source == original
    assert command.asset is not None
    assert command.asset.filename == "../camera.png"
    assert command.asset.mime_type == "image/png"
    assert command.asset.payload is payload


def test_multipart_adapter_rejects_non_binary_source_type():
    with pytest.raises(AdapterValidationError, match="must be binary"):
        multipart_envelope_to_command(
            envelope(), filename="note.txt", mime_type="text/plain", payload=b"body"
        )


def test_mobile_adapter_maps_legacy_policy_and_file_asset():
    command = mobile_form_to_command(
        source_type="file",
        client_request_id="android:123",
        filename="report.pdf",
        file_mime_type="application/pdf",
        payload=b"pdf",
        client_batch_id="batch-1",
        parent_client_request_id="parent:1",
        client_part_index=0,
        client_part_count=1,
        part_role="file",
    )

    assert command.source.adapter == "android"
    assert command.replay_policy == "legacy_mobile"
    assert command.asset is not None
    assert command.asset.filename == "report.pdf"
    assert command.asset.payload == b"pdf"
    assert command.capture.client_batch_id == "batch-1"
