"""Validation and limits for second-brain records.

Memory is intentionally treated as untrusted data. The service stores plain
text only; it never evaluates, imports, or executes memory content.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .errors import AccessDenied

MEMORY_KINDS = {
    "fact",
    "decision",
    "constraint",
    "task",
    "note",
    "session_summary",
}
MEMORY_STATUSES = {"active", "blocked", "done", "archived", "superseded"}
MEMORY_SOURCES = {"user", "agent", "tool"}
MAX_MEMORY_TITLE = 200
MAX_MEMORY_CONTENT = 20_000
MAX_MEMORY_TAGS = 20
MAX_MEMORY_TAG_LENGTH = 40
MAX_MEMORY_SOURCE_REF = 500
MAX_MEMORY_ENTITY_IDS = 50
MAX_MEMORY_ENTITY_ID_LENGTH = 200

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


def _optional_text(value: str | None, field: str, limit: int) -> str | None:
    if value is None:
        return None
    return _text(value, field, limit)


def _timestamp(value: str | None, field: str) -> str | None:
    value = _optional_text(value, field, 64)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat(timespec="seconds")


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
    source_ref: str | None = None,
    valid_from: str | None = None,
    valid_until: str | None = None,
    supersedes_id: int | None = None,
    code_hash: str | None = None,
    commit_sha: str | None = None,
    verified_at: str | None = None,
    related_entity_ids: list[str] | None = None,
    session_id: str | None = None,
) -> tuple[object, ...]:
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
    source_ref = _optional_text(source_ref, "source_ref", MAX_MEMORY_SOURCE_REF)
    valid_from = _timestamp(valid_from, "valid_from")
    valid_until = _timestamp(valid_until, "valid_until")
    if valid_from and valid_until:
        start = datetime.fromisoformat(valid_from.replace("Z", "+00:00"))
        end = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
        if end <= start:
            raise ValueError("valid_until must be later than valid_from")
    if supersedes_id is not None and (not isinstance(supersedes_id, int) or supersedes_id <= 0):
        raise ValueError("supersedes_id must be a positive integer")
    code_hash = _optional_text(code_hash, "code_hash", 128)
    commit_sha = _optional_text(commit_sha, "commit_sha", 128)
    verified_at = _timestamp(verified_at, "verified_at")
    if related_entity_ids is None:
        related_entity_ids = []
    if not isinstance(related_entity_ids, list) or len(related_entity_ids) > MAX_MEMORY_ENTITY_IDS:
        raise ValueError(f"related_entity_ids must contain at most {MAX_MEMORY_ENTITY_IDS} items")
    cleaned_entities: list[str] = []
    for entity_id in related_entity_ids:
        entity_id = _text(entity_id, "related_entity_id", MAX_MEMORY_ENTITY_ID_LENGTH)
        if entity_id not in cleaned_entities:
            cleaned_entities.append(entity_id)
    session_id = _optional_text(session_id, "session_id", 128)
    return (
        title,
        content,
        kind,
        cleaned_tags,
        priority,
        source,
        status,
        pinned,
        source_ref,
        valid_from,
        valid_until,
        supersedes_id,
        code_hash,
        commit_sha,
        verified_at,
        cleaned_entities,
        session_id,
    )
