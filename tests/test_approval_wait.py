"""Approval wait (first real-user feedback): a call that needs approval holds
the tool call open while the operator clicks Approve/Deny, instead of bouncing
the model back with a retry message (which ended the ChatGPT turn and forced
the user to type "approved" afterwards).

Approve mid-wait  → the call proceeds seamlessly (gate returns None).
Deny mid-wait     → terminal "Error: [APPROVAL_DENIED]" (never cached, no re-ask).
Nobody decides    → the classic APPROVAL REQUIRED retry message after timeout.
"""

from __future__ import annotations

import asyncio

import pytest

from harness.config import Config
from harness.context import HarnessServer
from harness.policy import Capability
from harness.server import _gate_with_wait
from harness.tasks import tools as tasktools


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture()
def ctx(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state", secret_route="x")
    cfg.approval_wait_seconds = 5
    srv = HarnessServer(cfg)
    tid = run(tasktools.start_task(srv, str(ws), "g")).split()[2]
    hc = srv.context_for(tid, "conn")
    yield srv, hc
    srv.tasks.close()


CMD = "my-unknown-tool --flag"


def _decide_soon(srv, status, delay=0.3):
    async def _inner():
        await asyncio.sleep(delay)
        pending = srv.tasks.pending_approvals()
        assert pending, "expected a pending approval to decide"
        srv.tasks.decide_approval(pending[0]["id"], status)
    return _inner


def test_approved_mid_wait_lets_the_call_proceed(ctx):
    srv, hc = ctx

    async def scenario():
        decider = asyncio.ensure_future(_decide_soon(srv, "approved")())
        gate = await _gate_with_wait(hc, Capability.EXECUTE, "run_command", CMD, detail=CMD)
        await decider
        return gate

    assert run(scenario()) is None  # None = proceed; the chat never broke


def test_denied_mid_wait_is_terminal_and_not_a_retry_loop(ctx):
    srv, hc = ctx

    async def scenario():
        decider = asyncio.ensure_future(_decide_soon(srv, "denied")())
        gate = await _gate_with_wait(hc, Capability.EXECUTE, "run_command", CMD, detail=CMD)
        await decider
        return gate

    gate = run(scenario())
    assert gate is not None and gate.startswith("Error: [APPROVAL_DENIED]")
    # Denial must not immediately re-ask: no fresh pending approval afterwards.
    assert srv.tasks.pending_approvals() == []


def test_timeout_returns_the_classic_retry_message(ctx):
    srv, hc = ctx
    srv.config.approval_wait_seconds = 1

    gate = run(_gate_with_wait(hc, Capability.EXECUTE, "run_command", CMD, detail=CMD))
    assert gate is not None and "APPROVAL REQUIRED" in gate
    assert len(srv.tasks.pending_approvals()) == 1  # still waiting for the operator


def test_wait_zero_keeps_the_old_immediate_bounce(ctx):
    srv, hc = ctx
    srv.config.approval_wait_seconds = 0

    gate = run(_gate_with_wait(hc, Capability.EXECUTE, "run_command", CMD, detail=CMD))
    assert gate is not None and "APPROVAL REQUIRED" in gate
