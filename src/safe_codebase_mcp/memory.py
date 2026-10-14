"""Validation and limits for second-brain records.

Memory is intentionally treated as untrusted data. The service stores plain
text only; it never evaluates, imports, or executes memory content.
"""

from __future__ import annotations

import re

from .errors import AccessDenied

MEMORY_KINDS = {
    "fact",
    "decision",
    "constraint",
    "task",
    "note",
    "session_summary",
}
MEMORY_STATUSES = {"active", "blocked", "done", "archived"}
MEMORY_SOURCES = {"user", "agent", "tool"}
MAX_MEMORY_TITLE = 200
MAX_MEMORY_CONTENT = 20_000
MAX_MEMORY_TAGS = 20
MAX_MEMORY_TAG_LENGTH = 40

_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_TOKEN_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_-]{16,}|github_pat_[A-Za-z0-9_]{16,}|xox[baprs]-[A-Za-z0-9-]{16,})\b"
)
_ASSIGNMENT_RE = re.compile(
    r"\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|aws_secret_access_key)\b"
    r"\s*[:=]\s*([A-Za-z0-9_./+=-]{20,})",
    re.IGNORECASE,
)


def _text(value: str, field: str, limit: int, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    cleaned = value.strip()
    if required and not cleaned:
        raise ValueError(f"{field} cannot be empty")
    if len(cleaned) > limit:
        raise ValueError(f"{field} exceeds the {limit}-character limit")
    return cleaned


def validate_memory(
    *,
    title: str,
    content: str,
    kind: str,
    tags: list[str] | None,
    priority: int,
    source: str,
    status: str,
    pinned: bool,
) -> tuple[str, str, str, list[str], int, str, str, bool]:
    title = _text(title, "title", MAX_MEMORY_TITLE)
    content = _text(content, "content", MAX_MEMORY_CONTENT)
    if kind not in MEMORY_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(sorted(MEMORY_KINDS))}")
    if status not in MEMORY_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(MEMORY_STATUSES))}")
    if source not in MEMORY_SOURCES:
        raise ValueError(f"source must be one of: {', '.join(sorted(MEMORY_SOURCES))}")
    if not isinstance(priority, int) or not 1 <= priority <= 5:
        raise ValueError("priority must be an integer from 1 to 5")
    if not isinstance(pinned, bool):
        raise ValueError("pinned must be a boolean")
    if tags is None:
        tags = []
    if not isinstance(tags, list) or len(tags) > MAX_MEMORY_TAGS:
        raise ValueError(f"tags must be a list of at most {MAX_MEMORY_TAGS} items")
    cleaned_tags: list[str] = []
    for tag in tags:
        tag = _text(tag, "tag", MAX_MEMORY_TAG_LENGTH)
        if tag not in cleaned_tags:
            cleaned_tags.append(tag)

    # The second brain is not a secret store. Reject recognizable credential
    # formats before they become durable and searchable.
    if _PRIVATE_KEY_RE.search(content) or _TOKEN_RE.search(content) or _ASSIGNMENT_RE.search(content):
        raise AccessDenied("memory content looks like a credential; store a redacted note instead")
    return title, content, kind, cleaned_tags, priority, source, status, pinned
