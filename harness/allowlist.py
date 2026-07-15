"""Remembered per-project command approvals (checklist 0.7).

`HARNESS_ARBITRARY_COMMANDS=ask` gates every unrecognized command behind a
one-shot approval. That is safe but repetitive: the operator would approve
`npm run generate` every single time. This module lets the operator say
"always allow this EXACT command in this project" — once.

Security properties:
  * The file lives in the STATE DIR, outside every workspace root, so the
    model's path-gated tools can never write it. Only the local CLI and the
    (localhost-only) cockpit can — the model cannot author its own allowlist.
  * Matching is exact (whitespace-normalized), per-project. Allowing
    `npm run generate` in project A allows nothing else, nowhere else.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _file(state_dir: Path) -> Path:
    return Path(state_dir) / "allowed_commands.json"


def _norm_cmd(command: str) -> str:
    return " ".join((command or "").split())


def _norm_ws(workspace) -> str:
    return os.path.realpath(str(workspace)) if workspace else ""


def load(state_dir: Path) -> dict[str, list[str]]:
    f = _file(state_dir)
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return {str(k): [str(c) for c in v] for k, v in data.items()} if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def _save(state_dir: Path, data: dict[str, list[str]]) -> None:
    _file(state_dir).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def allow(state_dir: Path, workspace, command: str) -> str:
    """Remember an exact command for a project. Returns the normalized command."""
    ws, cmd = _norm_ws(workspace), _norm_cmd(command)
    if not ws or not cmd:
        raise ValueError("allow() needs both a workspace path and a command")
    data = load(state_dir)
    entry = data.setdefault(ws, [])
    if cmd not in entry:
        entry.append(cmd)
        _save(state_dir, data)
    return cmd


def revoke(state_dir: Path, workspace, command: str) -> bool:
    ws, cmd = _norm_ws(workspace), _norm_cmd(command)
    data = load(state_dir)
    entry = data.get(ws, [])
    if cmd in entry:
        entry.remove(cmd)
        if not entry:
            data.pop(ws, None)
        _save(state_dir, data)
        return True
    return False


def is_allowed(state_dir: Path, workspaces, command: str) -> bool:
    """True if this exact command was remembered for ANY of the given workspace
    paths (a task may run in a worktree while the approval was stored against
    the project folder — both are checked)."""
    cmd = _norm_cmd(command)
    if not cmd:
        return False
    data = load(state_dir)
    for ws in workspaces:
        if ws and cmd in data.get(_norm_ws(ws), []):
            return True
    return False
