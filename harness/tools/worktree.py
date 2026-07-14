"""Git worktree-per-task: isolate risky work on its own branch + working copy.

Worktrees are created under the harness-owned worktrees root (an allowed
workspace root), so once created you open_workspace the returned path and work
there without ever touching your main checkout.
"""

from __future__ import annotations

import hashlib
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
    # Namespace by a hash of the FULL repo path, not just the basename, so two
    # different repos that happen to share a folder name can't collide.
    digest = hashlib.sha256(str(repo_root).encode("utf-8")).hexdigest()[:8]
    return hc.config.state_dir / "worktrees" / f"{repo_root.name}-{digest}" / safe_name


async def create_for_task(server, workspace: Path, task_id: str,
                          base: str | None = None) -> tuple[Path | None, str | None, str]:
    """Create and bind a worktree for a task (the physical-isolation half of
    task_id). Returns (worktree_path, base_commit, note); (None, base, note)
    means the task works in the shared checkout (not a git repo / no commits).
    Takes the server (executor + config), not a session context — it runs
    during start_task, before any session exists."""
    from types import SimpleNamespace

    shim = SimpleNamespace(executor=server.executor, config=server.config)
    root = await _repo_root(shim, workspace)
    if root is None:
        return None, None, "shared checkout (not a git repository)"
    head = await _git(shim, root, "rev-parse", "HEAD")
    base_commit = head.stdout.strip() if head.returncode == 0 else None
    if not base_commit:
        return None, None, "shared checkout (repository has no commits yet)"
    safe = _safe(f"task-{task_id}")
    target = _worktree_dir(shim, root, safe)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return target, base_commit, f"reusing existing worktree at {target}"
    args = ["worktree", "add", "-b", safe, str(target)]
    if base:
        args.append(base)
    r = await _git(shim, root, *args)
    if r.returncode != 0:
        err = r.stderr.strip() or r.stdout.strip()
        return None, base_commit, f"shared checkout (worktree creation failed: {err[:200]})"
    return target, base_commit, f"isolated worktree on branch '{safe}'"


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


async def remove_worktree(hc: HarnessContext, name: str, force: bool = False) -> str:
    ws = hc.require_workspace()
    root = await _repo_root(hc, ws)
    if root is None:
        return "Not a git repository."
    safe = _safe(name)
    target = _worktree_dir(hc, root, safe)
    # Try a safe remove first; only force (which discards uncommitted work) when
    # the caller explicitly asks. Prevents silent loss of in-progress changes.
    args = ["worktree", "remove", str(target)]
    if force:
        args.insert(2, "--force")
    r = await _git(hc, root, *args)
    if r.returncode != 0:
        err = (r.stderr.strip() or r.stdout.strip())
        if not force and ("dirty" in err.lower() or "contains modified" in err.lower() or "use --force" in err.lower()):
            return (
                f"Worktree '{safe}' has uncommitted changes. Commit them, or call "
                f"remove_worktree('{name}', force=true) to discard and remove."
            )
        return f"Error removing worktree: {err}"
    hc.log("remove_worktree", name=safe, force=force)
    return f"Removed worktree '{safe}'."
