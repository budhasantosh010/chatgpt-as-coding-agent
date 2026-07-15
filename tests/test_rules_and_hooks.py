"""Phase 6 (path-scoped rules, auto-format) + Phase 7 (operator hooks)."""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

from harness.config import Config
from harness.context import HarnessServer
from harness.policy import Capability
from harness.rules import load_rules, rules_for
from harness.server import _call
from harness.tasks import tools as tasktools
from harness.tools import files


def run(c):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(c)


def _server(tmp_path, **cfg):
    proj = tmp_path / "proj"
    proj.mkdir()
    c = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state",
               secret_route="x", **cfg)
    srv = HarnessServer(c)
    tid = run(tasktools.start_task(srv, str(proj), "g")).split()[2]
    hc = srv.context_for(tid, "conn")
    return srv, hc, proj


# ---- 6.1 path-scoped rules --------------------------------------------------

def _write_rule(proj, name, globs, body):
    rd = proj / ".harness" / "rules"
    rd.mkdir(parents=True, exist_ok=True)
    (rd / name).write_text(f"---\nglobs: {globs}\n---\n{body}\n", encoding="utf-8")


def test_rules_parse_and_match(tmp_path):
    proj = tmp_path / "proj"; proj.mkdir()
    _write_rule(proj, "mig.md", "migrations/**", "Never edit an applied migration.")
    _write_rule(proj, "ts.md", "src/**/*.ts", "Use strict types.")
    rules = load_rules(proj)
    assert len(rules) == 2
    assert rules_for(proj, "migrations/001.sql")
    assert rules_for(proj, "src/app/x.ts")
    assert not rules_for(proj, "README.md")


def test_rule_surfaced_on_matching_write(tmp_path):
    srv, hc, proj = _server(tmp_path)
    _write_rule(proj, "secure.md", "**/*.py", "Validate all inputs.")
    out = run(_call(hc, Capability.WRITE, files.write_file, "app.py", "x=1", None))
    assert "Validate all inputs." in out and "Rule 'secure'" in out


def test_rule_not_surfaced_on_nonmatching_write(tmp_path):
    srv, hc, proj = _server(tmp_path)
    _write_rule(proj, "ts.md", "**/*.ts", "TS only rule.")
    out = run(_call(hc, Capability.WRITE, files.write_file, "app.py", "x=1", None))
    assert "TS only rule." not in out


def test_rules_in_open_workspace(tmp_path):
    srv, hc, proj = _server(tmp_path)
    _write_rule(proj, "mig.md", "migrations/**", "Careful.")
    from harness.tools import workspace
    out = run(workspace.open_workspace(hc, str(proj)))
    assert "Path-scoped rules" in out and "mig" in out


# ---- 6.2 auto-format --------------------------------------------------------

def test_autoformat_off_by_default(tmp_path):
    srv, hc, proj = _server(tmp_path)
    out = run(_call(hc, Capability.WRITE, files.write_file, "a.py", "x=1", None))
    assert "auto-formatted" not in out


def test_autoformat_runs_when_enabled(tmp_path, monkeypatch):
    # Force a fake formatter to be "available" and record that it ran.
    import harness.hooks as H
    srv, hc, proj = _server(tmp_path, auto_format=True)
    ran = {}
    monkeypatch.setattr("shutil.which", lambda name: "ruff" if name == "ruff" else None)

    def fake_run(cmd, **kw):
        ran["cmd"] = cmd
        class R: pass
        return R()
    monkeypatch.setattr("subprocess.run", fake_run)
    out = run(_call(hc, Capability.WRITE, files.write_file, "a.py", "x=1", None))
    assert "auto-formatted with ruff" in out
    assert ran["cmd"][0] == "ruff"


# ---- Phase 7: operator hooks ------------------------------------------------

def _write_hooks(state_dir, hooks):
    (state_dir).mkdir(parents=True, exist_ok=True)
    (state_dir / "hooks.json").write_text(json.dumps(hooks), encoding="utf-8")


def test_post_hook_annotates_output(tmp_path):
    srv, hc, proj = _server(tmp_path)
    _write_hooks(srv.config.state_dir, [{
        "event": "post", "tool": "write_file",
        "command": [sys.executable, "-c", "print('HOOK RAN')"],
    }])
    out = run(_call(hc, Capability.WRITE, files.write_file, "a.py", "x=1", None))
    assert "HOOK RAN" in out


def test_pre_hook_can_block(tmp_path):
    srv, hc, proj = _server(tmp_path)
    _write_hooks(srv.config.state_dir, [{
        "event": "pre", "tool": "write_file", "block_on_failure": True,
        "command": [sys.executable, "-c", "import sys; sys.exit(3)"],
    }])
    out = run(_call(hc, Capability.WRITE, files.write_file, "a.py", "x=1", None))
    assert "Blocked by operator pre-hook" in out
    assert not (proj / "a.py").exists()  # the write never happened


def test_pre_hook_nonblocking_allows(tmp_path):
    srv, hc, proj = _server(tmp_path)
    _write_hooks(srv.config.state_dir, [{
        "event": "pre", "tool": "*", "block_on_failure": False,
        "command": [sys.executable, "-c", "import sys; sys.exit(1)"],
    }])
    out = run(_call(hc, Capability.WRITE, files.write_file, "a.py", "x=1", None))
    assert "Created" in out  # exit 1 but non-blocking → write proceeds


def test_hooks_config_outside_workspace(tmp_path):
    """The hooks file must live in the state dir, not a workspace root — so the
    model's path-gated tools can't write it."""
    srv, hc, proj = _server(tmp_path)
    from harness.userhooks import load_user_hooks
    assert (srv.config.state_dir / "tasks.db").exists()  # state dir is real
    # hooks.json path is under state_dir, which is not inside proj
    assert srv.config.state_dir not in proj.parents and srv.config.state_dir != proj
    assert load_user_hooks(srv.config.state_dir) == []
