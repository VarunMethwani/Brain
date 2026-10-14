"""Small SQLite store for indexed file and symbol metadata."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


class IndexDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                language TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS symbols (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                signature TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS symbols_name_idx ON symbols(name);
            CREATE INDEX IF NOT EXISTS symbols_path_idx ON symbols(path);
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def replace_file(
        self,
        *,
        path: str,
        sha256: str,
        size_bytes: int,
        mtime_ns: int,
        language: str,
        symbols: Iterable[tuple[str, str, int, int, str]],
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO files(path, sha256, size_bytes, mtime_ns, language)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                sha256=excluded.sha256,
                size_bytes=excluded.size_bytes,
                mtime_ns=excluded.mtime_ns,
                language=excluded.language
            """,
            (path, sha256, size_bytes, mtime_ns, language),
        )
        self.connection.execute("DELETE FROM symbols WHERE path = ?", (path,))
        self.connection.executemany(
            """
            INSERT INTO symbols(path, name, kind, start_line, end_line, signature)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ((path, name, kind, start, end, signature) for name, kind, start, end, signature in symbols),
        )

    def remove_missing(self, paths: set[str]) -> int:
        existing = [row[0] for row in self.connection.execute("SELECT path FROM files")]
        stale = [path for path in existing if path not in paths]
        self.connection.executemany("DELETE FROM files WHERE path = ?", ((path,) for path in stale))
        return len(stale)

    def commit(self) -> None:
        self.connection.commit()

    def list_files(self, limit: int = 1000) -> list[dict[str, object]]:
        rows = self.connection.execute(
            "SELECT path, size_bytes, language FROM files ORDER BY path LIMIT ?", (limit,)
        )
        return [dict(row) for row in rows]

    def search_symbols(self, query: str, limit: int = 50) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT path, name, kind, start_line, end_line, signature
            FROM symbols
            WHERE name LIKE ? COLLATE NOCASE
               OR signature LIKE ? COLLATE NOCASE
            ORDER BY path, start_line
            LIMIT ?
            """,
            (f"%{query}%", f"%{query}%", limit),
        )
        return [dict(row) for row in rows]

    def find_symbol(self, path: str, name: str) -> dict[str, object] | None:
        row = self.connection.execute(
            """
            SELECT path, name, kind, start_line, end_line, signature
            FROM symbols WHERE path = ? AND name = ?
            ORDER BY start_line LIMIT 1
            """,
            (path, name),
        ).fetchone()
        return dict(row) if row else None
