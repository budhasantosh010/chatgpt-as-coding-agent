"""Phase 7: bounded evidence-checked refinement passes."""

import asyncio
from unittest.mock import AsyncMock, patch

from harness.config import Config
from harness.context import HarnessServer
from harness.server import build_mcp
from harness.tasks import tools as task_tools
from harness.tasks.contracts import RunContract


def _server(tmp_path, *, loops=2, task_type="build", effort="off"):
    workspace = tmp_path / "project"
    workspace.mkdir()
    server = HarnessServer(Config(
        workspace_roots=[tmp_path], state_dir=tmp_path / "state", secret_route="r"
    ))
    project = server.tasks.register_project(str(workspace), "Project")
    task = server.tasks.create_task(project, str(workspace), goal="refine")
    linked = server.tasks.confirm_run_contract(task.id, RunContract.confirmed(
        task_type=task_type, effort_level=effort,
        credit_ceiling=2 if effort != "off" else 0,
        candidate_count=0, machine_concurrency=2, model_concurrency=1,
        framework="none", max_loops=loops,
    ))
    return server, linked


def _begin(server, task_id, weakness="weak", directive="improve", *, state="tree-1",
           verification_plan="pytest -q", verification_kind=""):
    fake = AsyncMock(return_value=state)
    with patch("harness.tasks.tools.tree_hash", new=fake):
        return asyncio.run(task_tools.begin_refinement_pass(
            server, task_id, weakness, directive, verification_plan,
            verification_kind,
        ))


def _pass_id(output):
    return next(word.rstrip(".") for word in output.split() if word.startswith("lp-"))


def _approval_id(output):
    return output.split("approvals approve ", 1)[1].split()[0]


def _complete(server, task_id, pass_id, outcome, evidence, delta="", *, state="tree-2"):
    fake = AsyncMock(return_value=state)
    with patch("harness.tasks.tools.tree_hash", new=fake):
        return asyncio.run(task_tools.complete_refinement_pass(
            server, task_id, pass_id, outcome, evidence, delta,
        ))


def test_loops_off_refuses_pass_without_creating_effort_scope(tmp_path):
    server, task = _server(tmp_path, loops=0, effort="off")

    output = _begin(server, task.id)

    assert "LOOPS_OFF" in output
    assert task.credit_scope_id == ""


def test_repeat_key_and_locked_max_are_enforced(tmp_path):
    server, task = _server(tmp_path, loops=1)
    first = _begin(server, task.id, state="same")

    assert first.startswith("Refinement pass")
    assert "LOOP_REPEAT" in _begin(server, task.id, state="same")


def test_research_source_pass_requires_source_evidence_and_delta(tmp_path):
    server, task = _server(tmp_path, task_type="research")
    server.tasks.add_event(task.id, "obs_read", path="design.md", content_sha256="abc")
    pass_id = _pass_id(_begin(server, task.id, verification_plan=""))

    weak = _complete(server, task.id, pass_id, "improved", [{
        "kind": "source", "file": "design.md", "lines": "1-2", "fact": "new fact"
    }])

    assert "DELTA_REQUIRED" in weak
    passed = _complete(server, task.id, pass_id, "improved", [{
        "kind": "source", "file": "design.md", "lines": "1-2", "fact": "new fact"
    }], "new conclusion replaces the old assumption")
    assert "completed: improved" in passed


def test_kind_mismatched_decision_evidence_is_rejected(tmp_path):
    server, task = _server(tmp_path, task_type="build")
    pass_id = _pass_id(_begin(server, task.id))

    output = _complete(server, task.id, pass_id, "improved", [{
        "kind": "decision", "what": "guess", "why": "intuition"
    }])

    assert "LOOP_KIND_MISMATCH" in output


def test_two_consecutive_no_gain_passes_trigger_plateau(tmp_path):
    server, task = _server(tmp_path, loops=3, task_type="build")
    for number in (1, 2):
        pass_id = _pass_id(_begin(server, task.id, state=f"in-{number}"))
        server.tasks.add_event(
            task.id, "obs_exec", exec_id=f"px-{number}", command="pytest -q",
            exit_code=0, tree_hash=f"out-{number}", fingerprint=f"fp-{number}",
        )
        result = _complete(server, task.id, pass_id, "no_gain", [{
            "kind": "execution", "exec_id": f"px-{number}"
        }], state=f"out-{number}")
        assert "completed: no_gain" in result

    assert "LOOP_PLATEAU" in _begin(server, task.id, state="third")


def test_operator_kind_waits_for_local_confirmation(tmp_path):
    server, task = _server(tmp_path, task_type="plan")
    pass_id = _pass_id(_begin(
        server, task.id, verification_kind="operator", verification_plan=""
    ))

    pending = _complete(server, task.id, pass_id, "improved", [], "looks clearer")
    assert "awaits operator" in pending
    row = server.tasks.get_loop_pass(task.id, pass_id)
    assert row["status"] == "pending_operator"
    assert row["proposed_outcome"] == "improved"
    assert "LOOP_PENDING_OPERATOR" in _begin(
        server, task.id, weakness="another", directive="continue", state="tree-next",
        verification_kind="operator", verification_plan="",
    )

    confirmed = task_tools.operator_confirm_refinement_pass(server, task.id, pass_id)
    assert "confirmed by operator" in confirmed
    assert server.tasks.get_loop_pass(task.id, pass_id)["status"] == "improved"


def test_locked_max_loops_stops_a_novel_extra_pass(tmp_path):
    server, task = _server(tmp_path, loops=1, task_type="research")
    server.tasks.add_event(task.id, "obs_read", path="a.md", content_sha256="x")
    pass_id = _pass_id(_begin(server, task.id, state="first", verification_plan=""))
    evidence = [{"kind": "source", "file": "a.md", "lines": "1", "fact": "fact"}]
    assert "completed" in _complete(
        server, task.id, pass_id, "improved", evidence, "changed", state="second"
    )

    assert "LOOP_LIMIT" in _begin(server, task.id, state="third", directive="another")


def test_loop_status_and_mcp_surface_are_visible(tmp_path):
    server, task = _server(tmp_path, loops=2, effort="off")
    _begin(server, task.id)

    assert "Loops: 1/2 used" in task_tools.get_effort_status(server, task.id)
    names = {tool.name for tool in asyncio.run(build_mcp(server.config, server).list_tools())}
    assert {"begin_refinement_pass", "complete_refinement_pass"} <= names


def test_loop_extension_requires_exact_operator_approval(tmp_path):
    server, task = _server(tmp_path, loops=1)
    asked = task_tools.request_extension(server, task.id, "loops", 2, "more refinement")

    assert "APPROVAL REQUIRED" in asked
    assert server.tasks.decide_approval(_approval_id(asked), "approved")
    assert "extended" in task_tools.request_extension(
        server, task.id, "loops", 2, "more refinement"
    ).lower()
    assert server.tasks.get_run_contract(task.id).max_loops == 3
