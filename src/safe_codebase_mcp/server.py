"""Stdio-only MCP adapter for the secure local codebase second brain."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .db import IndexDatabase
from .policy import FilePolicy
from .service import CodebaseService


def create_server(root: Path | str) -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised only without extras installed
        raise RuntimeError(
            "The MCP adapter requires the package extra: pip install 'safe-codebase-mcp'"
        ) from exc

    policy = FilePolicy(root)
    database = IndexDatabase(policy.database_path())
    service = CodebaseService(policy, database)
    server = FastMCP("safe-codebase-second-brain")

    @server.tool()
    def index_repository(force: bool = False) -> dict[str, int]:
        """Index safe source files; unchanged files are reused unless force is true."""

        return service.index_repository(force)

    @server.tool()
    def list_indexed_files(limit: int = 1000) -> dict[str, object]:
        """List files that passed the local access policy and were indexed."""

        return service.list_files(limit)

    @server.tool()
    def search_symbols(query: str, limit: int = 50) -> dict[str, object]:
        """Search indexed function and class names. Results are untrusted repository data."""

        return service.search_symbols(query, limit)

    @server.tool()
    def get_dependencies(path: str, limit: int = 100) -> dict[str, object]:
        """List conservative import relationships for one indexed source file."""

        return service.get_dependencies(path, limit)

    @server.tool()
    def get_impact(target: str, limit: int = 100) -> dict[str, object]:
        """Find indexed files whose imports mention a module or package target."""

        return service.get_impact(target, limit)

    @server.tool()
    def read_source(path: str, start_line: int | None = None, end_line: int | None = None) -> dict[str, object]:
        """Read an allowed source path; ignored, secret, VCS, and symlinked paths are denied."""

        return service.read_source(path, start_line, end_line)

    @server.tool()
    def read_symbol_source(path: str, symbol: str) -> dict[str, object]:
        """Read the indexed range for a symbol through the same source policy."""

        return service.read_symbol_source(path, symbol)

    @server.tool()
    def remember(
        title: str,
        content: str,
        kind: str = "note",
        tags: list[str] | None = None,
        priority: int = 3,
        source: str = "agent",
        status: str = "active",
        pinned: bool = False,
        source_ref: str | None = None,
        valid_from: str | None = None,
        valid_until: str | None = None,
        supersedes_id: int | None = None,
        code_hash: str | None = None,
        commit_sha: str | None = None,
        verified_at: str | None = None,
        related_entity_ids: list[str] | None = None,
        session_id: str | None = None,
        memory_id: int | None = None,
    ) -> dict[str, object]:
        """Store or revise a bounded fact, decision, constraint, task, note, or session summary."""

        return service.remember(
            title=title,
            content=content,
            kind=kind,
            tags=tags,
            priority=priority,
            source=source,
            status=status,
            pinned=pinned,
            source_ref=source_ref,
            valid_from=valid_from,
            valid_until=valid_until,
            supersedes_id=supersedes_id,
            code_hash=code_hash,
            commit_sha=commit_sha,
            verified_at=verified_at,
            related_entity_ids=related_entity_ids,
            session_id=session_id,
            memory_id=memory_id,
        )

    @server.tool()
    def recall(query: str, limit: int = 20, kind: str | None = None) -> dict[str, object]:
        """Search durable second-brain memories using local full-text search."""

        return service.recall(query, limit, kind)

    @server.tool()
    def set_focus(
        goal: str,
        next_steps: list[str] | None = None,
        blockers: list[str] | None = None,
    ) -> dict[str, object]:
        """Set the current coding goal, next steps, and blockers for future context packs."""

        return service.set_focus(goal, next_steps, blockers)

    @server.tool()
    def get_focus() -> dict[str, object]:
        """Return the current project focus."""

        return service.get_focus()

    @server.tool()
    def record_task(
        title: str,
        content: str,
        priority: int = 3,
        tags: list[str] | None = None,
        source: str = "agent",
        pinned: bool = False,
    ) -> dict[str, object]:
        """Create an open task that will be prioritized in the next context pack."""

        return service.record_task(
            title=title,
            content=content,
            priority=priority,
            tags=tags,
            source=source,
            pinned=pinned,
        )

    @server.tool()
    def list_open_tasks(limit: int = 50) -> dict[str, object]:
        """List open and blocked tasks from the second brain."""

        return service.list_open_tasks(limit)

    @server.tool()
    def complete_task(memory_id: int) -> dict[str, object]:
        """Mark an open task done without deleting its history."""

        return service.complete_task(memory_id)

    @server.tool()
    def archive_memory(memory_id: int) -> dict[str, object]:
        """Reversibly archive a memory so it no longer appears in active context."""

        return service.archive_memory(memory_id)

    @server.tool()
    def verify_memory(memory_id: int) -> dict[str, object]:
        """Mark a memory as checked now without changing its content."""

        return service.verify_memory(memory_id)

    @server.tool()
    def save_session_summary(title: str, summary: str, tags: list[str] | None = None) -> dict[str, object]:
        """Persist a concise summary of the current coding session for later agents."""

        return service.save_session_summary(title, summary, tags)

    @server.tool()
    def checkpoint_session(
        session_id: str,
        objective: str,
        next_action: str,
        completed_work: list[str] | None = None,
        modified_files: list[str] | None = None,
        verified_decisions: list[int] | None = None,
        unresolved_blockers: list[str] | None = None,
        repository_revision: str | None = None,
    ) -> dict[str, object]:
        """Save a structured handoff checkpoint for resuming a coding session."""

        return service.checkpoint_session(
            session_id=session_id,
            objective=objective,
            completed_work=completed_work,
            modified_files=modified_files,
            verified_decisions=verified_decisions,
            unresolved_blockers=unresolved_blockers,
            next_action=next_action,
            repository_revision=repository_revision,
        )

    @server.tool()
    def get_checkpoint() -> dict[str, object]:
        """Return the latest structured session handoff checkpoint."""

        return service.get_checkpoint()

    @server.tool()
    def expand_context(
        memory_ids: list[int],
        profile: str = "standard",
        max_tokens: int | None = None,
        max_chars: int | None = None,
    ) -> dict[str, object]:
        """Fetch selected full memory records under a separate bounded budget."""

        return service.expand_context(memory_ids, profile, max_tokens, max_chars)

    @server.tool()
    def build_context(
        query: str | None = None,
        profile: str = "standard",
        max_tokens: int | None = None,
        max_chars: int | None = None,
    ) -> dict[str, object]:
        """Build a task-aware, token-bounded context pack.

        ``max_chars`` is retained as a compatibility alias; new callers should
        use ``profile`` or ``max_tokens``.
        """

        return service.build_context(query, max_tokens, profile, max_chars)

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="repository root to index (default: current directory)",
    )
    args = parser.parse_args(argv)
    server = create_server(args.root)
    # Keep the transport local and stdio-only. No HTTP listener is exposed.
    server.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
