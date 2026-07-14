"""Session isolation via the explicit task handle.

The Phase-0 gap (all conversations shared the 'default' context) is fixed here:
identity lives in an explicit task_id, so two conversations working different
tasks get different contexts — different workspace, policy, and process owner.
"""

from __future__ import annotations

from harness.config import Config
from harness.context import HarnessServer


def _server(tmp_path):
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "s", secret_route="r")
    return HarnessServer(cfg)


def test_two_tasks_are_isolated(tmp_path):
    server = _server(tmp_path)
    ws_a = tmp_path / "A"; ws_a.mkdir()
    ws_b = tmp_path / "B"; ws_b.mkdir()
    pid = server.tasks.register_project(str(tmp_path))
    task_a = server.tasks.create_task(pid, str(ws_a), permission_mode="full")
    task_b = server.tasks.create_task(pid, str(ws_b), permission_mode="full")

    ctx_a = server.context_for(task_a.id, "default")
    ctx_b = server.context_for(task_b.id, "default")

    assert str(ctx_a.active_workspace) == str(ws_a)
    assert str(ctx_b.active_workspace) == str(ws_b)
    # Re-resolving A after B must still point at A (no cross-contamination).
    assert str(server.context_for(task_a.id, "default").active_workspace) == str(ws_a)
    # Process ownership keys differ, so one task can't touch another's processes.
    assert ctx_a.key != ctx_b.key


def test_task_carries_its_permission_mode(tmp_path):
    server = _server(tmp_path)
    ws = tmp_path / "P"; ws.mkdir()
    pid = server.tasks.register_project(str(tmp_path))
    t = server.tasks.create_task(pid, str(ws), permission_mode="plan")
    ctx = server.context_for(t.id, "default")
    assert ctx.policy.mode == "plan"


def test_unknown_task_id_is_rejected(tmp_path):
    from harness.security import SecurityError
    server = _server(tmp_path)
    try:
        server.context_for("T-doesnotexist", "default")
        assert False, "should have raised"
    except SecurityError:
        pass
