"""Phase 1: cross-process-safe task storage and immutable Run Contracts."""

from __future__ import annotations

import json
import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from harness.config import Config
from harness.context import HarnessServer
from harness.tasks.contracts import RunContract
from harness.tasks.model import TaskState
from harness.tasks.store import TaskConflictError, TaskStore
from harness.tasks import tools as task_tools
from harness.tasks import store as store_module


def _stores(tmp_path):
    db = tmp_path / "tasks.db"
    return TaskStore(db), TaskStore(db)


def _task(store: TaskStore):
    project = store.register_project("/repo/project", "Project")
    return store.create_task(project, "/repo/project", goal="original")


def test_create_task_with_contract_rolls_back_every_row_on_failure(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "atomic.db")
    project = store.register_project("/repo/project", "Project")
    contract = RunContract.confirmed(
        task_type="build", effort_level="low", credit_ceiling=2,
        candidate_count=0, machine_concurrency=1, model_concurrency=1,
        framework="none", max_loops=0,
    )
    task_ids = iter(("T-first", "T-rolled-back"))
    scope_ids = iter(("cs-first", "cs-second"))

    def fixed_id(prefix):
        if prefix == "T":
            return next(task_ids)
        if prefix == "rc":
            return "rc-duplicate"
        if prefix == "cs":
            return next(scope_ids)
        return f"{prefix}-event"

    monkeypatch.setattr(store_module, "_sid", fixed_id)
    store.create_task_with_contract(project, "/repo/project", contract, goal="first")

    with pytest.raises(sqlite3.IntegrityError):
        store.create_task_with_contract(project, "/repo/project", contract, goal="second")

    assert store.get_task("T-rolled-back") is None
    assert len(store.list_tasks()) == 1


def test_stale_whole_task_save_conflicts_instead_of_erasing_newer_data(tmp_path):
    first, second = _stores(tmp_path)
    task = _task(first)
    a = first.get_task(task.id)
    b = second.get_task(task.id)

    a.goal = "newer goal"
    first.save_task(a)
    b.pinned = True

    with pytest.raises(TaskConflictError, match="TASK_CONFLICT"):
        second.save_task(b)

    current = first.get_task(task.id)
    assert current.goal == "newer goal"
    assert current.pinned is False


def test_targeted_task_updates_preserve_changes_from_another_store(tmp_path):
    first, second = _stores(tmp_path)
    task = _task(first)

    assert first.set_task_pinned(task.id, True)
    assert second.set_task_chat_url(task.id, "https://chatgpt.com/c/example")

    current = first.get_task(task.id)
    assert current.pinned is True
    assert current.chat_url == "https://chatgpt.com/c/example"
    assert current.revision == 2


def test_targeted_status_update_preserves_another_store_change(tmp_path):
    first, second = _stores(tmp_path)
    task = _task(first)

    assert first.set_task_chat_url(task.id, "https://chatgpt.com/c/status-race")
    updated = second.set_task_status(task.id, TaskState.PLANNING)

    assert updated.status == TaskState.PLANNING
    current = first.get_task(task.id)
    assert current.chat_url == "https://chatgpt.com/c/status-race"
    assert current.status == TaskState.PLANNING


def test_confirmed_contract_is_separate_immutable_and_linked_to_task(tmp_path):
    first, second = _stores(tmp_path)
    task = _task(first)
    stale = second.get_task(task.id)
    contract = RunContract.confirmed(
        task_type="build",
        effort_level="high",
        credit_ceiling=16,
        candidate_count=3,
        machine_concurrency=4,
        model_concurrency=1,
        framework="aocs_omega",
        max_loops=2,
    )

    linked = first.confirm_run_contract(task.id, contract)

    assert linked.contract_id.startswith("rc-")
    assert linked.credit_scope_id.startswith("cs-")
    assert first.get_run_contract(task.id).contract_hash == contract.contract_hash
    with pytest.raises(ValueError, match="already has a confirmed Run Contract"):
        first.confirm_run_contract(task.id, contract)

    stale.goal = "stale overwrite"
    with pytest.raises(TaskConflictError):
        second.save_task(stale)
    assert first.get_run_contract(task.id).contract_hash == contract.contract_hash


def test_effort_off_contract_creates_no_credit_scope(tmp_path):
    store, other = _stores(tmp_path)
    task = _task(store)
    contract = RunContract.confirmed(
        task_type="plan",
        effort_level="off",
        credit_ceiling=0,
        candidate_count=2,
        machine_concurrency=2,
        model_concurrency=1,
        framework="none",
        max_loops=0,
    )

    linked = store.confirm_run_contract(task.id, contract)

    assert linked.contract_id
    assert linked.credit_scope_id == ""
    count = store._db.execute("SELECT COUNT(*) AS n FROM credit_scopes").fetchone()["n"]
    assert count == 0


def test_contract_hash_tampering_is_detected(tmp_path):
    store, other = _stores(tmp_path)
    task = _task(store)
    contract = RunContract.confirmed(
        task_type="research",
        effort_level="low",
        credit_ceiling=2,
        candidate_count=0,
        machine_concurrency=1,
        model_concurrency=1,
        framework="none",
        max_loops=0,
    )
    linked = store.confirm_run_contract(task.id, contract)
    row = store._db.execute(
        "SELECT contract_json FROM run_contracts WHERE contract_id=?",
        (linked.contract_id,),
    ).fetchone()
    damaged = json.loads(row["contract_json"])
    damaged["credit_ceiling"] = 999
    store._db.execute(
        "UPDATE run_contracts SET contract_json=? WHERE contract_id=?",
        (json.dumps(damaged), linked.contract_id),
    )
    store._db.commit()

    with pytest.raises(ValueError, match="CONTRACT_TAMPERED"):
        store.get_run_contract(task.id)


def test_ordinary_subtask_points_to_same_contract_and_scope(tmp_path):
    store, other = _stores(tmp_path)
    parent = _task(store)
    linked = store.confirm_run_contract(
        parent.id,
        RunContract.confirmed(
            task_type="build",
            effort_level="medium",
            credit_ceiling=8,
            candidate_count=0,
            machine_concurrency=2,
            model_concurrency=1,
            framework="none",
            max_loops=0,
        ),
    )

    output = task_tools.create_subtask(
        SimpleNamespace(tasks=store), linked.id, "investigate the failure"
    )
    child_id = next(token for token in output.split() if token.startswith("T-") and token != linked.id)
    child = store.get_task(child_id)

    assert child.contract_id == linked.contract_id
    assert child.credit_scope_id == linked.credit_scope_id
    assert store.get_run_contract(child.id).contract_hash == store.get_run_contract(linked.id).contract_hash


def test_ordinary_fork_points_to_same_contract_and_scope(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    server = HarnessServer(Config(
        workspace_roots=[tmp_path], state_dir=tmp_path / "state", secret_route="r"
    ))
    project = server.tasks.register_project(str(workspace), "Project")
    parent = server.tasks.create_task(project, str(workspace), goal="original")
    linked = server.tasks.confirm_run_contract(
        parent.id,
        RunContract.confirmed(
            task_type="build",
            effort_level="medium",
            credit_ceiling=8,
            candidate_count=0,
            machine_concurrency=2,
            model_concurrency=1,
            framework="none",
            max_loops=0,
        ),
    )

    output = asyncio.run(task_tools.fork_task(server, linked.id, "second approach"))
    child_id = next(
        token for token in output.split()
        if token.startswith("T-") and token != linked.id
    )
    child = server.tasks.get_task(child_id)

    assert child.contract_id == linked.contract_id
    assert child.credit_scope_id == linked.credit_scope_id
    assert server.tasks.get_run_contract(child.id).contract_hash == (
        server.tasks.get_run_contract(linked.id).contract_hash
    )
