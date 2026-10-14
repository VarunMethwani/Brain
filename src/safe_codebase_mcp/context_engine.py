"""Deterministic, budget-aware context selection and assembly."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable


PROFILE_TOKENS = {
    "minimal": 1_200,
    "standard": 2_400,
    "deep": 4_000,
}


def estimate_tokens(value: object) -> int:
    """Estimate model tokens without adding a tokenizer dependency.

    Four UTF-8-ish characters per token is intentionally conservative for
    source and prose. The estimate is applied to the complete JSON payload,
    not just the human-readable context string.
    """

    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return max(1, (len(serialized) + 3) // 4)


def resolve_budget(*, profile: str, max_tokens: int | None, max_chars: int | None) -> tuple[str, int]:
    if profile not in PROFILE_TOKENS:
        raise ValueError(f"profile must be one of: {', '.join(PROFILE_TOKENS)}")
    if max_chars is not None:
        if max_chars < 1_600 or max_chars > 48_000:
            raise ValueError("max_chars must be between 1600 and 48000")
        # Preserve the original API while moving the internal budget to tokens.
        max_tokens = max_chars // 4
    if max_tokens is None:
        max_tokens = PROFILE_TOKENS[profile]
    if not isinstance(max_tokens, int) or max_tokens < 400 or max_tokens > 12_000:
        raise ValueError("max_tokens must be an integer between 400 and 12000")
    return profile, max_tokens


@dataclass(frozen=True)
class Candidate:
    record: dict[str, object]
    category: str
    score: float
    reason: str


def infer_intent(query: str | None) -> str:
    if not query:
        return "general"
    text = query.casefold()
    if any(word in text for word in ("bug", "error", "failure", "broken", "regression", "debug")):
        return "debugging"
    if any(word in text for word in ("architecture", "design", "tradeoff", "why", "decision")):
        return "architecture"
    if any(word in text for word in ("security", "secret", "permission", "auth", "unsafe")):
        return "security"
    if any(word in text for word in ("implement", "build", "refactor", "change", "add", "fix")):
        return "implementation"
    return "general"


def category_weight(intent: str, category: str) -> float:
    weights = {
        "general": {"pinned": 7, "constraint": 6, "decision": 5, "task": 5, "query": 8, "summary": 3},
        "debugging": {"pinned": 5, "constraint": 7, "decision": 4, "task": 7, "query": 9, "summary": 3},
        "architecture": {"pinned": 5, "constraint": 8, "decision": 9, "task": 4, "query": 8, "summary": 4},
        "security": {"pinned": 6, "constraint": 10, "decision": 7, "task": 4, "query": 9, "summary": 3},
        "implementation": {"pinned": 5, "constraint": 6, "decision": 5, "task": 8, "query": 9, "summary": 3},
    }
    return weights.get(intent, weights["general"]).get(category, 1)


def make_candidates(
    *,
    query: str | None,
    pinned: Iterable[dict[str, object]],
    constraints: Iterable[dict[str, object]],
    decisions: Iterable[dict[str, object]],
    tasks: Iterable[dict[str, object]],
    summaries: Iterable[dict[str, object]],
    query_matches: Iterable[dict[str, object]],
) -> list[Candidate]:
    intent = infer_intent(query)
    candidates: dict[int, Candidate] = {}

    def add(records: Iterable[dict[str, object]], category: str, reason: str) -> None:
        for rank, record in enumerate(records):
            record_id = int(record["id"])
            priority = int(record.get("priority", 3))
            pinned_bonus = 3 if record.get("pinned") else 0
            score = category_weight(intent, category) * 10 + priority * 2 + pinned_bonus - rank * 0.15
            candidate = Candidate(record, category, score, reason)
            previous = candidates.get(record_id)
            if previous is None or candidate.score > previous.score:
                candidates[record_id] = candidate

    add(pinned, "pinned", "pinned project memory")
    add(constraints, "constraint", "active project constraint")
    add(decisions, "decision", "active project decision")
    add(tasks, "task", "open project task")
    add(summaries, "summary", "recent session summary")
    add(query_matches, "query", "matches the task query")
    return sorted(candidates.values(), key=lambda item: (-item.score, int(item.record["id"])))


def compact_memory_ref(candidate: Candidate) -> dict[str, object]:
    record = candidate.record
    result = {
        "id": record["id"],
        "kind": record["kind"],
        "title": record["title"],
        "tags": record.get("tags", []),
        "status": record["status"],
        "priority": record["priority"],
        "source": record["source"],
        "pinned": record["pinned"],
        "updated_at": record["updated_at"],
        "reason": candidate.reason,
    }
    for key in ("source_ref", "valid_from", "valid_until", "supersedes_id", "code_hash", "commit_sha", "verified_at", "session_id"):
        if record.get(key) is not None:
            result[key] = record[key]
    return result


def compact_code_ref(match: dict[str, object]) -> dict[str, object]:
    return {
        key: match[key]
        for key in ("path", "name", "kind", "start_line", "end_line", "signature")
        if key in match
    }
