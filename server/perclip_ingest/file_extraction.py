from __future__ import annotations

import re
import string
import zlib
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET


MAX_ZIP_ENTRIES = 2048
MAX_ZIP_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_ZIP_ENTRY_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class FileExtractionResult:
    text: str
    status: str
    engine: str = "perclip-file-extractor"
    engine_version: str = "v2"
    safe_error_code: str = ""
    quality_reason: str = ""


def extract_file_text(filename: str, payload: bytes, mime_type: str = "") -> FileExtractionResult:
    suffix = Path(filename or "").suffix.lower()
    try:
        if suffix in {".md", ".markdown", ".txt", ".csv", ".json", ".log"}:
            return FileExtractionResult(_decode_text(payload), "completed:text")
        if suffix in {".docx", ".docm"}:
            return FileExtractionResult(_extract_docx(payload), "completed:docx")
        if suffix in {".xlsx", ".xlsm"}:
            return FileExtractionResult(_extract_xlsx(payload), "completed:xlsx")
        if suffix in {".pptx", ".pptm"}:
            return FileExtractionResult(_extract_pptx(payload), "completed:pptx")
        if suffix == ".pdf":
            return FileExtractionResult(_extract_pdf(payload), "completed:pdf")
        if suffix == ".rtf":
            return FileExtractionResult(_extract_legacy_text(payload), "partial:legacy")
        if suffix in {".doc", ".ppt"}:
            return FileExtractionResult(
                "",
                "failed",
                safe_error_code="unsupported_media_type",
                quality_reason="unsupported_legacy_binary",
            )
        return FileExtractionResult(
            "",
            "failed",
            safe_error_code="unsupported_media_type",
            quality_reason=f"unsupported_binary:{suffix.lstrip('.') or mime_type or 'unknown'}",
        )
    except (KeyError, OSError, ValueError, zipfile.BadZipFile, ET.ParseError, zlib.error):
        if suffix == ".rtf":
            fallback = _extract_legacy_text(payload)
            return FileExtractionResult(
                fallback,
                "partial:fallback" if fallback else "failed",
                safe_error_code="" if fallback else "file_extract_failed",
                quality_reason="rtf_safe_fallback" if fallback else "no_usable_body",
            )
        return FileExtractionResult(
            "",
            "failed",
            safe_error_code="file_extract_failed",
            quality_reason="structured_extraction_failed",
        )


def _decode_text(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return _compact(payload.decode(encoding))
        except UnicodeDecodeError:
            continue
    return _compact(payload.decode("utf-8", errors="ignore"))


def _extract_docx(payload: bytes) -> str:
    with _validated_zip(payload) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraphs: list[str] = []
    for paragraph in root.iter(_qualified("w:p")):
        text = "".join(node.text or "" for node in paragraph.iter(_qualified("w:t"))).strip()
        if text:
            paragraphs.append(text)
    return _compact("\n".join(paragraphs))


def _extract_xlsx(payload: bytes) -> str:
    with _validated_zip(payload) as archive:
        shared = _xlsx_shared_strings(archive)
        rows: list[str] = []
        sheets = sorted(
            name for name in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
        )
        for name in sheets:
            root = ET.fromstring(archive.read(name))
            for row in root.iter(_qualified("x:row")):
                cells = [_xlsx_cell_text(cell, shared) for cell in row.iter(_qualified("x:c"))]
                value = "\t".join(cell for cell in cells if cell).strip()
                if value:
                    rows.append(value)
    return _compact("\n".join(rows))


def _extract_pptx(payload: bytes) -> str:
    with _validated_zip(payload) as archive:
        names = sorted(
            (name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
            key=lambda name: int(re.search(r"slide(\d+)\.xml$", name).group(1)),  # type: ignore[union-attr]
        )
        slides: list[str] = []
        for name in names:
            root = ET.fromstring(archive.read(name))
            text = " ".join(
                (node.text or "").strip() for node in root.iter(_qualified("a:t")) if (node.text or "").strip()
            )
            if text:
                slides.append(text)
    return _compact("\n".join(slides))


def _extract_pdf(payload: bytes) -> str:
    values: list[str] = []
    for stream in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", payload, flags=re.S):
        decoded = stream
        for candidate in (stream, stream.strip(b"\r\n")):
            try:
                decoded = zlib.decompress(candidate)
                break
            except zlib.error:
                continue
        text = decoded.decode("latin-1", errors="ignore")
        for raw in re.findall(r"\((?:\\.|[^\\)])*\)\s*Tj", text):
            values.append(_pdf_unescape(raw[1 : raw.rfind(")")]))
        for array in re.findall(r"\[(.*?)\]\s*TJ", text, flags=re.S):
            values.extend(_pdf_unescape(raw[1:-1]) for raw in re.findall(r"\((?:\\.|[^\\)])*\)", array))
    return _compact("\n".join(value for value in values if value.strip())) or _extract_legacy_text(payload)


def _extract_legacy_text(payload: bytes) -> str:
    decoded = _decode_text(payload)
    if decoded.startswith("{\\rtf"):
        decoded = re.sub(r"\\'[0-9a-fA-F]{2}", " ", decoded)
        decoded = re.sub(r"\\[a-zA-Z]+\d* ?", " ", decoded)
        return _compact(decoded.replace("{", " ").replace("}", " ").replace("\\", " "))
    runs = re.findall(rb"[\x09\x0a\x0d\x20-\x7e]{4,}", payload)
    if runs:
        return _compact("\n".join(run.decode("latin-1", errors="ignore") for run in runs))
    return decoded


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.iter(_qualified("x:t"))) for item in root.iter(_qualified("x:si"))]


def _validated_zip(payload: bytes) -> zipfile.ZipFile:
    archive = zipfile.ZipFile(BytesIO(payload))
    entries = archive.infolist()
    if (
        len(entries) > MAX_ZIP_ENTRIES
        or sum(entry.file_size for entry in entries) > MAX_ZIP_UNCOMPRESSED_BYTES
        or any(entry.file_size > MAX_ZIP_ENTRY_BYTES for entry in entries)
    ):
        archive.close()
        raise ValueError("office archive exceeds extraction budget")
    return archive


def _xlsx_cell_text(cell: ET.Element, shared: list[str]) -> str:
    if cell.attrib.get("t", "") == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(_qualified("x:t"))).strip()
    value = cell.find(_qualified("x:v"))
    if value is None or value.text is None:
        return ""
    raw = value.text.strip()
    if cell.attrib.get("t", "") == "s":
        try:
            return shared[int(raw)].strip()
        except (IndexError, ValueError):
            return raw
    return raw


def _pdf_unescape(value: str) -> str:
    return (
        value.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
        .replace(r"\n", "\n").replace(r"\r", "\n").replace(r"\t", "\t")
    )


def _qualified(name: str) -> str:
    namespaces = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    }
    prefix, tag = name.split(":", 1)
    return f"{{{namespaces[prefix]}}}{tag}"


def _compact(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.replace("\x00", " ").splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return "".join(char for char in cleaned if char in string.printable or ord(char) > 127).strip()
