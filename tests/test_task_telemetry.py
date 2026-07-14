"""I2+I3: the Task record reflects what tools actually did, and completion
requires evidence when acceptance criteria exist.

Audit finding: plan/changed_files/commands/test_results/checkpoints had ZERO
writers — task_status promised sections that stayed permanently empty, and a
task with 'tests pass' criteria completed without any test ever running.
"""

from __future__ import annotations

import asyncio

import pytest

from harness.config import Config
from harness.context import HarnessServer
from harness.policy import Capability
from harness.server import _call
from harness.tasks import tools as tasktools
from harness.tasks.model import TaskState
from harness.tools import files, shell
from harness.tools import todos as todos_tool


def run(c):
    return asyncio.run(c)


@pytest.fixture
def taskctx(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state",
                 secret_route="x")
    srv = HarnessServer(cfg)
    tid = run(tasktools.start_task(srv, str(ws), goal="g",
                                   permission_mode="auto_workspace")).split()[2]
    hc = srv.context_for(tid, "conn")
    yield srv, tid, hc, ws
    srv.tasks.close()


def test_write_file_records_changed_file(taskctx):
    srv, tid, hc, ws = taskctx
    run(_call(hc, Capability.WRITE, files.write_file, "a.txt", "hi", None))
    task = srv.tasks.get_task(tid)
    assert "a.txt" in task.changed_files


def test_run_command_records_command_and_exit(taskctx):
    srv, tid, hc, ws = taskctx
    run(_call(hc, Capability.EXECUTE, shell.run_command, "echo telemetry", None, 30))
    task = srv.tasks.get_task(tid)
    assert any("echo telemetry" in c["command"] for c in task.commands)
    assert task.commands[-1]["exit"] == 0


def test_test_command_records_test_result(taskctx):
    srv, tid, hc, ws = taskctx
    # A pytest invocation with no tests exits non-zero → recorded as failed.
    run(_call(hc, Capability.EXECUTE, shell.run_command,
              "python -m pytest does_not_exist_dir -q", None, 60))
    task = srv.tasks.get_task(tid)
    assert task.test_results, "test-runner commands must be recorded"
    assert task.test_results[-1]["passed"] is False


def test_write_todos_mirrors_plan(taskctx):
    srv, tid, hc, ws = taskctx
    run(_call(hc, Capability.WRITE, todos_tool.write_todos,
              ["step one", {"content": "step two", "status": "pending"}]))
    task = srv.tasks.get_task(tid)
    assert task.plan == ["step one", "step two"]


def test_task_status_renders_telemetry(taskctx):
    srv, tid, hc, ws = taskctx
    run(_call(hc, Capability.WRITE, files.write_file, "a.txt", "hi", None))
    run(_call(hc, Capability.EXECUTE, shell.run_command, "echo done", None, 30))
    out = tasktools.task_status(srv, tid)
    assert "Changed files" in out and "a.txt" in out
    assert "Recent commands" in out and "echo done" in out


def test_telemetry_never_raises(taskctx):
    """A broken store must not break the tool call."""
    srv, tid, hc, ws = taskctx

    class Boom:
        def get_task(self, *_):
            raise RuntimeError("db down")

    from harness.hooks import make_telemetry_hook
    srv.hooks.on_post(make_telemetry_hook(Boom()))
    out = run(_call(hc, Capability.WRITE, files.write_file, "b.txt", "x", None))
    assert "Created" in out  # tool call unaffected


# ---- I3: completion evidence ---------------------------------------------------

def _to_review_ready(srv, tid):
    for state in ("discovering", "planning", "implementing", "validating", "review_ready"):
        tasktools.advance_task(srv, tid, state)


def test_finish_requires_evidence_when_criteria_set(taskctx):
    srv, tid, hc, ws = taskctx
    tasktools.set_acceptance_criteria(srv, tid, ["tests pass"])
    _to_review_ready(srv, tid)
    out = tasktools.finish_task(srv, tid)
    assert "Not completed" in out
    assert srv.tasks.get_task(tid).status is not TaskState.COMPLETED


def test_finish_accepts_recorded_test_results(taskctx):
    srv, tid, hc, ws = taskctx
    tasktools.set_acceptance_criteria(srv, tid, ["tests pass"])
    run(_call(hc, Capability.EXECUTE, shell.run_command, "pytest --version", None, 60))
    _to_review_ready(srv, tid)
    out = tasktools.finish_task(srv, tid, "done")
    assert "completed" in out
    assert srv.tasks.get_task(tid).status is TaskState.COMPLETED


def test_finish_accepts_explicit_evidence(taskctx):
    srv, tid, hc, ws = taskctx
    tasktools.set_acceptance_criteria(srv, tid, ["manual check"])
    _to_review_ready(srv, tid)
    out = tasktools.finish_task(srv, tid, "done", evidence="manually verified X")
    assert "completed" in out


def test_finish_without_criteria_unchanged(taskctx):
    srv, tid, hc, ws = taskctx
    _to_review_ready(srv, tid)
    assert "completed" in tasktools.finish_task(srv, tid, "done")
