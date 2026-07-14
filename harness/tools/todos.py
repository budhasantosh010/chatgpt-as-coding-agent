"""Todo / plan surface: a persistent, structured task list per workspace.

This is the antidote to ChatGPT owning the turn loop: the agent writes a plan,
marks steps in_progress/completed, and it survives turn resets — so a new turn
can resume exactly where the last left off (surfaced in session_status).
"""

from __future__ import annotations

import json

from ..context import HarnessContext

_VALID_STATUS = {"pending", "in_progress", "completed"}
_MARKS = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}


def _todos_path(hc: HarnessContext):
    hc.require_workspace()
    assert hc.session is not None
    return hc.session.dir / "todos.json"


def load_todos(hc: HarnessContext) -> list[dict]:
    p = _todos_path(hc)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []


def _save(hc: HarnessContext, items: list[dict]) -> None:
    _todos_path(hc).write_text(json.dumps(items, indent=2), encoding="utf-8")


def format_todos(items: list[dict]) -> str:
    if not items:
        return "No todos. Use write_todos to plan a multi-step task."
    lines = ["# Todos"]
    for t in items:
        lines.append(f"{_MARKS.get(t['status'], '[ ]')} {t['content']}")
    done = sum(1 for t in items if t["status"] == "completed")
    lines.append(f"\n({done}/{len(items)} complete)")
    return "\n".join(lines)


def _normalize(todos: list) -> list[dict]:
    out: list[dict] = []
    for t in todos:
        if isinstance(t, str):
            content, status = t, "pending"
        elif isinstance(t, dict):
            content = str(t.get("content") or t.get("task") or "").strip()
            status = t.get("status", "pending")
            if status not in _VALID_STATUS:
                status = "pending"
        else:
            continue
        if content:
            out.append({"content": content, "status": status})
    return out


async def write_todos(hc: HarnessContext, todos: list) -> str:
    hc.require_workspace()
    items = _normalize(todos)
    _save(hc, items)
    hc.log("write_todos", count=len(items))
    return format_todos(items)


async def list_todos(hc: HarnessContext) -> str:
    hc.require_workspace()
    return format_todos(load_todos(hc))
