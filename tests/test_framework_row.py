"""Phase 6: explicit AOCS routing with a visible missing-record nag."""

import asyncio

from harness.config import Config
from harness.context import HarnessServer
from harness.server import build_mcp
from harness.tasks import tools as task_tools
from harness.tasks.contracts import RunContract


def _server(tmp_path, framework="aocs_omega"):
    workspace = tmp_path / "project"
    workspace.mkdir()
    server = HarnessServer(Config(
        workspace_roots=[tmp_path], state_dir=tmp_path / "state", secret_route="r"
    ))
    project = server.tasks.register_project(str(workspace), "Project")
    task = server.tasks.create_task(project, str(workspace), goal="framework")
    linked = server.tasks.confirm_run_contract(task.id, RunContract.confirmed(
        task_type="plan", effort_level="off", credit_ceiling=0,
        candidate_count=0, machine_concurrency=1, model_concurrency=1,
        framework=framework, max_loops=0,
    ))
    return server, linked


def test_declared_framework_is_visible_until_routing_is_recorded(tmp_path):
    server, task = _server(tmp_path)
    assert "FRAMEWORK: declared but unrecorded" in task_tools.get_effort_status(server, task.id)

    result = task_tools.record_framework_routing(
        server, task.id, ["decomposition", "red-team"], ["multi-model"], "one model"
    )

    assert "recorded" in result.lower()
    assert "FRAMEWORK: recorded" in task_tools.get_effort_status(server, task.id)


def test_resume_teaches_full_skill_loading_and_routing_call(tmp_path):
    server, task = _server(tmp_path)

    output = task_tools.resume_task(server, task.id)

    assert "my-aocs-omega" in output
    assert "IN FULL" in output
    assert "record_framework_routing" in output


def test_framework_off_needs_no_routing_and_rejects_false_record(tmp_path):
    server, task = _server(tmp_path, framework="none")

    assert "declared but unrecorded" not in task_tools.get_effort_status(server, task.id)
    output = task_tools.record_framework_routing(server, task.id, ["x"], [], "reason")

    assert "FRAMEWORK_OFF" in output


def test_framework_routing_is_exposed_as_mcp_tool(tmp_path):
    server, _ = _server(tmp_path)
    names = {tool.name for tool in asyncio.run(build_mcp(server.config, server).list_tools())}
    assert "record_framework_routing" in names
