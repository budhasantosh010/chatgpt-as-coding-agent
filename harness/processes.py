"""Background process manager: keep long-running commands (dev servers, watchers)
alive across tool calls, buffering their output so it can be polled incrementally.
"""

from __future__ import annotations

import asyncio

_BUFFER_CAP = 1_000_000  # chars of output retained per process


class ManagedProcess:
    def __init__(self, proc_id: str, command: str, cwd: str, proc: asyncio.subprocess.Process,
                 owner: str = "default"):
        self.id = proc_id
        self.command = command
        self.cwd = cwd
        self.owner = owner  # session/task key; only the owner may read/write/stop it
        self.proc = proc
        self.buffer = ""
        self.read_pos = 0
        self.status = "running"
        self.returncode: int | None = None
        self._reader: asyncio.Task | None = None

    def snapshot_new(self) -> str:
        chunk = self.buffer[self.read_pos :]
        self.read_pos = len(self.buffer)
        return chunk


class ProcessManager:
    def __init__(self):
        self._procs: dict[str, ManagedProcess] = {}
        self._counter = 0

    async def start(self, command: str, argv: list[str], cwd: str,
                    owner: str = "default", env: dict | None = None) -> ManagedProcess:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.PIPE,
        )
        self._counter += 1
        mp = ManagedProcess(f"p{self._counter}", command, cwd, proc, owner=owner)
        self._procs[mp.id] = mp
        mp._reader = asyncio.create_task(self._drain(mp))
        return mp

    async def _drain(self, mp: ManagedProcess) -> None:
        try:
            if mp.proc.stdout is not None:
                while True:
                    chunk = await mp.proc.stdout.read(4096)
                    if not chunk:
                        break
                    mp.buffer += chunk.decode("utf-8", "replace")
                    if len(mp.buffer) > _BUFFER_CAP:
                        overflow = len(mp.buffer) - _BUFFER_CAP
                        mp.buffer = mp.buffer[overflow:]
                        mp.read_pos = max(0, mp.read_pos - overflow)
        except Exception:  # noqa: BLE001 - a read error must not strand status
            pass
        finally:
            try:
                await mp.proc.wait()
            except Exception:  # noqa: BLE001
                pass
            mp.returncode = mp.proc.returncode
            if mp.status == "running":
                mp.status = "exited"

    def get(self, proc_id: str, owner: str | None = None) -> ManagedProcess | None:
        mp = self._procs.get(proc_id)
        if mp is None:
            return None
        if owner is not None and mp.owner != owner:
            return None  # not yours — as if it doesn't exist
        return mp

    def list(self, owner: str | None = None) -> list[ManagedProcess]:
        return [mp for mp in self._procs.values() if owner is None or mp.owner == owner]

    async def write(self, mp: ManagedProcess, text: str) -> None:
        if mp.proc.stdin is None or mp.proc.returncode is not None:
            raise ValueError("Process is not accepting input.")
        if not text.endswith("\n"):
            text += "\n"
        mp.proc.stdin.write(text.encode("utf-8"))
        await mp.proc.stdin.drain()

    async def stop(self, mp: ManagedProcess) -> None:
        if mp.proc.returncode is None:
            try:
                mp.proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(mp.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                mp.proc.kill()
                await mp.proc.wait()
        mp.status = "stopped"
        mp.returncode = mp.proc.returncode

    async def shutdown_all(self) -> None:
        for mp in list(self._procs.values()):
            await self.stop(mp)
