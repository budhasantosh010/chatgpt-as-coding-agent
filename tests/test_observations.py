"""Phase 3: server-owned read/write/execution observations and fingerprints."""

from __future__ import annotations

import asyncio
import os
import subprocess

import pytest

from harness.config import Config
from harness.context import HarnessServer
from harness.observations import tree_hash
from harness.policy import Capability
from harness.server import _call
from harness.tasks import tools as task_tools
from harness.tasks.contracts import RunContract
from harness.tools import files, process, shell


def run(coro):
    return asyncio.run(coro)


def _git(workspace, *args):
    return subprocess.run(
        ["git", *args], cwd=workspace, text=True, capture_output=True, check=True
    )


@pytest.fixture
def observed(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    cfg = Config(
        workspace_roots=[tmp_path], state_dir=tmp_path / "state", secret_route="r",
        auto_checkpoint=False, arbitrary_commands="allow",
    )
    server = HarnessServer(cfg)
    task_id = run(task_tools.start_task(
        server, str(workspace), "observe", "auto_workspace", isolation="workspace"
    )).split()[2]
    context = server.context_for(task_id, "observation-test")
    yield server, task_id, context, workspace
    server.tasks.close()


def _init_repo(workspace):
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "tests@example.com")
    _git(workspace, "config", "user.name", "Tests")
    (workspace / "tracked.txt").write_text("before\n", encoding="utf-8")
    _git(workspace, "add", "tracked.txt")
    _git(workspace, "commit", "-m", "initial")


def test_git_tree_hash_changes_when_untracked_content_changes_same_size(observed):
    server, task_id, context, workspace = observed
    _init_repo(workspace)
    untracked = workspace / "draft.txt"
    untracked.write_text("AAAA", encoding="utf-8")
    original_times = (untracked.stat().st_atime, untracked.stat().st_mtime)
    first = run(tree_hash(context))

    untracked.write_text("BBBB", encoding="utf-8")
    os.utime(untracked, original_times)
    second = run(tree_hash(context))

    assert first != second


def test_non_git_tree_hash_uses_touched_files_and_windows_paths(observed):
    server, task_id, context, workspace = observed
    nested = workspace / "nested" / "file.txt"
    nested.parent.mkdir()
    nested.write_text("one", encoding="utf-8")
    task = server.tasks.get_task(task_id)
    task.changed_files = [r"nested\file.txt"]
    server.tasks.save_task(task)
    first = run(tree_hash(context))

    nested.write_text("two", encoding="utf-8")
    second = run(tree_hash(context))

    assert first != second


def test_read_file_records_relative_normalized_path_and_content_hash(observed):
    server, task_id, context, workspace = observed
    nested = workspace / "nested" / "file.txt"
    nested.parent.mkdir()
    nested.write_text("hello\n", encoding="utf-8")

    run(_call(context, Capability.READ, files.read_file, r"nested\file.txt", None, None))

    event = [e for e in server.tasks.events(task_id) if e["type"] == "obs_read"][-1]
    assert event["path"] == "nested/file.txt"
    assert len(event["content_sha256"]) == 64


def test_write_batch_records_per_file_before_after_hash_and_tracked_flag(observed):
    server, task_id, context, workspace = observed
    _init_repo(workspace)

    output = run(_call(
        context,
        Capability.WRITE,
        files.apply_edits,
        [
            {"path": "tracked.txt", "content": "after\n"},
            {"path": r"new\file.txt", "content": "new\n"},
        ],
    ))

    assert "Applied 2" in output
    events = [e for e in server.tasks.events(task_id) if e["type"] == "obs_write"]
    assert [e["path"] for e in events] == ["tracked.txt", "new/file.txt"]
    assert events[0]["before_sha256"] != events[0]["after_sha256"]
    assert events[0]["tracked"] is True
    assert events[1]["before_sha256"] == ""
    assert events[1]["after_sha256"]
    assert events[1]["tracked"] is False


def test_run_command_records_execution_and_surfaces_citable_id(observed):
    server, task_id, context, workspace = observed

    output = run(_call(
        context, Capability.EXECUTE, shell.run_command, "echo observation", None, 30
    ))

    event = [e for e in server.tasks.events(task_id) if e["type"] == "obs_exec"][-1]
    assert event["exec_id"].startswith("px-")
    assert event["exec_id"] in output
    assert event["command"] == "echo observation"
    assert event["cwd"] == str(workspace)
    assert event["exit_code"] == 0
    assert event["duration_s"] >= 0
    assert event["runner"] == "local"
    assert len(event["tree_hash"]) == 64
    assert len(event["fingerprint"]) == 64


def test_execution_fingerprint_repeats_only_until_tree_changes(observed):
    server, task_id, context, workspace = observed
    _init_repo(workspace)

    for _ in range(2):
        run(_call(context, Capability.EXECUTE, shell.run_command, "echo same", None, 30))
    first_two = [e for e in server.tasks.events(task_id) if e["type"] == "obs_exec"]
    assert first_two[-2]["fingerprint"] == first_two[-1]["fingerprint"]

    run(_call(context, Capability.WRITE, files.write_file, "tracked.txt", "changed\n", None))
    run(_call(context, Capability.EXECUTE, shell.run_command, "echo same", None, 30))
    executions = [e for e in server.tasks.events(task_id) if e["type"] == "obs_exec"]
    assert executions[-1]["fingerprint"] != executions[-2]["fingerprint"]


def test_background_process_records_observation_when_it_terminates(observed):
    server, task_id, context, workspace = observed
    started = run(_call(
        context,
        Capability.EXECUTE,
        process.start_process,
        'python -c "print(123)"',
        None,
        0.2,
    ))
    process_id = started.split()[1]
    assert process_id.startswith("px-")

    run(_call(context, Capability.READ, process.read_process, process_id, 0.2))

    events = [e for e in server.tasks.events(task_id) if e["type"] == "obs_exec"]
    assert events[-1]["exec_id"] == process_id
    assert events[-1]["exit_code"] == 0


def test_real_recorded_verification_can_satisfy_contracted_gate(observed):
    server, task_id, context, workspace = observed
    task_tools.set_acceptance_criteria(server, task_id, ["project compiles"])
    server.tasks.confirm_run_contract(
        task_id,
        RunContract.confirmed(
            task_type="build", effort_level="off", credit_ceiling=0,
            candidate_count=0, machine_concurrency=1, model_concurrency=1,
            framework="none", max_loops=0,
        ),
    )
    output = run(_call(
        context, Capability.EXECUTE, shell.run_command,
        "python -m compileall .", None, 30,
    ))
    exec_id = output.split("[execution id: ", 1)[1].split("]", 1)[0]

    result = task_tools.satisfy_criterion(
        server, task_id, "AC-1", [{"kind": "execution", "exec_id": exec_id}]
    )

    assert "satisfied" in result.lower()
