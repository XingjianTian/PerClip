from __future__ import annotations

from perclip_ingest.ingest_adapters import json_envelope_to_command
from perclip_ingest.ingest_service import request_signature
from tests.test_ingest_v1_json import envelope


def test_request_signature_is_deterministic_and_excludes_original_text():
    command = json_envelope_to_command(envelope())
    first = request_signature(command)
    second = request_signature(command)
    assert first == second
    assert len(first) == 64
    assert "示例内容" not in first


def test_request_signature_changes_for_contract_identity_capture_routing_and_content():
    base = request_signature(json_envelope_to_command(envelope()))
    variants = []
    for mutate in (
        lambda body: body["source"].update(event_id="event-other"),
        lambda body: body["capture"].update(source_intent="manual"),
        lambda body: body["routing"].update(target_knowledge_base_id="kb_default"),
        lambda body: body["clip"].update(text="other"),
    ):
        body = envelope(); mutate(body); variants.append(request_signature(json_envelope_to_command(body)))
    assert all(value != base for value in variants)


def test_request_signature_is_canonical_for_dict_order_optional_empty_and_timestamp_offset():
    first = envelope()
    second = envelope()
    second["clip"]["captured_at"] = "2026-07-12T02:00:00Z"
    second["source"] = dict(reversed(list(second["source"].items())))
    second["capture"] = dict(reversed(list(second["capture"].items())))
    assert request_signature(json_envelope_to_command(first)) == request_signature(json_envelope_to_command(second))

    explicit_empty = envelope()
    minimal = envelope()
    for key in ("account_hint", "source_app"):
        minimal["source"].pop(key)
        explicit_empty["source"][key] = ""
    assert request_signature(json_envelope_to_command(minimal)) == request_signature(json_envelope_to_command(explicit_empty))
