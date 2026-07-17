"""Task lifecycle tools: register_project, start_task, list/status/resume,
set goal/criteria, advance state, finish, cancel.

These operate on the shared TaskStore (via the server), not a single workspace
context — they create and steer the tasks that everything else is scoped to.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..policy import VALID_MODES, check_ceiling
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


async def create_project(server, path: str, name: str = "") -> str:
    """Create a NEW project folder (git init + initial commit) and register it.

    Confinement (checklist 0.2): the new folder must sit INSIDE an existing
    approved root — this tool can create projects, never widen access. Creating
    a folder outside every root is an operator action (cockpit/CLI: roots add).
    The initial commit exists so worktree isolation works from the first task.
    """
    cand = Path(os.path.realpath(os.path.expanduser(str(path))))
    if not any(is_within(cand, r) for r in server.config.workspace_roots):
        allowed = ", ".join(str(r) for r in server.config.workspace_roots)
        raise SecurityError(
            f"{cand} is outside the approved roots — create_project cannot widen "
            f"access. Allowed roots: {allowed}"
        )
    if cand.exists() and any(cand.iterdir()):
        return (f"{cand} already exists and is not empty. Use register_project for "
                "existing folders.")
    cand.mkdir(parents=True, exist_ok=True)

    from types import SimpleNamespace

    from ..tools import gitcmd

    shim = SimpleNamespace(executor=server.executor, config=server.config)
    git_note = "git repository initialized"
    r = await gitcmd.git(shim, cand, "init")
    if r.returncode != 0:
        git_note = f"git init failed ({(r.stderr or r.stdout).strip()[:120]}) — no worktree isolation"
    else:
        readme = cand / "README.md"
        if not readme.exists():
            readme.write_text(f"# {name or cand.name}\n", encoding="utf-8")
        await gitcmd.git(shim, cand, "add", "-A")
        # Explicit fallback identity so the initial commit works even on a
        # machine with no global git user configured.
        c = await gitcmd.git(shim, cand, "-c", "user.name=harness",
                             "-c", "user.email=harness@localhost",
                             "commit", "-m", "Initial commit (create_project)")
        if c.returncode != 0:
            git_note = f"git init ok, initial commit failed ({(c.stderr or c.stdout).strip()[:120]})"
    pid = server.tasks.register_project(str(cand), name)
    return (
        f"Project created: {pid}\n  path: {cand}\n  name: {name or cand.name}\n"
        f"  {git_note}\nStart work with start_task(\"{cand}\", goal)."
    )


def _shared_checkout_gate(server, ws: Path) -> str | None:
    """Approval gate for isolation='workspace' (checklist 0.3). Keyed to the
    project path under the pseudo-task '_server' (no task exists yet); one-shot,
    hash-bound like every other approval."""
    import hashlib

    rhash = hashlib.sha256(f"_server\0start_task\0shared_checkout\0{ws}".encode()).hexdigest()
    granted = server.tasks.grantable_approval("_server", "shared_checkout", rhash)
    if granted:
        server.tasks.consume_approval(granted["id"])
        return None
    aid = server.tasks.add_approval(
        "_server", "shared_checkout", f"start_task: shared checkout in {ws}", rhash
    )
    return (
        "⏸ APPROVAL REQUIRED — isolation='workspace' gives up the task's own "
        "worktree and edits the shared checkout directly. The operator must "
        f"approve on the machine:\n    python -m harness approvals approve {aid}\n"
        "Then retry the same start_task call (or use isolation='auto' for an "
        "isolated worktree — the recommended default)."
    )


async def start_task(server, project_path: str, goal: str, permission_mode: str = "auto_workspace",
                     title: str = "", isolation: str = "", operator: bool = False) -> str:
    ws = _validate_workspace(server.config, project_path)
    if permission_mode not in VALID_MODES:
        raise SecurityError(f"permission_mode must be one of {VALID_MODES}, got {permission_mode!r}")
    # Server-side ceiling: the model may not grant itself privileges. full /
    # bypass_sandboxed (by default) are operator-only via the local CLI.
    check_ceiling(permission_mode, server.config.max_mode, server.config.sandbox)
    if not goal or not goal.strip():
        raise SecurityError("A task needs a goal.")
    # Empty isolation => use the operator's configured default (default_isolation,
    # normally "workspace": work in the project folder, like Codex/Claude Code).
    default_iso = getattr(server.config, "default_isolation", "workspace")
    model_chose = bool(isolation)
    if not isolation:
        isolation = default_iso
    if isolation not in ("auto", "worktree", "workspace"):
        raise SecurityError("isolation must be 'auto', 'worktree', or 'workspace'.")
    # Checklist 0.3: the MODEL must not silently opt out of physical isolation.
    # But when the operator has CONFIGURED workspace as the default, or the
    # operator (cockpit) starts the task, working in the checkout is the intended
    # behavior — no gate. The gate fires only when the model itself overrides an
    # isolation-default to grab the shared checkout.
    if isolation == "workspace" and model_chose and not operator and default_iso != "workspace":
        gate = _shared_checkout_gate(server, ws)
        if gate is not None:
            return gate
    pid = server.tasks.register_project(str(ws))
    task = server.tasks.create_task(
        pid, str(ws), goal=goal.strip(), title=(title or goal[:60]).strip(),
        permission_mode=permission_mode,
    )
    # Physical isolation: bind a worktree so concurrent tasks on the same
    # project never edit the same files. "auto" = worktree when it's a git repo
    # with commits; "workspace" opts into the shared checkout.
    iso_note = "shared checkout (isolation='workspace')"
    if isolation != "workspace":
        from ..tools import worktree as worktree_tool

        wt, base_commit, note = await worktree_tool.create_for_task(server, ws, task.id)
        task.base_commit = base_commit
        if wt is not None:
            task.worktree_path = str(wt)
            server.tasks.add_event(task.id, "worktree_bound", path=str(wt), base=base_commit)
        elif isolation == "worktree":
            server.tasks.save_task(task)
            raise SecurityError(f"isolation='worktree' requested but unavailable: {note}")
        server.tasks.save_task(task)
        iso_note = note
    active = task.worktree_path or str(ws)
    tail = ("stays isolated and resumable" if task.worktree_path
            else "is tracked and resumable")
    return (
        f"Started task {task.id}\n"
        f"  goal: {task.goal}\n"
        f"  working path: {active}\n"
        f"  isolation: {iso_note}\n"
        f"  permission mode: {permission_mode}\n"
        f"  state: {task.status.value}\n\n"
        f"Pass task_id=\"{task.id}\" to every tool call for this task so its work "
        f"{tail}."
    )


def create_subtask(server, parent_task_id: str, goal: str, title: str = "") -> str:
    """Decompose a task into a child task (same project/workspace/mode). Note:
    these are sub-*tasks* the same ChatGPT works through — not autonomous LLM
    sub-agents, which don't apply here (the harness has no model; ChatGPT is the
    brain)."""
    parent = _get(server, parent_task_id)
    if not goal or not goal.strip():
        raise SecurityError("A subtask needs a goal.")
    child = server.tasks.create_task(
        parent.project_id, parent.workspace_path, goal=goal.strip(),
        title=(title or goal[:60]).strip(), permission_mode=parent.permission_mode,
        parent_id=parent.id,
        # A subtask decomposes the SAME unit of work, so it shares the parent's
        # working copy (worktree) — no elevation flag is inherited, though.
        worktree_path=parent.worktree_path, base_commit=parent.base_commit,
    )
    server.tasks.add_event(parent.id, "subtask_created", child=child.id, goal=child.goal)
    return f"Created subtask {child.id} under {parent.id}\n  goal: {child.goal}\n  pass task_id=\"{child.id}\" for its work."


def list_tasks(server, status: str | None = None) -> str:
    tasks = server.tasks.list_tasks(status=status)
    if not tasks:
        return "No tasks yet. Create one with start_task(project_path, goal)."
    lines = ["# Tasks"]
    for t in tasks:
        indent = "    └ " if t.parent_id else "  "
        lines.append(f"{indent}[{t.id}] {t.status.value:12} {t.title or t.goal[:50]}")
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
    if task.commands:
        lines.append("**Recent commands:**")
        for c in task.commands[-5:]:
            code = c.get("exit") if isinstance(c, dict) else None
            cmd = c.get("command", "") if isinstance(c, dict) else str(c)
            lines.append(f"  - [{'ok' if code == 0 else code}] {cmd}")
    if task.test_results:
        lines.append("**Test/diagnostic runs:**")
        for t in task.test_results[-5:]:
            ok = t.get("passed") if isinstance(t, dict) else None
            lines.append(f"  - [{'PASS' if ok else 'FAIL'}] {t.get('command', '') if isinstance(t, dict) else t}")
    if task.checkpoints:
        lines.append(f"**Checkpoints:** {', '.join(task.checkpoints[-5:])}")
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


def finish_task(server, task_id: str, result: str = "", evidence: str = "") -> str:
    task = _get(server, task_id)
    if not can_transition(task.status, TaskState.COMPLETED):
        return (
            f"Task is {task.status.value}; move it to review_ready before completing "
            f"(advance_task). Or cancel_task if abandoning."
        )
    # Completion needs evidence when 'done' was defined — and the evidence must
    # be TRUE (checklist 0.1): a recorded FAILING run can never count as
    # completion evidence, no matter what text accompanies it. An honest
    # guardrail, not a boundary — the telemetry in task_status is what the
    # operator actually reviews.
    if task.acceptance_criteria:
        last = task.test_results[-1] if task.test_results else None
        last_passed = bool(last.get("passed")) if isinstance(last, dict) else bool(last)
        if last is not None and not last_passed:
            return (
                "Not completed: the most recent recorded test/diagnostic run "
                "FAILED. A failing run is not completion evidence — fix the "
                "failure and re-run until it passes, or cancel_task if abandoning."
            )
        if last is None and not evidence.strip():
            return (
                "Not completed: this task has acceptance criteria but no recorded "
                "test/diagnostic runs and no evidence was given. Run the relevant "
                "tests (run_command / diagnostics_check), or pass evidence=\"...\" "
                "explaining how each criterion was verified."
            )
    task.status = TaskState.COMPLETED
    task.result = result.strip() or "completed"
    server.tasks.save_task(task)
    server.tasks.add_event(task_id, "completed", result=task.result,
                           evidence=evidence.strip() or None)
    return f"Task {task_id} completed. {task.result}"


async def fork_task(server, task_id: str, goal: str = "", title: str = "") -> str:
    """Fork a task (checklist 8.1): a NEW task on the same project with its OWN
    worktree from the same base, copying the goal/criteria/plan — so two
    approaches to one problem can be tried side by side and compared."""
    src = _get(server, task_id)
    child = server.tasks.create_task(
        src.project_id, src.workspace_path,
        goal=(goal or src.goal).strip(), title=(title or f"fork of {src.id}").strip(),
        permission_mode=src.permission_mode,
        acceptance_criteria=list(src.acceptance_criteria),
        plan=list(src.plan),
        parent_id=src.id,
    )
    ws = Path(src.workspace_path)
    iso_note = "shared checkout (not a git repository)"
    from ..tools import worktree as worktree_tool

    wt, base_commit, note = await worktree_tool.create_for_task(server, ws, child.id)
    child.base_commit = base_commit
    if wt is not None:
        child.worktree_path = str(wt)
        server.tasks.add_event(child.id, "worktree_bound", path=str(wt), base=base_commit)
    iso_note = note
    server.tasks.save_task(child)
    server.tasks.add_event(task_id, "forked", child=child.id)
    server.tasks.add_event(child.id, "forked_from", parent=task_id)
    return (
        f"Forked {task_id} → {child.id}\n"
        f"  goal: {child.goal}\n"
        f"  working path: {child.worktree_path or child.workspace_path}\n"
        f"  isolation: {iso_note}\n"
        f"Pass task_id=\"{child.id}\" for the fork's work; the original task is untouched."
    )


def cancel_task(server, task_id: str, reason: str = "") -> str:
    task = _get(server, task_id)
    task.status = TaskState.CANCELLED
    task.result = f"cancelled: {reason}".strip(": ")
    server.tasks.save_task(task)
    server.tasks.add_event(task_id, "cancelled", reason=reason)
    return f"Task {task_id} cancelled."
