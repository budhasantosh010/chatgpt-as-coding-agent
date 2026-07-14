from __future__ import annotations

import asyncio

from harness.tools import memory


def run(coro):
    return asyncio.run(coro)


def test_remember_and_recall(hc):
    run(memory.remember(hc, "Timeline uses milliseconds internally"))
    run(memory.remember(hc, "Run npm run typecheck before finishing"))
    out = run(memory.recall(hc))
    assert "milliseconds" in out and "typecheck" in out


def test_recall_filter(hc):
    run(memory.remember(hc, "Uses Vitest for tests"))
    run(memory.remember(hc, "Prettier with 2-space indent"))
    out = run(memory.recall(hc, "vitest"))
    assert "Vitest" in out and "Prettier" not in out


def test_remember_with_key_updates(hc):
    run(memory.remember(hc, "old value", key="db"))
    run(memory.remember(hc, "new value", key="db"))
    out = run(memory.recall(hc))
    assert "new value" in out and "old value" not in out
    assert out.count("[db]") == 1


def test_forget(hc):
    run(memory.remember(hc, "temporary", key="temp"))
    run(memory.forget(hc, "temp"))
    out = run(memory.recall(hc))
    assert "temporary" not in out


def test_forget_unknown(hc):
    out = run(memory.forget(hc, "nope"))
    assert "No memory" in out
