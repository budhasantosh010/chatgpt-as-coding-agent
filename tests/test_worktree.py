from __future__ import annotations

import asyncio
import subprocess

import pytest

from harness.tools import worktree


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def git_repo_hc(hc, workspace):
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    (workspace / "f.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=workspace,
        check=True,
    )
    return hc


def test_create_and_list_worktree(git_repo_hc):
    out = run(worktree.create_worktree(git_repo_hc, "experiment"))
    assert "Created worktree 'experiment'" in out

    listed = run(worktree.list_worktrees(git_repo_hc))
    assert "experiment" in listed


def test_worktree_has_repo_content(git_repo_hc):
    out = run(worktree.create_worktree(git_repo_hc, "feature-x"))
    # Extract the path line and confirm the committed file is present in isolation.
    path_line = out.splitlines()[1]
    from pathlib import Path

    assert (Path(path_line) / "f.txt").read_text(encoding="utf-8") == "hello\n"


def test_remove_worktree(git_repo_hc):
    run(worktree.create_worktree(git_repo_hc, "temp"))
    out = run(worktree.remove_worktree(git_repo_hc, "temp"))
    assert "Removed worktree 'temp'" in out
    listed = run(worktree.list_worktrees(git_repo_hc))
    assert "temp" not in listed


def test_worktree_without_git(hc):
    out = run(worktree.create_worktree(hc, "x"))
    assert "Not a git repository" in out
