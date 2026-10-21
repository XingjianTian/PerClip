from __future__ import annotations

from perclip_ingest.mime_policy import is_allowed_mime_type, normalize_mime_type


def test_normalizes_mime_parameters_and_case():
    assert normalize_mime_type("Text/Plain; charset=utf-8") == "text/plain"


def test_allows_expected_mobile_clip_mime_types():
    assert is_allowed_mime_type("text/plain")
    assert is_allowed_mime_type("image/jpeg")
    assert is_allowed_mime_type("audio/mp4")
    assert is_allowed_mime_type("audio/aac")
    assert is_allowed_mime_type("application/pdf")
    assert is_allowed_mime_type("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert is_allowed_mime_type("application/octet-stream")


def test_rejects_executable_mime_types():
    assert not is_allowed_mime_type("application/x-msdownload")
    assert not is_allowed_mime_type("application/x-sh")
