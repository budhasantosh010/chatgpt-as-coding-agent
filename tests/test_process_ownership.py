"""Background processes are owned by their session/task: another owner can't
see, read, or stop them. And shutdown_all is wired into the app lifespan."""

from __future__ import annotations

import asyncio

from harness.config import Config
from harness.context import HarnessServer
from harness.tools import process


def run(c):
    return asyncio.run(c)


def _two_sessions(tmp_path):
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "s", secret_route="r")
    server = HarnessServer(cfg)
    ws = tmp_path / "proj"
    ws.mkdir(exist_ok=True)
    a = server.session_for("A")
    a.set_workspace(str(ws))
    b = server.session_for("B")
    b.set_workspace(str(ws))
    return server, a, b


def test_process_is_private_to_its_owner(tmp_path):
    server, a, b = _two_sessions(tmp_path)
    try:
        started = run(process.start_process(a, "python -c \"import time; time.sleep(3)\"", None, 0.5))
        pid = started.split()[1]  # "Started pN in ..."
        # B cannot see A's process.
        b_list = run(process.list_processes(b))
        assert pid not in b_list
        # B cannot stop A's process.
        stopped = run(process.stop_process(b, pid))
        assert "Unknown process" in stopped
        # A can.
        a_list = run(process.list_processes(a))
        assert pid in a_list
        assert "Unknown" not in run(process.stop_process(a, pid))
    finally:
        run(server.processes.shutdown_all())


def test_app_lifespan_wraps_shutdown(tmp_path):
    from harness.app import build_asgi_app
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "s2", secret_route="r")
    app, server = build_asgi_app(cfg)
    # The lifespan was replaced with our wrapper (a closure named 'lifespan').
    assert app.router.lifespan_context.__name__ == "lifespan"
