from __future__ import annotations

import zipfile
from io import BytesIO

from perclip_ingest.content_cleaning import clean_content
from perclip_ingest import file_extraction
from perclip_ingest.file_extraction import extract_file_text


def zip_payload(files: dict[str, str]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_extracts_utf8_and_gb18030_text_without_external_dependency():
    utf8 = extract_file_text("note.md", "第一行\nSecond".encode())
    gb = extract_file_text("note.txt", "中文内容".encode("gb18030"))

    assert utf8.text == "第一行\nSecond"
    assert gb.text == "中文内容"
    assert utf8.status == gb.status == "completed:text"


def test_extracts_docx_paragraphs_from_open_xml():
    payload = zip_payload(
        {
            "word/document.xml": """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>Alpha</w:t></w:r><w:r><w:t> Beta</w:t></w:r></w:p></w:body>
            </w:document>
            """
        }
    )

    result = extract_file_text("sample.docx", payload)

    assert result.text == "Alpha Beta"
    assert result.status == "completed:docx"


def test_broken_container_returns_safe_status_without_exception_details():
    result = extract_file_text("broken.docx", b"not a zip")

    assert result.status == "failed"
    assert result.text == ""
    assert result.safe_error_code == "file_extract_failed"
    assert "BadZipFile" not in result.status


def test_office_archive_budget_blocks_oversized_uncompressed_entry(monkeypatch):
    monkeypatch.setattr(file_extraction, "MAX_ZIP_ENTRY_BYTES", 8)
    payload = zip_payload({"word/document.xml": "123456789"})

    result = extract_file_text("oversized.docx", payload)

    assert result.status == "failed"
    assert result.text == ""
    assert result.status != "completed:docx"


def test_cleaner_removes_navigation_legal_tail_and_duplicate_lines():
    result = clean_content(
        "首页\nUseful body\nUseful body\n沪ICP备 123456号\nMore useful detail"
    )

    assert result.text == "Useful body\n\nMore useful detail"
    assert result.removed_count == 3
    assert result.engine_version == "v4"


def test_cleaner_preserves_section_numbering_and_unrelated_numbers():
    source = "第1节 开始\n第一节 保持\n编号 12\n日期 2026-07-22\n版本 3.14"

    result = clean_content(source)

    assert result.text.split("\n\n") == source.splitlines()


def test_cleaner_redacts_only_explicit_secret_values_and_is_idempotent():
    source = "\n".join(
        [
            "OAuth token rotation policy",
            "secret management best practices",
            "cookie security model",
            "authorization design",
            "passwordless authentication",
            "Basic authentication security",
            "JSON 中 token 字段的设计",
            "Authorization: Bearer actual-token-value",
            "Authorization: Basic c3ludGhldGljLWJhc2lj",
            "Authorization: Token synthetic-header-token",
            "Authorization: ApiKey synthetic-header-key",
            '"token": "synthetic-json-token"',
            "'api_key': 'synthetic-json-key'",
            "secret: synthetic-yaml-secret",
            "API_KEY=synthetic-env-key",
            "token: [redacted]",
            '"password": "[redacted]"',
            "```python",
            "policy = 'ordinary code'",
            "password=actual-password",
            "```",
        ]
    )

    once = clean_content(source)
    twice = clean_content(once.text)

    for sentence in (
        "OAuth token rotation policy",
        "secret management best practices",
        "cookie security model",
        "authorization design",
        "passwordless authentication",
        "Basic authentication security",
        "JSON 中 token 字段的设计",
        "policy = 'ordinary code'",
    ):
        assert sentence in once.text
    assert "Authorization: Bearer [redacted]" in once.text
    assert "Authorization: Basic [redacted]" in once.text
    assert "Authorization: Token [redacted]" in once.text
    assert "Authorization: ApiKey [redacted]" in once.text
    assert '"token": "[redacted]"' in once.text
    assert "'api_key': '[redacted]'" in once.text
    assert "secret: [redacted]" in once.text
    assert "API_KEY=[redacted]" in once.text
    assert "token: [redacted]" in once.text
    assert '"password": "[redacted]"' in once.text
    assert "password=[redacted]" in once.text
    assert twice.text == once.text


def test_unknown_binary_never_uses_printable_run_fallback():
    result = extract_file_text(
        "unsupported.bin",
        b"PERCLIP_SYNTHETIC_UNSUPPORTED_BINARY printable payload",
        "application/octet-stream",
    )

    assert result.status == "failed"
    assert result.safe_error_code == "unsupported_media_type"
    assert result.text == ""
