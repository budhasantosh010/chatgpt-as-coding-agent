"""Task lifecycle tools: register_project, start_task, list/status/resume,
set goal/criteria, advance state, finish, cancel.

These operate on the shared TaskStore (via the server), not a single workspace
context — they create and steer the tasks that everything else is scoped to.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..policy import VALID_MODES
from ..security import SecurityError, is_within
from .model import TaskState, can_transition


def _validate_workspace(config, path: str) -> Path:
    cand = Path(os.path.realpath(os.path.expanduser(str(path))))
    if not cand.exists() or not cand.is_dir():
        raise SecurityError(f"Workspace path does not exist or is not a directory: {cand}")
    if not any(is_within(cand, r) for r in config.workspace_roots):
        allowed = ", ".join(str(r) for r in config.workspace_roots)
        raise SecurityError(f"{cand} is outside the approved roots. Allowed: {allowed}")
    return cand


def register_project(server, path: str, name: str = "") -> str:
    ws = _validate_workspace(server.config, path)
    pid = server.tasks.register_project(str(ws), name)
    return f"Project registered: {pid}\n  path: {ws}\n  name: {name or ws.name}"


def start_task(server, project_path: str, goal: str, permission_mode: str = "auto_workspace", title: str = "") -> str:
    ws = _validate_workspace(server.config, project_path)
    if permission_mode not in VALID_MODES:
        raise SecurityError(f"permission_mode must be one of {VALID_MODES}, got {permission_mode!r}")
    if not goal or not goal.strip():
        raise SecurityError("A task needs a goal.")
    pid = server.tasks.register_project(str(ws))
    task = server.tasks.create_task(
        pid, str(ws), goal=goal.strip(), title=(title or goal[:60]).strip(),
        permission_mode=permission_mode,
    )
    return (
        f"Started task {task.id}\n"
        f"  goal: {task.goal}\n"
        f"  workspace: {ws}\n"
        f"  permission mode: {permission_mode}\n"
        f"  state: {task.status.value}\n\n"
        f"Pass task_id=\"{task.id}\" to every tool call for this task so its work "
        f"stays isolated and resumable."
    )


def list_tasks(server, status: str | None = None) -> str:
    tasks = server.tasks.list_tasks(status=status)
    if not tasks:
        return "No tasks yet. Create one with start_task(project_path, goal)."
    lines = ["# Tasks"]
    for t in tasks:
        lines.append(f"  [{t.id}] {t.status.value:12} {t.title or t.goal[:50]}")
    return "\n".join(lines)


def _render_task(server, task) -> list[str]:
    lines = [
        f"# Task {task.id} — {task.status.value}",
        f"**Goal:** {task.goal}",
        f"**Workspace:** {task.worktree_path or task.workspace_path}",
        f"**Permission mode:** {task.permission_mode}",
    ]
    if task.acceptance_criteria:
        lines.append("**Acceptance criteria:**")
        lines += [f"  - {c}" for c in task.acceptance_criteria]
    if task.plan:
        lines.append("**Plan:**")
        lines += [f"  - {p}" for p in task.plan]
    if task.changed_files:
        lines.append(f"**Changed files:** {', '.join(task.changed_files)}")
    if task.blockers:
        lines.append(f"**Blockers:** {'; '.join(task.blockers)}")
    if task.result:
        lines.append(f"**Result:** {task.result}")
    return lines


def _get(server, task_id):
    task = server.tasks.get_task(task_id)
    if task is None:
        raise SecurityError(f"Unknown task_id {task_id!r}. Use list_tasks.")
    return task


def task_status(server, task_id: str) -> str:
    task = _get(server, task_id)
    lines = _render_task(server, task)
    events = server.tasks.events(task_id, 15)
    if events:
        lines += ["", "**Recent events:**"]
        for e in events:
            extra = {k: v for k, v in e.items() if k not in ("time", "type")}
            lines.append(f"  {e['time']}  {e['type']}  {extra or ''}")
    return "\n".join(lines)


def resume_task(server, task_id: str) -> str:
    task = _get(server, task_id)
    return (
        f"Resuming task {task.id} ({task.status.value}).\n"
        + "\n".join(_render_task(server, task))
        + f"\n\nContinue by passing task_id=\"{task_id}\" to your tool calls."
    )


def set_task_goal(server, task_id: str, goal: str) -> str:
    task = _get(server, task_id)
    task.goal = goal.strip()
    server.tasks.save_task(task)
    server.tasks.add_event(task_id, "goal_set", goal=task.goal)
    return f"Updated goal for {task_id}."


def set_acceptance_criteria(server, task_id: str, criteria: list) -> str:
    task = _get(server, task_id)
    task.acceptance_criteria = [str(c).strip() for c in criteria if str(c).strip()]
    server.tasks.save_task(task)
    server.tasks.add_event(task_id, "criteria_set", count=len(task.acceptance_criteria))
    return f"Set {len(task.acceptance_criteria)} acceptance criteria for {task_id}."


def advance_task(server, task_id: str, to_state: str) -> str:
    task = _get(server, task_id)
    try:
        target = TaskState(to_state)
    except ValueError:
        return f"Unknown state {to_state!r}. Valid: {', '.join(s.value for s in TaskState)}"
    if not can_transition(task.status, target):
        return f"Illegal transition {task.status.value} → {target.value}."
    prev = task.status
    task.status = target
    server.tasks.save_task(task)
    server.tasks.add_event(task_id, "state_change", **{"from": prev.value, "to": target.value})
    return f"Task {task_id}: {prev.value} → {target.value}."


def finish_task(server, task_id: str, result: str = "") -> str:
    task = _get(server, task_id)
    if not can_transition(task.status, TaskState.COMPLETED):
        return (
            f"Task is {task.status.value}; move it to review_ready before completing "
            f"(advance_task). Or cancel_task if abandoning."
        )
    task.status = TaskState.COMPLETED
    task.result = result.strip() or "completed"
    server.tasks.save_task(task)
    server.tasks.add_event(task_id, "completed", result=task.result)
    return f"Task {task_id} completed. {task.result}"


def cancel_task(server, task_id: str, reason: str = "") -> str:
    task = _get(server, task_id)
    task.status = TaskState.CANCELLED
    task.result = f"cancelled: {reason}".strip(": ")
    server.tasks.save_task(task)
    server.tasks.add_event(task_id, "cancelled", reason=reason)
    return f"Task {task_id} cancelled."
