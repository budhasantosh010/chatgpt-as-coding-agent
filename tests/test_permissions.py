"""Fine-grained permission modes, command classification, and the approval flow."""

from __future__ import annotations

import asyncio

from harness.config import Config
from harness.context import HarnessServer
from harness.permissions import Action, classify_command, decide
from harness.policy import Decision
from harness.policy import Capability
from harness.server import _call
from harness.tasks import tools as tt
from harness.tools import files, shell


def run(c):
    return asyncio.run(c)


# --- command classification ------------------------------------------------

def test_classify_commands():
    assert classify_command("pytest -q") is Action.COMMAND_ARBITRARY
    assert classify_command("git push origin main") is Action.GIT_REMOTE_WRITE
    assert classify_command("npm install left-pad") is Action.PACKAGE_INSTALL
    assert classify_command("curl https://evil.com") is Action.NETWORK
    assert classify_command("terraform apply") is Action.DEPLOYMENT


def test_mode_matrix():
    assert decide("plan", Action.FILE_WRITE) is Decision.DENY
    assert decide("plan", Action.FILE_READ) is Decision.ALLOW
    assert decide("build_ask", Action.FILE_WRITE) is Decision.ASK
    assert decide("auto_workspace", Action.FILE_WRITE) is Decision.ALLOW
    assert decide("auto_workspace", Action.COMMAND_ARBITRARY) is Decision.ALLOW
    assert decide("auto_workspace", Action.GIT_REMOTE_WRITE) is Decision.ASK
    assert decide("full", Action.DEPLOYMENT) is Decision.ALLOW


# --- approval flow end-to-end ---------------------------------------------

def _server_task(tmp_path, mode):
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "s", secret_route="r")
    server = HarnessServer(cfg)
    ws = tmp_path / "proj"; ws.mkdir()
    out = tt.start_task(server, str(ws), "g", mode)
    tid = next(t for t in out.split() if t.startswith("T-"))
    return server, tid, ws


def test_build_ask_requires_then_grants_approval(tmp_path):
    server, tid, ws = _server_task(tmp_path, "build_ask")
    hc = server.context_for(tid, "default")

    # First write asks for approval (no file written).
    out = run(_call(hc, Capability.WRITE, files.write_file, "a.txt", "hi"))
    assert "APPROVAL REQUIRED" in out
    assert not (ws / "a.txt").exists()

    # Operator approves the pending request.
    pending = server.tasks.pending_approvals(tid)
    assert len(pending) == 1
    assert server.tasks.decide_approval(pending[0]["id"], "approved")

    # Retry now succeeds (one-shot consumed).
    out2 = run(_call(hc, Capability.WRITE, files.write_file, "a.txt", "hi"))
    assert "Created" in out2 and (ws / "a.txt").read_text() == "hi"

    # A second write asks again (approval was one-shot).
    out3 = run(_call(hc, Capability.WRITE, files.write_file, "b.txt", "yo"))
    assert "APPROVAL REQUIRED" in out3


def test_auto_workspace_allows_local_but_asks_remote(tmp_path):
    server, tid, ws = _server_task(tmp_path, "auto_workspace")
    hc = server.context_for(tid, "default")
    # Local command runs.
    ok = run(_call(hc, Capability.EXECUTE, shell.run_command, "echo hello", None, 30))
    assert "hello" in ok
    # A push asks for approval.
    push = run(_call(hc, Capability.EXECUTE, shell.run_command, "git push origin main", None, 30))
    assert "APPROVAL REQUIRED" in push
