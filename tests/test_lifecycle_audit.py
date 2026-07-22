"""Task-lifecycle tools must land in audit.jsonl and the live feed.

The defect: the operator's reconciliation ritual is "compare what ChatGPT says
it did against audit.jsonl". But lifecycle tools (task_status, begin_cycle,
advance_task, finish_task, ...) are server-scoped — they bind no workspace, so
they never travelled the capability pipeline that writes the audit line. A real
flight produced ZERO audit rows while ChatGPT was demonstrably calling tools.
An audit log that silently omits a whole class of calls is worse than no audit
log, because it reads as a complete history.
"""

from __future__ import annotations

import asyncio
import json

from harness.config import Config
from harness.context import HarnessServer
from harness.server import _task_id_argument, build_mcp
from harness.tasks import tools as task_tools


def _server(tmp_path, *, permission_mode="auto_workspace"):
    workspace = tmp_path / "project"
    workspace.mkdir()
    server = HarnessServer(Config(
        workspace_roots=[tmp_path], state_dir=tmp_path / "state", secret_route="r",
    ))
    project = server.tasks.register_project(str(workspace), "Project")
    task = server.tasks.create_task(project, str(workspace), goal="fix the bug")
    if permission_mode != "auto_workspace":
        server.tasks.mutate_task(
            task.id, lambda t: setattr(t, "permission_mode", permission_mode)
        )
    return server, task, workspace


def _audit_rows(server):
    path = server.config.state_dir / "audit.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_read_only_lifecycle_call_is_audited(tmp_path):
    """task_status changes nothing, which is exactly why it must be recorded:
    'I checked the status' is otherwise an unverifiable claim."""
    server, task, _ = _server(tmp_path)
    mcp = build_mcp(server.config, server)

    asyncio.run(mcp.call_tool("task_status", {"task_id": task.id}))

    rows = [row for row in _audit_rows(server) if row["tool"] == "task_status"]
    assert rows, "task_status left no audit trail"
    assert rows[0]["task_id"] == task.id
    server.tasks.close()


def test_mutating_lifecycle_call_is_audited_with_its_argument(tmp_path):
    server, task, _ = _server(tmp_path)
    mcp = build_mcp(server.config, server)

    asyncio.run(mcp.call_tool(
        "advance_task", {"task_id": task.id, "to_state": "discovering"}
    ))

    rows = [row for row in _audit_rows(server) if row["tool"] == "advance_task"]
    assert rows, "advance_task left no audit trail"
    assert rows[0]["task_id"] == task.id
    # The detail column is what makes `harness watch` readable: the target
    # state, not a repeat of the task id.
    assert rows[0]["detail"] == "discovering"
    server.tasks.close()


def test_denied_mutation_is_still_recorded(tmp_path):
    """A refusal is the security-relevant half of the story. The denial returns
    before the tool body runs, so it needs its own recording point."""
    server, task, _ = _server(tmp_path, permission_mode="read_only")
    mcp = build_mcp(server.config, server)

    result = asyncio.run(mcp.call_tool("set_acceptance_criteria", {
        "task_id": task.id,
        "criteria": [{"text": "pytest passes", "verification_kind": "machine"}],
    }))

    assert "PERMISSION_DENIED" in str(result)
    assert [
        row for row in _audit_rows(server) if row["tool"] == "set_acceptance_criteria"
    ], "a denied lifecycle mutation vanished from the audit log"
    server.tasks.close()


def test_task_id_is_read_from_the_signature_not_sniffed(tmp_path):
    """start_task's first argument is a project PATH. Sniffing the string (or
    assuming argument 0 is always a task id) would file every new task under a
    task_id that is really a directory name."""
    assert _task_id_argument(task_tools.start_task, ("C:/projects/T-shirt", "goal")) is None
    assert _task_id_argument(task_tools.task_status, ("T-abc123",)) == "T-abc123"
    assert _task_id_argument(task_tools.list_tasks, ("new",)) is None


def test_lifecycle_calls_reach_the_live_feed_too(tmp_path):
    """Same recording hooks as the capability path, so the Workbench activity
    view and audit.jsonl cannot disagree about what happened."""
    server, task, _ = _server(tmp_path)
    mcp = build_mcp(server.config, server)

    asyncio.run(mcp.call_tool("task_status", {"task_id": task.id}))

    published = [
        event for event in server.events.since(0)
        if event["data"].get("tool") == "task_status"
    ]
    assert published, "lifecycle call never reached the live event bus"
    server.tasks.close()
