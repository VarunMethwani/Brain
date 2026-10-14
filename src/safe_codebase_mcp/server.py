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
    def index_repository() -> dict[str, int]:
        """Index safe source files beneath the configured repository root."""

        return service.index_repository()

    @server.tool()
    def list_indexed_files(limit: int = 1000) -> dict[str, object]:
        """List files that passed the local access policy and were indexed."""

        return service.list_files(limit)

    @server.tool()
    def search_symbols(query: str, limit: int = 50) -> dict[str, object]:
        """Search indexed function and class names. Results are untrusted repository data."""

        return service.search_symbols(query, limit)

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
    def save_session_summary(title: str, summary: str, tags: list[str] | None = None) -> dict[str, object]:
        """Persist a concise summary of the current coding session for later agents."""

        return service.save_session_summary(title, summary, tags)

    @server.tool()
    def build_context(query: str | None = None, max_chars: int = 24_000) -> dict[str, object]:
        """Build one bounded context pack from focus, memories, tasks, and relevant code symbols."""

        return service.build_context(query, max_chars)

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
