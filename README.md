# Safe Codebase MCP

Safe Codebase MCP is a local-first MCP server for indexing source symbols and
reading approved source ranges. It is designed around the security problems
that occur when an AI agent can ask a local tool to read arbitrary paths.

## Security defaults

- stdio transport only; the server does not open an HTTP or TCP listener
- no cloud summarization or outbound source-content feature
- absolute paths and `..` traversal are rejected
- `.git`, common credential files, `.env*`, private-key formats, and ignored
  files are denied on every source-read path
- symlinked files and directories are skipped or rejected
- source and MCP response sizes are bounded
- the SQLite database is created below `.codebase-index/` with symlink checks
- tool results label repository content as untrusted data

The project uses a small standard-library scanner instead of executing project
code or loading repository-controlled plugins. It extracts common Python,
JavaScript/TypeScript, Rust, and class/function declarations without running
the source.

## Install and run

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
safe-codebase-mcp --root /path/to/repository
```

Configure the MCP client to launch the command over stdio. The configured root
is the only repository that can be inspected. The first `index_repository`
call creates `.codebase-index/index.sqlite3` inside that root.

## Development checks

```bash
python -m unittest discover -s tests -v
python -m pip install -e '.[dev]'
bandit -r src/safe_codebase_mcp -ll
pip-audit
```

This repository intentionally does not include a lockfile because the MCP SDK
is installed from the package index at deployment time; production users
should lock the resolved environment in their own release process and review
the resulting dependency tree.

## Scope and limitations

This is a local index and retrieval service, not a sandbox for untrusted code.
Do not run it with a repository root that contains credentials you need to keep
available to the MCP process. File-policy checks are designed to prevent
accidental exposure through the tools, but no process with filesystem access
can protect against a compromised operating system or a privileged debugger.

See [SECURITY.md](SECURITY.md) for the threat model and reporting guidance.
