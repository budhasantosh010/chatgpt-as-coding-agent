"""Shell tool: run a command in the configured shell, workspace as default cwd."""

from __future__ import annotations

import sys
from pathlib import Path

from ..context import HarnessContext
from ..proc import run_subprocess
from ..security import assert_command_allowed


def _shell_argv(config_shell: str, command: str) -> list[str]:
    if config_shell:
        return [config_shell, "-c", command]
    if sys.platform == "win32":
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    return ["/bin/bash", "-lc", command]


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

    argv = _shell_argv(hc.config.shell, command)
    timeout = max(1, min(timeout, 600))

    result = await run_subprocess(argv, cwd=str(work), timeout=timeout)
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
