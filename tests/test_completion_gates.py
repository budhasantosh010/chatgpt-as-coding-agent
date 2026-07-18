"""Phase 2: contracted work completes only through per-criterion proof gates."""

from __future__ import annotations

import asyncio

from harness.config import Config
from harness.context import HarnessServer
from harness.evidence import classify_verification_command
from harness.server import build_mcp
from harness.tasks import tools as task_tools
from harness.tasks.contracts import RunContract
from harness.tasks.model import TaskState


def _server(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    server = HarnessServer(Config(
        workspace_roots=[tmp_path], state_dir=tmp_path / "state", secret_route="r"
    ))
    project = server.tasks.register_project(str(workspace), "Project")
    return server, workspace, project


def _contracted(tmp_path, criteria=("first requirement",), task_type="build"):
    server, workspace, project = _server(tmp_path)
    task = server.tasks.create_task(
        project, str(workspace), goal="contracted", acceptance_criteria=list(criteria)
    )
    linked = server.tasks.confirm_run_contract(
        task.id,
        RunContract.confirmed(
            task_type=task_type,
            effort_level="off",
            credit_ceiling=0,
            candidate_count=0,
            machine_concurrency=2,
            model_concurrency=1,
            framework="none",
            max_loops=0,
        ),
    )
    return server, linked


def _review_ready(server, task_id):
    for state in ("discovering", "planning", "implementing", "validating", "review_ready"):
        task_tools.advance_task(server, task_id, state)


def _make_source_criterion(server, task_id, *, criterion_id="AC-1", path="README.md"):
    task = server.tasks.get_task(task_id)
    criterion = next(c for c in task.criteria_v2 if c["id"] == criterion_id)
    criterion["verification_kind"] = "source"
    server.tasks.save_task(task)
    server.tasks.add_event(task_id, "obs_read", path=path, content_sha256="sha-read")
    return [{"kind": "source", "file": path, "lines": "1-5", "fact": "the requirement is present"}]


def test_confirm_converts_legacy_criteria_without_changing_legacy_list(tmp_path):
    server, task = _contracted(tmp_path, ("alpha", "beta"))

    assert task.acceptance_criteria == ["alpha", "beta"]
    assert task.criteria_v2 == [
        {
            "id": "AC-1", "text": "alpha", "required": True, "status": "open",
            "verification_kind": "machine", "evidence_refs": [], "verified_at": "",
        },
        {
            "id": "AC-2", "text": "beta", "required": True, "status": "open",
            "verification_kind": "machine", "evidence_refs": [], "verified_at": "",
        },
    ]


def test_uncontracted_task_still_accepts_explicit_prose_evidence(tmp_path):
    server, workspace, project = _server(tmp_path)
    task = server.tasks.create_task(
        project, str(workspace), goal="legacy", acceptance_criteria=["manual check"]
    )
    _review_ready(server, task.id)

    output = task_tools.finish_task(server, task.id, "done", "manually checked")

    assert "completed" in output.lower()
    assert server.tasks.get_task(task.id).status == TaskState.COMPLETED


def test_contracted_task_rejects_prose_and_lists_open_required_criteria(tmp_path):
    server, task = _contracted(tmp_path)
    _review_ready(server, task.id)

    output = task_tools.finish_task(server, task.id, "done", "trust me, checked")

    assert "Not completed" in output
    assert "AC-1" in output
    assert server.tasks.get_task(task.id).status == TaskState.REVIEW_READY


def test_source_evidence_satisfies_one_criterion_and_allows_completion(tmp_path):
    server, task = _contracted(tmp_path, task_type="research")
    evidence = _make_source_criterion(server, task.id)

    output = task_tools.satisfy_criterion(server, task.id, "AC-1", evidence)

    assert "satisfied" in output.lower()
    saved = server.tasks.get_task(task.id)
    assert saved.criteria_v2[0]["status"] == "satisfied"
    assert saved.criteria_v2[0]["evidence_refs"][0]["content_sha256"] == "sha-read"
    _review_ready(server, task.id)
    assert "completed" in task_tools.finish_task(server, task.id, "done").lower()


def test_source_reference_is_rejected_when_file_was_not_read(tmp_path):
    server, task = _contracted(tmp_path, task_type="research")
    current = server.tasks.get_task(task.id)
    current.criteria_v2[0]["verification_kind"] = "source"
    server.tasks.save_task(current)

    output = task_tools.satisfy_criterion(
        server,
        task.id,
        "AC-1",
        [{"kind": "source", "file": "unread.md", "lines": "1", "fact": "x"}],
    )

    assert "EVIDENCE_INVALID" in output
    assert server.tasks.get_task(task.id).criteria_v2[0]["status"] == "open"


def test_dedicated_verification_classifier_excludes_trivial_safe_commands():
    assert classify_verification_command("pytest -q") is True
    assert classify_verification_command("npm test") is True
    assert classify_verification_command("echo hello") is False
    assert classify_verification_command("Get-ChildItem") is False
    assert classify_verification_command("git status") is False
    assert classify_verification_command("npm run deploy") is False
    assert classify_verification_command("make clean") is False
    assert classify_verification_command("black .") is False


def test_public_criteria_api_accepts_source_operator_and_mixed_kinds(tmp_path):
    server, task = _contracted(tmp_path, criteria=("tests pass",))

    result = task_tools.set_acceptance_criteria(server, task.id, [
        {"text": "tests pass", "verification_kind": "machine"},
        {"text": "sources agree", "verification_kind": "source"},
        {"text": "UI is acceptable", "verification_kind": "operator"},
        {"text": "risk is closed", "verification_kind": "mixed", "required": False},
    ])

    assert "Set 4" in result
    criteria = server.tasks.get_task(task.id).criteria_v2
    assert [item["verification_kind"] for item in criteria] == [
        "machine", "source", "operator", "mixed",
    ]
    assert criteria[-1]["required"] is False


def test_later_write_invalidates_earlier_execution_evidence(tmp_path):
    server, task = _contracted(tmp_path)
    server.tasks.add_event(
        task.id, "obs_exec", exec_id="px-old", command="pytest -q",
        exit_code=0, tree_hash="before", started_at="2026-07-18T12:00:01Z",
    )
    server.tasks.add_event(
        task.id, "obs_write", write_id="ev-later", path="app.py",
        before_sha256="a", after_sha256="b", tracked=True,
    )

    output = task_tools.satisfy_criterion(
        server, task.id, "AC-1", [{"kind": "execution", "exec_id": "px-old"}]
    )

    assert "EVIDENCE_INVALID" in output


def test_completed_contract_cannot_reopen_gates_and_tamper_blocks_completion(tmp_path):
    server, task = _contracted(tmp_path, task_type="research")
    current = server.tasks.get_task(task.id)
    current.criteria_v2[0].update(status="satisfied", verification_kind="source")
    server.tasks.save_task(current)
    _review_ready(server, task.id)
    assert "completed" in task_tools.finish_task(server, task.id, "done").lower()

    refused = task_tools.set_acceptance_criteria(server, task.id, ["new gate"])
    assert "TASK_TERMINAL" in refused
    assert server.tasks.get_task(task.id).criteria_v2[0]["status"] == "satisfied"

    (tmp_path / "tamper").mkdir()
    server2, task2 = _contracted(tmp_path / "tamper", task_type="research")
    current2 = server2.tasks.get_task(task2.id)
    current2.criteria_v2[0].update(status="satisfied", verification_kind="source")
    server2.tasks.save_task(current2)
    _review_ready(server2, task2.id)
    server2.tasks._db.execute(
        "UPDATE run_contracts SET contract_hash='tampered' WHERE contract_id=?",
        (task2.contract_id,),
    )
    server2.tasks._db.commit()
    assert "CONTRACT_TAMPERED" in task_tools.finish_task(server2, task2.id, "done")


def test_one_recognized_execution_may_satisfy_multiple_criteria(tmp_path):
    server, task = _contracted(tmp_path, ("tests pass", "regression covered"))
    server.tasks.add_event(
        task.id,
        "obs_exec",
        exec_id="px-pass",
        command="pytest -q",
        exit_code=0,
        tree_hash="tree-1",
    )
    evidence = [{"kind": "execution", "exec_id": "px-pass"}]

    first = task_tools.satisfy_criterion(server, task.id, "AC-1", evidence)
    second = task_tools.satisfy_criterion(server, task.id, "AC-2", evidence)

    assert "satisfied" in first.lower()
    assert "satisfied" in second.lower()


def test_echo_execution_never_satisfies_machine_criterion(tmp_path):
    server, task = _contracted(tmp_path)
    server.tasks.add_event(
        task.id,
        "obs_exec",
        exec_id="px-echo",
        command="echo hello",
        exit_code=0,
        tree_hash="tree-1",
    )

    output = task_tools.satisfy_criterion(
        server, task.id, "AC-1", [{"kind": "execution", "exec_id": "px-echo"}]
    )

    assert "EVIDENCE_INVALID" in output


def test_failing_verification_execution_never_satisfies_machine_criterion(tmp_path):
    server, task = _contracted(tmp_path)
    server.tasks.add_event(
        task.id,
        "obs_exec",
        exec_id="px-fail",
        command="pytest -q",
        exit_code=1,
        tree_hash="tree-1",
    )

    output = task_tools.satisfy_criterion(
        server, task.id, "AC-1", [{"kind": "execution", "exec_id": "px-fail"}]
    )

    assert "EVIDENCE_INVALID" in output


def test_setting_contracted_criteria_preserves_unchanged_and_rejects_rewrites(tmp_path):
    server, task = _contracted(tmp_path, ("alpha",), task_type="research")
    evidence = _make_source_criterion(server, task.id)
    task_tools.satisfy_criterion(server, task.id, "AC-1", evidence)

    task_tools.set_acceptance_criteria(server, task.id, [
        {"text": "alpha", "verification_kind": "source"}, "beta",
    ])
    unchanged = server.tasks.get_task(task.id)
    assert unchanged.criteria_v2[0]["status"] == "satisfied"
    assert unchanged.criteria_v2[1]["id"] == "AC-2"

    refused = task_tools.set_acceptance_criteria(server, task.id, [
        {"text": "alpha revised", "verification_kind": "source"}, "beta",
    ])
    edited = server.tasks.get_task(task.id)
    assert "CRITERIA_LOCKED" in refused
    assert edited.criteria_v2[0]["id"] == "AC-1"
    assert edited.criteria_v2[0]["text"] == "alpha"
    assert edited.criteria_v2[0]["status"] == "satisfied"
    assert edited.criteria_v2[0]["evidence_refs"]


def test_optional_open_criterion_does_not_block_but_latest_failure_does(tmp_path):
    server, task = _contracted(tmp_path, ("required", "optional"), task_type="research")
    current = server.tasks.get_task(task.id)
    current.criteria_v2[0]["verification_kind"] = "source"
    current.criteria_v2[0]["status"] = "satisfied"
    current.criteria_v2[0]["evidence_refs"] = [{"kind": "source", "file": "x"}]
    current.criteria_v2[0]["verified_at"] = "2026-07-18T12:00:00Z"
    current.criteria_v2[1]["required"] = False
    current.test_results = [{"command": "pytest", "passed": False}]
    server.tasks.save_task(current)
    _review_ready(server, task.id)

    failed = task_tools.finish_task(server, task.id, "done")
    assert "FAILED" in failed

    current = server.tasks.get_task(task.id)
    current.test_results = [{"command": "pytest", "passed": True}]
    server.tasks.save_task(current)
    assert "completed" in task_tools.finish_task(server, task.id, "done").lower()


def test_model_cannot_satisfy_operator_criterion(tmp_path):
    server, task = _contracted(tmp_path)
    current = server.tasks.get_task(task.id)
    current.criteria_v2[0]["verification_kind"] = "operator"
    server.tasks.save_task(current)

    output = task_tools.satisfy_criterion(server, task.id, "AC-1", [])

    assert "OPERATOR_REQUIRED" in output
    assert server.tasks.get_task(task.id).criteria_v2[0]["status"] == "open"


def test_satisfy_criterion_is_exposed_as_an_mcp_tool(tmp_path):
    server, workspace, project = _server(tmp_path)
    mcp = build_mcp(server.config, server)

    names = {tool.name for tool in asyncio.run(mcp.list_tools())}

    assert "satisfy_criterion" in names
