#!/usr/bin/env python3
"""Run a small deterministic retrieval/context benchmark.

This benchmark uses an isolated temporary repository and synthetic ground truth
so it never changes a user's project. Replace or extend CASES with real,
anonymized coding tasks for release evaluation.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from safe_codebase_mcp.context_engine import estimate_tokens  # noqa: E402
from safe_codebase_mcp.db import IndexDatabase  # noqa: E402
from safe_codebase_mcp.policy import FilePolicy  # noqa: E402
from safe_codebase_mcp.service import CodebaseService  # noqa: E402


@dataclass(frozen=True)
class Case:
    query: str
    expected_title: str


TOPICS = (
    ("database pooling", "Database pool architecture", "PostgreSQL asyncpg pool configuration"),
    ("authentication sessions", "Authentication session policy", "Session expiry and refresh policy"),
    ("path security", "Filesystem boundary decision", "Resolved path containment and symlink denial"),
    ("context budgets", "Context budget decision", "Token-aware context selection and compact refs"),
    ("import dependencies", "Import graph decision", "Conservative dependency relationship indexing"),
    ("task checkpoints", "Session checkpoint policy", "Objective blockers and next action handoff"),
    ("memory supersession", "Memory lifecycle decision", "Superseded decisions and validity windows"),
    ("incremental indexing", "Incremental index decision", "Hash-verified unchanged file reuse"),
    ("source symbols", "Symbol extraction policy", "AST ranges and regex fallback"),
    ("prompt injection", "Untrusted content constraint", "Repository results are reference data"),
)

CASES = tuple(
    Case(f"{topic} {variant}", title)
    for topic, title, content in TOPICS
    for variant in (topic, content.split()[0], f"how does {topic} work", f"decision about {topic}", f"{topic} policy")
)


def run() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="brain-benchmark-") as temporary:
        root = Path(temporary)
        (root / "fixture.py").write_text("def context_fixture():\n    return True\n", encoding="utf-8")
        policy = FilePolicy(root)
        database = IndexDatabase(policy.database_path())
        try:
            service = CodebaseService(policy, database)
            for topic, title, content in TOPICS:
                service.remember(title=title, content=content, kind="decision", priority=4, source="tool")
            service.index_repository()

            hits = 0
            recall_tokens: list[int] = []
            context_tokens: list[int] = []
            latencies_ms: list[float] = []
            for case in CASES:
                started = time.perf_counter()
                result = service.recall(case.query, limit=5)
                latencies_ms.append((time.perf_counter() - started) * 1000)
                matches = result["matches"]
                if any(item["title"] == case.expected_title for item in matches):
                    hits += 1
                recall_tokens.append(estimate_tokens(result))
                context_tokens.append(estimate_tokens(service.build_context(case.query, profile="standard")))

            sorted_latency = sorted(latencies_ms)
            p95_index = min(len(sorted_latency) - 1, int(len(sorted_latency) * 0.95))
            return {
                "cases": len(CASES),
                "recall_at_5": round(hits / len(CASES), 4),
                "average_recall_tokens": round(sum(recall_tokens) / len(recall_tokens), 2),
                "average_context_tokens": round(sum(context_tokens) / len(context_tokens), 2),
                "p95_recall_latency_ms": round(sorted_latency[p95_index], 3),
            }
        finally:
            database.close()


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
