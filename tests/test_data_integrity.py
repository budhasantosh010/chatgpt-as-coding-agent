"""Data-integrity fixes: memory id collisions, atomic writes, worktree
namespacing + guarded removal."""

from __future__ import annotations

import asyncio

from harness.statefile import read_json, write_json_atomic
from harness.tools import memory


def run(c):
    return asyncio.run(c)


def test_memory_ids_do_not_collide_after_delete(hc):
    run(memory.remember(hc, "first"))    # m1
    run(memory.remember(hc, "second"))   # m2
    run(memory.remember(hc, "third"))    # m3
    run(memory.forget(hc, "m1"))         # delete earliest
    run(memory.remember(hc, "fourth"))   # must NOT reuse m3
    items = memory.load_memories(hc)
    ids = [it["id"] for it in items]
    assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"
    assert "m4" in ids


def test_atomic_write_roundtrip(tmp_path):
    p = tmp_path / "state" / "x.json"
    write_json_atomic(p, {"a": 1, "b": [2, 3]})
    assert read_json(p, None) == {"a": 1, "b": [2, 3]}
    # no leftover temp files
    assert not list(p.parent.glob("*.tmp*"))


def test_read_json_tolerates_corruption(tmp_path):
    p = tmp_path / "y.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert read_json(p, []) == []


def test_worktree_dir_namespaced_by_repo_path(tmp_path):
    from harness.config import Config
    from harness.context import HarnessContext
    from harness.tools.worktree import _worktree_dir
    from pathlib import Path

    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "s", secret_route="r")
    hc = HarnessContext(cfg)
    a = _worktree_dir(hc, Path("/home/alice/proj"), "task")
    b = _worktree_dir(hc, Path("/home/bob/proj"), "task")
    assert a != b, "same-basename repos must not share a worktree dir"
