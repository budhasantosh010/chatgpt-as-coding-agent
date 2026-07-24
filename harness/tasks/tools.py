"""Task lifecycle tools: register_project, start_task, list/status/resume,
set goal/criteria, advance state, finish, cancel.

These operate on the shared TaskStore (via the server), not a single workspace
context — they create and steer the tasks that everything else is scoped to.
"""

from __future__ import annotations

import os
import math
import hashlib
import json
from pathlib import Path

from ..evidence import validate_evidence
from ..observations import tree_hash
from ..policy import VALID_MODES, check_ceiling
from ..security import SecurityError, is_within
from ..session import _now_iso
from .effort import receipt_fingerprint, write_receipt_view
from .contracts import RunContract
from .model import TaskState, can_transition


_TERMINAL_STATES = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
_CRITERION_KINDS = {"machine", "source", "operator", "mixed"}


def _terminal_error(task) -> str | None:
    if task.status in _TERMINAL_STATES:
        return "Error: [TASK_TERMINAL] terminal tasks are immutable"
    return None


def _criterion_spec(value) -> dict | None:
    if isinstance(value, dict):
        text = str(value.get("text", "")).strip()
        kind = str(value.get("verification_kind", "machine")).strip()
        required = value.get("required", True)
        if not text or kind not in _CRITERION_KINDS or not isinstance(required, bool):
            return None
        return {"text": text, "verification_kind": kind, "required": required}
    text = str(value).strip()
    return {"text": text, "verification_kind": "machine", "required": True} if text else None


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
                     title: str = "", isolation: str = "", operator: bool = False,
                     contract: RunContract | None = None) -> str:
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
    create = (server.tasks.create_task_with_contract if contract is not None
              else server.tasks.create_task)
    create_args = (pid, str(ws), contract) if contract is not None else (pid, str(ws))
    task = create(
        *create_args, goal=goal.strip(), title=(title or goal[:60]).strip(),
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
    contract_note = ""
    if contract is not None:
        contract_note = (
            f"  Run Contract: EFFORT {contract.effort_level}; ULTRA "
            f"{contract.candidate_count}; FRAMEWORK {contract.framework}; "
            f"LOOPS {contract.max_loops}; hash {contract.contract_hash[:12]}\n"
        )
    return (
        f"Started task {task.id}\n"
        f"  goal: {task.goal}\n"
        f"  working path: {active}\n"
        f"  isolation: {iso_note}\n"
        f"  permission mode: {permission_mode}\n"
        f"{contract_note}"
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
        contract_id=parent.contract_id,
        credit_scope_id=parent.credit_scope_id,
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
    if task.contract_id:
        contract = server.tasks.get_run_contract(task.id)
        satisfied = sum(c.get("status") == "satisfied" for c in task.criteria_v2)
        lines.append(
            f"**Run Contract:** EFFORT {contract.effort_level}; ULTRA "
            f"{contract.candidate_count}; FRAMEWORK {contract.framework}; "
            f"LOOPS {contract.max_loops}; gates {satisfied}/{len(task.criteria_v2)}."
        )
        if contract.framework == "aocs_omega":
            lines.append(
                "**Framework protocol:** Load `my-aocs-omega` IN FULL using paged "
                "`load_skill` offsets, then call `record_framework_routing` before implementation."
            )
    if task.acceptance_criteria:
        lines.append("**Acceptance criteria:**")
        lines += [f"  - {c}" for c in task.acceptance_criteria]
    if task.contract_id and task.criteria_v2:
        lines.append("**Verified acceptance gates:**")
        lines += [
            f"  - [{criterion.get('status', 'open')}] {criterion.get('id')}: "
            f"{criterion.get('text', '')} ({criterion.get('verification_kind', 'machine')})"
            for criterion in task.criteria_v2
        ]
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
    if (error := _terminal_error(task)):
        return error
    task.goal = goal.strip()
    server.tasks.save_task(task)
    server.tasks.add_event(task_id, "goal_set", goal=task.goal)
    return f"Updated goal for {task_id}."


def set_acceptance_criteria(server, task_id: str, criteria: list) -> str:
    task = _get(server, task_id)
    if (error := _terminal_error(task)):
        return error
    if not isinstance(criteria, list):
        return "Error: [CRITERIA_INVALID] criteria must be a list"
    cleaned = [_criterion_spec(item) for item in criteria]
    if any(item is None for item in cleaned):
        return "Error: [CRITERIA_INVALID] each criterion needs text and a valid verification_kind"
    cleaned = [item for item in cleaned if item is not None]
    if not task.contract_id:
        task.acceptance_criteria = [item["text"] for item in cleaned]
        task.criteria_v2 = [
            {
                "id": f"AC-{index}", **item, "status": "open",
                "evidence_refs": [], "verified_at": "",
            }
            for index, item in enumerate(cleaned, 1)
        ]
        server.tasks.save_task(task)
    else:
        def change(current):
            existing = list(current.criteria_v2)
            if len(cleaned) < len(existing):
                raise ValueError("[CRITERIA_LOCKED] confirmed acceptance gates cannot be removed")
            for index, criterion in enumerate(existing):
                requested = cleaned[index]
                if any((
                    criterion.get("text") != requested["text"],
                    criterion.get("verification_kind", "machine") != requested["verification_kind"],
                    bool(criterion.get("required", True)) != requested["required"],
                )):
                    raise ValueError("[CRITERIA_LOCKED] confirmed acceptance gates cannot be rewritten")
            ids = [
                int(str(item.get("id", "")).split("-")[-1])
                for item in existing if str(item.get("id", "")).split("-")[-1].isdigit()
            ]
            next_id = max(ids, default=0) + 1
            updated = [dict(item) for item in existing]
            for requested in cleaned[len(existing):]:
                updated.append({
                    "id": f"AC-{next_id}", **requested, "status": "open",
                    "evidence_refs": [], "verified_at": "",
                })
                next_id += 1
            current.acceptance_criteria = [item["text"] for item in cleaned]
            current.criteria_v2 = updated

        try:
            server.tasks.mutate_task(task_id, change)
        except ValueError as exc:
            return f"Error: {exc}"
    server.tasks.add_event(task_id, "criteria_set", count=len(cleaned))
    return f"Set {len(cleaned)} acceptance criteria for {task_id}."


def _criterion_accepts(required_kind: str, kinds: frozenset[str]) -> bool:
    if required_kind == "machine":
        return "machine" in kinds
    if required_kind == "source":
        return "source" in kinds
    if required_kind == "mixed":
        return bool(kinds.intersection({"machine", "source"}))
    return False


def satisfy_criterion(server, task_id: str, criterion_id: str, evidence: list) -> str:
    task = _get(server, task_id)
    if (error := _terminal_error(task)):
        return error
    if not task.contract_id:
        return "Error: [NOT_CONTRACTED] this task uses legacy completion evidence"
    criterion = next(
        (item for item in task.criteria_v2 if item.get("id") == criterion_id), None
    )
    if criterion is None:
        return f"Error: [UNKNOWN_CRITERION] {criterion_id}"
    required_kind = criterion.get("verification_kind", "machine")
    if required_kind == "operator":
        return "Error: [OPERATOR_REQUIRED] this criterion must be confirmed in the Workbench"

    try:
        contract = server.tasks.get_run_contract(task_id)
        checked = validate_evidence(
            server.tasks, task, evidence,
            opened_at=contract.confirmed_at if contract else "",
        )
    except ValueError as exc:
        return f"Error: {exc}"
    if not _criterion_accepts(required_kind, checked.kinds):
        return (
            f"Error: [EVIDENCE_KIND] {criterion_id} requires {required_kind} evidence"
        )

    def change(current):
        target = next(
            (item for item in current.criteria_v2 if item.get("id") == criterion_id), None
        )
        if target is None:
            raise ValueError(f"[UNKNOWN_CRITERION] {criterion_id}")
        if target.get("verification_kind") == "operator":
            raise ValueError("[OPERATOR_REQUIRED] criterion changed during validation")
        target["status"] = "satisfied"
        target["evidence_refs"] = checked.refs
        target["verified_at"] = _now_iso()

    server.tasks.mutate_task(task_id, change)
    server.tasks.add_event(
        task_id, "criterion_satisfied", criterion_id=criterion_id,
        evidence_kinds=sorted(checked.kinds),
    )
    return f"Criterion {criterion_id} satisfied with {checked.tier} evidence."


def operator_satisfy_criterion(server, task_id: str, criterion_id: str) -> str:
    task = _get(server, task_id)
    if (error := _terminal_error(task)):
        raise ValueError(error.removeprefix("Error: "))
    criterion = next(
        (item for item in task.criteria_v2 if item.get("id") == criterion_id), None
    )
    if criterion is None:
        raise ValueError(f"[UNKNOWN_CRITERION] {criterion_id}")
    if criterion.get("verification_kind") != "operator":
        raise ValueError("[NOT_OPERATOR_CRITERION] only operator-kind criteria use this endpoint")

    def change(current):
        target = next(
            item for item in current.criteria_v2 if item.get("id") == criterion_id
        )
        target["status"] = "satisfied"
        target["evidence_refs"] = [{"kind": "operator", "confirmed_by": "operator"}]
        target["verified_at"] = _now_iso()

    server.tasks.mutate_task(task_id, change)
    server.tasks.add_event(task_id, "criterion_operator_satisfied", criterion_id=criterion_id)
    return f"Criterion {criterion_id} confirmed by operator."


def record_framework_routing(
    server, task_id: str, activated: list, skipped: list, reason: str
) -> str:
    task = _get(server, task_id)
    if (error := _terminal_error(task)):
        return error
    contract = server.tasks.get_run_contract(task_id)
    if contract is None or contract.framework == "none":
        return "Error: [FRAMEWORK_OFF] this contract declares no framework"
    if not isinstance(activated, list) or not isinstance(skipped, list):
        return "Error: [ROUTING_INVALID] activated and skipped must be lists"
    used = [str(item).strip() for item in activated if str(item).strip()]
    omitted = [str(item).strip() for item in skipped if str(item).strip()]
    if not used and not omitted:
        return "Error: [ROUTING_INVALID] record at least one activated or skipped part"
    if set(used).intersection(omitted):
        return "Error: [ROUTING_INVALID] a framework part cannot be both activated and skipped"
    if not str(reason).strip():
        return "Error: [ROUTING_INVALID] reason is required"
    server.tasks.add_event(
        task_id, "framework_routing", activated=used, skipped=omitted,
        reason=str(reason).strip(), framework=contract.framework,
    )
    return f"Framework routing recorded ({len(used)} activated, {len(omitted)} skipped)."


def begin_cycle(
    server, task_id: str, question: str, purpose: str = "", verification_plan: str = ""
) -> str:
    try:
        cycle = server.tasks.begin_cycle(task_id, question, purpose, verification_plan)
    except ValueError as exc:
        return f"Error: {exc}"
    return (
        f"Cycle {cycle['cycle_id']} opened. Scope {cycle['scope_id']} "
        f"({cycle['effort_level']}): spent {cycle['spent']}/{cycle['ceiling']}."
    )


def abandon_cycle(server, task_id: str, cycle_id: str, reason: str) -> str:
    if not server.tasks.abandon_cycle(task_id, cycle_id, reason):
        return "Error: [NO_OPEN_CYCLE] cycle is missing or no longer open"
    server.tasks.add_event(
        task_id, "effort_cycle_abandoned", cycle_id=cycle_id, reason=reason
    )
    return f"Cycle {cycle_id} abandoned without spending a credit."


def _framework_status(server, task_id: str, contract) -> str:
    if contract is None or contract.framework == "none":
        return "FRAMEWORK: Off."
    recorded = any(
        event["type"] == "framework_routing" for event in server.tasks.events(task_id, 100)
    )
    return "FRAMEWORK: recorded." if recorded else "FRAMEWORK: declared but unrecorded."


def _loop_status(server, task_id: str, contract) -> str:
    if contract is None or contract.max_loops == 0:
        return "Loops: Off."
    rows = server.tasks.loop_passes(task_id)
    state = rows[-1]["status"] if rows else "none"
    return f"Loops: {len(rows)}/{contract.max_loops} used; latest {state}."


def get_effort_status(server, task_id: str) -> str:
    task = _get(server, task_id)
    try:
        contract = server.tasks.get_run_contract(task_id)
    except ValueError as exc:
        return f"Error: {exc}"
    framework = _framework_status(server, task_id, contract)
    loops = _loop_status(server, task_id, contract)
    if contract is None or contract.effort_level == "off" or not task.credit_scope_id:
        return f"EFFORT Off. No credit scope exists. {framework} {loops}"
    status = server.tasks.effort_status(task.credit_scope_id)
    for receipt in server.tasks.spent_receipts(task.credit_scope_id):
        try:
            write_receipt_view(
                server.config.state_dir, receipt["task_id"], receipt
            )
        except OSError:
            pass
    tiers = status["tiers"]
    decision_limit = math.ceil(
        server.config.decision_caps[contract.task_type] * status["ceiling"]
    )
    current_open = next(
        (row["credit_id"] for row in status["open_cycles"] if row["task_id"] == task_id),
        "none",
    )
    satisfied = sum(
        1 for criterion in task.criteria_v2 if criterion.get("status") == "satisfied"
    )
    candidates_used = server.tasks.candidate_usage(task_id)
    return (
        f"Scope {status['scope_id']} {contract.effort_level} "
        f"{status['spent']}/{status['ceiling']} "
        f"(machine {tiers.get('machine', 0)}, source {tiers.get('source', 0)}, "
        f"decision {tiers.get('decision', 0)}/{decision_limit} cap). "
        f"Open cycle: {current_open}. Criteria: {satisfied}/{len(task.criteria_v2)} "
        f"satisfied. Contract hash OK. Candidates: "
        f"{candidates_used}/{contract.candidate_count} used. {framework} {loops}"
    )


def request_extension(
    server, task_id: str, kind: str, amount: int, reason: str, scope_id: str = ""
) -> str:
    if kind not in {"credits", "loops", "candidates"}:
        return "Error: [EXTENSION_KIND] kind must be credits, loops, or candidates"
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        return "Error: [EXTENSION_AMOUNT] amount must be a positive integer"
    if not str(reason).strip():
        return "Error: [EXTENSION_REASON] reason is required"
    task = _get(server, task_id)
    if (error := _terminal_error(task)):
        return error
    try:
        contract = server.tasks.get_run_contract(task_id)
    except ValueError as exc:
        return f"Error: {exc}"
    if contract is None:
        return "Error: [NO_CONTRACT] task has no confirmed Run Contract"
    if kind == "credits" and (contract.effort_level == "off" or not task.credit_scope_id):
        return "Error: [EFFORT_OFF] an extension cannot enable EFFORT"
    if kind == "candidates" and not contract.ultra_enabled:
        return "Error: [CONTROL_OFF] an extension cannot enable ULTRA"
    if kind == "loops" and contract.max_loops == 0:
        return "Error: [CONTROL_OFF] an extension cannot enable LOOPS"
    detail = {
        "task_id": task_id, "kind": kind, "amount": amount,
        "reason": str(reason).strip(),
        "scope_id": (scope_id or task.credit_scope_id) if kind == "credits" else "",
    }
    encoded = json.dumps(detail, sort_keys=True, separators=(",", ":"))
    request_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    action = f"effort_extension:{kind}:+{amount}"
    approval = server.tasks.matching_approval(task_id, action, request_hash)
    if approval and approval["status"] == "denied":
        return "Error: [APPROVAL_DENIED] the operator denied this extension"
    if not approval or approval["status"] == "pending":
        aid = approval["id"] if approval else server.tasks.add_approval(
            task_id, action, encoded, request_hash
        )
        return (
            "⏸ APPROVAL REQUIRED — extension is pending.\n"
            f"    python -m harness approvals approve {aid}\n"
            f"Then retry the same call. (Deny with: python -m harness approvals deny {aid})"
        )
    if approval["status"] != "approved":
        return "Error: [APPROVAL_USED] this extension approval is no longer usable"
    try:
        applied = server.tasks.apply_approved_extension(
            task_id, approval["id"], action, request_hash, kind, amount, detail["scope_id"]
        )
    except ValueError as exc:
        return f"Error: {exc}"
    summary = (
        f"scope {detail['scope_id']} ceiling {applied['value']}"
        if kind == "credits" else f"{kind} limit {applied['value']}"
    )
    return f"Contract extended: {summary}."


def complete_cycle(
    server, task_id: str, cycle_id: str, conclusion: str, decision: str, evidence: list
) -> str:
    task = _get(server, task_id)
    if (error := _terminal_error(task)):
        return error
    cycle = server.tasks.get_cycle(task_id, cycle_id)
    if cycle is None or cycle["status"] != "open":
        return "Error: [NO_OPEN_CYCLE] cycle is missing or no longer open"
    try:
        contract = server.tasks.get_run_contract(task_id)
        checked = validate_evidence(
            server.tasks, task, evidence, opened_at=cycle["opened"],
            verification_plan=cycle["verification_plan"].splitlines(),
            cycle_id=cycle_id, question=cycle["question"],
            allow_custom_verification=True,
        )
    except ValueError as exc:
        return f"Error: {exc}"
    receipt = {
        "cycle_id": cycle_id, "task_id": task_id, "scope_id": cycle["scope_id"],
        "question": cycle["question"], "conclusion": str(conclusion).strip(),
        "decision": str(decision).strip(), "tier": checked.tier,
        "evidence_refs": checked.refs, "ignored_refs": checked.ignored,
        "validated_at": _now_iso(), "semantic_relevance": "operator audit required",
    }
    return _spend_validated_cycle(server, task, contract, cycle, receipt, checked)


def _spend_validated_cycle(server, task, contract, cycle, receipt, checked) -> str:
    fingerprint = receipt_fingerprint(
        cycle["question"], receipt["conclusion"], checked.refs
    )
    scope = server.tasks.effort_status(cycle["scope_id"])
    decision_limit = math.ceil(
        server.config.decision_caps[contract.task_type] * scope["ceiling"]
    )
    try:
        status = server.tasks.spend_cycle(
            task.id, cycle["credit_id"], tier=checked.tier,
            fingerprint=fingerprint, receipt=receipt, decision_limit=decision_limit,
        )
    except ValueError as exc:
        return f"Error: {exc}"
    for ref in checked.refs:
        if ref.get("verification_approval_id"):
            server.tasks.consume_approval(ref["verification_approval_id"])
    try:
        write_receipt_view(server.config.state_dir, task.id, receipt)
    except OSError as exc:
        server.tasks.add_event(
            task.id, "receipt_view_failed", cycle_id=cycle["credit_id"],
            error=str(exc)[:200],
        )
    server.tasks.add_event(
        task.id, "effort_credit_spent", cycle_id=cycle["credit_id"], tier=checked.tier
    )
    return (
        f"Credit spent ({checked.tier} tier). Scope {cycle['scope_id']}: "
        f"{status['spent']}/{status['ceiling']}. Receipt: {status['receipt_path']}"
    )


async def begin_refinement_pass(
    server, task_id: str, target_weakness: str, directive: str,
    verification_plan: str, verification_kind: str = "",
) -> str:
    task = _get(server, task_id)
    if (error := _terminal_error(task)):
        return error
    contract = server.tasks.get_run_contract(task_id)
    if contract is None or contract.max_loops == 0:
        return "Error: [LOOPS_OFF] this contract has no refinement passes"
    kind = verification_kind or ("machine" if contract.task_type == "build" else "source")
    if kind not in {"machine", "source", "operator", "mixed"}:
        return "Error: [LOOP_KIND] verification_kind is invalid"
    weakness, instruction = str(target_weakness).strip(), str(directive).strip()
    if not weakness or not instruction:
        return "Error: [LOOP_INPUT] target_weakness and directive are required"
    state = await tree_hash(server.context_for(task_id, "refinement-loop"))
    normalized = " ".join(weakness.lower().split()) + "\n" + " ".join(instruction.lower().split())
    repeat_key = hashlib.sha256(f"{state}\n{normalized}".encode("utf-8")).hexdigest()
    try:
        opened = server.tasks.begin_loop_pass(
            task.id, verification_kind=kind, input_state_hash=state,
            target_weakness=weakness, directive=instruction, repeat_key=repeat_key,
            verification_plan=str(verification_plan).strip(),
        )
    except ValueError as exc:
        return f"Error: {exc}"
    return (
        f"Refinement pass {opened['pass_id']} opened "
        f"({opened['pass_number']}/{opened['max_loops']}, {kind})."
    )


async def complete_refinement_pass(
    server, task_id: str, pass_id: str, outcome: str, evidence: list,
    delta_summary: str = "",
) -> str:
    task = _get(server, task_id)
    if (error := _terminal_error(task)):
        return error
    loop = server.tasks.get_loop_pass(task_id, pass_id)
    if loop is None or loop["status"] != "open":
        return "Error: [NO_OPEN_LOOP] pass is missing or no longer open"
    if outcome not in {"improved", "no_gain", "worse"}:
        return "Error: [LOOP_OUTCOME] outcome must be improved, no_gain, or worse"
    kind = loop["verification_kind"]
    output_state = await tree_hash(server.context_for(task_id, "refinement-loop"))
    if kind == "operator":
        server.tasks.complete_loop_pass(
            task_id, pass_id, status="pending_operator",
            output_state_hash=output_state, delta_summary=str(delta_summary).strip(),
            proposed_outcome=outcome,
        )
        server.tasks.add_event(
            task_id, "loop_pending_operator", pass_id=pass_id, outcome=outcome
        )
        return f"Refinement pass {pass_id} awaits operator confirmation."
    try:
        checked = validate_evidence(
            server.tasks, task, evidence, opened_at=loop["opened"],
            verification_plan=loop["verification_plan"].splitlines(),
            cycle_id=pass_id, question=loop["target_weakness"],
            allow_custom_verification=True,
        )
    except ValueError as exc:
        return f"Error: {exc}"
    if kind == "machine" and checked.tier != "machine":
        return "Error: [LOOP_KIND_MISMATCH] machine evidence is required"
    if kind == "source" and checked.tier != "source":
        return "Error: [LOOP_KIND_MISMATCH] source evidence is required"
    if kind == "source" and not str(delta_summary).strip():
        return "Error: [DELTA_REQUIRED] source passes require a changed conclusion"
    if kind == "mixed" and checked.tier not in {"machine", "source"}:
        return "Error: [LOOP_KIND_MISMATCH] machine or source evidence is required"
    server.tasks.complete_loop_pass(
        task_id, pass_id, status=outcome, output_state_hash=output_state,
        delta_summary=str(delta_summary).strip(),
    )
    server.tasks.add_event(task_id, "loop_completed", pass_id=pass_id, outcome=outcome)
    note = " Revert to the previous best state." if outcome == "worse" else ""
    return f"Refinement pass {pass_id} completed: {outcome}.{note}"


def operator_confirm_refinement_pass(server, task_id: str, pass_id: str) -> str:
    task = _get(server, task_id)
    if (error := _terminal_error(task)):
        return error
    pending = server.tasks.get_loop_pass(task_id, pass_id)
    if pending is None or pending.get("status") != "pending_operator":
        return "Error: [NO_PENDING_LOOP] no operator loop awaits confirmation"
    outcome = pending.get("proposed_outcome", "")
    if outcome not in {"improved", "no_gain", "worse"}:
        return "Error: [LOOP_OUTCOME_MISSING] pending outcome is not recoverable"
    try:
        server.tasks.confirm_operator_loop(task_id, pass_id, outcome)
    except ValueError as exc:
        return f"Error: {exc}"
    server.tasks.add_event(
        task_id, "loop_operator_confirmed", pass_id=pass_id,
        outcome=outcome,
    )
    return f"Refinement pass {pass_id} confirmed by operator: {outcome}."


def advance_task(server, task_id: str, to_state: str) -> str:
    task = _get(server, task_id)
    try:
        target = TaskState(to_state)
    except ValueError:
        return f"Unknown state {to_state!r}. Valid: {', '.join(s.value for s in TaskState)}"
    if not can_transition(task.status, target):
        return f"Illegal transition {task.status.value} → {target.value}."
    prev = task.status
    server.tasks.set_task_status(task_id, target)
    server.tasks.add_event(task_id, "state_change", **{"from": prev.value, "to": target.value})
    return f"Task {task_id}: {prev.value} → {target.value}."


def finish_task(server, task_id: str, result: str = "", evidence: str = "") -> str:
    task = _get(server, task_id)
    if not can_transition(task.status, TaskState.COMPLETED):
        return (
            f"Task is {task.status.value}; move it to review_ready before completing "
            f"(advance_task). Or cancel_task if abandoning."
        )
    if task.contract_id:
        try:
            contract = server.tasks.get_run_contract(task_id)
        except ValueError as exc:
            return f"Error: {exc}"
        open_loops = [
            row for row in server.tasks.loop_passes(task_id)
            if row["status"] in {"open", "pending_operator"}
        ] if contract else []
        if open_loops:
            return "Not completed: close or confirm the open refinement pass first."
        open_required = [
            criterion for criterion in task.criteria_v2
            if criterion.get("required", True)
            and criterion.get("status") not in ("satisfied", "waived")
        ]
        if open_required:
            pending = ", ".join(
                f"{criterion.get('id')} ({criterion.get('status', 'open')})"
                for criterion in open_required
            )
            return (
                "Not completed: contracted tasks require valid proof for every "
                f"required criterion. Still open: {pending}."
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
        if last is None and not evidence.strip() and not task.contract_id:
            return (
                "Not completed: this task has acceptance criteria but no recorded "
                "test/diagnostic runs and no evidence was given. Run the relevant "
                "tests (run_command / diagnostics_check), or pass evidence=\"...\" "
                "explaining how each criterion was verified."
            )
    completion_result = result.strip() or "completed"

    def complete(current):
        current.status = TaskState.COMPLETED
        current.result = completion_result

    server.tasks.mutate_task(task_id, complete)
    server.tasks.add_event(task_id, "completed", result=completion_result,
                           evidence=evidence.strip() or None)
    return f"Task {task_id} completed. {completion_result}"


async def fork_task(
    server, task_id: str, goal: str = "", title: str = "", candidate: bool = False
) -> str:
    """Fork a task (checklist 8.1): a NEW task on the same project with its OWN
    worktree from the same base, copying the goal/criteria/plan — so two
    approaches to one problem can be tried side by side and compared."""
    src = _get(server, task_id)
    fields = dict(
        goal=(goal or src.goal).strip(), title=(title or f"fork of {src.id}").strip(),
        permission_mode=src.permission_mode,
        acceptance_criteria=list(src.acceptance_criteria),
        criteria_v2=[{
            **dict(criterion), "status": "open", "evidence_refs": [], "verified_at": "",
        } for criterion in src.criteria_v2],
        plan=list(src.plan),
        parent_id=src.id,
    )
    # A fork is an INDEPENDENT second attempt, so it gets its OWN run contract and
    # OWN credit scope — never a pointer into the parent's. Sharing the scope row
    # (which this once did) meant deleting a fork ran DELETE ... WHERE scope_id and
    # took the ORIGINAL task's spent credits and receipts down with it.
    # Candidates and subtasks are deliberately different: they decompose ONE budget
    # and share the parent's scope on purpose, which the store's delete guard keeps
    # safe. See test_ordinary_fork_gets_its_own_contract_and_scope.
    parent_contract = server.tasks.get_run_contract(src.id)
    try:
        if candidate:
            child = server.tasks.create_candidate_task(
                src, contract_id=src.contract_id, **fields
            )
        elif parent_contract is not None:
            child = server.tasks.create_task_with_contract(
                src.project_id, src.workspace_path,
                RunContract.confirmed(
                    task_type=parent_contract.task_type,
                    effort_level=parent_contract.effort_level,
                    credit_ceiling=parent_contract.credit_ceiling,
                    candidate_count=parent_contract.candidate_count,
                    machine_concurrency=parent_contract.machine_concurrency,
                    model_concurrency=parent_contract.model_concurrency,
                    framework=parent_contract.framework,
                    max_loops=parent_contract.max_loops,
                ),
                **fields,
            )
        else:
            child = server.tasks.create_task(
                src.project_id, src.workspace_path, **fields
            )
    except ValueError as exc:
        return f"Error: {exc}"
    ws = Path(src.workspace_path)
    iso_note = "shared checkout (not a git repository)"
    from ..tools import worktree as worktree_tool

    wt, base_commit, note = await worktree_tool.create_for_task(server, ws, child.id)
    if candidate and wt is None:
        server.tasks.rollback_candidate_task(src.id, child.id)
        return f"Error: [CANDIDATE_ISOLATION] candidate requires its own git worktree: {note}"
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
    if (error := _terminal_error(task)):
        return error
    task.status = TaskState.CANCELLED
    task.result = f"cancelled: {reason}".strip(": ")
    server.tasks.save_task(task)
    server.tasks.add_event(task_id, "cancelled", reason=reason)
    return f"Task {task_id} cancelled."
