"""Stale-write guard + auto-checkpoint-before-edit (data-loss protections)."""

from __future__ import annotations

import asyncio

import pytest

from harness.config import Config
from harness.context import HarnessServer
from harness.policy import Capability
from harness.server import _call
from harness.tools import files, git


def run(c):
    return asyncio.run(c)


def _server_hc(tmp_path):
    # no_task_mode="full": these tests exercise write paths through the
    # fallback session, not the S2 cap (tests/test_no_task_fallback.py pins that).
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state",
                 secret_route="r", mode="full", no_task_mode="full")
    server = HarnessServer(cfg)
    hc = server.session_for("s")
    ws = tmp_path / "proj"
    ws.mkdir(exist_ok=True)
    hc.set_workspace(str(ws))
    return hc, ws


def test_read_file_surfaces_sha(tmp_path):
    hc, ws = _server_hc(tmp_path)
    (ws / "f.txt").write_text("hello\n", encoding="utf-8")
    out = run(files.read_file(hc, "f.txt"))
    assert "sha256:" in out


def test_stale_write_is_rejected(tmp_path):
    hc, ws = _server_hc(tmp_path)
    (ws / "f.txt").write_text("original\n", encoding="utf-8")
    out = run(files.read_file(hc, "f.txt"))
    sha = out.split("sha256:")[1].split("]")[0]
    # Someone edits the file externally after the model read it.
    (ws / "f.txt").write_text("changed by human\n", encoding="utf-8")
    with pytest.raises(ValueError):
        run(files.write_file(hc, "f.txt", "model version\n", expected_sha=sha))
    # The human's change survives.
    assert (ws / "f.txt").read_text(encoding="utf-8") == "changed by human\n"


def test_fresh_write_with_correct_sha_succeeds(tmp_path):
    hc, ws = _server_hc(tmp_path)
    (ws / "f.txt").write_text("original\n", encoding="utf-8")
    out = run(files.read_file(hc, "f.txt"))
    sha = out.split("sha256:")[1].split("]")[0]
    msg = run(files.write_file(hc, "f.txt", "new\n", expected_sha=sha))
    assert "Overwrote" in msg or "Created" in msg


def test_auto_checkpoint_before_edit(tmp_path):
    # A WRITE through _call auto-creates a checkpoint (repo must exist).
    hc, ws = _server_hc(tmp_path)
    run(git._git(hc, ws, "init"))
    (ws / "a.txt").write_text("v1\n", encoding="utf-8")
    run(git._git(hc, ws, "add", "-A"))
    run(git._git(hc, ws, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init"))

    before = run(_call(hc, Capability.READ, git.list_checkpoints))
    assert "No checkpoints" in before
    run(_call(hc, Capability.WRITE, files.write_file, "a.txt", "v2\n"))
    after = run(_call(hc, Capability.READ, git.list_checkpoints))
    assert "auto (pre-edit)" in after
