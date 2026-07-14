"""Regression tests for the red-team findings (reproduced against real code).

Each test asserts the FIXED behavior, so they fail on commit ba0e387 and pass
once Phase 0 lands. Origin: an independent audit + local reproduction.
"""

from __future__ import annotations

import asyncio
import os

from harness.config import Config
from harness.context import HarnessServer
from harness.policy import Capability
from harness.server import _call
from harness.tools import files, memory as mem_tool, search, shell


def run(c):
    return asyncio.run(c)


def _server(tmp_path, mode="full"):
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state",
                 secret_route="r", mode=mode)
    return HarnessServer(cfg)


def _ws(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir(exist_ok=True)
    return ws


# --- Finding: error strings bypass the scrub post-hook --------------------

def test_error_output_is_scrubbed(tmp_path):
    server = _server(tmp_path)
    hc = server.session_for("s")
    hc.set_workspace(str(_ws(tmp_path)))
    token = "ghp_" + "b" * 36
    out = run(_call(hc, Capability.READ, files.read_file, f"missing-{token}.txt"))
    assert token not in out, "secret in an error message must be scrubbed"
    assert "REDACTED" in out


# --- Finding: run_command inherits full host env --------------------------

def test_run_command_does_not_leak_host_env(tmp_path):
    server = _server(tmp_path)
    hc = server.session_for("s")
    hc.set_workspace(str(_ws(tmp_path)))
    os.environ["FAKE_HARNESS_SECRET"] = "envleak_XYZ789"
    try:
        cmd = "python -c \"import os;print(os.environ.get('FAKE_HARNESS_SECRET','<absent>'))\""
        out = run(_call(hc, Capability.EXECUTE, shell.run_command, cmd, None, 30))
        assert "envleak_XYZ789" not in out, "host env must not leak into run_command"
    finally:
        os.environ.pop("FAKE_HARNESS_SECRET", None)


# --- Finding: grep applies no secret-path policy --------------------------

def test_grep_does_not_leak_secret_file(tmp_path):
    server = _server(tmp_path)
    hc = server.session_for("s")
    ws = _ws(tmp_path)
    # 'credentials' matches DEFAULT_SECRET_GLOBS and is NOT hidden, so ripgrep
    # would otherwise read it.
    (ws / "credentials").write_text("AUTH_TOKEN=supersecret_pw_42\n", encoding="utf-8")
    hc.set_workspace(str(ws))
    out = run(_call(hc, Capability.READ, search.grep, "AUTH_TOKEN", None, None, False, 0, "content"))
    assert "supersecret_pw_42" not in out, "grep must not surface secret-file contents"


# --- Finding: .env files are not blocked ----------------------------------

def test_env_file_is_blocked_but_example_is_allowed(tmp_path):
    server = _server(tmp_path)
    hc = server.session_for("s")
    ws = _ws(tmp_path)
    (ws / ".env").write_text("SECRET_KEY=zzz\n", encoding="utf-8")
    (ws / ".env.example").write_text("SECRET_KEY=\n", encoding="utf-8")
    hc.set_workspace(str(ws))
    blocked = run(_call(hc, Capability.READ, files.read_file, ".env"))
    assert "zzz" not in blocked and ("secret" in blocked.lower() or "refus" in blocked.lower())
    allowed = run(_call(hc, Capability.READ, files.read_file, ".env.example"))
    assert "SECRET_KEY" in allowed  # example is safe to read


# --- Finding: read_only allows state mutations ----------------------------

def test_state_mutating_tools_are_not_classified_read():
    # The server must gate these as mutations, not READ, so read_only blocks them.
    from harness.server import capability_for
    for tool in ("create_checkpoint", "remember", "forget", "write_todos"):
        assert capability_for(tool) is not Capability.READ, f"{tool} must not be READ"


def test_git_internals_are_not_writable(tmp_path):
    server = _server(tmp_path)
    hc = server.session_for("s")
    ws = _ws(tmp_path)
    (ws / ".git").mkdir(exist_ok=True)
    hc.set_workspace(str(ws))
    out = run(_call(hc, Capability.WRITE, files.write_file, ".git/hooks/pre-commit", "#!/bin/sh\nevil\n"))
    assert out.startswith("Error:")
    assert not (ws / ".git" / "hooks" / "pre-commit").exists()


def test_read_only_denies_mutations_via_policy(tmp_path):
    from harness.server import capability_for
    server = _server(tmp_path, mode="read_only")
    hc = server.session_for("s")
    hc.set_workspace(str(_ws(tmp_path)))
    out = run(_call(hc, capability_for("remember"), mem_tool.remember, "a fact", None))
    assert out.startswith("Error:"), "remember must be denied in read_only mode"
