"""Tool lifecycle hooks: veto, transform, ordering, the built-in audit + scrub
hooks, and end-to-end integration through the server's _call."""

from __future__ import annotations

import asyncio
import json

import pytest

from harness.config import Config
from harness.context import HarnessContext, HarnessServer
from harness.hooks import HookManager, HookVeto, ToolCall, make_audit_hook
from harness.policy import Capability
from harness.security import SecurityError
from harness.server import _call
from harness.tools import files


def run(coro):
    return asyncio.run(coro)


def _tc(result="out"):
    return ToolCall(tool="t", capability=Capability.READ, session_key="k", result=result)


def test_pre_hook_veto_raises():
    hm = HookManager()

    def veto(call):
        raise HookVeto("blocked by policy")

    hm.on_pre(veto)
    with pytest.raises(SecurityError):
        run(hm.run_pre(_tc()))


def test_post_hook_transforms_output():
    hm = HookManager()
    hm.on_post(lambda call: (call.result or "") + " [tagged]")
    out = run(hm.run_post(_tc("hello")))
    assert out == "hello [tagged]"


def test_post_hook_none_leaves_unchanged():
    hm = HookManager()
    hm.on_post(lambda call: None)
    assert run(hm.run_post(_tc("hello"))) == "hello"


def test_post_hooks_thread_in_order():
    hm = HookManager()
    hm.on_post(lambda call: (call.result or "") + "A")
    hm.on_post(lambda call: (call.result or "") + "B")
    assert run(hm.run_post(_tc("x"))) == "xAB"


def test_async_hook_supported():
    hm = HookManager()

    async def ahook(call):
        return (call.result or "") + "!"

    hm.on_post(ahook)
    assert run(hm.run_post(_tc("hi"))) == "hi!"


def test_audit_hook_writes_line(tmp_path):
    audit = tmp_path / "audit.jsonl"
    hook = make_audit_hook(audit)
    hook(ToolCall(tool="read_file", capability=Capability.READ, session_key="s1"))
    lines = audit.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["tool"] == "read_file" and rec["session"] == "s1" and rec["capability"] == "read"


def test_call_scrubs_secret_from_file_read(tmp_path):
    # End-to-end: a secret sitting in a file is redacted as it passes back
    # through _call's post hooks (the scrub hook is registered by HarnessServer).
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "config.env").write_text("TOKEN=ghp_" + "a" * 36 + "\n", encoding="utf-8")
    config = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state",
                    secret_route="r", mode="full")
    server = HarnessServer(config)
    hc = server.session_for("sess")
    hc.set_workspace(str(ws))

    out = run(_call(hc, Capability.READ, files.read_file, "config.env"))
    assert "ghp_" not in out
    assert "[REDACTED:github-token]" in out
    assert "redacted 1 secret" in out


def test_call_veto_blocks_tool(tmp_path):
    config = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state",
                    secret_route="r", mode="full")
    server = HarnessServer(config)
    hc = server.session_for("sess")
    hc.hooks.on_pre(_deny_writes)
    (tmp_path / "proj").mkdir()
    hc.set_workspace(str(tmp_path / "proj"))

    out = run(_call(hc, Capability.WRITE, files.write_file, "x.txt", "data"))
    assert out.startswith("Error:") and "no writes" in out
    assert not (tmp_path / "proj" / "x.txt").exists()


def _deny_writes(call: ToolCall):
    if call.capability is Capability.WRITE:
        raise HookVeto("no writes allowed in this demo")
