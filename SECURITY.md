# Security model

## Threat model

The server assumes repository files may contain prompt injection, credentials,
or symlinks prepared by another user. It treats all repository content as
untrusted data and does not execute source, shell commands, hooks, plugins, or
repository configuration.

The server is local-first. Its only supported transport is MCP stdio, and the
implementation contains no cloud summarizer or generic outbound HTTP client.
Adding an external provider requires a separate review. In particular, any
future outbound feature must call `FilePolicy.validate_read` first and require
an explicit operator opt-in.

## Filesystem guarantees

Every source read goes through `FilePolicy`:

1. input must be relative and cannot contain `..` or NUL bytes;
2. VCS metadata, common secret files, private-key formats, and `.gitignore`
   matches are denied;
3. every existing path component must not be a symlink;
4. the resolved path must remain below the configured root;
5. file size, text-ness, and MCP response limits are enforced.

Index traversal applies the same policy and never follows symlinks. Database
creation is restricted to `.codebase-index/` below the root, with checks on the
directory and database file before creation.

These checks reduce path traversal and accidental disclosure risks. They are
not a substitute for OS-level permissions, read-only workspaces, containers,
or a dedicated unprivileged account.

## Dependency and release hygiene

- Keep the MCP SDK constrained to the reviewed major range.
- Run `pip-audit` and `bandit` before releases.
- Review the complete resolved dependency tree; the manifest alone is not a
  vulnerability scan.
- Run the security regression tests whenever the policy, indexer, or server
  tools change.

## Reporting

Please do not include credentials or private source in an issue. Report a
reproducible security issue privately to the repository owner, including the
affected version, operating system, minimal reproduction, and impact.
