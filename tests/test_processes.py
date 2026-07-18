"""Background process manager: start, capture output, and stop."""

from __future__ import annotations

import asyncio
import sys

from harness.processes import ProcessManager


def run(coro):
    return asyncio.run(coro)


def test_start_captures_output_and_exits():
    async def scenario():
        mgr = ProcessManager()
        mp = await mgr.start(
            "print hi",
            [sys.executable, "-c", "print('hello-from-proc')"],
            cwd=".",
        )
        # Wait for it to finish and its reader to drain.
        for _ in range(50):
            if mp.status == "exited":
                break
            await asyncio.sleep(0.1)
        return mp

    mp = run(scenario())
    assert "hello-from-proc" in mp.buffer
    assert mp.status == "exited"
    assert mp.returncode == 0


def test_incremental_read_advances_cursor():
    async def scenario():
        mgr = ProcessManager()
        mp = await mgr.start("echo", [sys.executable, "-c", "print('abc')"], cwd=".")
        for _ in range(50):
            if mp.status == "exited":
                break
            await asyncio.sleep(0.1)
        first = mp.snapshot_new()
        second = mp.snapshot_new()
        return first, second

    first, second = run(scenario())
    assert "abc" in first
    assert second == ""  # already consumed


def test_stop_long_running_process():
    async def scenario():
        mgr = ProcessManager()
        mp = await mgr.start(
            "sleep loop",
            [sys.executable, "-c", "import time; time.sleep(9999)"],
            cwd=".",
        )
        await asyncio.sleep(0.3)
        assert mp.status == "running"
        await mgr.stop(mp)
        return mp

    mp = run(scenario())
    assert mp.status == "stopped"
    assert mp.returncode is not None


def test_list_and_get():
    async def scenario():
        mgr = ProcessManager()
        mp = await mgr.start("x", [sys.executable, "-c", "pass"], cwd=".")
        return mgr.get(mp.id), mgr.list()

    got, listed = run(scenario())
    assert got is not None and len(listed) == 1


def test_random_ids_and_atomic_group_limit():
    async def scenario():
        mgr = ProcessManager()
        first = await mgr.start(
            "wait", [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=".", group="contract", group_limit=1,
        )
        try:
            try:
                await mgr.start(
                    "wait2", [sys.executable, "-c", "import time; time.sleep(30)"],
                    cwd=".", group="contract", group_limit=1,
                )
            except ValueError as exc:
                error = str(exc)
            else:
                error = ""
        finally:
            await mgr.stop(first)
        return first.id, error

    proc_id, error = run(scenario())
    assert proc_id.startswith("px-") and proc_id != "px-1"
    assert "MACHINE_CONCURRENCY" in error
