"""I1: physical task isolation — start_task on a git repo binds its own worktree.

Audit exploit: two tasks on one project shared the same physical files, and
nothing ever wrote Task.worktree_path. Now start_task(isolation='auto') creates
and PERSISTS a worktree per task; context_for binds to it.
"""

from __future__ import annotations

import asyncio

import pytest

from harness.config import Config
from harness.context import HarnessServer
from harness.security import SecurityError
from harness.tasks import tools as tasktools


def run(c):
    return asyncio.run(c)


@pytest.fixture
def server(tmp_path):
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state",
                 secret_route="x")
    srv = HarnessServer(cfg)
    yield srv, tmp_path
    srv.tasks.close()


def _git_repo(srv, base, name="repo"):
    from harness.tools import gitcmd

    ws = base / name
    ws.mkdir()
    (ws / "f.txt").write_text("v1\n", encoding="utf-8")

    async def _init():
        shim = type("S", (), {"executor": srv.executor, "config": srv.config})()
        await gitcmd.git(shim, ws, "init")
        await gitcmd.git(shim, ws, "config", "user.email", "t@t")
        await gitcmd.git(shim, ws, "config", "user.name", "t")
        await gitcmd.git(shim, ws, "add", "-A")
        await gitcmd.git(shim, ws, "commit", "-m", "init")

    run(_init())
    return ws


def _start(srv, ws, isolation="auto"):
    msg = run(tasktools.start_task(srv, str(ws), goal="g",
                                   permission_mode="auto_workspace", isolation=isolation))
    return msg.split()[2]


def test_start_task_binds_worktree_for_git_repo(server):
    srv, base = server
    ws = _git_repo(srv, base)
    tid = _start(srv, ws)
    task = srv.tasks.get_task(tid)
    assert task.worktree_path is not None
    assert task.worktree_path != str(ws)
    assert task.base_commit  # HEAD recorded


def test_two_tasks_same_project_get_disjoint_files(server):
    """The audit's isolation exploit, reproduced: a write in task A must be
    invisible to task B."""
    srv, base = server
    ws = _git_repo(srv, base)
    tid_a, tid_b = _start(srv, ws), _start(srv, ws)

    hc_a = srv.context_for(tid_a, "conn-a")
    hc_b = srv.context_for(tid_b, "conn-b")
    assert hc_a.active_workspace != hc_b.active_workspace

    (hc_a.active_workspace / "only-in-a.txt").write_text("A", encoding="utf-8")
    assert not (hc_b.active_workspace / "only-in-a.txt").exists()
    assert not (ws / "only-in-a.txt").exists()  # main checkout untouched


def test_isolation_workspace_opts_out(server):
    srv, base = server
    ws = _git_repo(srv, base)
    # checklist 0.3: opting out of worktree isolation needs operator approval.
    first = run(tasktools.start_task(srv, str(ws), goal="g",
                                     permission_mode="auto_workspace",
                                     isolation="workspace"))
    assert "APPROVAL REQUIRED" in first
    aid = first.split("approvals approve ")[1].split()[0]
    assert srv.tasks.decide_approval(aid, "approved")
    tid = _start(srv, ws, isolation="workspace")
    task = srv.tasks.get_task(tid)
    assert task.worktree_path is None
    hc = srv.context_for(tid, "conn")
    assert str(hc.active_workspace) == str(ws)


def test_non_git_project_falls_back_to_shared(server):
    srv, base = server
    ws = base / "plain"
    ws.mkdir()
    tid = _start(srv, ws)  # auto on a non-repo: no worktree, no error
    task = srv.tasks.get_task(tid)
    assert task.worktree_path is None


def test_explicit_worktree_on_non_git_errors(server):
    srv, base = server
    ws = base / "plain2"
    ws.mkdir()
    with pytest.raises(SecurityError, match="worktree"):
        _start(srv, ws, isolation="worktree")


def test_subtask_shares_parent_worktree(server):
    srv, base = server
    ws = _git_repo(srv, base)
    parent = _start(srv, ws)
    out = tasktools.create_subtask(srv, parent, "child goal")
    child = next(t for t in out.split() if t.startswith("T-") and t != parent)
    p, c = srv.tasks.get_task(parent), srv.tasks.get_task(child)
    assert c.worktree_path == p.worktree_path
    assert c.base_commit == p.base_commit
