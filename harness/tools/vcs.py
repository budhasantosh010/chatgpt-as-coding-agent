"""Guarded version-control actions: git_commit (local) + open_pr (remote, via gh).

A real commit honors the user's git identity and config — but NOT the repo's
own hooks by default (hardened="no_hooks"): a cloned repo's pre-commit hook
must not execute code on the host just because the model committed. Operators
who want their hooks to run set HARNESS_COMMIT_HOOKS=true.
"""

from __future__ import annotations

from ..context import HarnessContext
from . import gitcmd


def _commit_hardening(hc: HarnessContext):
    return False if getattr(hc.config, "commit_hooks", False) else "no_hooks"


async def _repo_root(hc: HarnessContext, ws):
    r = await gitcmd.git(hc, ws, "rev-parse", "--show-toplevel", hardened="no_hooks")
    if r.returncode != 0 or not r.stdout.strip():
        return None
    from pathlib import Path
    return Path(r.stdout.strip())


async def git_commit(hc: HarnessContext, message: str, add_all: bool = True) -> str:
    ws = hc.require_workspace()
    if not message or not message.strip():
        raise ValueError("A commit needs a message.")
    root = await _repo_root(hc, ws)
    if root is None:
        return "Not a git repository. Run: git init"
    level = _commit_hardening(hc)
    if add_all:
        add = await gitcmd.git(hc, root, "add", "-A", hardened=level)
        if add.returncode != 0:
            return f"Error staging: {add.stderr.strip()}"
    r = await gitcmd.git(hc, root, "commit", "-m", message, hardened=level)
    out = (r.stdout + "\n" + r.stderr).strip()
    if r.returncode != 0:
        if "nothing to commit" in out.lower():
            return "Nothing to commit (working tree clean)."
        if "please tell me who you are" in out.lower() or "user.email" in out.lower():
            return ("Commit failed: git identity not configured. Set it once:\n"
                    "  git config --global user.email you@example.com\n"
                    "  git config --global user.name \"Your Name\"")
        return f"Commit failed:\n{out}"
    hc.log("git_commit")
    return f"Committed.\n{out}"
