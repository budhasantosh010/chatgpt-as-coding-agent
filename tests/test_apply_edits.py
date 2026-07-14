from __future__ import annotations

import asyncio

import pytest

from harness.tools import files


def run(coro):
    return asyncio.run(coro)


def test_multi_op_atomic_apply(hc, workspace):
    (workspace / "keep.py").write_text("value = 1\n", encoding="utf-8")
    (workspace / "old.txt").write_text("bye", encoding="utf-8")

    out = run(files.apply_edits(hc, [
        {"path": "new.py", "content": "print('hi')\n"},
        {"path": "keep.py", "old_string": "value = 1", "new_string": "value = 2"},
        {"path": "old.txt", "delete": True},
    ]))
    assert "3 operation" in out
    assert (workspace / "new.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert (workspace / "keep.py").read_text(encoding="utf-8") == "value = 2\n"
    assert not (workspace / "old.txt").exists()


def test_rollback_on_invalid_edit_changes_nothing(hc, workspace):
    (workspace / "a.py").write_text("original a\n", encoding="utf-8")

    # Second op is invalid (old_string not found) -> whole batch must abort,
    # and the first op (creating b.py) must not persist.
    with pytest.raises(ValueError):
        run(files.apply_edits(hc, [
            {"path": "b.py", "content": "new file\n"},
            {"path": "a.py", "old_string": "does-not-exist", "new_string": "x"},
        ]))

    assert (workspace / "a.py").read_text(encoding="utf-8") == "original a\n"
    assert not (workspace / "b.py").exists()  # validation aborted before any write


def test_empty_edits_rejected(hc):
    with pytest.raises(ValueError):
        run(files.apply_edits(hc, []))
