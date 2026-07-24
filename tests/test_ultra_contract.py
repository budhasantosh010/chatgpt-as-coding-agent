"""Phase 5: ULTRA candidate limits and conditional effort scopes."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, patch

from harness.config import Config
from harness.context import HarnessServer
from harness.tasks import tools as task_tools
from harness.tasks.contracts import RunContract
from harness.tasks.store import TaskStore


def _server(tmp_path, *, candidates=2, effort="low"):
    workspace = tmp_path / "project"
    workspace.mkdir()
    server = HarnessServer(Config(
        workspace_roots=[tmp_path], state_dir=tmp_path / "state", secret_route="r"
    ))
    project = server.tasks.register_project(str(workspace), "Project")
    task = server.tasks.create_task(project, str(workspace), goal="ultra")
    linked = server.tasks.confirm_run_contract(task.id, RunContract.confirmed(
        task_type="build", effort_level=effort,
        credit_ceiling=2 if effort != "off" else 0,
        candidate_count=candidates, machine_concurrency=2, model_concurrency=1,
        framework="none", max_loops=0,
    ))
    return server, linked


def _fork(server, task_id, *, candidate=False):
    workspace = Path(server.tasks.get_task(task_id).workspace_path)
    isolated = workspace.parent / f"candidate-{task_id}-{server.tasks.candidate_usage(task_id)}"
    result = (isolated, "base", "isolated test worktree") if candidate else (
        None, "", "test checkout"
    )
    fake = AsyncMock(return_value=result)
    with patch("harness.tools.worktree.create_for_task", new=fake):
        return asyncio.run(task_tools.fork_task(server, task_id, candidate=candidate))


def _child_id(output):
    return output.split("→", 1)[1].split()[0]


def _approval_id(output):
    return output.split("approvals approve ", 1)[1].split()[0]


def test_candidate_forks_get_fresh_scopes_and_stop_at_locked_limit(tmp_path):
    server, task = _server(tmp_path, candidates=2, effort="low")

    first = server.tasks.get_task(_child_id(_fork(server, task.id, candidate=True)))
    second = server.tasks.get_task(_child_id(_fork(server, task.id, candidate=True)))
    refused = _fork(server, task.id, candidate=True)

    assert first.contract_id == task.contract_id == second.contract_id
    assert first.credit_scope_id not in {"", task.credit_scope_id}
    assert second.credit_scope_id not in {"", task.credit_scope_id, first.credit_scope_id}
    assert "CANDIDATE_LIMIT" in refused


def test_candidate_fork_requires_ultra_and_plain_fork_gets_own_scope(tmp_path):
    server, task = _server(tmp_path, candidates=0, effort="low")

    assert "NOT_ULTRA" in _fork(server, task.id, candidate=True)
    plain = server.tasks.get_task(_child_id(_fork(server, task.id)))

    # A plain fork is an independent attempt: its own contract and its own scope,
    # so deleting it can never erase the original's credits.
    assert plain.contract_id and plain.contract_id != task.contract_id
    assert plain.credit_scope_id and plain.credit_scope_id != task.credit_scope_id


def test_candidate_fails_closed_without_isolated_worktree_and_releases_quota(tmp_path):
    server, task = _server(tmp_path, candidates=1, effort="low")
    fake = AsyncMock(return_value=(None, "", "git worktree unavailable"))
    with patch("harness.tools.worktree.create_for_task", new=fake):
        output = asyncio.run(task_tools.fork_task(server, task.id, candidate=True))

    assert "CANDIDATE_ISOLATION" in output
    assert server.tasks.candidate_usage(task.id) == 0


def test_candidate_never_inherits_satisfied_proof_from_parent(tmp_path):
    server, task = _server(tmp_path, candidates=1, effort="off")
    current = server.tasks.get_task(task.id)
    current.acceptance_criteria = ["tests pass"]
    current.criteria_v2 = [{
        "id": "AC-1", "text": "tests pass", "required": True,
        "status": "satisfied", "verification_kind": "machine",
        "evidence_refs": [{"kind": "execution", "exec_id": "px-parent"}],
        "verified_at": "2026-07-18T12:00:00Z",
    }]
    server.tasks.save_task(current)

    child = server.tasks.get_task(_child_id(_fork(server, task.id, candidate=True)))

    assert child.criteria_v2[0]["status"] == "open"
    assert child.criteria_v2[0]["evidence_refs"] == []
    assert child.criteria_v2[0]["verified_at"] == ""


def test_ultra_candidate_with_effort_off_has_no_credit_scope(tmp_path):
    server, task = _server(tmp_path, candidates=2, effort="off")

    candidate = server.tasks.get_task(_child_id(_fork(server, task.id, candidate=True)))

    assert candidate.contract_id == task.contract_id
    assert candidate.credit_scope_id == ""
    assert server.tasks.get_run_contract(candidate.id).ultra_enabled is True


def test_plain_fork_under_ultra_gets_its_own_scope(tmp_path):
    # Even under an ULTRA contract, a PLAIN (non-candidate) fork is independent:
    # it gets its own scope, not the shared root budget the candidates draw on.
    server, task = _server(tmp_path, candidates=2, effort="low")

    plain = server.tasks.get_task(_child_id(_fork(server, task.id)))

    assert plain.credit_scope_id not in {"", task.credit_scope_id}


def test_candidate_extension_is_approval_bound_and_raises_locked_limit(tmp_path):
    server, task = _server(tmp_path, candidates=1, effort="off")
    assert "Forked" in _fork(server, task.id, candidate=True)
    assert "CANDIDATE_LIMIT" in _fork(server, task.id, candidate=True)

    asked = task_tools.request_extension(server, task.id, "candidates", 1, "compare")
    assert "APPROVAL REQUIRED" in asked
    assert server.tasks.decide_approval(_approval_id(asked), "approved")
    extended = task_tools.request_extension(server, task.id, "candidates", 1, "compare")

    assert "extended" in extended.lower()
    assert server.tasks.get_run_contract(task.id).candidate_count == 2
    assert "Forked" in _fork(server, task.id, candidate=True)


def test_effort_status_reports_candidate_usage_separately(tmp_path):
    server, task = _server(tmp_path, candidates=2, effort="low")
    _fork(server, task.id, candidate=True)

    status = task_tools.get_effort_status(server, task.id)

    assert "Candidates: 1/2 used" in status


def test_two_store_instances_cannot_race_past_candidate_limit(tmp_path):
    server, task = _server(tmp_path, candidates=1, effort="off")
    other = TaskStore(server.tasks.path)
    fields = {"goal": "candidate", "parent_id": task.id,
              "contract_id": task.contract_id}

    def create(store):
        try:
            return store.create_candidate_task(store.get_task(task.id), **fields).id
        except ValueError as exc:
            return str(exc)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, (server.tasks, other)))
    finally:
        other.close()

    assert sum(result.startswith("T-") for result in results) == 1
    assert sum("CANDIDATE_LIMIT" in result for result in results) == 1
