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
    title: str = ""
    goal: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    permission_mode: str = "auto_workspace"
    status: TaskState = TaskState.NEW
    base_commit: str | None = None
    worktree_path: str | None = None
    plan: list = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    commands: list = Field(default_factory=list)
    test_results: list = Field(default_factory=list)
    checkpoints: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    result: str | None = None
    created: str = ""
    updated: str = ""
