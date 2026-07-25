"""Turn Ledger: the model-published record of a coding conversation.

This is NOT a transcript. The harness never sees the chat — MCP carries tool
calls, not prose — so the only text available is what the model chooses to
hand over. That makes this a *ledger of published turns*, and the naming stays
honest about it everywhere it surfaces.

The asymmetry is deliberate and mirrors effort receipts: the model supplies the
prose (user_request, assistant_response, decisions, next_action); the SERVER
writes turn_id, timestamps, and the tool calls it actually observed. A turn
claiming work the server never saw is visible as such, side by side.

Nothing here may satisfy an acceptance gate, spend a credit, or count as
evidence. Receipts and credits stay server-observed; this stays model-claimed.
The two are stored apart and labelled apart so they can never blur.

Layout — under the state dir so it never pollutes the repo, the same rule
``tools/memory.py`` states for memories:

    tasks/<task_id>/chat/
        turns.jsonl     published turns, append-only
        transcript.md   human-readable mirror
        open.json       the in-flight turn: server observations, unpublished

Honest limit, stated once and repeated in the tool docstring: a conversational
turn that calls no harness tool is invisible here. Asking "why SQLite?" and
getting an answer leaves no trace. This records the coding conversation, not
the whole chat.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from ..session import _now_iso
from ..statefile import locked, read_json, write_json_atomic

# Provenance is a first-class field, never inferred at read time.
OPERATOR_ENTERED = "operator_entered"   # typed by the human into a harness surface
MODEL_REPORTED = "model_reported"       # the human's words, retold by the model
MODEL_PUBLISHED = "model_published"     # the model's answer, as the model published it
MACHINE_OBSERVED = "machine_observed"   # written by the server from what it saw

# Tools that orient rather than work. These must not open a turn: resuming a
# task or reading the ledger would otherwise create an unpublished turn out of
# thin air and trip the gate before any work happened.
_ORIENTATION = frozenset({
    "resume_task", "task_status", "list_tasks", "get_effort_status",
    "publish_turn", "discard_turn", "list_todos", "list_checkpoints",
    "list_worktrees", "list_processes", "mcp_servers", "mcp_tools",
    "session_status", "recall", "list_skills", "health",
})


def chat_dir(state_dir: Path, task_id: str) -> Path:
    return Path(state_dir) / "tasks" / task_id / "chat"


def _open_path(state_dir: Path, task_id: str) -> Path:
    return chat_dir(state_dir, task_id) / "open.json"


def _turns_path(state_dir: Path, task_id: str) -> Path:
    return chat_dir(state_dir, task_id) / "turns.jsonl"


def _transcript_path(state_dir: Path, task_id: str) -> Path:
    return chat_dir(state_dir, task_id) / "transcript.md"


def observe(state_dir: Path, task_id: str, tool: str) -> None:
    """Record that the server saw `tool` run for this task.

    Opens a turn on the first non-orientation call. Best-effort by construction:
    observation must never be able to break a tool call, so every failure here
    is swallowed the same way the audit hook swallows its own.
    """
    if not task_id or tool in _ORIENTATION:
        return
    path = _open_path(state_dir, task_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with locked(path):
            state = read_json(path, None)
            if not state:
                state = {
                    "turn_id": f"tr-{secrets.token_hex(6)}",
                    "opened_at": _now_iso(),
                    "tool_calls": [],
                    "cycles_completed": 0,
                    "provenance": MACHINE_OBSERVED,
                }
            state["tool_calls"].append({"tool": tool, "at": _now_iso()})
            if tool == "complete_cycle":
                state["cycles_completed"] = int(state.get("cycles_completed", 0)) + 1
            write_json_atomic(path, state)
    except OSError:
        pass


def open_turn(state_dir: Path, task_id: str) -> dict | None:
    """The in-flight unpublished turn, or None."""
    return read_json(_open_path(state_dir, task_id), None) or None


def unpublished_work(state_dir: Path, task_id: str) -> int:
    state = open_turn(state_dir, task_id)
    return len(state.get("tool_calls", [])) if state else 0


def crossed_a_turn_boundary(state_dir: Path, task_id: str) -> bool:
    """True when the open turn already closed a cycle.

    The server cannot see turn boundaries — a turn boundary is a user message,
    and no user message ever reaches the harness. A COMPLETED CYCLE is the
    closest observable proxy: it is a self-contained unit of work the model
    declared finished. Opening a second cycle on top of an unpublished one is
    therefore the earliest point where "more work without publishing" is
    provable rather than guessed.

    This is why the gate does not fire on ordinary tool calls: read_file →
    begin_cycle inside a single turn is normal, and blocking it would break
    every honest run to catch a dishonest one.
    """
    state = open_turn(state_dir, task_id)
    return bool(state) and int(state.get("cycles_completed", 0)) > 0


def publish(
    state_dir: Path,
    task_id: str,
    *,
    user_request: str,
    assistant_response: str,
    decisions: list | None = None,
    next_action: str = "",
    request_provenance: str = MODEL_REPORTED,
) -> dict:
    """Close the open turn with the model's account of it.

    Returns the stored record. Raises ValueError if there is nothing to publish,
    so a model cannot manufacture turns that never happened.
    """
    if request_provenance not in (OPERATOR_ENTERED, MODEL_REPORTED):
        raise ValueError(
            "[PROVENANCE_INVALID] request_provenance must be "
            f"{OPERATOR_ENTERED!r} or {MODEL_REPORTED!r}"
        )
    observed = open_turn(state_dir, task_id)
    if not observed:
        raise ValueError(
            "[NO_OPEN_TURN] nothing to publish — the server observed no tool "
            "calls for this task since the last publish"
        )
    record = {
        "turn_id": observed["turn_id"],
        "task_id": task_id,
        "opened_at": observed["opened_at"],
        "published_at": _now_iso(),
        # Model-supplied. Every field carries its own provenance so a reader
        # never has to guess which half of the record to trust.
        "user_request": {"text": user_request, "provenance": request_provenance},
        "assistant_response": {
            "text": assistant_response, "provenance": MODEL_PUBLISHED,
        },
        "decisions": [str(d) for d in (decisions or [])],
        "next_action": next_action,
        # Server-supplied. The model cannot write these.
        "observed": {
            "provenance": MACHINE_OBSERVED,
            "tool_calls": observed.get("tool_calls", []),
            "count": len(observed.get("tool_calls", [])),
            "cycles_completed": int(observed.get("cycles_completed", 0)),
        },
    }
    path = _turns_path(state_dir, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    _append_transcript(state_dir, task_id, record)
    _open_path(state_dir, task_id).unlink(missing_ok=True)
    return record


def discard(state_dir: Path, task_id: str, reason: str) -> dict | None:
    """Abandon the open turn without publishing it.

    The escape hatch: without it a failed publish would lock the task's gates
    forever. The discard is itself written to the ledger, so dropping a turn
    leaves a visible hole rather than a silent one.
    """
    observed = open_turn(state_dir, task_id)
    if not observed:
        return None
    record = {
        "turn_id": observed["turn_id"],
        "task_id": task_id,
        "opened_at": observed["opened_at"],
        "published_at": _now_iso(),
        "discarded": True,
        "discard_reason": reason,
        "observed": {
            "provenance": MACHINE_OBSERVED,
            "tool_calls": observed.get("tool_calls", []),
            "count": len(observed.get("tool_calls", [])),
            "cycles_completed": int(observed.get("cycles_completed", 0)),
        },
    }
    path = _turns_path(state_dir, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    _append_transcript(state_dir, task_id, record)
    _open_path(state_dir, task_id).unlink(missing_ok=True)
    return record


def recent(state_dir: Path, task_id: str, limit: int = 5) -> list[dict]:
    path = _turns_path(state_dir, task_id)
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue  # a torn line must not sink the whole ledger
    return rows[-limit:] if limit > 0 else rows


def _append_transcript(state_dir: Path, task_id: str, record: dict) -> None:
    path = _transcript_path(state_dir, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            f"# Turn ledger — task {task_id}\n\n"
            "Model-published. Not an observed transcript: the harness never "
            "sees the chat, and turns that call no harness tool leave no "
            "trace here. Never usable as acceptance evidence.\n",
            encoding="utf-8",
        )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## Turn {record['turn_id']} — {record['published_at']}\n\n")
        if record.get("discarded"):
            fh.write(f"*Discarded without publishing: {record['discard_reason']}*\n")
        else:
            req = record["user_request"]
            resp = record["assistant_response"]
            fh.write(f"**You** *({req['provenance']})*\n\n{req['text']}\n\n")
            fh.write(f"**ChatGPT** *({resp['provenance']})*\n\n{resp['text']}\n\n")
            if record.get("decisions"):
                fh.write("**Decisions:**\n")
                fh.writelines(f"- {d}\n" for d in record["decisions"])
                fh.write("\n")
            if record.get("next_action"):
                fh.write(f"**Next:** {record['next_action']}\n\n")
        seen = record["observed"]
        tools = ", ".join(sorted({c["tool"] for c in seen["tool_calls"]})) or "none"
        fh.write(f"<sub>Server observed {seen['count']} tool calls: {tools}</sub>\n")
