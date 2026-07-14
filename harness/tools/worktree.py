"""Git worktree-per-task: isolate risky work on its own branch + working copy.

Worktrees are created under the harness-owned worktrees root (an allowed
workspace root), so once created you open_workspace the returned path and work
there without ever touching your main checkout.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..context import HarnessContext
from . import gitcmd


async def _git(hc: HarnessContext, base: Path, *args: str, timeout: int = 60):
    return await gitcmd.git(hc, base, *args, timeout=timeout)


async def _repo_root(hc: HarnessContext, ws: Path) -> Path | None:
    r = await _git(hc, ws, "rev-parse", "--show-toplevel")
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return Path(os.path.realpath(r.stdout.strip()))


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")[:60] or "wt"


def _worktree_dir(hc: HarnessContext, repo_root: Path, safe_name: str) -> Path:
    return hc.config.state_dir / "worktrees" / repo_root.name / safe_name


async def create_worktree(hc: HarnessContext, name: str, base: str | None = None) -> str:
    ws = hc.require_workspace()
    root = await _repo_root(hc, ws)
    if root is None:
        return "Not a git repository. Worktrees need git."
    safe = _safe(name)
    target = _worktree_dir(hc, root, safe)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return f"A worktree path already exists at {target}. Pick another name or remove it."

    args = ["worktree", "add", "-b", safe, str(target)]
    if base:
        args.append(base)
    r = await _git(hc, root, *args)
    if r.returncode != 0:
        return f"Error creating worktree: {r.stderr.strip() or r.stdout.strip()}"
    hc.log("create_worktree", name=safe, path=str(target))
    return (
        f"Created worktree '{safe}' on new branch '{safe}' at:\n{target}\n"
        "Open it with open_workspace(<path>) to work there in isolation."
    )


async def list_worktrees(hc: HarnessContext) -> str:
    ws = hc.require_workspace()
    root = await _repo_root(hc, ws)
    if root is None:
        return "Not a git repository."
    r = await _git(hc, root, "worktree", "list")
    return r.stdout.strip() or "No worktrees."


async def remove_worktree(hc: HarnessContext, name: str) -> str:
    ws = hc.require_workspace()
    root = await _repo_root(hc, ws)
    if root is None:
        return "Not a git repository."
    safe = _safe(name)
    target = _worktree_dir(hc, root, safe)
    r = await _git(hc, root, "worktree", "remove", "--force", str(target))
    if r.returncode != 0:
        return f"Error removing worktree: {r.stderr.strip() or r.stdout.strip()}"
    hc.log("remove_worktree", name=safe)
    return f"Removed worktree '{safe}'."
