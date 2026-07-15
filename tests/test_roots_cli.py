"""UX1: operator-managed workspace roots via `harness roots` + roots.json merge.

The user's pain: adding a project folder meant editing HARNESS_WORKSPACE_ROOTS
in the launch-cwd .env and restarting. roots.json (state dir) + a CLI make it a
one-liner — and crucially, roots are operator-only: no MCP tool writes them, and
roots.json lives outside every workspace root so the model can't reach it.
"""

from __future__ import annotations

import os

import pytest

from harness.__main__ import _cmd_roots
from harness.config import Config


@pytest.fixture
def cfg(tmp_path):
    return Config(workspace_roots=[tmp_path / "seed"], state_dir=tmp_path / "state",
                  secret_route="x")


def test_add_and_list_roundtrip(tmp_path, cfg, capsys):
    proj = tmp_path / "projects"
    proj.mkdir()
    assert _cmd_roots(cfg, "add", str(proj)) == 0
    assert os.path.realpath(str(proj)) in Config.load_extra_roots(cfg.state_dir)


def test_roots_json_merged_into_config(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir(parents=True)
    proj = tmp_path / "extra"
    proj.mkdir()
    cfg = Config(state_dir=state, secret_route="x")
    _cmd_roots(cfg, "add", str(proj))

    # from_env is the real startup path (harness __main__ uses it); it merges
    # roots.json so the added root is active after restart.
    monkeypatch.setenv("HARNESS_STATE_DIR", str(state))
    monkeypatch.setenv("HARNESS_SECRET_ROUTE", "x")
    fresh = Config.from_env(load_dotenv=False)
    roots = [os.path.realpath(str(r)) for r in fresh.workspace_roots]
    assert os.path.realpath(str(proj)) in roots


def test_env_and_file_roots_both_active(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir(parents=True)
    env_root = tmp_path / "from_env"
    env_root.mkdir()
    file_root = tmp_path / "from_file"
    file_root.mkdir()

    cfg = Config(state_dir=state, secret_route="x")
    _cmd_roots(cfg, "add", str(file_root))

    monkeypatch.setenv("HARNESS_STATE_DIR", str(state))
    monkeypatch.setenv("HARNESS_SECRET_ROUTE", "x")
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(env_root))
    merged = Config.from_env(load_dotenv=False)
    roots = [os.path.realpath(str(r)) for r in merged.workspace_roots]
    assert os.path.realpath(str(env_root)) in roots
    assert os.path.realpath(str(file_root)) in roots


def test_remove(tmp_path, cfg):
    proj = tmp_path / "p"
    proj.mkdir()
    _cmd_roots(cfg, "add", str(proj))
    assert _cmd_roots(cfg, "remove", str(proj)) == 0
    assert os.path.realpath(str(proj)) not in Config.load_extra_roots(cfg.state_dir)


def test_add_rejects_nonexistent_dir(tmp_path, cfg):
    assert _cmd_roots(cfg, "add", str(tmp_path / "nope")) == 1


def test_roots_json_is_outside_workspace_roots(tmp_path):
    """The model cannot write roots.json: it lives in the state dir, which is not
    inside any workspace root, so path confinement blocks it."""
    from harness.security import is_within

    state = tmp_path / "state"
    state.mkdir(parents=True)
    cfg = Config(workspace_roots=[tmp_path / "ws"], state_dir=state, secret_route="x")
    (tmp_path / "ws").mkdir()
    roots_file = Config._roots_file(cfg.state_dir)
    assert not any(is_within(roots_file, root) for root in cfg.workspace_roots)
