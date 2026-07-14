"""Tools for long-running processes: start / read / write / stop / list.

Wraps the shared ProcessManager. Commands run in the configured shell with the
workspace as cwd, subject to the same destructive-command guard as run_command.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..context import HarnessContext
from ..security import assert_command_allowed
from .shell import _shell_argv


def _require_manager(hc: HarnessContext):
    if hc.processes is None:
        raise ValueError("Process manager is unavailable.")
    return hc.processes


def _status_line(mp) -> str:
    rc = "" if mp.returncode is None else f" (exit {mp.returncode})"
    return f"[{mp.id}] {mp.status}{rc}  {mp.command}"


async def start_process(hc: HarnessContext, command: str, cwd: str | None = None, wait: float = 1.0) -> str:
    mgr = _require_manager(hc)
    assert_command_allowed(command)
    work = hc.resolve_read(cwd) if cwd is not None else (hc.active_workspace or Path.cwd())
    if not work.is_dir():
        work = work.parent

    argv = _shell_argv(hc.config.shell, command)
    mp = await mgr.start(command, argv, str(work))
    hc.log("start_process", id=mp.id, command=command)

    await asyncio.sleep(max(0.0, min(wait, 10.0)))
    initial = mp.snapshot_new()
    header = f"Started {mp.id} in {work} — status {mp.status}\n"
    body = f"--- initial output ---\n{initial}" if initial.strip() else "(no output yet — poll with read_process)"
    return header + body


async def read_process(hc: HarnessContext, process_id: str, wait: float = 0.0) -> str:
    mgr = _require_manager(hc)
    mp = mgr.get(process_id)
    if mp is None:
        return f"Unknown process {process_id!r}. Use list_processes."
    if wait and wait > 0:
        await asyncio.sleep(min(wait, 30.0))
    new = mp.snapshot_new()
    max_chars = hc.config.max_output_chars
    if len(new) > max_chars:
        new = new[-max_chars:]
    footer = f"\n[{mp.status}" + ("" if mp.returncode is None else f", exit {mp.returncode}") + "]"
    return (new if new.strip() else "(no new output)") + footer


async def write_process(hc: HarnessContext, process_id: str, input: str) -> str:
    mgr = _require_manager(hc)
    mp = mgr.get(process_id)
    if mp is None:
        return f"Unknown process {process_id!r}."
    await mgr.write(mp, input)
    hc.log("write_process", id=process_id)
    return f"Sent input to {process_id}."


async def stop_process(hc: HarnessContext, process_id: str) -> str:
    mgr = _require_manager(hc)
    mp = mgr.get(process_id)
    if mp is None:
        return f"Unknown process {process_id!r}."
    await mgr.stop(mp)
    hc.log("stop_process", id=process_id)
    return f"Stopped {process_id} (exit {mp.returncode})."


async def list_processes(hc: HarnessContext) -> str:
    mgr = _require_manager(hc)
    procs = mgr.list()
    if not procs:
        return "No background processes. Start one with start_process."
    return "# Background processes\n" + "\n".join(_status_line(mp) for mp in procs)
