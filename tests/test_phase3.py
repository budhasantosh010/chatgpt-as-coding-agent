"""Phase 3 tools: notebook, image, subtasks, git_commit."""

from __future__ import annotations

import asyncio
import json
import shutil

import pytest

from harness.config import Config
from harness.context import HarnessServer
from harness.tasks import tools as tt
from harness.tools import images, notebook, vcs


def run(c):
    return asyncio.run(c)


def _server_hc(tmp_path):
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "s", secret_route="r")
    server = HarnessServer(cfg)
    hc = server.session_for("s")
    ws = tmp_path / "proj"; ws.mkdir()
    hc.set_workspace(str(ws))
    return server, hc, ws


_NB = {
    "cells": [
        {"cell_type": "markdown", "metadata": {}, "source": ["# Title\n"]},
        {"cell_type": "code", "metadata": {}, "source": ["x = 1\n"], "outputs": [], "execution_count": None},
    ],
    "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
}


def test_notebook_read_and_edit(tmp_path):
    _s, hc, ws = _server_hc(tmp_path)
    (ws / "nb.ipynb").write_text(json.dumps(_NB), encoding="utf-8")
    out = run(notebook.notebook_read(hc, "nb.ipynb"))
    assert "[0] markdown" in out and "[1] code" in out

    run(notebook.notebook_edit(hc, "nb.ipynb", 1, "x = 42\n", "replace"))
    nb = json.loads((ws / "nb.ipynb").read_text(encoding="utf-8"))
    assert "".join(nb["cells"][1]["source"]) == "x = 42\n"

    run(notebook.notebook_edit(hc, "nb.ipynb", 0, "# inserted\n", "insert", "markdown"))
    nb = json.loads((ws / "nb.ipynb").read_text(encoding="utf-8"))
    assert len(nb["cells"]) == 3

    run(notebook.notebook_edit(hc, "nb.ipynb", 0, mode="delete"))
    nb = json.loads((ws / "nb.ipynb").read_text(encoding="utf-8"))
    assert len(nb["cells"]) == 2


def test_read_image_bytes(tmp_path):
    _s, hc, ws = _server_hc(tmp_path)
    # a tiny valid-enough PNG header + data
    png = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 32
    (ws / "shot.png").write_bytes(png)
    data, fmt = images.read_image_bytes(hc, "shot.png")
    assert fmt == "png" and data == png


def test_read_image_rejects_non_image(tmp_path):
    _s, hc, ws = _server_hc(tmp_path)
    (ws / "notes.txt").write_text("hi", encoding="utf-8")
    with pytest.raises(ValueError):
        images.read_image_bytes(hc, "notes.txt")


def test_create_subtask(tmp_path):
    server, hc, ws = _server_hc(tmp_path)
    parent = next(t for t in tt.start_task(server, str(ws), "parent goal", "auto_workspace").split() if t.startswith("T-"))
    out = tt.create_subtask(server, parent, "child goal")
    child = next(t for t in out.split() if t.startswith("T-") and t != parent)
    ctask = server.tasks.get_task(child)
    assert ctask.parent_id == parent
    listing = tt.list_tasks(server)
    assert "└" in listing  # child indented


def test_git_commit(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    server, hc, ws = _server_hc(tmp_path)
    run(vcs.gitcmd.git(hc, ws, "init", hardened=False))
    run(vcs.gitcmd.git(hc, ws, "config", "user.email", "t@t", hardened=False))
    run(vcs.gitcmd.git(hc, ws, "config", "user.name", "t", hardened=False))
    (ws / "a.txt").write_text("hello\n", encoding="utf-8")
    out = run(vcs.git_commit(hc, "add a"))
    assert "Committed" in out
    # second commit with nothing new
    out2 = run(vcs.git_commit(hc, "noop"))
    assert "Nothing to commit" in out2
