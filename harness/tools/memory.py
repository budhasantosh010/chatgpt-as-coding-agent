"""Tiered, model-writable memory: global ↔ project ↔ task.

Facts the agent deliberately saves across sessions. Three scopes:
  * global  — applies everywhere (your conventions, preferences).
  * project — shared by a repo AND all its worktrees (resolved via git's common
              dir, so a worktree inherits the project's memory). Default.
  * task    — scoped to the current task_id (or the workspace if no task).

Stored under the state dir so it never pollutes the repo. Distinct from
AGENTS.md/CLAUDE.md (user-authored rules) and the session journal (auto events).
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from ..context import HarnessContext
from ..session import _now_iso
from ..statefile import locked, read_json, write_json_atomic

_SCOPES = ("global", "project", "task")


def _mem_dir(hc: HarnessContext) -> Path:
    d = hc.config.state_dir / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _project_key(hc: HarnessContext) -> str:
    """Identify the project so worktrees share memory: hash the repo root derived
    from git's common dir (same for a repo and all its worktrees). Falls back to
    the workspace path when not a git repo."""
    ws = hc.active_workspace
    try:
        from . import gitcmd

        r = await gitcmd.git(hc, ws, "rev-parse", "--git-common-dir")
        if r.returncode == 0 and r.stdout.strip():
            common = Path(r.stdout.strip())
            if not common.is_absolute():
                common = ws / common
            repo_root = os.path.realpath(str(common.parent))
            return hashlib.sha256(repo_root.encode("utf-8")).hexdigest()[:16]
    except Exception:  # noqa: BLE001 - any git failure -> path fallback
        pass
    return hashlib.sha256(str(ws).encode("utf-8")).hexdigest()[:16]


async def _scope_path(hc: HarnessContext, scope: str) -> Path:
    if scope == "global":
        return _mem_dir(hc) / "global.json"
    if scope == "task":
        if hc.task_id:
            return _mem_dir(hc) / f"task-{hc.task_id}.json"
        assert hc.session is not None
        return hc.session.dir / "memory.json"  # legacy per-workspace fallback
    return _mem_dir(hc) / f"proj-{await _project_key(hc)}.json"  # project (default)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "note"


def _next_auto_id(items: list[dict]) -> str:
    n = 0
    for it in items:
        m = re.fullmatch(r"m(\d+)", it.get("id", ""))
        if m:
            n = max(n, int(m.group(1)))
    return f"m{n + 1}"


async def _all_tiers(hc: HarnessContext) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for scope in _SCOPES:
        path = await _scope_path(hc, scope)
        for it in read_json(path, []):
            out.append((scope, it))
    return out


async def load_memories(hc: HarnessContext) -> list[dict]:
    """Merged memories across all tiers (used by open_workspace + callers)."""
    hc.require_workspace()
    return [it for _scope, it in await _all_tiers(hc)]


async def remember(hc: HarnessContext, text: str, key: str | None = None, scope: str = "project") -> str:
    hc.require_workspace()
    if not text or not text.strip():
        raise ValueError("Cannot remember empty text.")
    if scope not in _SCOPES:
        raise ValueError(f"scope must be one of {_SCOPES}, got {scope!r}")
    path = await _scope_path(hc, scope)
    with locked(path):
        items = read_json(path, [])
        mem_id = _slug(key) if key else None
        if mem_id:
            for item in items:
                if item["id"] == mem_id:
                    item["text"] = text
                    item["created"] = _now_iso()
                    write_json_atomic(path, items)
                    hc.log("remember", id=mem_id, scope=scope, updated=True)
                    return f"Updated {scope} memory '{mem_id}'."
        if not mem_id:
            mem_id = _next_auto_id(items)
        items.append({"id": mem_id, "text": text, "created": _now_iso()})
        write_json_atomic(path, items)
    hc.log("remember", id=mem_id, scope=scope)
    return f"Saved {scope} memory '{mem_id}'."


async def recall(hc: HarnessContext, query: str | None = None) -> str:
    hc.require_workspace()
    tiers = await _all_tiers(hc)
    if query:
        q = query.lower()
        tiers = [(s, it) for s, it in tiers if q in it["text"].lower() or q in it["id"].lower()]
    if not tiers:
        return (
            f"No memories matching {query!r}." if query
            else "No memories yet. Use remember(text) to save one."
        )
    return "# Memories\n" + "\n".join(f"- [{it['id']}] ({s}) {it['text']}" for s, it in tiers)


async def forget(hc: HarnessContext, key: str) -> str:
    hc.require_workspace()
    for scope in _SCOPES:
        path = await _scope_path(hc, scope)
        with locked(path):
            items = read_json(path, [])
            kept = [it for it in items if it["id"] != key]
            if len(kept) != len(items):
                write_json_atomic(path, kept)
                hc.log("forget", id=key, scope=scope)
                return f"Forgot {scope} memory {key!r}."
    return f"No memory with id {key!r}. Use recall() to list ids."
