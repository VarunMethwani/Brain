"""Bounded source scanner and lightweight symbol extractor."""

from __future__ import annotations

import hashlib
import ast
import re
from dataclasses import dataclass
from pathlib import Path

from .db import IndexDatabase
from .errors import AccessDenied, FileTooLarge
from .policy import FilePolicy


SUPPORTED_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".json",
    ".kt",
    ".kts",
    ".md",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".scss",
    ".sh",
    ".sql",
    ".svelte",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}

LANGUAGES = {
    ".cc": "cpp",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".html": "html",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "json",
    ".md": "markdown",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".sh": "shell",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".vue": "vue",
    ".yaml": "yaml",
    ".yml": "yaml",
}


@dataclass(frozen=True)
class IndexStats:
    indexed_files: int
    indexed_symbols: int
    skipped_files: int
    removed_files: int
    unchanged_files: int = 0


_PATTERNS = (
    ("function", re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\b")),
    ("class", re.compile(r"^\s*class\s+([A-Za-z_]\w*)\b")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\b")),
    ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)\b")),
    ("function", re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)\b")),
    ("function", re.compile(r"^\s*(?:public|private|protected|static|async|def)+\s+([A-Za-z_]\w*)\s*\(")),
)


def _extract_python_symbols(text: str) -> list[tuple[str, str, int, int, str]] | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None

    symbols: list[tuple[str, str, int, int, str]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.parents: list[ast.AST] = []

        def visit(self, node: ast.AST) -> None:  # type: ignore[override]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = int(getattr(node, "lineno", 1))
                end = int(getattr(node, "end_lineno", start))
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                if kind == "function" and any(isinstance(parent, ast.ClassDef) for parent in self.parents):
                    kind = "method"
                signature = " ".join(text.splitlines()[start - 1].strip().split())[:240]
                symbols.append((node.name, kind, start, max(start, end), signature))
            self.parents.append(node)
            self.generic_visit(node)
            self.parents.pop()

    Visitor().visit(tree)
    return sorted(symbols, key=lambda symbol: (symbol[2], -symbol[3], symbol[0]))


def extract_symbols(text: str, language: str = "") -> list[tuple[str, str, int, int, str]]:
    if language == "python":
        parsed = _extract_python_symbols(text)
        if parsed is not None:
            return parsed
    lines = text.splitlines()
    found: list[tuple[str, str, int, str]] = []
    for line_number, line in enumerate(lines, start=1):
        for kind, pattern in _PATTERNS:
            match = pattern.match(line)
            if match:
                signature = " ".join(line.strip().split())[:240]
                found.append((match.group(1), kind, line_number, signature))
                break
    symbols: list[tuple[str, str, int, int, str]] = []
    for index, (name, kind, start, signature) in enumerate(found):
        end = found[index + 1][2] - 1 if index + 1 < len(found) else max(start, len(lines))
        symbols.append((name, kind, start, end, signature))
    return symbols


class CodebaseIndexer:
    def __init__(self, policy: FilePolicy, database: IndexDatabase) -> None:
        self.policy = policy
        self.database = database

    def index(self, *, force: bool = False) -> IndexStats:
        indexed_files = 0
        indexed_symbols = 0
        skipped_files = 0
        present_paths: set[str] = set()
        unchanged_files = 0

        for relative in self.policy.iter_indexable_files(SUPPORTED_EXTENSIONS):
            try:
                text = self.policy.read_text(relative)
                path = self.policy.validate_read(relative)
                stat = path.stat()
            except (AccessDenied, FileTooLarge, OSError):
                skipped_files += 1
                continue
            present_paths.add(relative)
            digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
            existing = self.database.get_file_metadata(relative)
            if (
                not force
                and existing is not None
                and int(existing["size_bytes"]) == stat.st_size
                and int(existing["mtime_ns"]) == stat.st_mtime_ns
                and str(existing["sha256"]) == digest
            ):
                unchanged_files += 1
                continue
            symbols = extract_symbols(text, LANGUAGES.get(path.suffix.lower(), ""))
            self.database.replace_file(
                path=relative,
                sha256=digest,
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                language=LANGUAGES.get(path.suffix.lower(), path.suffix.lower().lstrip(".")),
                symbols=symbols,
            )
            indexed_files += 1
            indexed_symbols += len(symbols)

        removed_files = self.database.remove_missing(present_paths)
        self.database.commit()
        return IndexStats(indexed_files, indexed_symbols, skipped_files, removed_files, unchanged_files)
