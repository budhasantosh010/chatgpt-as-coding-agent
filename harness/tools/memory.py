"""Model-writable memory: facts the agent chooses to remember across sessions.

Distinct from two neighbors:
  * AGENTS.md / CLAUDE.md  = user-authored project rules (read on open_workspace).
  * the session journal     = automatic event log for resume.
Memory is what the *agent* deliberately saves — decisions, gotchas, conventions
it discovered — scoped to the workspace and stored in the harness state dir so it
never pollutes the repo.
"""

from __future__ import annotations

import json
import re

from ..context import HarnessContext
from ..session import _now_iso


def _mem_path(hc: HarnessContext):
    hc.require_workspace()
    assert hc.session is not None
    return hc.session.dir / "memory.json"


def load_memories(hc: HarnessContext) -> list[dict]:
    p = _mem_path(hc)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []


def _save(hc: HarnessContext, items: list[dict]) -> None:
    _mem_path(hc).write_text(json.dumps(items, indent=2), encoding="utf-8")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "note"


async def remember(hc: HarnessContext, text: str, key: str | None = None) -> str:
    hc.require_workspace()
    if not text or not text.strip():
        raise ValueError("Cannot remember empty text.")
    items = load_memories(hc)
    mem_id = _slug(key) if key else None

    if mem_id:
        for item in items:
            if item["id"] == mem_id:
                item["text"] = text
                item["created"] = _now_iso()
                _save(hc, items)
                hc.log("remember", id=mem_id, updated=True)
                return f"Updated memory '{mem_id}'."
    if not mem_id:
        mem_id = f"m{len(items) + 1}"

    items.append({"id": mem_id, "text": text, "created": _now_iso()})
    _save(hc, items)
    hc.log("remember", id=mem_id)
    return f"Saved memory '{mem_id}'."


async def recall(hc: HarnessContext, query: str | None = None) -> str:
    hc.require_workspace()
    items = load_memories(hc)
    if query:
        q = query.lower()
        items = [it for it in items if q in it["text"].lower() or q in it["id"].lower()]
    if not items:
        return (
            f"No memories matching {query!r}." if query
            else "No memories yet. Use remember(text) to save one."
        )
    return "# Memories\n" + "\n".join(f"- [{it['id']}] {it['text']}" for it in items)


async def forget(hc: HarnessContext, key: str) -> str:
    hc.require_workspace()
    items = load_memories(hc)
    kept = [it for it in items if it["id"] != key]
    if len(kept) == len(items):
        return f"No memory with id {key!r}. Use recall() to list ids."
    _save(hc, kept)
    hc.log("forget", id=key)
    return f"Forgot memory {key!r}."
