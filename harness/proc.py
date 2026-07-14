"""One async subprocess implementation, shared by every tool that shells out
(run_command, grep, git). Non-blocking so a long command never freezes the
server's event loop.
"""

from __future__ import annotations

import asyncio
import os
import sys


def shell_argv(config_shell: str, command: str) -> list[str]:
    """Argv that runs ``command`` through the host shell.

    Canonical home for this so shell.py, executor.py, and processes.py all agree
    on how a command string becomes a process: an explicit shell if configured,
    else PowerShell on Windows / bash on POSIX.
    """
    if config_shell:
        return [config_shell, "-c", command]
    if sys.platform == "win32":
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    return ["/bin/bash", "-lc", command]


class ProcessResult:
    def __init__(self, returncode: int, stdout: str, stderr: str, timed_out: bool = False):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out

    @property
    def combined(self) -> str:
        out = self.stdout or ""
        if self.stderr:
            out += ("\n" if out and not out.endswith("\n") else "") + self.stderr
        return out


async def run_subprocess(
    argv: list[str],
    *,
    cwd: str | None = None,
    timeout: int = 120,
    encoding: str = "utf-8",
    env: dict[str, str] | None = None,
) -> ProcessResult:
    full_env = {**os.environ, **env} if env else None
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=full_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        return ProcessResult(127, "", f"executable not found: {exc}")

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.communicate()
        return ProcessResult(-1, "", f"timed out after {timeout}s", timed_out=True)

    return ProcessResult(
        proc.returncode if proc.returncode is not None else -1,
        stdout.decode(encoding, "replace"),
        stderr.decode(encoding, "replace"),
    )
