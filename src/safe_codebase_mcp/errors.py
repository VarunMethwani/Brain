"""Errors exposed by the security policy and service layer."""


class CodebaseError(Exception):
    """Base class for expected application errors."""


class AccessDenied(CodebaseError):
    """Raised when a path is outside the supported read/write policy."""


class FileTooLarge(CodebaseError):
    """Raised when a file exceeds the configured safety limit."""


class SymbolNotFound(CodebaseError):
    """Raised when a requested indexed symbol does not exist."""
