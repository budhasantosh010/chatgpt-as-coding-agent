"""Task record + lifecycle state machine.

A Task is a persisted engineering unit (not just a todo): it has a goal,
acceptance criteria, a bound workspace/worktree, a permission mode, and a
lifecycle it moves through under an explicit legal-transition guard.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class TaskState(str, Enum):
    NEW = "new"
    DISCOVERING = "discovering"
    PLANNING = "planning"
    IMPLEMENTING = "implementing"
    VALIDATING = "validating"
    REPAIRING = "repairing"
    REVIEW_READY = "review_ready"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Legal forward transitions. Any state may also go to BLOCKED/CANCELLED/FAILED.
_LEGAL: dict[TaskState, set[TaskState]] = {
    TaskState.NEW: {TaskState.DISCOVERING, TaskState.PLANNING},
    TaskState.DISCOVERING: {TaskState.PLANNING},
    TaskState.PLANNING: {TaskState.IMPLEMENTING},
    TaskState.IMPLEMENTING: {TaskState.VALIDATING},
    TaskState.VALIDATING: {TaskState.REPAIRING, TaskState.REVIEW_READY},
    TaskState.REPAIRING: {TaskState.VALIDATING, TaskState.IMPLEMENTING},
    TaskState.REVIEW_READY: {TaskState.COMPLETED, TaskState.IMPLEMENTING},
    TaskState.BLOCKED: {TaskState.PLANNING, TaskState.IMPLEMENTING, TaskState.DISCOVERING},
}
_TERMINAL = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
_ALWAYS = {TaskState.BLOCKED, TaskState.CANCELLED, TaskState.FAILED}


def can_transition(src: TaskState, dst: TaskState) -> bool:
    if src == dst:
        return True
    if src in _TERMINAL:
        return False
    if dst in _ALWAYS:
        return True
    return dst in _LEGAL.get(src, set())


class Task(BaseModel):
    id: str
    project_id: str
    workspace_path: str
    parent_id: str | None = None
    title: str = ""
    goal: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    criteria_v2: list = Field(default_factory=list)
    permission_mode: str = "auto_workspace"
    # True only when the operator raised this task's mode via the local CLI
    # (`harness tasks set-mode`). Lets the task run above config.max_mode.
    operator_elevated: bool = False
    status: TaskState = TaskState.NEW
    base_commit: str | None = None
    worktree_path: str | None = None
    plan: list = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    commands: list = Field(default_factory=list)
    test_results: list = Field(default_factory=list)
    checkpoints: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    # Files the operator pinned to this task in the cockpit (drag-drop). Surfaced
    # in task_status so ChatGPT reads them itself; also the "attach a file" UX.
    pinned_files: list[str] = Field(default_factory=list)
    # Optional link back to the ChatGPT conversation driving this task (operator
    # pastes it in the cockpit). The harness never controls ChatGPT's sidebar.
    chat_url: str = ""
    # Durable navigation preference owned by the task domain, not browser state.
    pinned: bool = False
    # Archived sessions stay fully intact (audit trail, contract, receipts) and
    # simply drop out of the default sidebar. Reversible; deletion is not.
    archived: bool = False
    # Operator-owned "come back to this" marker. Deliberately manual: the harness
    # will not decide on its own what the operator has and has not read.
    unread: bool = False
    # Explicit family-wide link to the immutable Run Contract. Empty keeps the
    # pre-four-controls behavior.
    contract_id: str = ""
    # Shared budget pot. Empty when EFFORT is Off or no contract exists.
    credit_scope_id: str = ""
    # Authoritative optimistic-concurrency version is stored in the promoted DB
    # column and copied here whenever a task is loaded.
    revision: int = 0
    result: str | None = None
    created: str = ""
    updated: str = ""
