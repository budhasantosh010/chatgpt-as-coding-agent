"""Git-based review + safety net: diff, checkpoint, list, restore.

Checkpoints are full-workspace snapshots captured with git plumbing into a
private ref namespace (refs/harness/checkpoints/*) using a throwaway index — so
they never disturb the user's branch, commit history, or staging area. Restore
reverts the working tree to a snapshot, including removing files added since.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime
from pathlib import Path

from ..context import HarnessContext
from ..security import SecurityError, is_within
from ..session import _now_iso  # reuse the timestamp helper
from . import gitcmd

_REF_PREFIX = "refs/harness/checkpoints/"

# Identity for the snapshot commits so commit-tree never fails on a machine
# without a configured git user. These commits live only in the private ref.
_IDENT_ENV = {
    "GIT_AUTHOR_NAME": "chatgpt-code-harness",
    "GIT_AUTHOR_EMAIL": "harness@localhost",
    "GIT_COMMITTER_NAME": "chatgpt-code-harness",
    "GIT_COMMITTER_EMAIL": "harness@localhost",
}


async def _git(hc: HarnessContext, base: Path, *args: str, env: dict | None = None, timeout: int = 60):
    merged = dict(_IDENT_ENV)
    if env:
        merged.update(env)
    return await gitcmd.git(hc, base, *args, env=merged, timeout=timeout)


async def _repo_root(hc: HarnessContext, ws: Path) -> Path | None:
    r = await _git(hc, ws, "rev-parse", "--show-toplevel")
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return Path(os.path.realpath(r.stdout.strip()))


def _guard_root(hc: HarnessContext, root: Path) -> Path:
    if not any(is_within(root, r) for r in hc.config.workspace_roots):
        raise SecurityError(
            f"Git repo root {root} is outside the approved workspace roots. "
            "Open the repository root as the workspace to use checkpoints."
        )
    return root


def _cp_file(hc: HarnessContext) -> Path:
    assert hc.session is not None
    return hc.session.dir / "checkpoints.json"


def _load_checkpoints(hc: HarnessContext) -> list[dict]:
    import json

    f = _cp_file(hc)
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []


def _save_checkpoints(hc: HarnessContext, records: list[dict]) -> None:
    import json

    _cp_file(hc).write_text(json.dumps(records, indent=2), encoding="utf-8")


def _tmp_index(hc: HarnessContext) -> Path:
    d = hc.config.state_dir / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"idx-{secrets.token_hex(6)}"


# ---- tools -----------------------------------------------------------------


async def git_diff(hc: HarnessContext, path: str | None = None) -> str:
    ws = hc.require_workspace()
    root = await _repo_root(hc, ws)
    if root is None:
        return "Not a git repository. Run: git init"

    status = (await _git(hc, root, "status", "--short")).stdout.strip()
    head = await _git(hc, root, "rev-parse", "--verify", "HEAD")
    diff_args = ["diff", "HEAD"] if head.returncode == 0 else ["diff"]
    if path:
        diff_args += ["--", path]
    diff = (await _git(hc, root, *diff_args)).stdout

    max_chars = hc.config.max_output_chars
    truncated = ""
    if len(diff) > max_chars:
        diff = diff[:max_chars]
        truncated = f"\n[diff truncated at {max_chars} chars]"

    parts = [f"# git status ({root})", "```", status or "(clean)", "```"]
    if diff.strip():
        parts += ["# diff vs HEAD", "```diff", diff + truncated, "```"]
    return "\n".join(parts)


async def create_checkpoint(hc: HarnessContext, label: str | None = None) -> str:
    ws = hc.require_workspace()
    root = await _repo_root(hc, ws)
    if root is None:
        return "Not a git repository. Run: git init  (checkpoints need git)."
    _guard_root(hc, root)

    label = (label or "checkpoint").strip()
    tmp = _tmp_index(hc)
    env = {"GIT_INDEX_FILE": str(tmp)}
    try:
        add = await _git(hc, root, "add", "-A", env=env)
        if add.returncode != 0:
            return f"Error staging snapshot: {add.stderr.strip()}"
        tree = (await _git(hc, root, "write-tree", env=env)).stdout.strip()
        if not tree:
            return "Error: could not write snapshot tree."
        head = await _git(hc, root, "rev-parse", "--verify", "HEAD")
        ct_args = ["commit-tree", tree, "-m", f"harness checkpoint: {label}"]
        if head.returncode == 0:
            ct_args += ["-p", head.stdout.strip()]
        commit = (await _git(hc, root, *ct_args, env=env)).stdout.strip()
        if not commit:
            return "Error: could not create snapshot commit."
        cid = f"cp-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        upd = await _git(hc, root, "update-ref", f"{_REF_PREFIX}{cid}", commit)
        if upd.returncode != 0:
            return f"Error creating checkpoint ref: {upd.stderr.strip()}"
    finally:
        tmp.unlink(missing_ok=True)

    records = _load_checkpoints(hc)
    records.append({"id": cid, "label": label, "commit": commit, "time": _now_iso()})
    _save_checkpoints(hc, records)
    hc.log("create_checkpoint", id=cid, label=label)
    return f"Checkpoint {cid} created — {label} ({commit[:8]})"


async def list_checkpoints(hc: HarnessContext) -> str:
    hc.require_workspace()
    records = _load_checkpoints(hc)
    if not records:
        return "No checkpoints yet. Create one with create_checkpoint before risky edits."
    lines = ["# Checkpoints (newest last)"]
    for rec in records:
        lines.append(f"  {rec['id']}  {rec['time']}  {rec['commit'][:8]}  {rec['label']}")
    return "\n".join(lines)


async def restore_checkpoint(hc: HarnessContext, checkpoint_id: str) -> str:
    ws = hc.require_workspace()
    root = await _repo_root(hc, ws)
    if root is None:
        return "Not a git repository."
    _guard_root(hc, root)

    rec = next((r for r in _load_checkpoints(hc) if r["id"] == checkpoint_id), None)
    if rec is None:
        avail = ", ".join(r["id"] for r in _load_checkpoints(hc)) or "(none)"
        return f"Unknown checkpoint {checkpoint_id!r}. Available: {avail}"
    commit = rec["commit"]

    tmp = _tmp_index(hc)
    env = {"GIT_INDEX_FILE": str(tmp)}
    removed: list[str] = []
    try:
        await _git(hc, root, "add", "-A", env=env)
        now_tree = (await _git(hc, root, "write-tree", env=env)).stdout.strip()
        rt = await _git(hc, root, "read-tree", commit, env=env)
        if rt.returncode != 0:
            return f"Error reading checkpoint tree: {rt.stderr.strip()}"
        co = await _git(hc, root, "checkout-index", "-a", "-f", env=env)
        if co.returncode != 0:
            return f"Error restoring files: {co.stderr.strip()}"
        # Delete files that were added after the checkpoint (present now, absent in target).
        diff = await _git(hc, root, "diff", "--diff-filter=A", "--name-only", f"{commit}^{{tree}}", now_tree)
        for rel in diff.stdout.splitlines():
            rel = rel.strip()
            if not rel:
                continue
            p = Path(os.path.realpath(str(root / rel)))
            if is_within(p, root) and p.is_file():
                p.unlink()
                removed.append(rel)
    finally:
        tmp.unlink(missing_ok=True)

    hc.log("restore_checkpoint", id=checkpoint_id, removed=len(removed))
    note = f" Removed {len(removed)} file(s) added since." if removed else ""
    return f"Restored working tree to checkpoint {checkpoint_id} ({rec['label']}).{note}"
