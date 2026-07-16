"""Fine-grained action classes + the mode×action decision matrix.

The base PermissionPolicy (policy.py) gates the coarse READ/WRITE/EXECUTE
capability. This refines EXECUTE by *classifying the command*: a local `pytest`
is not the same risk as `git push` or `terraform apply`. That's what makes
`auto_workspace` meaningfully safer than `full` — workspace edits and local
commands run automatically, but anything that reaches the network, a remote, a
package registry, or a deploy target needs operator approval.
"""

from __future__ import annotations

import re
from enum import Enum

from .policy import Capability, Decision


class Action(str, Enum):
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    COMMAND_SAFE = "command_safe"
    COMMAND_ARBITRARY = "command_arbitrary"
    NETWORK = "network"
    PACKAGE_INSTALL = "package_install"
    GIT_LOCAL_WRITE = "git_local_write"
    GIT_REMOTE_WRITE = "git_remote_write"
    DATABASE_MUTATION = "database_mutation"
    DEPLOYMENT = "deployment"
    # Federated MCP servers: listing them is a read; CALLING one can do anything
    # (browser control, DBs, messages), so it never auto-runs below full.
    EXTERNAL_READ = "external_read"
    EXTERNAL_CALL = "external_call"


# Command patterns → action class (first match wins). High-signal only.
# HONESTY NOTE: this classifier is advisory hardening, NOT a security boundary.
# A regex cannot determine what arbitrary shell code does (`python -c` one-liners
# will always slip through). The real boundaries are the mode table (deny/ask)
# and the Docker sandbox with network=none. HARNESS_ARBITRARY_COMMANDS=ask makes
# auto_workspace ask for anything unrecognized, closing the fall-through.
_GIT_OPTS = r"(?:\s+-[A-Za-z](?:\s+\S+)?|\s+--[\w-]+(?:=\S+)?)*"  # e.g. `-C .`, `--no-pager`
_CMD_PATTERNS: tuple[tuple[Action, re.Pattern], ...] = (
    (Action.GIT_REMOTE_WRITE, re.compile(rf"\bgit{_GIT_OPTS}\s+(push|pull|fetch|remote|clone)\b", re.I)),
    (Action.GIT_REMOTE_WRITE, re.compile(r"\bgh\s+(pr|repo|release|api)\b", re.I)),
    (Action.PACKAGE_INSTALL, re.compile(r"\b(npm|pnpm|yarn|pip|pip3|poetry|cargo|gem|apt|apt-get|brew|go)\s+(install|add|get)\b", re.I)),
    (Action.PACKAGE_INSTALL, re.compile(r"\bnpx\b|\buvx\b", re.I)),
    (Action.DEPLOYMENT, re.compile(r"\b(kubectl|helm|terraform|serverless|vercel|netlify|fly|heroku|docker\s+push)\b", re.I)),
    (Action.DEPLOYMENT, re.compile(r"\baws\s+|\bgcloud\s+|\baz\s+", re.I)),
    (Action.NETWORK, re.compile(r"\b(curl|wget|nc|netcat|ssh|scp|rsync|telnet|ftp)\b", re.I)),
    # PowerShell + Windows download primitives
    (Action.NETWORK, re.compile(r"\b(Invoke-WebRequest|Invoke-RestMethod|iwr|irm|Start-BitsTransfer|bitsadmin)\b|certutil\s+-urlcache", re.I)),
    # Best-effort: inline python/node one-liners that obviously reach the network
    (Action.NETWORK, re.compile(r"\b(python[0-9.]*|node)\s+(-c|-e)\s+.*(urllib|urlopen|requests\.|socket\.|http\.client|fetch\()", re.I | re.S)),
    (Action.DATABASE_MUTATION, re.compile(r"\b(psql|mysql|mongo|redis-cli|sqlite3)\b|\b(DROP|TRUNCATE|DELETE\s+FROM|ALTER)\b", re.I)),
)


# ---- positive SAFE tier (checklist 0.6) -------------------------------------
# Everyday dev commands that auto-run even under HARNESS_ARBITRARY_COMMANDS=ask,
# so ask-mode gates the unknown without nagging about `pytest`. Safety rules:
#   * the WHOLE command must match (fullmatch), so `pytest; evil.exe` never
#     rides in on pytest's back;
#   * commands containing shell metacharacters (chaining, subshells, redirects)
#     are never safe-classified — they fall through to ARBITRARY;
#   * risky patterns above are checked FIRST, so `pip install` stays gated.
_SHELL_META = re.compile(r"[;&|`$<>{}\n]")
_SAFE_FULL: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.I) for p in (
        r"(?:python[0-9.]*\s+-m\s+)?pytest(?:\s.*)?",
        r"python[0-9.]*\s+-m\s+(?:unittest|mypy|ruff|black|isort|flake8|tox|compileall)(?:\s.*)?",
        r"(?:tox|mypy|ruff|black|isort|flake8|pylint)(?:\s.*)?",
        r"(?:npm|pnpm|yarn)\s+(?:test|run\s+[\w:.-]+)(?:\s.*)?",
        r"(?:jest|vitest|tsc|eslint|prettier)(?:\s.*)?",
        r"cargo\s+(?:test|build|check|clippy|fmt)(?:\s.*)?",
        r"go\s+(?:test|build|vet|fmt)(?:\s.*)?",
        r"dotnet\s+(?:test|build)(?:\s.*)?",
        r"make(?:\s+[\w.-]+)?",
        r"echo(?:\s.*)?",
        r"(?:ls|dir|pwd|whoami|Get-ChildItem|Get-Location)(?:\s.*)?",
    )
)
# Local-only, inspection/staging git operations. Hook-capable `git commit` is
# deliberately excluded: raw run_command uses the host shell, not gitcmd's
# hook-neutralized argv adapter, so it must pass through operator approval.
_GIT_LOCAL_FULL = re.compile(
    r"git\s+(?:-C\s+\S+\s+)?(?:--no-pager\s+)?"
    r"(?:status|log|diff|show|branch|add|checkout|switch|restore|stash|"
    r"rev-parse|describe|blame|tag|worktree\s+list)(?:\s.*)?",
    re.I,
)


def classify_command(command: str) -> Action:
    for action, pat in _CMD_PATTERNS:
        if pat.search(command or ""):
            return action
    c = (command or "").strip()
    if c and not _SHELL_META.search(c):
        if _GIT_LOCAL_FULL.fullmatch(c):
            return Action.GIT_LOCAL_WRITE
        if any(p.fullmatch(c) for p in _SAFE_FULL):
            return Action.COMMAND_SAFE
    return Action.COMMAND_ARBITRARY


def action_for(capability: Capability, command: str | None = None) -> Action:
    if capability is Capability.READ:
        return Action.FILE_READ
    if capability is Capability.WRITE:
        return Action.FILE_WRITE
    if capability is Capability.EXECUTE:
        return classify_command(command) if command is not None else Action.COMMAND_ARBITRARY
    return Action.COMMAND_ARBITRARY


# Actions that automatically run in auto_workspace (everything else there ASKs).
# EXTERNAL_CALL is deliberately NOT here: an external MCP tool can do anything,
# so it always asks below full.
_AUTO_WORKSPACE_ALLOW = {
    Action.FILE_READ, Action.FILE_WRITE, Action.FILE_DELETE,
    Action.COMMAND_SAFE, Action.COMMAND_ARBITRARY, Action.GIT_LOCAL_WRITE,
    Action.EXTERNAL_READ,
}

_READS = {Action.FILE_READ, Action.EXTERNAL_READ}


def decide(mode: str, action: Action, arbitrary_commands: str = "allow") -> Decision:
    if mode in ("full", "bypass_sandboxed"):
        return Decision.ALLOW
    if mode in ("read_only", "plan"):
        return Decision.ALLOW if action in _READS else Decision.DENY
    if mode == "build_ask":
        return Decision.ALLOW if action in _READS else Decision.ASK
    if mode == "auto_workspace":
        # HARNESS_ARBITRARY_COMMANDS=ask closes the classifier fall-through:
        # anything not positively recognized asks instead of auto-running.
        if action is Action.COMMAND_ARBITRARY and arbitrary_commands == "ask":
            return Decision.ASK
        return Decision.ALLOW if action in _AUTO_WORKSPACE_ALLOW else Decision.ASK
    return Decision.DENY  # unknown mode: fail closed
