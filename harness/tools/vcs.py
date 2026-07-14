"""Guarded version-control actions: git_commit (local) + open_pr (remote, via gh).

Unlike the harness's checkpoint plumbing (which runs git hardened — hooks off,
config ignored), a real commit must honor the user's git identity, config, and
pre-commit hooks, so it runs gitcmd with hardened=False.
"""

from __future__ import annotations

from ..context import HarnessContext
from . import gitcmd


async def _repo_root(hc: HarnessContext, ws):
    r = await gitcmd.git(hc, ws, "rev-parse", "--show-toplevel", hardened=False)
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
    if add_all:
        add = await gitcmd.git(hc, root, "add", "-A", hardened=False)
        if add.returncode != 0:
            return f"Error staging: {add.stderr.strip()}"
    r = await gitcmd.git(hc, root, "commit", "-m", message, hardened=False)
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
