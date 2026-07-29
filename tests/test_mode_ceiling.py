"""S1: ChatGPT must not be able to grant itself privileges.

The audit exploit: start_task(permission_mode="full") ran with full powers, and
"bypass_sandboxed" was selectable with no sandbox running. Now HARNESS_MAX_MODE
(default auto_workspace) is a server-side ceiling enforced BOTH at start_task
and at context_for (so it also clamps legacy rows / subtask inheritance), and
only the local operator CLI can elevate a task above it.
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
    ws = tmp_path / "proj"
    ws.mkdir()
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state",
                 secret_route="x", mode="full")
    srv = HarnessServer(cfg)
    yield srv, ws
    srv.tasks.close()


def _start(srv, ws, mode):
    msg = run(tasktools.start_task(srv, str(ws), goal="g", permission_mode=mode))
    return msg.split()[2]


def test_start_task_rejects_full(server):
    srv, ws = server
    with pytest.raises(SecurityError, match="ceiling"):
        _start(srv, ws, "full")


def test_start_task_rejects_bypass_without_docker(server):
    srv, ws = server
    with pytest.raises(SecurityError):
        _start(srv, ws, "bypass_sandboxed")


def test_start_task_allows_up_to_ceiling(server):
    srv, ws = server
    for mode in ("read_only", "plan", "build_ask", "auto_workspace"):
        tid = _start(srv, ws, mode)
        assert srv.tasks.get_task(tid).permission_mode == mode


def test_context_for_clamps_legacy_full_task(server):
    """A task row already stored with mode=full (legacy DB / direct edit) runs
    at the ceiling, not at full — context_for is authoritative."""
    srv, ws = server
    tid = _start(srv, ws, "auto_workspace")
    task = srv.tasks.get_task(tid)
    task.permission_mode = "full"  # simulate a legacy/tampered row
    srv.tasks.save_task(task)
    hc = srv.context_for(tid, "conn")
    assert hc.policy.mode == "auto_workspace"


def test_operator_elevation_rides_above_ceiling(server):
    srv, ws = server
    tid = _start(srv, ws, "auto_workspace")
    task = srv.tasks.get_task(tid)
    task.permission_mode = "full"
    task.operator_elevated = True  # what `harness tasks set-mode` sets
    srv.tasks.save_task(task)
    hc = srv.context_for(tid, "conn")
    assert hc.policy.mode == "full"


def test_bypass_without_docker_degrades_to_auto_workspace(server):
    srv, ws = server
    tid = _start(srv, ws, "auto_workspace")
    task = srv.tasks.get_task(tid)
    task.permission_mode = "bypass_sandboxed"
    task.operator_elevated = True
    srv.tasks.save_task(task)
    hc = srv.context_for(tid, "conn")
    # elevated or not: no docker → no "rely on the sandbox" mode
    assert hc.policy.mode == "auto_workspace"


def test_operator_may_start_a_task_at_full(server):
    """The cockpit is the operator. The ceiling asks whether the MODEL may grant
    itself powers, so it must not stand between the operator and a mode the same
    server already lets them set with `tasks set-mode`."""
    srv, ws = server
    msg = run(tasktools.start_task(srv, str(ws), goal="g", permission_mode="full",
                                   operator=True))
    task = srv.tasks.get_task(msg.split()[2])
    assert task.permission_mode == "full"
    # Without the recorded elevation, effective_mode() clamps it straight back.
    assert task.operator_elevated is True
    assert srv.context_for(task.id, "conn").policy.mode == "full"


def test_operator_start_still_needs_docker_for_bypass(server):
    """Elevation is about authority; the sandbox check is about whether the
    sandbox exists. The operator cannot conjure a container by asking."""
    srv, ws = server
    with pytest.raises(SecurityError, match="sandbox"):
        run(tasktools.start_task(srv, str(ws), goal="g",
                                 permission_mode="bypass_sandboxed", operator=True))


def test_operator_flag_does_not_leak_to_the_model_path(server):
    """The default is still refusal — only an explicit operator=True waives it."""
    srv, ws = server
    with pytest.raises(SecurityError, match="ceiling"):
        _start(srv, ws, "full")


def test_operator_start_below_ceiling_is_not_marked_elevated(server):
    srv, ws = server
    msg = run(tasktools.start_task(srv, str(ws), goal="g",
                                   permission_mode="build_ask", operator=True))
    assert srv.tasks.get_task(msg.split()[2]).operator_elevated is False


def test_cli_set_mode_elevates(tmp_path):
    from harness.__main__ import _cmd_tasks

    ws = tmp_path / "proj"
    ws.mkdir()
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state",
                 secret_route="x")
    srv = HarnessServer(cfg)
    try:
        tid = _start(srv, ws, "auto_workspace")
    finally:
        srv.tasks.close()
    assert _cmd_tasks(cfg, "set-mode", tid, "full") == 0
    srv2 = HarnessServer(cfg)
    try:
        task = srv2.tasks.get_task(tid)
        assert task.permission_mode == "full"
        assert task.operator_elevated is True
        hc = srv2.context_for(tid, "conn")
        assert hc.policy.mode == "full"
    finally:
        srv2.tasks.close()
