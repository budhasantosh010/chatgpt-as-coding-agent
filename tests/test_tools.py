"""Tool behavior tests. Async tools are driven via asyncio.run so no
pytest-asyncio dependency is needed.
"""

from __future__ import annotations

import asyncio

import pytest

from harness.tools import files, search


def run(coro):
    return asyncio.run(coro)


def test_write_then_read_roundtrip(hc):
    msg = run(files.write_file(hc, "a/b/note.txt", "line1\nline2\n"))
    assert "Created" in msg
    content = run(files.read_file(hc, "a/b/note.txt"))
    assert "line1" in content and "line2" in content


def test_edit_unique(hc, workspace):
    (workspace / "f.txt").write_text("hello world", encoding="utf-8")
    run(files.edit_file(hc, "f.txt", "world", "there"))
    assert (workspace / "f.txt").read_text(encoding="utf-8") == "hello there"


def test_edit_ambiguous_raises(hc, workspace):
    (workspace / "f.txt").write_text("x x x", encoding="utf-8")
    with pytest.raises(ValueError):
        run(files.edit_file(hc, "f.txt", "x", "y"))


def test_edit_replace_all(hc, workspace):
    (workspace / "f.txt").write_text("x x x", encoding="utf-8")
    run(files.edit_file(hc, "f.txt", "x", "y", replace_all=True))
    assert (workspace / "f.txt").read_text(encoding="utf-8") == "y y y"


def test_read_offset_limit(hc, workspace):
    (workspace / "big.txt").write_text("\n".join(str(i) for i in range(1, 101)), encoding="utf-8")
    out = run(files.read_file(hc, "big.txt", offset=10, limit=5))
    assert "10" in out and "14" in out and "\n20" not in out


def test_list_dir(hc, workspace):
    (workspace / "one.txt").write_text("1", encoding="utf-8")
    (workspace / "sub").mkdir()
    out = run(files.list_dir(hc, None))
    assert "one.txt" in out and "sub/" in out


def test_glob(hc, workspace):
    (workspace / "a.py").write_text("x", encoding="utf-8")
    (workspace / "b.py").write_text("x", encoding="utf-8")
    (workspace / "c.txt").write_text("x", encoding="utf-8")
    out = run(search.glob_files(hc, "*.py"))
    assert "a.py" in out and "b.py" in out and "c.txt" not in out


def test_grep(hc, workspace):
    (workspace / "code.py").write_text("def target():\n    return 42\n", encoding="utf-8")
    out = run(search.grep(hc, "target"))
    assert "code.py" in out and "target" in out


def test_read_missing_file_raises(hc):
    with pytest.raises(FileNotFoundError):
        run(files.read_file(hc, "does-not-exist.txt"))
