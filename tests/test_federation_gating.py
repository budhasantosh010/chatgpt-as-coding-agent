"""S5+S6: federation and diagnostics obey the permission gate.

Audit exploits: mcp_call worked in plan/read_only modes with no gate at all,
and diagnostics_check (declared READ) executed tsc/cargo in plan mode.
"""

from __future__ import annotations

import asyncio

import pytest

from harness.config import Config
from harness.context import HarnessServer
from harness.permissions import Action, decide
from harness.policy import Capability, Decision
from harness.security import SecurityError
from harness.server import _gate, capability_for
from harness.tasks import tools as tasktools


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


def _task(srv, ws, mode):
    return tasktools.start_task(srv, str(ws), goal="g", permission_mode=mode).split()[2]


# ---- decision matrix ---------------------------------------------------------

def test_external_call_matrix():
    assert decide("read_only", Action.EXTERNAL_CALL) is Decision.DENY
    assert decide("plan", Action.EXTERNAL_CALL) is Decision.DENY
    assert decide("build_ask", Action.EXTERNAL_CALL) is Decision.ASK
    assert decide("auto_workspace", Action.EXTERNAL_CALL) is Decision.ASK
    assert decide("full", Action.EXTERNAL_CALL) is Decision.ALLOW


def test_external_read_matrix():
    for mode in ("read_only", "plan", "build_ask", "auto_workspace", "full"):
        assert decide(mode, Action.EXTERNAL_READ) is Decision.ALLOW


# ---- gate behavior through real task contexts --------------------------------

def test_mcp_call_denied_in_plan_mode(server):
    srv, ws = server
    hc = srv.context_for(_task(srv, ws, "plan"), "conn")
    with pytest.raises(SecurityError):
        _gate(hc, None, "mcp_call", "pw.click({})", action=Action.EXTERNAL_CALL)


def test_mcp_call_asks_in_auto_workspace(server):
    srv, ws = server
    hc = srv.context_for(_task(srv, ws, "auto_workspace"), "conn")
    msg = _gate(hc, None, "mcp_call", "pw.click({})", action=Action.EXTERNAL_CALL)
    assert msg is not None and "APPROVAL REQUIRED" in msg


def test_mcp_listing_allowed_in_plan_mode(server):
    srv, ws = server
    hc = srv.context_for(_task(srv, ws, "plan"), "conn")
    assert _gate(hc, None, "mcp_tools", "pw", action=Action.EXTERNAL_READ) is None


# ---- diagnostics is EXECUTE ---------------------------------------------------

def test_diagnostics_capability_is_execute():
    assert capability_for("diagnostics_check") is Capability.EXECUTE


def test_diagnostics_denied_in_plan_mode(server):
    srv, ws = server
    from harness.server import _call
    from harness.tools import diagnostics

    hc = srv.context_for(_task(srv, ws, "plan"), "conn")
    out = run(_call(hc, capability_for("diagnostics_check"), diagnostics.diagnostics, None))
    assert out.startswith("Error:") and "denied" in out


def test_diagnostics_runs_in_auto_workspace(server):
    srv, ws = server
    from harness.server import _call
    from harness.tools import diagnostics

    (ws / "x.py").write_text("x = 1\n", encoding="utf-8")
    hc = srv.context_for(_task(srv, ws, "auto_workspace"), "conn")
    out = run(_call(hc, capability_for("diagnostics_check"), diagnostics.diagnostics, None))
    assert not out.startswith("Error:")


# ---- command extraction stays correct for shell tools -------------------------

def test_open_pr_command_still_classified_remote():
    from harness.permissions import classify_command
    assert classify_command('gh pr create --title "t" --body "b"') is Action.GIT_REMOTE_WRITE
