from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from safe_codebase_mcp.db import IndexDatabase
from safe_codebase_mcp.errors import AccessDenied
from safe_codebase_mcp.indexer import CodebaseIndexer
from safe_codebase_mcp.policy import FilePolicy
from safe_codebase_mcp.service import CodebaseService


class SecurityRegressionTests(unittest.TestCase):
    def make_repo(self) -> tuple[tempfile.TemporaryDirectory[str], Path, FilePolicy]:
        handle = tempfile.TemporaryDirectory()
        root = Path(handle.name)
        (root / ".gitignore").write_text("ignored.py\nbuild/\n", encoding="utf-8")
        (root / "safe.py").write_text("def hello():\n    return 'ok'\n", encoding="utf-8")
        (root / "ignored.py").write_text("def should_not_be_seen():\n    return 'ignored'\n", encoding="utf-8")
        (root / ".env").write_text("TOKEN=do-not-read\n", encoding="utf-8")
        (root / ".git").mkdir()
        (root / ".git" / "config").write_text("[remote]\nurl=secret\n", encoding="utf-8")
        (root / "build").mkdir()
        (root / "build" / "generated.py").write_text("def generated(): pass\n", encoding="utf-8")
        return handle, root, FilePolicy(root)

    def test_sensitive_and_ignored_files_are_denied(self) -> None:
        handle, _, policy = self.make_repo()
        try:
            for path in (".env", ".git/config", "ignored.py", "build/generated.py"):
                with self.subTest(path=path):
                    with self.assertRaises(AccessDenied):
                        policy.read_text(path)
        finally:
            handle.cleanup()

    def test_traversal_and_absolute_paths_are_denied(self) -> None:
        handle, _, policy = self.make_repo()
        try:
            for path in ("../outside.py", "safe.py/../../outside.py", "/etc/passwd"):
                with self.subTest(path=path):
                    with self.assertRaises(AccessDenied):
                        policy.read_text(path)
        finally:
            handle.cleanup()

    def test_indexer_never_follows_symlinked_source(self) -> None:
        handle, root, policy = self.make_repo()
        try:
            outside = Path(handle.name).parent / f"outside-{os.getpid()}.py"
            outside.write_text("def outside_secret(): pass\n", encoding="utf-8")
            link = root / "linked.py"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not available in this environment")
            with self.assertRaises(AccessDenied):
                policy.read_text("linked.py")
            database = IndexDatabase(policy.database_path())
            try:
                CodebaseIndexer(policy, database).index()
                indexed_paths = {item["path"] for item in database.list_files()}
                self.assertIn("safe.py", indexed_paths)
                self.assertNotIn("linked.py", indexed_paths)
            finally:
                database.close()
        finally:
            handle.cleanup()

    def test_line_range_reads_use_the_same_policy(self) -> None:
        handle, _, policy = self.make_repo()
        database = IndexDatabase(policy.database_path())
        try:
            service = CodebaseService(policy, database)
            service.index_repository()
            indexed_paths = {item["path"] for item in service.list_files()["files"]}
            self.assertEqual({"safe.py"}, indexed_paths)
            with self.assertRaises(AccessDenied):
                service.read_source("ignored.py", 1, 1)
            result = service.read_symbol_source("safe.py", "hello")
            self.assertEqual("def hello():\n    return 'ok'", result["content"])
        finally:
            database.close()
            handle.cleanup()

    def test_database_symlink_is_denied(self) -> None:
        handle, root, policy = self.make_repo()
        try:
            target = Path(handle.name).parent / f"db-target-{os.getpid()}"
            target.mkdir()
            storage = root / ".codebase-index"
            try:
                storage.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not available in this environment")
            with self.assertRaises(AccessDenied):
                policy.database_path()
        finally:
            handle.cleanup()


if __name__ == "__main__":
    unittest.main()
