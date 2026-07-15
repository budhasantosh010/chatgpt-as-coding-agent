"""operation_id idempotency (no duplicate side effects) + result envelope."""

from __future__ import annotations

import asyncio

from harness.config import Config
from harness.context import HarnessServer
from harness.policy import Capability
from harness.result import error_code_for
from harness.server import _call_idem
from harness.tasks import tools as tt
from harness.tools import files


def run(c):
    return asyncio.run(c)


def _server_task(tmp_path):
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "s", secret_route="r")
    server = HarnessServer(cfg)
    ws = tmp_path / "proj"; ws.mkdir()
    tid = next(t for t in run(tt.start_task(server, str(ws), "g", "auto_workspace")).split() if t.startswith("T-"))
    return server, tid, ws


def test_operation_id_skips_re_execution(tmp_path):
    server, tid, ws = _server_task(tmp_path)
    hc = server.context_for(tid, "default")

    out1 = run(_call_idem(hc, Capability.WRITE, "op-1", files.write_file, "a.txt", "hello"))
    assert "Created" in out1 and (ws / "a.txt").exists()

    # Remove the side effect, then replay the SAME operation_id.
    (ws / "a.txt").unlink()
    out2 = run(_call_idem(hc, Capability.WRITE, "op-1", files.write_file, "a.txt", "hello"))
    assert "cached" in out2
    assert not (ws / "a.txt").exists(), "cached replay must NOT re-execute the write"


def test_different_operation_id_executes(tmp_path):
    server, tid, ws = _server_task(tmp_path)
    hc = server.context_for(tid, "default")
    run(_call_idem(hc, Capability.WRITE, "op-A", files.write_file, "a.txt", "x"))
    (ws / "a.txt").unlink()
    run(_call_idem(hc, Capability.WRITE, "op-B", files.write_file, "a.txt", "x"))
    assert (ws / "a.txt").exists()  # new op id runs for real


def test_errors_are_not_cached(tmp_path):
    server, tid, ws = _server_task(tmp_path)
    hc = server.context_for(tid, "default")
    # Editing a missing file errors; must not be recorded (so a later valid retry runs).
    run(_call_idem(hc, Capability.WRITE, "op-e", files.edit_file, "missing.txt", "a", "b"))
    assert server.tasks.get_operation("op-e", tid, "edit_file") is None


def test_operation_id_scoped_to_task(tmp_path):
    """Audit S4 exploit: task B replaying task A's operation_id must EXECUTE,
    not receive A's cached result."""
    server, tid_a, ws = _server_task(tmp_path)
    tid_b = next(t for t in run(tt.start_task(server, str(ws), "g2", "auto_workspace")).split() if t.startswith("T-"))

    hc_a = server.context_for(tid_a, "conn-a")
    run(_call_idem(hc_a, Capability.WRITE, "same-op", files.write_file, "a.txt", "from A"))

    hc_b = server.context_for(tid_b, "conn-b")
    out_b = run(_call_idem(hc_b, Capability.WRITE, "same-op", files.write_file, "b.txt", "from B"))
    assert "cached" not in out_b
    assert (ws / "b.txt").read_text() == "from B"


def test_operation_id_scoped_to_tool(tmp_path):
    """Same op_id on a different tool must not return the other tool's result."""
    server, tid, ws = _server_task(tmp_path)
    hc = server.context_for(tid, "default")
    run(_call_idem(hc, Capability.WRITE, "op-x", files.write_file, "a.txt", "v1"))
    out = run(_call_idem(hc, Capability.WRITE, "op-x", files.edit_file, "a.txt", "v1", "v2"))
    assert "cached" not in out
    assert (ws / "a.txt").read_text() == "v2"


def test_error_codes():
    assert error_code_for("Error: Stale write blocked: x") == "STALE_FILE"
    assert error_code_for("Error: 'file_write' is denied in 'plan' mode") == "PERMISSION_DENIED"
    assert error_code_for("⏸ APPROVAL REQUIRED — ...") == "APPROVAL_REQUIRED"


def test_errors_carry_stable_codes(tmp_path):
    """The _call error path emits `Error: [CODE] message`."""
    server, tid, ws = _server_task(tmp_path)
    hc = server.context_for(tid, "default")
    out = run(_call_idem(hc, Capability.WRITE, None, files.edit_file, "missing.txt", "a", "b"))
    assert out.startswith("Error: [NOT_FOUND]")
