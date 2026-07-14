from __future__ import annotations

import asyncio

from harness.tools import todos


def run(coro):
    return asyncio.run(coro)


def test_write_and_list_todos_from_strings(hc):
    run(todos.write_todos(hc, ["Find the bug", "Fix it", "Add a test"]))
    out = run(todos.list_todos(hc))
    assert "Find the bug" in out and "Add a test" in out
    assert "0/3 complete" in out


def test_todos_with_status(hc):
    run(todos.write_todos(hc, [
        {"content": "step one", "status": "completed"},
        {"content": "step two", "status": "in_progress"},
        {"content": "step three"},
    ]))
    out = run(todos.list_todos(hc))
    assert "[x] step one" in out
    assert "[~] step two" in out
    assert "[ ] step three" in out
    assert "1/3 complete" in out


def test_write_todos_replaces(hc):
    run(todos.write_todos(hc, ["old"]))
    run(todos.write_todos(hc, ["new"]))
    out = run(todos.list_todos(hc))
    assert "new" in out and "old" not in out


def test_invalid_status_defaults_pending(hc):
    run(todos.write_todos(hc, [{"content": "x", "status": "bogus"}]))
    out = run(todos.list_todos(hc))
    assert "[ ] x" in out
