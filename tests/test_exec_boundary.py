"""Every subprocess path goes through the executor seam (no raw bypass), and git
runs with repo hooks/config neutralized."""

from __future__ import annotations

import asyncio
import os

import pytest

from harness.config import Config
from harness.context import HarnessContext
from harness.executor import LocalExecutor
from harness.tools import gitcmd, search


def run(c):
    return asyncio.run(c)


class SpyExecutor(LocalExecutor):
    """Records every run_argv call so tests can prove routing."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.calls: list[list[str]] = []

    async def run_argv(self, argv, cwd=None, timeout=60, env=None):
        self.calls.append(list(argv))
        return await super().run_argv(argv, cwd=cwd, timeout=timeout, env=env)


def _hc(tmp_path, executor):
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "s", secret_route="r")
    hc = HarnessContext(cfg, executor=executor)
    ws = tmp_path / "proj"
    ws.mkdir(exist_ok=True)
    hc.set_workspace(str(ws))
    return hc


def test_git_runs_with_hooks_disabled(tmp_path):
    spy = SpyExecutor("")
    hc = _hc(tmp_path, spy)
    run(gitcmd.git(hc, hc.active_workspace, "rev-parse", "--show-toplevel"))
    assert spy.calls, "git must route through executor.run_argv"
    argv = spy.calls[0]
    assert argv[0] == "git"
    assert "core.hooksPath=" + os.devnull in " ".join(argv), "git must disable repo hooks"


def test_grep_routes_through_executor(tmp_path):
    import shutil
    if shutil.which("rg") is None:
        pytest.skip("ripgrep not installed; python fallback path")
    spy = SpyExecutor("")
    hc = _hc(tmp_path, spy)
    (hc.active_workspace / "a.py").write_text("needle = 1\n", encoding="utf-8")
    run(search.grep(hc, "needle"))
    assert any(c and c[0].endswith("rg") or "rg" in (c[0] if c else "") for c in spy.calls), \
        "grep must route ripgrep through executor.run_argv"
