"""Shell tool: run a command via the session's executor, workspace as default cwd."""

from __future__ import annotations

from pathlib import Path

from ..context import HarnessContext
from ..executor import LocalExecutor
from ..security import assert_command_allowed


async def run_command(
    hc: HarnessContext,
    command: str,
    cwd: str | None = None,
    timeout: int = 120,
) -> str:
    assert_command_allowed(command)

    if cwd is not None:
        work = hc.resolve_read(cwd)
    else:
        work = hc.active_workspace or Path.cwd()
    if not work.is_dir():
        work = work.parent

    timeout = max(1, min(timeout, 600))
    # Route through the configured execution backend (local shell by default,
    # optional Docker sandbox). Fall back to local if none was injected (tests).
    executor = getattr(hc, "executor", None) or LocalExecutor(hc.config.shell)

    result = await executor.run(command, work, timeout)
    if result.timed_out:
        hc.log("run_command", command=command, result=f"timeout after {timeout}s")
        return f"[timed out after {timeout}s]\ncwd: {work}\ncommand: {command}"

    combined = result.combined
    max_chars = hc.config.max_output_chars
    truncated = ""
    if len(combined) > max_chars:
        combined = combined[:max_chars]
        truncated = f"\n[output truncated at {max_chars} chars]"

    hc.log("run_command", command=command, exit_code=result.returncode)
    return f"cwd: {work}\nexit code: {result.returncode}\n--- output ---\n{combined}{truncated}"
