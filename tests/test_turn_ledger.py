"""Turn Ledger: model-published conversation turns, checked against what the
server actually observed, and structurally barred from being evidence."""

from __future__ import annotations

import json

from harness.config import Config
from harness.context import HarnessServer
from harness.tasks import tools as task_tools
from harness.tasks import turns
from harness.tasks.contracts import RunContract


def _server(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    server = HarnessServer(Config(
        workspace_roots=[tmp_path], state_dir=tmp_path / "state", secret_route="r"
    ))
    project = server.tasks.register_project(str(workspace), "Project")
    task = server.tasks.create_task(project, str(workspace), goal="build the thing")
    return server, task


def _contracted(tmp_path, *, ceiling=8):
    server, task = _server(tmp_path)
    linked = server.tasks.confirm_run_contract(task.id, RunContract.confirmed(
        task_type="build", effort_level="medium", credit_ceiling=ceiling,
        candidate_count=0, machine_concurrency=1, model_concurrency=1,
        framework="none", max_loops=0,
    ))
    return server, linked


def test_publishing_requires_work_the_server_actually_saw(tmp_path):
    # A model must not be able to manufacture a turn out of nothing; the ledger
    # is only ever a commentary on observed activity.
    server, task = _server(tmp_path)

    output = task_tools.publish_turn(server, task.id, "do a thing", "did the thing")

    assert "NO_OPEN_TURN" in output


def test_published_turn_keeps_model_prose_and_server_call_list_apart(tmp_path):
    server, task = _server(tmp_path)
    server.record_tool_call("read_file", task.id, ("calc.py",))
    server.record_tool_call("edit_file", task.id, ("calc.py",))

    task_tools.publish_turn(
        server, task.id, "fix the add bug", "swapped - for + in add()",
        ["kept the signature"], "check the logout path",
    )

    row = turns.recent(server.config.state_dir, task.id, 5)[-1]
    assert row["user_request"] == {
        "text": "fix the add bug", "provenance": turns.MODEL_REPORTED,
    }
    assert row["assistant_response"]["provenance"] == turns.MODEL_PUBLISHED
    # The server's half the model never touches.
    assert row["observed"]["provenance"] == turns.MACHINE_OBSERVED
    assert row["observed"]["count"] == 2
    assert [c["tool"] for c in row["observed"]["tool_calls"]] == ["read_file", "edit_file"]
    assert row["next_action"] == "check the logout path"


def test_ledger_lives_in_the_state_dir_never_in_the_project(tmp_path):
    # Chat text in the repo is one stray `git add` from being published, which
    # is why memory.py keeps its files out too.
    server, task = _server(tmp_path)
    server.record_tool_call("read_file", task.id, ("calc.py",))
    task_tools.publish_turn(server, task.id, "q", "a")

    assert (server.config.state_dir / "tasks" / task.id / "chat" / "turns.jsonl").exists()
    assert not list((tmp_path / "project").rglob("*.jsonl"))
    assert not (tmp_path / "project" / ".harness-local").exists()


def test_orientation_tools_do_not_open_a_turn(tmp_path):
    # Resuming a task must not conjure an unpublished turn and trip the gate
    # before any work has happened.
    server, task = _server(tmp_path)

    for tool in ("resume_task", "task_status", "get_effort_status", "list_tasks"):
        server.record_tool_call(tool, task.id, ())

    assert turns.open_turn(server.config.state_dir, task.id) is None
    assert turns.unpublished_work(server.config.state_dir, task.id) == 0


def test_gate_does_not_fire_mid_turn_before_any_cycle_closes(tmp_path):
    # read_file -> begin_cycle is one honest turn. Blocking it to catch a
    # dishonest one would break every normal run.
    server, task = _contracted(tmp_path)
    server.record_tool_call("read_file", task.id, ("calc.py",))

    output = task_tools.begin_cycle(server, task.id, "why does add fail?")

    assert "TURN_UNPUBLISHED" not in output
    assert "opened" in output


def test_second_cycle_is_blocked_until_the_first_turn_is_published(tmp_path):
    # A completed cycle is the earliest turn boundary the server can prove.
    server, task = _contracted(tmp_path)
    server.record_tool_call("complete_cycle", task.id, ())

    blocked = task_tools.begin_cycle(server, task.id, "next question")

    assert "TURN_UNPUBLISHED" in blocked
    assert "publish_turn" in blocked


def test_publishing_clears_the_gate(tmp_path):
    server, task = _contracted(tmp_path)
    server.record_tool_call("complete_cycle", task.id, ())
    assert "TURN_UNPUBLISHED" in task_tools.begin_cycle(server, task.id, "next")

    task_tools.publish_turn(server, task.id, "fix it", "fixed it")

    assert "opened" in task_tools.begin_cycle(server, task.id, "next question")


def test_discard_clears_the_gate_and_leaves_the_hole_visible(tmp_path):
    # The escape hatch: without it a failed publish locks the task forever.
    # Dropping a turn must still be legible as a gap in the ledger.
    server, task = _contracted(tmp_path)
    server.record_tool_call("complete_cycle", task.id, ())

    assert "discarded" in task_tools.discard_turn(server, task.id, "answer was lost")

    assert "opened" in task_tools.begin_cycle(server, task.id, "next question")
    row = turns.recent(server.config.state_dir, task.id, 5)[-1]
    assert row["discarded"] is True
    assert row["discard_reason"] == "answer was lost"
    assert row["observed"]["count"] == 1  # the work is still on the record


def test_discard_demands_a_reason(tmp_path):
    server, task = _server(tmp_path)
    server.record_tool_call("edit_file", task.id, ("calc.py",))

    assert "REASON_REQUIRED" in task_tools.discard_turn(server, task.id, "   ")
    assert turns.unpublished_work(server.config.state_dir, task.id) == 1


def test_finish_task_refuses_while_any_work_is_unpublished(tmp_path):
    # Stricter than begin_cycle's gate: no reading of "done" leaves the last
    # stretch of work unrecorded.
    server, task = _server(tmp_path)
    server.record_tool_call("edit_file", task.id, ("calc.py",))

    output = task_tools.finish_task(server, task.id, "all done")

    assert "TURN_UNPUBLISHED" in output
    assert "1 observed tool calls" in output


def test_resume_task_replays_the_ledger_and_labels_it_non_evidence(tmp_path):
    # This is the whole point: a NEW chat picks up where the last one stopped.
    server, task = _server(tmp_path)
    server.record_tool_call("edit_file", task.id, ("auth.py",))
    task_tools.publish_turn(
        server, task.id, "fix the login bug",
        "session was checked before the token loaded", [], "verify logout",
    )

    output = task_tools.resume_task(server, task.id)

    assert "fix the login bug" in output
    assert "session was checked before the token loaded" in output
    assert "Pick up here:** verify logout" in output
    assert "NOT an observed transcript" in output
    assert "Never evidence" in output


def test_resume_task_warns_about_an_unpublished_turn(tmp_path):
    server, task = _server(tmp_path)
    server.record_tool_call("run_command", task.id, ("pytest",))

    output = task_tools.resume_task(server, task.id)

    assert "unpublished" in output


def test_transcript_markdown_mirrors_the_ledger_with_provenance(tmp_path):
    server, task = _server(tmp_path)
    server.record_tool_call("run_command", task.id, ("pytest -q",))
    task_tools.publish_turn(server, task.id, "run the tests", "18 passed", ["kept sqlite"])

    text = (server.config.state_dir / "tasks" / task.id / "chat" / "transcript.md").read_text(
        encoding="utf-8"
    )
    assert "**You** *(model_reported)*" in text
    assert "**ChatGPT** *(model_published)*" in text
    assert "- kept sqlite" in text
    assert "Server observed 1 tool calls: run_command" in text
    assert "Never usable as acceptance evidence" in text


def test_a_torn_ledger_line_does_not_sink_the_rest(tmp_path):
    server, task = _server(tmp_path)
    server.record_tool_call("edit_file", task.id, ("a.py",))
    task_tools.publish_turn(server, task.id, "first", "first answer")
    path = server.config.state_dir / "tasks" / task.id / "chat" / "turns.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"turn_id": "tr-torn"\n')  # truncated write, as from a crash

    rows = turns.recent(server.config.state_dir, task.id, 10)

    assert [row["user_request"]["text"] for row in rows] == ["first"]


def test_publish_rejects_a_forged_provenance(tmp_path):
    # The model may claim its own words; it may not claim the operator typed them
    # into the Workbench, nor invent a machine-observed label.
    server, task = _server(tmp_path)
    server.record_tool_call("edit_file", task.id, ("a.py",))

    for bad in (turns.MACHINE_OBSERVED, turns.MODEL_PUBLISHED, "trusted"):
        try:
            turns.publish(
                server.config.state_dir, task.id,
                user_request="q", assistant_response="a", request_provenance=bad,
            )
        except ValueError as exc:
            assert "PROVENANCE_INVALID" in str(exc)
        else:  # pragma: no cover - only reached on a regression
            raise AssertionError(f"{bad} should not be accepted")


def test_turn_records_are_json_and_carry_the_task_id(tmp_path):
    server, task = _server(tmp_path)
    server.record_tool_call("edit_file", task.id, ("a.py",))
    task_tools.publish_turn(server, task.id, "q", "a")

    path = server.config.state_dir / "tasks" / task.id / "chat" / "turns.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == 1
    assert rows[0]["task_id"] == task.id
    assert rows[0]["turn_id"].startswith("tr-")
