"""Security primitives: path confinement, secret-file blocking, command policy.

These are enforced in code so that a bad tool call — whether from a model
mistake or prompt injection embedded in repo content — cannot reach outside the
approved workspace roots or run a catastrophic command.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path


class SecurityError(Exception):
    """Raised when an operation violates a security boundary."""


def _real(path: Path) -> Path:
    """Best-effort realpath that also works for not-yet-existing files.

    Resolves symlinks on the existing prefix and normalizes the rest, so a
    symlink can't be used to escape a workspace root.
    """
    return Path(os.path.realpath(str(path)))


def is_within(child: Path, parent: Path) -> bool:
    try:
        _real(child).relative_to(_real(parent))
        return True
    except ValueError:
        return False


def resolve_in_roots(
    path_str: str,
    roots: list[Path],
    *,
    base: Path | None = None,
) -> Path:
    """Resolve ``path_str`` and assert it lives inside an approved root.

    Relative paths resolve against ``base`` (the active workspace). Absolute
    paths are taken as-is. Either way the realpath must be within one of
    ``roots`` or a :class:`SecurityError` is raised.
    """
    if not path_str or not str(path_str).strip():
        raise SecurityError("Empty path is not allowed.")

    p = Path(path_str)
    if not p.is_absolute():
        if base is None:
            raise SecurityError(
                "No active workspace. Call open_workspace(path) before using a "
                "relative path, or pass an absolute path inside an approved root."
            )
        p = base / p

    real = _real(p)
    for root in roots:
        if is_within(real, root):
            return real

    allowed = ", ".join(str(r) for r in roots)
    raise SecurityError(
        f"Path {real} is outside the approved workspace roots. Allowed roots: {allowed}"
    )


def is_secret_path(path: Path, globs: list[str]) -> bool:
    """True if any path component or the full path matches a secret glob."""
    name = path.name
    parts = path.parts
    full = str(path).replace("\\", "/")
    for pattern in globs:
        pat = pattern.replace("\\", "/")
        if fnmatch.fnmatch(name, pat):
            return True
        if "/" in pat and fnmatch.fnmatch(full, pat if pat.startswith("*") else f"*{pat}"):
            return True
        if any(fnmatch.fnmatch(part, pat) for part in parts):
            return True
        # Treat ".ssh" dir contents as secret regardless of filename.
    if ".ssh" in parts or ".gnupg" in parts:
        return True
    return False


def assert_readable(path: Path, globs: list[str]) -> None:
    if is_secret_path(path, globs):
        raise SecurityError(
            f"Refusing to read {path.name}: it matches a secret/credential pattern. "
            "Its contents would be exposed to ChatGPT. Add it to an allowlist "
            "deliberately if you really need this."
        )


def assert_writable(path: Path, globs: list[str]) -> None:
    if is_secret_path(path, globs):
        raise SecurityError(
            f"Refusing to write {path.name}: it matches a secret/credential pattern."
        )


# Catastrophic command patterns. This is a backstop against disaster, not a
# sandbox — real isolation for untrusted use means a container/VM. For personal
# use on your own machine these are the "never, obviously" cases.
_DESTRUCTIVE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\brm\s+(-[a-z]*\s+)*-[a-z]*[rf][a-z]*\s+(-[a-z]*\s+)*(/|~|\$HOME)(\s|$)", re.I),
    re.compile(r"\brm\s+-rf\s+\*", re.I),
    re.compile(r"\bmkfs\.", re.I),
    re.compile(r"\bdd\b.*\bof=/dev/", re.I),
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", re.I),  # fork bomb
    re.compile(r">\s*/dev/sd[a-z]", re.I),
    re.compile(r"\bformat\s+[a-z]:", re.I),
    re.compile(r"\b(del|erase)\b.*/[sqf].*[a-z]:\\", re.I),
    re.compile(r"Remove-Item\b.*-Recurse.*-Force.*(\\|/)(\s|$)", re.I),
    re.compile(r"\b(shutdown|reboot|halt|poweroff)\b", re.I),
    re.compile(r"\bgit\s+push\b.*--force", re.I),
)


def assert_command_allowed(command: str) -> None:
    if not command or not command.strip():
        raise SecurityError("Empty command.")
    for pattern in _DESTRUCTIVE_PATTERNS:
        if pattern.search(command):
            raise SecurityError(
                "Refusing to run this command: it matches a destructive-command "
                f"guard ({pattern.pattern!r}). Run it yourself if you truly intend to."
            )
