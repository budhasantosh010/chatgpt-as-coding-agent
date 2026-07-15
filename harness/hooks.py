"""Tool lifecycle hooks: observe, veto, or transform every tool call.

This is the extensibility backbone. Cross-cutting concerns — audit logging,
output scrubbing, and future policies like approvals or per-tool rate limits —
attach here as hooks instead of being threaded through all ~30 tool wrappers.
Adding such a policy becomes "register a hook"; tool code never changes.

Design:
    * ``pre`` hooks run before the tool. A pre-hook may raise :class:`HookVeto`
      to block the call with a message the model sees.
    * ``post`` hooks run after the tool and may return a replacement string to
      transform the output (e.g. redaction). Returning ``None`` leaves it as-is.

Hooks may be sync or async. One :class:`HookManager` lives on the server and is
shared by every session, so a hook sees the whole machine's activity.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .policy import Capability
from .security import SecurityError


@dataclass
class ToolCall:
    """Everything a hook may inspect about one tool invocation."""

    tool: str
    capability: Optional[Capability]
    session_key: str
    args: tuple = ()
    result: Optional[str] = None  # populated for post hooks
    context: object = None  # the HarnessContext (so hooks can act on the session)
    meta: dict = field(default_factory=dict)


class HookVeto(SecurityError):
    """Raised by a pre-hook to block a tool call.

    Subclasses SecurityError so the server's existing error normalization turns
    it into a readable ``Error: ...`` message for the model without special
    casing.
    """


PreHook = Callable[[ToolCall], "None | Awaitable[None]"]
PostHook = Callable[[ToolCall], "Optional[str] | Awaitable[Optional[str]]"]


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


class HookManager:
    """Runs registered hooks around each tool call. One instance per server."""

    def __init__(self):
        self._pre: list[PreHook] = []
        self._post: list[PostHook] = []

    def on_pre(self, hook: PreHook) -> None:
        self._pre.append(hook)

    def on_post(self, hook: PostHook) -> None:
        self._post.append(hook)

    async def run_pre(self, call: ToolCall) -> None:
        for hook in self._pre:
            await _maybe_await(hook(call))

    async def run_post(self, call: ToolCall) -> str:
        """Run post hooks in registration order, threading each hook's output
        into the next. Returns the final (possibly transformed) result string."""
        result = call.result or ""
        for hook in self._post:
            call.result = result
            transformed = await _maybe_await(hook(call))
            if transformed is not None:
                result = transformed
        return result


# ---- built-in hooks --------------------------------------------------------


def make_audit_hook(audit_path: Path) -> PreHook:
    """Pre-hook: append one line per tool call to a single audit log, so there
    is a durable record of everything ChatGPT did on the machine (across all
    sessions), independent of the per-workspace journals."""
    from .session import _now_iso

    audit_path = Path(audit_path)

    def _audit(call: ToolCall) -> None:
        record = {
            "time": _now_iso(),
            "session": call.session_key,
            "tool": call.tool,
            "capability": call.capability.value if call.capability else None,
        }
        try:
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            with audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # auditing must never break a tool call

    return _audit


def make_autocheckpoint_hook(min_interval: float = 60.0) -> PreHook:
    """Pre-hook: snapshot the workspace before a mutation, so there is always a
    recent restore point even if the model forgets to checkpoint. Fires before
    WRITE *and* EXECUTE (a shell command can mutate files too). Debounced — at
    most one auto-checkpoint per ``min_interval`` seconds per workspace — and
    the debounce resets on a workspace switch so a new workspace always gets a
    fresh pre-batch snapshot. Failures are logged, never silent."""
    import time

    from .policy import Capability

    async def _auto(call: ToolCall) -> None:
        if call.capability not in (Capability.WRITE, Capability.EXECUTE):
            return
        hc = call.context
        if hc is None or getattr(hc, "active_workspace", None) is None:
            return
        now = time.monotonic()
        last = getattr(hc, "_last_auto_cp", None)
        last_ws = getattr(hc, "_last_auto_cp_ws", None)
        same_ws = last_ws == str(hc.active_workspace)
        if last is not None and same_ws and (now - last) < min_interval:
            return
        hc._last_auto_cp = now
        hc._last_auto_cp_ws = str(hc.active_workspace)
        try:
            from .tools import git as git_tool
            await git_tool.create_checkpoint(hc, "auto (pre-edit)")
        except Exception as exc:  # noqa: BLE001 - must not block the edit, but never silent
            call.meta["autocheckpoint_failed"] = str(exc)
            try:
                hc.log("autocheckpoint_failed", error=str(exc)[:200])
            except Exception:  # noqa: BLE001
                pass

    return _auto


def make_telemetry_hook(store) -> PostHook:
    """Post-hook: populate the Task record from what tools ACTUALLY did, so
    task_status shows real changed files / commands / test results instead of
    permanently-empty fields (audit I2). Best-effort — telemetry must never
    break or slow a tool call."""
    import re

    _WRITE_TOOLS = {"write_file", "edit_file", "apply_patch", "notebook_edit"}
    _TEST_PAT = re.compile(
        r"\b(pytest|npm\s+(run\s+)?test|yarn\s+test|pnpm\s+test|cargo\s+test|"
        r"go\s+test|jest|vitest|unittest|tox)\b", re.I,
    )
    _CAP = 100  # keep task blobs bounded

    def _telemetry(call: ToolCall) -> None:
        try:
            hc = call.context
            tid = getattr(hc, "task_id", None)
            if not tid or store is None:
                return
            result = call.result or ""
            if result.startswith("Error:") or "APPROVAL REQUIRED" in result:
                return  # only record work that actually happened
            task = store.get_task(tid)
            if task is None:
                return
            tool, args = call.tool, (call.args or ())
            dirty = False
            if tool in _WRITE_TOOLS and args and isinstance(args[0], str):
                if args[0] not in task.changed_files:
                    task.changed_files.append(args[0])
                    dirty = True
            elif tool == "apply_edits" and args and isinstance(args[0], list):
                for e in args[0]:
                    p = e.get("path") if isinstance(e, dict) else None
                    if p and p not in task.changed_files:
                        task.changed_files.append(p)
                        dirty = True
            elif tool in ("run_command", "start_process") and args and isinstance(args[0], str):
                cmd = args[0]
                m = re.search(r"exit code:\s*(-?\d+)", result)
                entry = {"command": cmd[:200], "exit": int(m.group(1)) if m else None}
                task.commands = (task.commands + [entry])[-_CAP:]
                dirty = True
                if _TEST_PAT.search(cmd):
                    task.test_results = (task.test_results + [
                        {"command": cmd[:200], "passed": bool(m and m.group(1) == "0")}
                    ])[-_CAP:]
            elif tool == "create_checkpoint":
                m = re.search(r"Checkpoint (\S+) created", result)
                if m and m.group(1) not in task.checkpoints:
                    task.checkpoints.append(m.group(1))
                    dirty = True
            elif tool == "diagnostics" and args is not None:
                task.test_results = (task.test_results + [
                    {"command": "diagnostics_check",
                     "passed": "no issues" in result.lower() or "0 error" in result.lower()}
                ])[-_CAP:]
                dirty = True
            elif tool == "write_todos" and args and isinstance(args[0], list):
                task.plan = [
                    (t.get("content", "") if isinstance(t, dict) else str(t))[:200]
                    for t in args[0]
                ][:_CAP]
                dirty = True
            if dirty:
                task.changed_files = task.changed_files[-_CAP:]
                store.save_task(task)
        except Exception:  # noqa: BLE001 - telemetry must never break a tool call
            pass

    return _telemetry


def make_scrub_hook() -> PostHook:
    """Post-hook: redact known secret formats from tool output before it leaves
    the machine. Returns None (no change) when nothing matched."""
    from .scrub import scrub_text

    def _scrub(call: ToolCall) -> Optional[str]:
        scrubbed, n = scrub_text(call.result or "")
        if n:
            return f"{scrubbed}\n[harness: redacted {n} secret(s) from this output]"
        return None

    return _scrub
