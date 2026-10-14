"""SQLite store for indexed code metadata and second-brain records."""

from __future__ import annotations

import sqlite3
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _memory_dict(row: sqlite3.Row) -> dict[str, object]:
    result = dict(row)
    try:
        result["tags"] = json.loads(str(result.pop("tags_json")))
    except (TypeError, ValueError, json.JSONDecodeError):
        result["tags"] = []
    try:
        result["related_entity_ids"] = json.loads(str(result.pop("related_entity_ids_json")))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        result["related_entity_ids"] = []
    result["pinned"] = bool(result["pinned"])
    return result


_MEMORY_COLUMNS = """
    id, kind, title, content, tags_json, status, priority, source, pinned,
    created_at, updated_at, source_ref, valid_from, valid_until, supersedes_id,
    code_hash, commit_sha, verified_at, related_entity_ids_json, session_id
"""


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

            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active',
                priority INTEGER NOT NULL DEFAULT 3,
                source TEXT NOT NULL DEFAULT 'agent',
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source_ref TEXT,
                valid_from TEXT,
                valid_until TEXT,
                supersedes_id INTEGER,
                code_hash TEXT,
                commit_sha TEXT,
                verified_at TEXT,
                related_entity_ids_json TEXT NOT NULL DEFAULT '[]',
                session_id TEXT
            );
            CREATE INDEX IF NOT EXISTS memories_kind_status_idx
                ON memories(kind, status, priority, updated_at);
            CREATE INDEX IF NOT EXISTS memories_validity_idx
                ON memories(valid_from, valid_until);
            CREATE TABLE IF NOT EXISTS project_state (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        self._migrate_memory_columns()
        self._fts_available = self._init_memory_search()
        self.connection.commit()

    def _migrate_memory_columns(self) -> None:
        existing = {
            str(row[1]) for row in self.connection.execute("PRAGMA table_info(memories)")
        }
        additions = {
            "source_ref": "TEXT",
            "valid_from": "TEXT",
            "valid_until": "TEXT",
            "supersedes_id": "INTEGER",
            "code_hash": "TEXT",
            "commit_sha": "TEXT",
            "verified_at": "TEXT",
            "related_entity_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            "session_id": "TEXT",
        }
        for column, definition in additions.items():
            if column not in existing:
                self.connection.execute(f"ALTER TABLE memories ADD COLUMN {column} {definition}")

    def _init_memory_search(self) -> bool:
        try:
            already_exists = self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'memory_fts'"
            ).fetchone()
            self.connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    memory_id UNINDEXED, title, content, tags
                )
                """
            )
            if already_exists is None:
                self.connection.execute(
                    """
                    INSERT INTO memory_fts(memory_id, title, content, tags)
                    SELECT id, title, content, tags_json FROM memories
                    """
                )
            return True
        except sqlite3.OperationalError:
            return False

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

    def get_file_metadata(self, path: str) -> dict[str, object] | None:
        row = self.connection.execute(
            "SELECT path, sha256, size_bytes, mtime_ns, language FROM files WHERE path = ?",
            (path,),
        ).fetchone()
        return dict(row) if row else None

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

    # --- second-brain memory -------------------------------------------------

    def _sync_memory_search(self, memory_id: int) -> None:
        if not self._fts_available:
            return
        self.connection.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
        row = self.connection.execute(
            "SELECT id, title, content, tags_json FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if row:
            self.connection.execute(
                "INSERT INTO memory_fts(memory_id, title, content, tags) VALUES (?, ?, ?, ?)",
                (row["id"], row["title"], row["content"], row["tags_json"]),
            )

    def remember(
        self,
        *,
        title: str,
        content: str,
        kind: str,
        tags: list[str],
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
        memory_id: int | None = None,
    ) -> dict[str, object]:
        timestamp = _now()
        tags_json = json.dumps(tags, ensure_ascii=False)
        related_entity_ids_json = json.dumps(related_entity_ids or [], ensure_ascii=False)
        if memory_id is None:
            cursor = self.connection.execute(
                """
                INSERT INTO memories(
                    kind, title, content, tags_json, status, priority, source,
                    pinned, created_at, updated_at, source_ref, valid_from,
                    valid_until, supersedes_id, code_hash, commit_sha,
                    verified_at, related_entity_ids_json, session_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind,
                    title,
                    content,
                    tags_json,
                    status,
                    priority,
                    source,
                    int(pinned),
                    timestamp,
                    timestamp,
                    source_ref,
                    valid_from,
                    valid_until,
                    supersedes_id,
                    code_hash,
                    commit_sha,
                    verified_at,
                    related_entity_ids_json,
                    session_id,
                ),
            )
            memory_id = int(cursor.lastrowid)
        else:
            existing = self.connection.execute("SELECT id FROM memories WHERE id = ?", (memory_id,)).fetchone()
            if existing is None:
                raise ValueError(f"memory not found: {memory_id}")
            self.connection.execute(
                """
                UPDATE memories SET kind = ?, title = ?, content = ?, tags_json = ?,
                    status = ?, priority = ?, source = ?, pinned = ?, updated_at = ?,
                    source_ref = ?, valid_from = ?, valid_until = ?, supersedes_id = ?,
                    code_hash = ?, commit_sha = ?, verified_at = ?,
                    related_entity_ids_json = ?, session_id = ?
                WHERE id = ?
                """,
                (
                    kind,
                    title,
                    content,
                    tags_json,
                    status,
                    priority,
                    source,
                    int(pinned),
                    timestamp,
                    source_ref,
                    valid_from,
                    valid_until,
                    supersedes_id,
                    code_hash,
                    commit_sha,
                    verified_at,
                    related_entity_ids_json,
                    session_id,
                    memory_id,
                ),
            )
        if supersedes_id is not None and supersedes_id != memory_id:
            self.connection.execute(
                """
                UPDATE memories SET status = 'superseded', valid_until = COALESCE(valid_until, ?),
                    pinned = 0, updated_at = ?
                WHERE id = ?
                """,
                (timestamp, timestamp, supersedes_id),
            )
        self._sync_memory_search(memory_id)
        self.connection.commit()
        return self.get_memory(memory_id)  # type: ignore[return-value]

    def get_memory(self, memory_id: int) -> dict[str, object] | None:
        row = self.connection.execute(
            f"SELECT {_MEMORY_COLUMNS} FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()
        return _memory_dict(row) if row else None

    def archive_memory(self, memory_id: int) -> dict[str, object]:
        cursor = self.connection.execute(
            "UPDATE memories SET status = 'archived', pinned = 0, updated_at = ? WHERE id = ?",
            (_now(), memory_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"memory not found: {memory_id}")
        self.connection.commit()
        return self.get_memory(memory_id)  # type: ignore[return-value]

    def list_memories(
        self,
        *,
        limit: int = 100,
        kind: str | None = None,
        status: str | None = "active",
        pinned_only: bool = False,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        parameters: list[object] = []
        if kind:
            clauses.append("kind = ?")
            parameters.append(kind)
        if status:
            clauses.append("status = ?")
            parameters.append(status)
            if status in {"active", "blocked"}:
                now = _now()
                clauses.extend(["(valid_from IS NULL OR valid_from <= ?)", "(valid_until IS NULL OR valid_until > ?)"])
                parameters.extend([now, now])
        if pinned_only:
            clauses.append("pinned = 1")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.connection.execute(
            f"""
            SELECT {_MEMORY_COLUMNS}
            FROM memories{where}
            ORDER BY pinned DESC, priority DESC, updated_at DESC, id DESC
            LIMIT ?
            """,
            (*parameters, limit),
        )
        return [_memory_dict(row) for row in rows]

    def list_open_tasks(self, limit: int = 100) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT """ + _MEMORY_COLUMNS + """
            FROM memories
            WHERE kind = 'task' AND status IN ('active', 'blocked')
              AND (valid_from IS NULL OR valid_from <= ?)
              AND (valid_until IS NULL OR valid_until > ?)
            ORDER BY CASE status WHEN 'blocked' THEN 0 ELSE 1 END,
                     pinned DESC, priority DESC, updated_at DESC, id DESC
            LIMIT ?
            """,
            (_now(), _now(), limit),
        )
        return [_memory_dict(row) for row in rows]

    def complete_task(self, memory_id: int) -> dict[str, object]:
        cursor = self.connection.execute(
            "UPDATE memories SET status = 'done', pinned = 0, updated_at = ? WHERE id = ? AND kind = 'task'",
            (_now(), memory_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"open task not found: {memory_id}")
        self.connection.commit()
        return self.get_memory(memory_id)  # type: ignore[return-value]

    def search_memories(
        self, query: str, *, limit: int = 20, kind: str | None = None
    ) -> list[dict[str, object]]:
        tokens: list[str] = []
        for token in re.findall(r"[\w-]+", query, re.UNICODE):
            token = token[:64]
            tokens.append(token)
            # A tiny, deterministic lexical expansion handles common coding
            # language morphology without pretending to be semantic search.
            if token.endswith("ing") and len(token) > 5:
                tokens.append(token[:-3])
            elif token.endswith("ed") and len(token) > 4:
                tokens.append(token[:-2])
            elif token.endswith("s") and len(token) > 4:
                tokens.append(token[:-1])
        tokens = list(dict.fromkeys(tokens))
        if not tokens:
            return []
        if self._fts_available:
            # OR plus prefix matching avoids dropping useful memories merely
            # because one natural-language term was expressed differently.
            fts_query = " OR ".join('"' + token.replace('"', "") + '"*' for token in tokens)
            now = _now()
            clauses = [
                "memory_fts MATCH ?",
                "(m.valid_from IS NULL OR m.valid_from <= ?)",
                "(m.valid_until IS NULL OR m.valid_until > ?)",
            ]
            parameters: list[object] = [fts_query, now, now]
            if kind:
                clauses.append("m.kind = ?")
                parameters.append(kind)
            parameters.append(limit)
            rows = self.connection.execute(
                f"""
                SELECT m.id, m.kind, m.title, m.content, m.tags_json, m.status,
                       m.priority, m.source, m.pinned, m.created_at, m.updated_at,
                       m.source_ref, m.valid_from, m.valid_until, m.supersedes_id,
                       m.code_hash, m.commit_sha, m.verified_at,
                       m.related_entity_ids_json, m.session_id,
                       bm25(memory_fts) AS score
                FROM memory_fts JOIN memories AS m ON m.id = memory_fts.memory_id
                WHERE {' AND '.join(clauses)} AND m.status NOT IN ('archived', 'superseded')
                ORDER BY score, m.pinned DESC, m.priority DESC, m.updated_at DESC
                LIMIT ?
                """,
                (*parameters,),
            )
        else:
            needle = f"%{query}%"
            now = _now()
            clauses = [
                "(m.title LIKE ? OR m.content LIKE ? OR m.tags_json LIKE ?)",
                "(m.valid_from IS NULL OR m.valid_from <= ?)",
                "(m.valid_until IS NULL OR m.valid_until > ?)",
            ]
            parameters = [needle, needle, needle, now, now]
            if kind:
                clauses.append("m.kind = ?")
                parameters.append(kind)
            parameters.append(limit)
            rows = self.connection.execute(
                f"""
                SELECT m.id, m.kind, m.title, m.content, m.tags_json, m.status,
                       m.priority, m.source, m.pinned, m.created_at, m.updated_at,
                       m.source_ref, m.valid_from, m.valid_until, m.supersedes_id,
                       m.code_hash, m.commit_sha, m.verified_at,
                       m.related_entity_ids_json, m.session_id,
                       0.0 AS score
                FROM memories AS m
                WHERE {' AND '.join(clauses)} AND m.status NOT IN ('archived', 'superseded')
                ORDER BY m.pinned DESC, m.priority DESC, m.updated_at DESC
                LIMIT ?
                """,
                (*parameters,),
            )
        return [_memory_dict(row) | {"score": row["score"]} for row in rows]

    def verify_memory(self, memory_id: int) -> dict[str, object]:
        cursor = self.connection.execute(
            "UPDATE memories SET verified_at = ?, updated_at = ? WHERE id = ?",
            (_now(), _now(), memory_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"memory not found: {memory_id}")
        self.connection.commit()
        return self.get_memory(memory_id)  # type: ignore[return-value]

    # --- project state -------------------------------------------------------

    def set_state(self, key: str, value: object) -> dict[str, object]:
        timestamp = _now()
        self.connection.execute(
            """
            INSERT INTO project_state(key, value_json, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json,
                                           updated_at = excluded.updated_at
            """,
            (key, json.dumps(value, ensure_ascii=False), timestamp),
        )
        self.connection.commit()
        return {"key": key, "value": value, "updated_at": timestamp}

    def get_state(self, key: str) -> object | None:
        row = self.connection.execute("SELECT value_json FROM project_state WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
