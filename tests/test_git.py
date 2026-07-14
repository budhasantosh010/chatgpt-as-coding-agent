"""Checkpoint / restore cycle tests — the highest-risk logic in the harness.

These prove a snapshot can fully restore the working tree: modified files revert,
deleted files come back, and files added after the snapshot are removed.
"""

from __future__ import annotations

import asyncio
import subprocess

import pytest

from harness.tools import git


def run(coro):
    return asyncio.run(coro)


def _git_init(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


@pytest.fixture
def git_hc(hc, workspace):
    _git_init(workspace)
    return hc


def test_checkpoint_and_restore_reverts_modifications(git_hc, workspace):
    (workspace / "a.txt").write_text("original", encoding="utf-8")

    out = run(git.create_checkpoint(git_hc, "before edits"))
    assert "created" in out.lower()
    cid = out.split()[1]

    (workspace / "a.txt").write_text("CHANGED", encoding="utf-8")
    assert (workspace / "a.txt").read_text(encoding="utf-8") == "CHANGED"

    run(git.restore_checkpoint(git_hc, cid))
    assert (workspace / "a.txt").read_text(encoding="utf-8") == "original"


def test_restore_removes_files_added_after_checkpoint(git_hc, workspace):
    (workspace / "keep.txt").write_text("keep", encoding="utf-8")
    out = run(git.create_checkpoint(git_hc, "snap"))
    cid = out.split()[1]

    (workspace / "added_later.txt").write_text("junk", encoding="utf-8")
    assert (workspace / "added_later.txt").exists()

    run(git.restore_checkpoint(git_hc, cid))
    assert not (workspace / "added_later.txt").exists()
    assert (workspace / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_restore_recreates_deleted_files(git_hc, workspace):
    (workspace / "gone.txt").write_text("here", encoding="utf-8")
    out = run(git.create_checkpoint(git_hc, "snap"))
    cid = out.split()[1]

    (workspace / "gone.txt").unlink()
    assert not (workspace / "gone.txt").exists()

    run(git.restore_checkpoint(git_hc, cid))
    assert (workspace / "gone.txt").read_text(encoding="utf-8") == "here"


def test_list_checkpoints(git_hc):
    run(git.create_checkpoint(git_hc, "one"))
    run(git.create_checkpoint(git_hc, "two"))
    out = run(git.list_checkpoints(git_hc))
    assert "one" in out and "two" in out


def test_git_diff_shows_changes(git_hc, workspace):
    (workspace / "f.txt").write_text("v1\n", encoding="utf-8")
    out = run(git.git_diff(git_hc))
    assert "f.txt" in out


def test_checkpoint_without_git_is_graceful(hc):
    # hc's workspace is not a git repo here.
    out = run(git.create_checkpoint(hc, "x"))
    assert "not a git repository" in out.lower()


def test_unknown_checkpoint_id(git_hc):
    out = run(git.restore_checkpoint(git_hc, "cp-does-not-exist"))
    assert "unknown checkpoint" in out.lower()
