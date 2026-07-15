"""Supervisor engine-child lifecycle: PID file + stale-orphan reaping.

Found via real-user testing: force-killing the supervisor orphaned the engine
child. The supervisor now records the child PID and reaps a stale one on start.
"""

from __future__ import annotations

import subprocess
import sys

from harness.config import Config
from harness.cockpit.supervisor import Supervisor


def _sup(tmp_path):
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state",
                 secret_route="x", cockpit_port=8899)
    return Supervisor(cfg)


def test_reap_is_noop_without_pidfile(tmp_path):
    sup = _sup(tmp_path)
    # No engine.pid yet → reaping does nothing and doesn't raise.
    sup._reap_stale_engine()
    assert not sup._pid_file().exists()
    sup.cockpit.server.tasks.close()


def test_reap_kills_recorded_pid(tmp_path):
    sup = _sup(tmp_path)
    # A real, long-lived child we pretend was a leftover engine.
    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    sup._pid_file().parent.mkdir(parents=True, exist_ok=True)
    sup._pid_file().write_text(str(victim.pid), encoding="utf-8")
    sup._reap_stale_engine()
    # Reaped: the pid file is gone and the process dies shortly.
    assert not sup._pid_file().exists()
    try:
        victim.wait(timeout=10)
    except subprocess.TimeoutExpired:
        victim.kill()
        raise AssertionError("stale engine PID was not reaped")
    sup.cockpit.server.tasks.close()


def test_reap_survives_dead_pid(tmp_path):
    sup = _sup(tmp_path)
    # A PID that's already gone must not raise.
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    sup._pid_file().parent.mkdir(parents=True, exist_ok=True)
    sup._pid_file().write_text(str(p.pid), encoding="utf-8")
    sup._reap_stale_engine()  # should not raise
    assert not sup._pid_file().exists()
    sup.cockpit.server.tasks.close()
