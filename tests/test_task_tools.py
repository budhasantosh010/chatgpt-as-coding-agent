"""Task lifecycle tools + their integration with the task-scoped context."""

from __future__ import annotations

import asyncio

from harness.config import Config
from harness.context import HarnessServer
from harness.policy import Capability
from harness.server import _call
from harness.security import SecurityError
from harness.tasks import tools as tt
from harness.tools import files


def run(c):
    return asyncio.run(c)


def _server(tmp_path):
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "s", secret_route="r")
    return HarnessServer(cfg)


def _extract_id(text: str) -> str:
    # "Started task T-abcd..." — grab the T-token
    for tok in text.replace("\n", " ").split():
        if tok.startswith("T-"):
            return tok
    raise AssertionError(f"no task id in: {text}")


def test_start_task_and_scoped_file_write(tmp_path):
    server = _server(tmp_path)
    ws = tmp_path / "proj"; ws.mkdir()
    out = tt.start_task(server, str(ws), "add feature", "auto_workspace")
    tid = _extract_id(out)

    # Resolve the task context and write through it (proves the workspace is bound).
    hc = server.context_for(tid, "default")
    msg = run(_call(hc, Capability.WRITE, files.write_file, "x.txt", "hi\n"))
    assert "Created" in msg
    assert (ws / "x.txt").exists()


def test_lifecycle_transitions(tmp_path):
    server = _server(tmp_path)
    ws = tmp_path / "proj"; ws.mkdir()
    tid = _extract_id(tt.start_task(server, str(ws), "g", "auto_workspace"))

    # Illegal jump rejected.
    assert "Illegal" in tt.advance_task(server, tid, "completed")
    # Legal path to review_ready then finish.
    for state in ("planning", "implementing", "validating", "review_ready"):
        assert "→" in tt.advance_task(server, tid, state)
    done = tt.finish_task(server, tid, "shipped")
    assert "completed" in done.lower()
    assert server.tasks.get_task(tid).status.value == "completed"


def test_set_goal_and_criteria(tmp_path):
    server = _server(tmp_path)
    ws = tmp_path / "proj"; ws.mkdir()
    tid = _extract_id(tt.start_task(server, str(ws), "g", "auto_workspace"))
    tt.set_task_goal(server, tid, "new goal")
    tt.set_acceptance_criteria(server, tid, ["tests pass", "no lint errors"])
    status = tt.task_status(server, tid)
    assert "new goal" in status
    assert "tests pass" in status


def test_start_task_rejects_outside_root(tmp_path):
    server = _server(tmp_path)
    try:
        tt.start_task(server, "/etc", "g", "auto_workspace")
        assert False
    except SecurityError:
        pass


def test_plan_mode_task_blocks_writes(tmp_path):
    server = _server(tmp_path)
    ws = tmp_path / "proj"; ws.mkdir()
    tid = _extract_id(tt.start_task(server, str(ws), "g", "plan"))
    hc = server.context_for(tid, "default")
    out = run(_call(hc, Capability.WRITE, files.write_file, "x.txt", "hi"))
    assert out.startswith("Error:"), "plan mode must deny writes"
