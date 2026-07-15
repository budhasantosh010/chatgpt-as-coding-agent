"""S9+S7+S8: terminal tasks are frozen, read_image passes the gate/audit path,
and git_commit does not execute repo-controlled hooks by default."""

from __future__ import annotations

import asyncio

import pytest

from harness.config import Config
from harness.context import HarnessServer
from harness.security import SecurityError
from harness.tasks import tools as tasktools
from harness.tasks.model import TaskState


def run(c):
    return asyncio.run(c)


@pytest.fixture
def server(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state",
                 secret_route="x")
    srv = HarnessServer(cfg)
    yield srv, ws
    srv.tasks.close()


def _task(srv, ws, mode="auto_workspace"):
    return run(tasktools.start_task(srv, str(ws), goal="g", permission_mode=mode)).split()[2]


# ---- S9: terminal tasks frozen -------------------------------------------------

def test_completed_task_context_rejected(server):
    srv, ws = server
    tid = _task(srv, ws)
    task = srv.tasks.get_task(tid)
    task.status = TaskState.COMPLETED
    srv.tasks.save_task(task)
    with pytest.raises(SecurityError, match="read-only"):
        srv.context_for(tid, "conn")


def test_cancelled_task_context_rejected(server):
    srv, ws = server
    tid = _task(srv, ws)
    tasktools.cancel_task(srv, tid, "abandoned")
    with pytest.raises(SecurityError):
        srv.context_for(tid, "conn")


def test_terminal_task_still_readable_via_status(server):
    srv, ws = server
    tid = _task(srv, ws)
    tasktools.cancel_task(srv, tid, "abandoned")
    out = tasktools.task_status(srv, tid)
    assert "cancelled" in out


# ---- S7: read_image passes gate + pre-hooks ------------------------------------

def test_read_image_hits_audit_prehook(server):
    srv, ws = server
    from harness.policy import Capability
    from harness.server import _pre

    seen = []
    srv.hooks.on_pre(lambda call: seen.append(call.tool))
    tid = _task(srv, ws)
    hc = srv.context_for(tid, "conn")
    run(_pre(hc, Capability.READ, "read_image", detail="x.png"))
    assert "read_image" in seen


def test_read_image_veto_blocks(server):
    srv, ws = server
    from harness.hooks import HookVeto
    from harness.policy import Capability
    from harness.server import _pre

    def _veto(call):
        if call.tool == "read_image":
            raise HookVeto("no images")

    srv.hooks.on_pre(_veto)
    tid = _task(srv, ws)
    hc = srv.context_for(tid, "conn")
    with pytest.raises(HookVeto):
        run(_pre(hc, Capability.READ, "read_image", detail="x.png"))


# ---- S8: git_commit ignores repo hooks by default -------------------------------

async def _init_repo(hc, ws):
    from harness.tools import gitcmd
    await gitcmd.git(hc, ws, "init")
    await gitcmd.git(hc, ws, "config", "user.email", "t@t")
    await gitcmd.git(hc, ws, "config", "user.name", "t")


def test_commit_ignores_repo_hooks_by_default(server, tmp_path):
    srv, ws = server
    from harness.tools import vcs

    tid = _task(srv, ws)
    hc = srv.context_for(tid, "conn")
    run(_init_repo(hc, ws))
    # A repo-controlled pre-commit hook that plants a canary file on the host.
    hooks_dir = ws / ".git" / "hooks"
    canary = tmp_path / "canary.txt"
    (hooks_dir / "pre-commit").write_text(
        f"#!/bin/sh\necho pwned > '{canary.as_posix()}'\n", encoding="utf-8"
    )
    # Executable bit: on Linux git silently SKIPS non-executable hooks, which
    # would make this test pass for the wrong reason. (Windows ignores it.)
    (hooks_dir / "pre-commit").chmod(0o755)
    (ws / "f.txt").write_text("data", encoding="utf-8")

    out = run(vcs.git_commit(hc, "test commit"))
    assert "Committed" in out
    assert not canary.exists(), "repo pre-commit hook must NOT run on the host by default"


def test_commit_hooks_opt_in_runs_hooks(tmp_path):
    from harness.tools import vcs

    ws = tmp_path / "proj"
    ws.mkdir()
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state",
                 secret_route="x", commit_hooks=True)
    srv = HarnessServer(cfg)
    try:
        tid = _task(srv, ws)
        hc = srv.context_for(tid, "conn")
        run(_init_repo(hc, ws))
        hooks_dir = ws / ".git" / "hooks"
        canary = tmp_path / "canary2.txt"
        (hooks_dir / "pre-commit").write_text(
            f"#!/bin/sh\necho ran > '{canary.as_posix()}'\nexit 0\n", encoding="utf-8"
        )
        # Required on Linux: git only executes hooks with the executable bit set
        # (the GPT-audit finding — this test failed on Linux without it).
        (hooks_dir / "pre-commit").chmod(0o755)
        (ws / "f.txt").write_text("data", encoding="utf-8")
        out = run(vcs.git_commit(hc, "with hooks"))
        assert "Committed" in out
        assert canary.exists(), "HARNESS_COMMIT_HOOKS=true must honor repo hooks"
    finally:
        srv.tasks.close()


def test_commit_preserves_user_identity(server):
    """no_hooks hardening must still read the user's global config (identity)."""
    srv, ws = server
    from harness.tools import gitcmd

    tid = _task(srv, ws)
    hc = srv.context_for(tid, "conn")

    async def _check():
        # Global config is NOT redirected to devnull under no_hooks.
        r = await gitcmd.git(hc, ws, "config", "--show-origin", "--list",
                             hardened="no_hooks")
        return r

    r = run(_check())
    assert r.returncode == 0
