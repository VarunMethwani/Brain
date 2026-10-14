"""Filesystem policy applied to every codebase read and internal write.

The policy is intentionally conservative. It does not attempt to infer whether
an agent has good intentions: ignored files, common credential files, VCS
metadata, and symlinked paths are unavailable to the MCP service.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Iterable

from .errors import AccessDenied, FileTooLarge


class FilePolicy:
    """Validate and read files below one immutable repository root."""

    _PROTECTED_DIRECTORIES = {
        ".git",
        ".hg",
        ".svn",
        ".ssh",
        ".aws",
        ".gnupg",
        ".codebase-index",
        "__pycache__",
        "node_modules",
    }
    _PROTECTED_FILES = {
        ".dockerconfigjson",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "authorized_keys",
        "credentials.json",
        "credentials.yaml",
        "credentials.yml",
        "service-account.json",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
    }
    _PROTECTED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".kdb")
    _PROTECTED_PREFIXES = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa")

    def __init__(
        self,
        root: Path | str,
        *,
        max_file_bytes: int = 2 * 1024 * 1024,
        max_read_chars: int = 120_000,
        max_index_files: int = 10_000,
        max_index_directories: int = 10_000,
    ) -> None:
        root_path = Path(root).expanduser()
        try:
            resolved_root = root_path.resolve(strict=True)
        except OSError as exc:
            raise AccessDenied(f"repository root cannot be resolved: {root}") from exc
        if not resolved_root.is_dir():
            raise AccessDenied(f"repository root is not a directory: {root}")
        if any(value <= 0 for value in (max_file_bytes, max_read_chars, max_index_files, max_index_directories)):
            raise ValueError("file, response, and scan limits must be positive")
        self.root = resolved_root
        self.max_file_bytes = max_file_bytes
        self.max_read_chars = max_read_chars
        self.max_index_files = max_index_files
        self.max_index_directories = max_index_directories
        self._ignore_rules = self._load_ignore_rules()

    @staticmethod
    def _normalise_relative(value: str) -> tuple[tuple[str, ...], str]:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise AccessDenied("path must be a non-empty string without NUL bytes")

        # Accept slash-separated input consistently across clients, but never
        # accept an absolute path or a parent traversal component.
        portable = value.replace("\\", "/")
        if portable.startswith("/") or (len(portable) >= 2 and portable[1] == ":"):
            raise AccessDenied("absolute paths are not allowed")
        parts: list[str] = []
        for part in portable.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                raise AccessDenied("parent traversal is not allowed")
            parts.append(part)
        if not parts:
            raise AccessDenied("repository root is not a readable file")
        return tuple(parts), "/".join(parts)

    def _load_ignore_rules(self) -> list[str]:
        ignore_file = self.root / ".gitignore"
        if ignore_file.is_symlink() or not ignore_file.is_file():
            return []
        try:
            data = ignore_file.read_bytes()[:64 * 1024]
        except OSError:
            return []
        rules: list[str] = []
        for raw_line in data.decode("utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line == "!":
                continue
            if line.startswith("\\#"):
                line = line[1:]
            rules.append(line[:512])
            if len(rules) >= 512:
                break
        return rules

    @classmethod
    def is_protected(cls, relative: str, *, is_directory: bool = False) -> bool:
        parts = relative.split("/")
        lower_parts = [part.lower() for part in parts]
        if any(part in cls._PROTECTED_DIRECTORIES for part in lower_parts):
            return True
        if is_directory:
            return lower_parts[-1] in {"secrets", "credentials"}
        basename = lower_parts[-1]
        if basename == ".env" or basename.startswith(".env."):
            return True
        if basename in cls._PROTECTED_FILES:
            return True
        if basename.endswith(cls._PROTECTED_SUFFIXES):
            return True
        if basename.startswith(cls._PROTECTED_PREFIXES):
            return True
        return False

    @staticmethod
    def _gitignore_matches(pattern: str, relative: str, *, is_directory: bool) -> bool:
        directory_pattern = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        anchored = pattern.startswith("/")
        pattern = pattern.lstrip("/")
        if not pattern:
            return False

        if directory_pattern:
            if relative == pattern or relative.startswith(pattern + "/"):
                return True
            if not anchored and any(part == pattern for part in relative.split("/")):
                return True
            return False

        if "/" in pattern or anchored:
            return fnmatch.fnmatchcase(relative, pattern)
        # A pattern without a slash applies at any directory depth according
        # to .gitignore semantics.
        return any(fnmatch.fnmatchcase(part, pattern) for part in relative.split("/"))

    def is_ignored(self, relative: str, *, is_directory: bool = False) -> bool:
        if self.is_protected(relative, is_directory=is_directory):
            return True
        ignored = False
        for rule in self._ignore_rules:
            negated = rule.startswith("!")
            pattern = rule[1:] if negated else rule
            if self._gitignore_matches(pattern, relative, is_directory=is_directory):
                ignored = not negated
        return ignored

    def _check_no_symlink(self, parts: Iterable[str]) -> Path:
        current = self.root
        for part in parts:
            current /= part
            try:
                if current.is_symlink():
                    raise AccessDenied("symlinked paths are not allowed")
            except OSError as exc:
                raise AccessDenied("path cannot be inspected safely") from exc
        return current

    def validate_read(self, relative: str) -> Path:
        parts, normalised = self._normalise_relative(relative)
        if self.is_ignored(normalised):
            raise AccessDenied("path is excluded by the repository file-access policy")
        candidate = self._check_no_symlink(parts)
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise AccessDenied("path cannot be resolved") from exc
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise AccessDenied("path resolves outside the repository root") from exc
        if not resolved.is_file():
            raise AccessDenied("path is not a regular file")
        try:
            size = resolved.stat().st_size
        except OSError as exc:
            raise AccessDenied("file metadata cannot be read") from exc
        if size > self.max_file_bytes:
            raise FileTooLarge(f"file exceeds the {self.max_file_bytes}-byte limit")
        return resolved

    def read_text(self, relative: str) -> str:
        path = self.validate_read(relative)
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb") as handle:
                data = handle.read(self.max_file_bytes + 1)
        except OSError as exc:
            raise AccessDenied("file cannot be read safely") from exc
        if len(data) > self.max_file_bytes:
            raise FileTooLarge(f"file exceeds the {self.max_file_bytes}-byte limit")
        if b"\x00" in data:
            raise AccessDenied("binary files are not available through source tools")
        return data.decode("utf-8", errors="replace")

    def iter_indexable_files(self, extensions: set[str]) -> Iterable[str]:
        """Yield safe, relative files without following any symlink."""

        pending = [self.root]
        visited_directories = 0
        yielded_files = 0
        while pending:
            if visited_directories >= self.max_index_directories:
                return
            directory = pending.pop()
            visited_directories += 1
            try:
                entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
            except OSError:
                continue
            for entry in entries:
                try:
                    relative = entry.path and Path(entry.path).relative_to(self.root).as_posix()
                    if not relative:
                        continue
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if not self.is_ignored(relative, is_directory=True):
                            pending.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if Path(entry.name).suffix.lower() not in extensions:
                        continue
                    if self.is_ignored(relative):
                        continue
                    if yielded_files >= self.max_index_files:
                        return
                    # Validate before yielding so the scanner cannot acquire a
                    # path that the reader would later reject.
                    self.validate_read(relative)
                    yielded_files += 1
                    yield relative
                except (AccessDenied, OSError):
                    continue

    def database_path(self) -> Path:
        """Return a private SQLite path after validating its write boundary."""

        storage = self.root / ".codebase-index"
        if storage.exists() and storage.is_symlink():
            raise AccessDenied("index storage cannot be a symlink")
        try:
            storage.mkdir(mode=0o700, exist_ok=True)
        except OSError as exc:
            raise AccessDenied("index storage cannot be created") from exc
        if storage.is_symlink() or not storage.is_dir():
            raise AccessDenied("index storage is not a private directory")

        database = storage / "index.sqlite3"
        if database.exists() and database.is_symlink():
            raise AccessDenied("index database cannot be a symlink")
        if not database.exists():
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                fd = os.open(database, flags, 0o600)
                os.close(fd)
            except FileExistsError:
                pass
            except OSError as exc:
                raise AccessDenied("index database cannot be created safely") from exc
        if database.is_symlink():
            raise AccessDenied("index database cannot be a symlink")
        try:
            database.resolve(strict=True).relative_to(self.root)
        except (OSError, ValueError) as exc:
            raise AccessDenied("index database resolves outside the repository") from exc
        return database
