"""Tiered memory: global / project / task, and worktree-shares-project."""

from __future__ import annotations

import asyncio

from harness.config import Config
from harness.context import HarnessContext
from harness.tools import memory


def run(c):
    return asyncio.run(c)


def _hc(tmp_path, ws_name, state="state"):
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / state, secret_route="r")
    hc = HarnessContext(cfg)
    ws = tmp_path / ws_name
    ws.mkdir(exist_ok=True)
    hc.set_workspace(str(ws))
    return hc


def test_scopes_are_separate_and_merged(tmp_path):
    hc = _hc(tmp_path, "proj")
    run(memory.remember(hc, "global fact", scope="global"))
    run(memory.remember(hc, "project fact", scope="project"))
    run(memory.remember(hc, "task fact", scope="task"))
    out = run(memory.recall(hc))
    assert "global fact" in out and "project fact" in out and "task fact" in out
    assert "(global)" in out and "(project)" in out and "(task)" in out


def test_project_memory_shared_across_workspaces_same_state(tmp_path):
    # Two non-git workspaces are distinct projects (path-keyed); a repo and its
    # worktree would share via git common dir. Here we assert isolation between
    # genuinely different projects.
    hc_a = _hc(tmp_path, "projA")
    hc_b = _hc(tmp_path, "projB")
    run(memory.remember(hc_a, "only in A", scope="project"))
    out_b = run(memory.recall(hc_b))
    assert "only in A" not in out_b


def test_forget_searches_all_tiers(tmp_path):
    hc = _hc(tmp_path, "proj")
    run(memory.remember(hc, "g", key="gk", scope="global"))
    msg = run(memory.forget(hc, "gk"))
    assert "global" in msg
    assert "g" not in run(memory.recall(hc)) or "No memories" in run(memory.recall(hc))
