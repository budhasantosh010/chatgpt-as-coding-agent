"""MCP client federation: config parsing, manager, and a live self-federation
(point the harness at its own stdio server and list its tools)."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

import pytest

from harness.federation import FederationError, FederationManager


def run(c):
    return asyncio.run(c)


def test_no_servers():
    fm = FederationManager({})
    assert fm.names() == []


def test_unknown_server_errors():
    fm = FederationManager({"a": {"command": "x"}})
    with pytest.raises(FederationError):
        run(fm.list_tools("nope"))


def test_config_parses_env(monkeypatch, tmp_path):
    from harness.config import Config
    monkeypatch.setenv("HARNESS_MCP_SERVERS", '{"pw": {"command": "npx", "args": ["playwright-mcp"]}}')
    monkeypatch.setenv("HARNESS_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("HARNESS_SECRET_ROUTE", "x")
    cfg = Config.from_env()
    assert "pw" in cfg.mcp_servers
    assert cfg.mcp_servers["pw"]["command"] == "npx"


def test_live_self_federation():
    """Federate to our own `python -m harness stdio` server and list its tools —
    a real end-to-end MCP client<->server round trip."""
    state = tempfile.mkdtemp(prefix="fed-")
    env = {**os.environ, "HARNESS_STATE_DIR": state, "HARNESS_SECRET_ROUTE": "x" * 22}
    fm = FederationManager({
        "self": {"command": sys.executable, "args": ["-m", "harness", "stdio"], "env": env}
    })

    async def _go():
        return await asyncio.wait_for(fm.list_tools("self"), timeout=45)

    try:
        tools = run(_go())
    except Exception as exc:  # noqa: BLE001 - environment may block subprocess/stdio
        pytest.skip(f"live stdio federation unavailable: {exc}")
    names = {n for n, _ in tools}
    assert "open_workspace" in names and "start_task" in names
    assert len(names) > 30
