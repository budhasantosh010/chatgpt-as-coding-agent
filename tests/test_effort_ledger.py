"""Phase 4: atomic effort scopes, cycles, validated receipts, and extensions."""

from __future__ import annotations

import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from harness.config import Config
from harness.context import HarnessServer
from harness.server import _task_mutation_denial, build_mcp
from harness.tasks import tools as task_tools
from harness.tasks.contracts import RunContract


def _server(tmp_path, *, effort="low", ceiling=2, task_type="research", candidates=0):
    workspace = tmp_path / "project"
    workspace.mkdir()
    server = HarnessServer(Config(
        workspace_roots=[tmp_path], state_dir=tmp_path / "state", secret_route="r",
        decision_caps={"build": 0.2, "review": 0.8, "plan": 0.8, "research": 0.8},
    ))
    project = server.tasks.register_project(str(workspace), "Project")
    task = server.tasks.create_task(project, str(workspace), goal="effort")
    linked = server.tasks.confirm_run_contract(
        task.id,
        RunContract.confirmed(
            task_type=task_type,
            effort_level=effort,
            credit_ceiling=ceiling,
            candidate_count=candidates,
            machine_concurrency=2,
            model_concurrency=1,
            framework="none",
            max_loops=0,
        ),
    )
    return server, linked


def _decision(number):
    return [{
        "kind": "decision",
        "what": f"chose option {number}",
        "why": f"tradeoff analysis {number}",
    }]


def test_contract_mutation_gate_denies_read_only_but_allows_plan(tmp_path):
    server, task = _server(tmp_path)
    current = server.tasks.get_task(task.id)
    current.permission_mode = "read_only"
    server.tasks.save_task(current)

    assert "PERMISSION_DENIED" in _task_mutation_denial(server, task.id)

    current = server.tasks.get_task(task.id)
    current.permission_mode = "plan"
    server.tasks.save_task(current)
    assert _task_mutation_denial(server, task.id) is None


def _cycle_id(output):
    return next(token.rstrip(".") for token in output.split() if token.startswith("cy-"))


def _approval_id(output):
    return output.split("approvals approve ", 1)[1].split()[0]


def test_effort_off_has_no_cycle_or_scope(tmp_path):
    server, task = _server(tmp_path, effort="off", ceiling=0)

    output = task_tools.begin_cycle(server, task.id, "question")

    assert "EFFORT_OFF" in output
    assert task.credit_scope_id == ""


def test_one_open_cycle_per_task_and_abandon_spends_nothing(tmp_path):
    server, task = _server(tmp_path)
    opened = task_tools.begin_cycle(server, task.id, "question", "purpose")
    cycle_id = _cycle_id(opened)

    assert "spent 0/2" in opened
    assert "CYCLE_OPEN" in task_tools.begin_cycle(server, task.id, "other")
    abandoned = task_tools.abandon_cycle(server, task.id, cycle_id, "changed direction")
    assert "abandoned" in abandoned.lower()

    status = task_tools.get_effort_status(server, task.id)
    assert "0/2" in status
    assert "Open cycle: none" in status
    assert "opened" in task_tools.begin_cycle(server, task.id, "replacement").lower()


def test_valid_decision_receipt_spends_atomically_without_completing_task(tmp_path):
    server, task = _server(tmp_path)
    cycle_id = _cycle_id(task_tools.begin_cycle(server, task.id, "choose architecture"))

    output = task_tools.complete_cycle(
        server, task.id, cycle_id, "selected cache", "decision recorded", _decision(1)
    )

    assert output.startswith("Credit spent (decision tier).")
    assert "1/2" in output
    assert "tradeoff analysis" not in output
    row = server.tasks._db.execute(
        "SELECT status, tier, receipt_json FROM credits WHERE credit_id=?", (cycle_id,)
    ).fetchone()
    receipt = json.loads(row["receipt_json"])
    assert row["status"] == "spent"
    assert row["tier"] == "decision"
    assert receipt["conclusion"] == "selected cache"
    assert server.tasks.get_task(task.id).status.value == "new"


def test_invalid_receipt_does_not_spend_and_open_cycle_can_retry(tmp_path):
    server, task = _server(tmp_path)
    cycle_id = _cycle_id(task_tools.begin_cycle(server, task.id, "weak evidence"))

    rejected = task_tools.complete_cycle(
        server, task.id, cycle_id, "claim", "none", [{"kind": "decision", "what": "x"}]
    )

    assert "EVIDENCE_INVALID" in rejected or "RECEIPT_WEAK" in rejected
    row = server.tasks._db.execute(
        "SELECT status, receipt_json FROM credits WHERE credit_id=?", (cycle_id,)
    ).fetchone()
    assert row["status"] == "open"
    assert row["receipt_json"]

    accepted = task_tools.complete_cycle(
        server, task.id, cycle_id, "claim", "now supported", _decision(1)
    )
    assert accepted.startswith("Credit spent")


def test_scope_exhaustion_is_shared_by_ordinary_subtask(tmp_path):
    server, task = _server(tmp_path)
    child_output = task_tools.create_subtask(server, task.id, "child")
    child_id = next(token for token in child_output.split() if token.startswith("T-") and token != task.id)

    first = _cycle_id(task_tools.begin_cycle(server, task.id, "q1"))
    task_tools.complete_cycle(server, task.id, first, "c1", "d1", _decision(1))
    second = _cycle_id(task_tools.begin_cycle(server, child_id, "q2"))
    task_tools.complete_cycle(server, child_id, second, "c2", "d2", _decision(2))

    assert "NO_CREDITS" in task_tools.begin_cycle(server, task.id, "q3")
    assert "NO_CREDITS" in task_tools.begin_cycle(server, child_id, "q4")
    assert "2/2" in task_tools.get_effort_status(server, child_id)


def test_two_store_instances_cannot_open_two_cycles_for_same_task(tmp_path):
    server, task = _server(tmp_path)
    from harness.tasks.store import TaskStore

    other = TaskStore(server.tasks.path)
    first = server.tasks.begin_cycle(task.id, "q1", "", "")

    try:
        second_error = None
        try:
            other.begin_cycle(task.id, "q2", "", "")
        except ValueError as exc:
            second_error = str(exc)
    finally:
        other.close()

    assert first["cycle_id"].startswith("cy-")
    assert "CYCLE_OPEN" in second_error


def test_machine_receipt_requires_and_uses_pre_registered_verification(tmp_path):
    server, task = _server(tmp_path)
    cycle = _cycle_id(task_tools.begin_cycle(
        server, task.id, "run tests", verification_plan="pytest -q"
    ))
    server.tasks.add_event(
        task.id, "obs_exec", exec_id="px-tests", command="pytest -q",
        exit_code=0, tree_hash="tree-1", fingerprint="exec-fp-1",
    )

    output = task_tools.complete_cycle(
        server, task.id, cycle, "tests pass", "continue",
        [{"kind": "execution", "exec_id": "px-tests"}],
    )

    assert "machine tier" in output


def test_machine_execution_must_exactly_match_verification_plan(tmp_path):
    server, task = _server(tmp_path)
    cycle = _cycle_id(task_tools.begin_cycle(
        server, task.id, "verify", verification_plan="pytest -q"
    ))
    server.tasks.add_event(
        task.id, "obs_exec", exec_id="px-other", command="pytest tests/unit -q",
        exit_code=0, tree_hash="tree", fingerprint="fp-other",
    )
    output = task_tools.complete_cycle(
        server, task.id, cycle, "claim", "continue",
        [{"kind": "execution", "exec_id": "px-other"}],
    )

    assert "EVIDENCE_INVALID" in output


def test_source_receipt_uses_prior_server_recorded_read(tmp_path):
    server, task = _server(tmp_path)
    server.tasks.add_event(
        task.id, "obs_read", path="README.md", content_sha256="read-hash"
    )
    cycle = _cycle_id(task_tools.begin_cycle(server, task.id, "read design"))
    output = task_tools.complete_cycle(
        server, task.id, cycle, "design understood", "continue",
        [{"kind": "source", "file": "README.md", "lines": "1-5", "fact": "documents design"}],
    )

    assert "source tier" in output


def test_diff_receipt_requires_changed_server_recorded_write(tmp_path):
    server, task = _server(tmp_path)
    cycle = _cycle_id(task_tools.begin_cycle(server, task.id, "make change"))
    server.tasks.add_event(
        task.id, "obs_write", write_id="ev-change", path="app.py",
        before_sha256="before", after_sha256="after", tracked=True,
    )
    output = task_tools.complete_cycle(
        server, task.id, cycle, "change made", "continue",
        [{"kind": "diff", "write_ids": ["ev-change"], "note": "updated app"}],
    )

    assert "machine tier" in output


def test_ordinary_command_approval_never_turns_echo_into_proof(tmp_path):
    server, task = _server(tmp_path)
    cycle = _cycle_id(task_tools.begin_cycle(
        server, task.id, "verify", verification_plan="echo hello"
    ))
    aid = server.tasks.add_approval(
        task.id, "command_arbitrary", "run_command: echo hello", "ordinary"
    )
    assert server.tasks.decide_approval(aid, "approved")
    server.tasks.add_event(
        task.id, "obs_exec", exec_id="px-echo", command="echo hello",
        exit_code=0, tree_hash="tree", fingerprint="fp-echo",
    )
    output = task_tools.complete_cycle(
        server, task.id, cycle, "claim", "continue",
        [{"kind": "execution", "exec_id": "px-echo"}],
    )

    assert "EVIDENCE_INVALID" in output


def test_duplicate_receipt_is_rejected_scope_wide_across_subtask(tmp_path):
    server, task = _server(tmp_path, ceiling=3)
    child_output = task_tools.create_subtask(server, task.id, "child")
    child_id = next(token for token in child_output.split() if token.startswith("T-") and token != task.id)
    first = _cycle_id(task_tools.begin_cycle(server, task.id, "same question"))
    task_tools.complete_cycle(server, task.id, first, "same answer", "d", _decision(1))
    duplicate = _cycle_id(task_tools.begin_cycle(server, child_id, "same question"))
    output = task_tools.complete_cycle(
        server, child_id, duplicate, "same answer", "d", _decision(1)
    )
    assert "RECEIPT_REJECTED" in output
    assert "1/3" in task_tools.get_effort_status(server, child_id)


def test_receipt_identity_ignores_unknown_keys_and_duplicate_refs(tmp_path):
    server, task = _server(tmp_path, ceiling=3)
    server.tasks.add_event(
        task.id, "obs_read", path="README.md", content_sha256="same-read"
    )
    ref = {"kind": "source", "file": "README.md", "lines": "1", "fact": "fact"}
    first = _cycle_id(task_tools.begin_cycle(server, task.id, "same question"))
    assert "source tier" in task_tools.complete_cycle(
        server, task.id, first, "same answer", "continue", [ref, ref]
    )
    second = _cycle_id(task_tools.begin_cycle(server, task.id, "same question"))
    replay = task_tools.complete_cycle(
        server, task.id, second, "same answer", "continue", [{**ref, "nonce": "2"}]
    )

    assert "RECEIPT_REJECTED" in replay


def test_decision_tier_cannot_exceed_task_type_cap(tmp_path):
    server, task = _server(tmp_path, ceiling=8, task_type="build")
    for number in (1, 2):
        cycle = _cycle_id(task_tools.begin_cycle(server, task.id, f"q{number}"))
        assert "decision tier" in task_tools.complete_cycle(
            server, task.id, cycle, f"c{number}", "d", _decision(number)
        )
    third = _cycle_id(task_tools.begin_cycle(server, task.id, "q3"))
    output = task_tools.complete_cycle(
        server, task.id, third, "c3", "d", _decision(3)
    )
    assert "DECISION_CAP" in output
    assert "2/8" in task_tools.get_effort_status(server, task.id)


def test_unchanged_rerun_execution_fingerprint_cannot_spend_twice(tmp_path):
    server, task = _server(tmp_path, ceiling=3, task_type="build")
    first = _cycle_id(task_tools.begin_cycle(
        server, task.id, "q1", verification_plan="pytest -q"
    ))
    server.tasks.add_event(
        task.id, "obs_exec", exec_id="px-1", command="pytest -q",
        exit_code=0, tree_hash="same-tree", fingerprint="same-exec-fp",
    )
    task_tools.complete_cycle(
        server, task.id, first, "c1", "d1", [{"kind": "execution", "exec_id": "px-1"}]
    )
    second = _cycle_id(task_tools.begin_cycle(
        server, task.id, "q2", verification_plan="pytest -q"
    ))
    server.tasks.add_event(
        task.id, "obs_exec", exec_id="px-2", command="pytest -q",
        exit_code=0, tree_hash="same-tree", fingerprint="same-exec-fp",
    )
    output = task_tools.complete_cycle(
        server, task.id, second, "c2", "d2", [{"kind": "execution", "exec_id": "px-2"}]
    )

    assert "RECEIPT_REJECTED" in output
    assert "1/3" in task_tools.get_effort_status(server, task.id)


def test_missing_receipt_view_regenerates_from_atomic_database_truth(tmp_path):
    server, task = _server(tmp_path)
    cycle = _cycle_id(task_tools.begin_cycle(server, task.id, "q"))
    task_tools.complete_cycle(server, task.id, cycle, "c", "d", _decision(1))
    view = server.config.state_dir / "tasks" / task.id / "effort" / f"{cycle}.md"
    assert view.exists()
    view.unlink()

    task_tools.get_effort_status(server, task.id)

    assert view.exists()
    assert "Effort receipt" in view.read_text(encoding="utf-8")


def test_custom_verification_needs_separate_evidence_approval(tmp_path):
    server, task = _server(tmp_path, task_type="build")
    command = 'python -c "print(2 + 2)"'
    cycle = _cycle_id(task_tools.begin_cycle(
        server, task.id, "prove calculation", verification_plan=command
    ))
    server.tasks.add_event(
        task.id, "obs_exec", exec_id="px-custom", command=command,
        exit_code=0, tree_hash="tree", fingerprint="custom-fp",
    )
    evidence = [{
        "kind": "execution", "exec_id": "px-custom",
        "reason": "the command deterministically evaluates the calculation",
    }]

    first = task_tools.complete_cycle(
        server, task.id, cycle, "result is 4", "accept", evidence
    )
    assert "VERIFICATION_APPROVAL_REQUIRED" in first
    pending = server.tasks.pending_approvals(task.id)
    assert pending[-1]["action"] == "verification_evidence"
    assert server.tasks.decide_approval(pending[-1]["id"], "approved")

    second = task_tools.complete_cycle(
        server, task.id, cycle, "result is 4", "accept", evidence
    )
    assert "machine tier" in second


def test_credit_extension_requires_approval_and_updates_contract_atomically(tmp_path):
    server, task = _server(tmp_path, ceiling=2)

    asked = task_tools.request_extension(server, task.id, "credits", 3, "more work")
    assert "APPROVAL REQUIRED" in asked
    assert server.tasks.effort_status(task.credit_scope_id)["ceiling"] == 2

    assert server.tasks.decide_approval(_approval_id(asked), "approved")
    result = task_tools.request_extension(server, task.id, "credits", 3, "more work")
    assert "extended" in result.lower()
    assert server.tasks.get_run_contract(task.id).credit_ceiling == 5
    assert server.tasks.effort_status(task.credit_scope_id)["ceiling"] == 5


def test_approved_extension_is_consumed_atomically_under_concurrency(tmp_path):
    server, task = _server(tmp_path, ceiling=2)
    asked = task_tools.request_extension(server, task.id, "credits", 3, "more work")
    assert server.tasks.decide_approval(_approval_id(asked), "approved")
    other = HarnessServer(server.config)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda current: task_tools.request_extension(
                    current, task.id, "credits", 3, "more work"
                ),
                (server, other),
            ))
    finally:
        other.tasks.close()

    assert sum("extended" in result.lower() for result in results) == 1
    assert server.tasks.effort_status(task.credit_scope_id)["ceiling"] == 5


def test_named_scope_extension_does_not_raise_future_candidate_budget(tmp_path):
    server, task = _server(tmp_path, ceiling=2, candidates=2)
    first = server.tasks.create_candidate_task(
        task, goal="first", title="first", permission_mode="auto_workspace",
        contract_id=task.contract_id, parent_id=task.id,
    )
    asked = task_tools.request_extension(
        server, first.id, "credits", 3, "candidate needs more", first.credit_scope_id
    )
    assert server.tasks.decide_approval(_approval_id(asked), "approved")
    assert "extended" in task_tools.request_extension(
        server, first.id, "credits", 3, "candidate needs more", first.credit_scope_id
    ).lower()

    second = server.tasks.create_candidate_task(
        task, goal="second", title="second", permission_mode="auto_workspace",
        contract_id=task.contract_id, parent_id=task.id,
    )

    assert server.tasks.effort_status(first.credit_scope_id)["ceiling"] == 5
    assert server.tasks.effort_status(second.credit_scope_id)["ceiling"] == 2
    assert server.tasks.get_run_contract(task.id).credit_ceiling == 2


def test_background_execution_started_before_cycle_is_stale_even_if_polled_later(tmp_path):
    server, task = _server(tmp_path, task_type="build")
    cycle = _cycle_id(task_tools.begin_cycle(
        server, task.id, "fresh proof", verification_plan="pytest -q"
    ))
    opened = server.tasks.get_cycle(task.id, cycle)["opened"]
    server.tasks.add_event(
        task.id, "obs_exec", exec_id="px-background", command="pytest -q",
        exit_code=0, tree_hash="tree", fingerprint="background",
        started_at="2020-01-01T00:00:00Z", polled_after=opened,
    )

    output = task_tools.complete_cycle(
        server, task.id, cycle, "done", "accept",
        [{"kind": "execution", "exec_id": "px-background"}],
    )

    assert "EVIDENCE_INVALID" in output


def test_denied_credit_extension_never_changes_the_budget(tmp_path):
    server, task = _server(tmp_path, ceiling=2)
    asked = task_tools.request_extension(server, task.id, "credits", 1, "optional")

    assert server.tasks.decide_approval(_approval_id(asked), "denied")
    denied = task_tools.request_extension(server, task.id, "credits", 1, "optional")

    assert "APPROVAL_DENIED" in denied
    assert server.tasks.get_run_contract(task.id).credit_ceiling == 2
    assert server.tasks.effort_status(task.credit_scope_id)["ceiling"] == 2


def test_receipt_view_crash_never_rolls_back_a_spent_credit(tmp_path):
    server, task = _server(tmp_path)
    cycle = _cycle_id(task_tools.begin_cycle(server, task.id, "q"))
    with patch.object(task_tools, "write_receipt_view", side_effect=OSError("disk")):
        result = task_tools.complete_cycle(server, task.id, cycle, "c", "d", _decision(1))

    assert "Credit spent" in result
    assert server.tasks.effort_status(task.credit_scope_id)["spent"] == 1
    task_tools.get_effort_status(server, task.id)
    view = server.config.state_dir / "tasks" / task.id / "effort" / f"{cycle}.md"
    assert view.exists()


def test_finish_task_never_reads_the_credit_ledger(tmp_path):
    server, task = _server(tmp_path)
    server.tasks.set_task_status(task.id, "review_ready")

    with patch.object(server.tasks, "effort_status", side_effect=AssertionError("ledger read")):
        result = task_tools.finish_task(server, task.id, "done", "notes only")

    assert "completed" in result.lower()


def test_all_effort_operations_are_exposed_as_mcp_tools(tmp_path):
    server, _ = _server(tmp_path)
    names = {tool.name for tool in asyncio.run(build_mcp(server.config, server).list_tools())}

    assert {"begin_cycle", "complete_cycle", "abandon_cycle",
            "get_effort_status", "request_extension"} <= names
