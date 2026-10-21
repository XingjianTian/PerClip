from datetime import datetime

import pytest

from integrations.wechat_bridge.errors import MappingError, UnsupportedEventError
from integrations.wechat_bridge.mapping import WechatIngestMapper
from integrations.wechat_bridge.models import (
    WechatFileEvent, WechatImageEvent, WechatLinkEvent, WechatTextEvent, WechatUnsupportedEvent,
)


NOW = datetime.fromisoformat("2026-07-12T10:00:00+08:00")


def mapper(): return WechatIngestMapper("prod_main", "")


@pytest.mark.parametrize("event,source,multipart,mime", [
    (WechatTextEvent(event_id="m 1", occurred_at=NOW, timezone="Asia/Shanghai", text="hello"), "text", False, "text/plain"),
    (WechatLinkEvent(event_id="m 2", occurred_at=NOW, timezone="Asia/Shanghai", url="https://example.com/a"), "url", False, "text/uri-list"),
    (WechatImageEvent(event_id="m 3", occurred_at=NOW, timezone="Asia/Shanghai", filename="../photo.jpg", mime_type="image/jpeg"), "image", True, "image/jpeg"),
    (WechatFileEvent(event_id="m 4", occurred_at=NOW, timezone="Asia/Shanghai", filename=r"C:\private\note.pdf", mime_type="application/pdf"), "file", True, "application/pdf"),
])
def test_stable_identity_and_mapping(event, source, multipart, mime):
    first = mapper().map(event); second = mapper().map(event)
    assert first == second
    assert first.client_request_id == f"wechat:prod_main:{event.event_id.replace(' ', '-')}"
    assert first.multipart is multipart
    assert first.envelope["clip"]["source_type"] == source
    assert first.envelope["clip"]["mime_type"] == mime
    assert first.envelope["source"]["adapter"] == "wechat_bot"
    assert first.envelope["source"]["source_app"] == "WeChat"
    assert first.envelope["clip"]["captured_at"] == "2026-07-12T02:00:00Z"
    assert first.envelope["clip"]["captured_timezone"] == "Asia/Shanghai"


def test_identity_does_not_depend_on_content_hints_or_receive_time():
    a = WechatTextEvent(event_id="stable", occurred_at=NOW, timezone="Asia/Shanghai", text="one", sender_hint="A")
    b = WechatTextEvent(event_id="stable", occurred_at=NOW, timezone="Asia/Shanghai", text="two", sender_hint="B")
    assert mapper().client_request_id(a) == mapper().client_request_id(b)
    redacted = WechatTextEvent(event_id="stable", occurred_at=NOW, timezone="Asia/Shanghai", text="x", sender_hint="wxid_private")
    assert mapper().map(redacted).envelope["source"]["account_hint"] == ""


def test_batch_uses_zero_based_capture_identity():
    event = WechatFileEvent(event_id="part-1", parent_event_id="parent", part_index=1, part_count=2,
                            occurred_at=NOW, timezone="Asia/Shanghai", filename="a.pdf", mime_type="application/pdf")
    mapped = mapper().map(event)
    assert mapped.client_request_id == "wechat:prod_main:parent:part:1"
    capture = mapped.envelope["capture"]
    assert capture == {"client_batch_id": "batch:prod_main:parent", "parent_client_request_id": "wechat:prod_main:parent",
                       "part_index": 1, "part_count": 2, "part_role": "file", "source_intent": "share",
                       "content_fingerprint": ""}


def test_three_part_identity_is_stable_and_unique():
    mapped = []
    for index in range(3):
        event = WechatFileEvent(event_id=f"common-event-{index}", parent_event_id="parent", part_index=index,
                                part_count=3, occurred_at=NOW, timezone="Asia/Shanghai",
                                filename=f"part-{index}.pdf", mime_type="application/pdf")
        mapped.append(mapper().map(event))
    assert [item.client_request_id for item in mapped] == [
        "wechat:prod_main:parent:part:0", "wechat:prod_main:parent:part:1",
        "wechat:prod_main:parent:part:2",
    ]
    assert mapper().map(WechatFileEvent(event_id="changed-metadata", parent_event_id="parent", part_index=1,
                                       part_count=3, occurred_at=NOW, timezone="Asia/Shanghai",
                                       filename="changed.pdf", mime_type="application/pdf")).client_request_id == mapped[1].client_request_id


def test_multipart_requires_parent_event_id():
    event = WechatFileEvent(event_id="common", part_index=0, part_count=2, occurred_at=NOW,
                            timezone="Asia/Shanghai", filename="a.pdf", mime_type="application/pdf")
    with pytest.raises(MappingError): mapper().map(event)


@pytest.mark.parametrize("event", [
    WechatLinkEvent(event_id="x", occurred_at=NOW, timezone="Asia/Shanghai", url="file:///etc/passwd"),
    WechatLinkEvent(event_id="x", occurred_at=NOW, timezone="Asia/Shanghai", url="data:text/plain;base64,WA=="),
    WechatTextEvent(event_id="x", occurred_at=NOW, timezone="Asia/Shanghai", text="data:text/plain;base64,WA=="),
    WechatImageEvent(event_id="x", occurred_at=NOW, timezone="Asia/Shanghai", mime_type="application/pdf"),
])
def test_rejects_url_base64_and_bad_mime(event):
    with pytest.raises(MappingError): mapper().map(event)


def test_filename_basename_and_controlled_fallback():
    image = WechatImageEvent(event_id="x", occurred_at=NOW, timezone="Asia/Shanghai", filename="../../secret.png", mime_type="")
    assert mapper().filename_for(image) == "secret.png"
    assert mapper().map(image).envelope["clip"]["mime_type"] == "image/jpeg"


def test_unsupported_is_explicit_and_raw_object_not_projected():
    event = WechatUnsupportedEvent(event_id="x", occurred_at=NOW, timezone="Asia/Shanghai", media_reference=object(), unsupported_type="voice")
    with pytest.raises(UnsupportedEventError): mapper().map(event)
    assert "media_reference" not in repr(event)


def test_invalid_timezone_and_naive_time_rejected():
    with pytest.raises(MappingError): mapper().map(WechatTextEvent(event_id="x", occurred_at=NOW, timezone="Mars/Base", text="x"))
    with pytest.raises(MappingError): mapper().map(WechatTextEvent(event_id="x", occurred_at=datetime(2026, 1, 1), timezone="UTC", text="x"))
