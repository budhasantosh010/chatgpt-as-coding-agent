"""S2: the no-task fallback session must not run at the operator's mode.

The audit escaped a plan-mode task by simply omitting task_id — the fallback
session ran at config.mode (default "full"). Now the fallback is capped at
config.no_task_mode (default read_only) and the deny message tells the model
to start a task.
"""

from __future__ import annotations

import asyncio

import pytest

from harness.config import Config
from harness.context import HarnessServer


def run(c):
    return asyncio.run(c)


@pytest.fixture
def server(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    cfg = Config(
        workspace_roots=[tmp_path], state_dir=tmp_path / "state",
        secret_route="x", mode="full",
    )
    srv = HarnessServer(cfg)
    yield srv, ws
    srv.tasks.close()


def _write_via_server(srv, ws, task_id=None):
    from harness.policy import Capability
    from harness.server import _call
    from harness.tools import files

    hc = srv.context_for(task_id, "conn-1")
    if hc.active_workspace is None:
        hc.set_workspace(str(ws))
    return run(_call(hc, Capability.WRITE, files.write_file, str(ws / "a.txt"), "hi", None))


def test_no_task_write_denied_and_hints_start_task(server):
    srv, ws = server
    out = _write_via_server(srv, ws, task_id=None)
    assert out.startswith("Error:")
    assert "read_only" in out
    assert "start_task" in out


def test_no_task_read_still_works(server):
    srv, ws = server
    from harness.policy import Capability
    from harness.server import _call
    from harness.tools import files

    (ws / "r.txt").write_text("hello", encoding="utf-8")
    hc = srv.context_for(None, "conn-1")
    hc.set_workspace(str(ws))
    out = run(_call(hc, Capability.READ, files.read_file, "r.txt", None, None))
    assert "hello" in out


def test_task_write_works(server):
    srv, ws = server
    from harness.tasks import tools as tasktools

    msg = tasktools.start_task(srv, str(ws), goal="test writes", permission_mode="auto_workspace")
    task_id = msg.split()[2]
    out = _write_via_server(srv, ws, task_id=task_id)
    assert not out.startswith("Error:")
    assert (ws / "a.txt").read_text(encoding="utf-8") == "hi"


def test_legacy_flag_restores_full_fallback(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    cfg = Config(
        workspace_roots=[tmp_path], state_dir=tmp_path / "state",
        secret_route="x", mode="full", no_task_mode="full",
    )
    srv = HarnessServer(cfg)
    try:
        out = _write_via_server(srv, ws, task_id=None)
        assert not out.startswith("Error:")
    finally:
        srv.tasks.close()
