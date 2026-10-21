from __future__ import annotations

import re
from dataclasses import dataclass

from .secret_redaction import redact_structured_secret_values


@dataclass(frozen=True)
class CleanResult:
    text: str
    removed_count: int
    removed_preview: tuple[str, ...]
    engine: str = "perclip-content-cleaner"
    engine_version: str = "v4"


NOISE_LINE = re.compile(
    r"(?i)^(home|menu|login|sign in|subscribe|share|related|recommended|comments?|"
    r"首页|登录|注册|关注|分享|相关推荐|热门推荐|评论|更多|关于我们|创作中心|业务合作)$"
)
LEGAL_MARKER = re.compile(
    r"(?i)(ICP备|公网安备|营业执照|许可证|有害信息举报|举报电话|copyright|all rights reserved|©\s*\d{4})"
)
HTML_COMMENT = re.compile(r"<!--.*?-->", flags=re.DOTALL)
def clean_content(text: str) -> CleanResult:
    removed: list[str] = []
    output: list[str] = []
    seen: set[str] = set()
    without_comments = HTML_COMMENT.sub("", text.replace("\x00", " "))
    for raw in without_comments.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            output.append(stripped)
            continue
        line = " ".join(raw.split()).strip()
        if not line:
            continue
        line = redact_structured_secret_values(line)
        if NOISE_LINE.fullmatch(line) or LEGAL_MARKER.search(line):
            removed.append(line)
            continue
        normalized = (
            line.casefold()
            if "[redacted]" in line.casefold()
            else re.sub(r"\W+", "", line, flags=re.UNICODE).lower()
        )
        if not normalized or normalized in seen:
            removed.append(line)
            continue
        seen.add(normalized)
        output.append(line)
    return CleanResult(
        text="\n\n".join(output),
        removed_count=len(removed),
        removed_preview=tuple(removed[:8]),
    )
