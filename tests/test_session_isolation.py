"""Tier-0 architecture: concurrent sessions must not corrupt each other's state."""

from __future__ import annotations

from harness.config import Config
from harness.context import HarnessServer


def _config(tmp_path):
    return Config(
        workspace_roots=[tmp_path],
        state_dir=tmp_path / "state",
        secret_route="x" * 32,
        mode="full",
    )


def test_sessions_are_isolated(tmp_path):
    (tmp_path / "proj_a").mkdir()
    (tmp_path / "proj_b").mkdir()
    server = HarnessServer(_config(tmp_path))

    sa = server.session_for("conversation-A")
    sb = server.session_for("conversation-B")
    assert sa is not sb

    sa.set_workspace(str(tmp_path / "proj_a"))
    sb.set_workspace(str(tmp_path / "proj_b"))

    # B opening its workspace must not have changed A's.
    assert sa.active_workspace.name == "proj_a"
    assert sb.active_workspace.name == "proj_b"


def test_same_key_returns_same_session(tmp_path):
    server = HarnessServer(_config(tmp_path))
    first = server.session_for("same")
    second = server.session_for("same")
    assert first is second


def test_none_key_maps_to_default(tmp_path):
    server = HarnessServer(_config(tmp_path))
    assert server.session_for(None) is server.session_for("default")


def test_shared_config_across_sessions(tmp_path):
    server = HarnessServer(_config(tmp_path))
    assert server.session_for("a").config is server.session_for("b").config
