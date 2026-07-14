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
    recent restore point even if the model forgets to checkpoint. Debounced —
    at most one auto-checkpoint per ``min_interval`` seconds per session — so a
    burst of edits is captured as one pre-batch state, not spammed."""
    import time

    from .policy import Capability

    async def _auto(call: ToolCall) -> None:
        if call.capability is not Capability.WRITE:
            return
        hc = call.context
        if hc is None or getattr(hc, "active_workspace", None) is None:
            return
        now = time.monotonic()
        last = getattr(hc, "_last_auto_cp", None)
        if last is not None and (now - last) < min_interval:
            return
        hc._last_auto_cp = now
        try:
            from .tools import git as git_tool
            await git_tool.create_checkpoint(hc, "auto (pre-edit)")
        except Exception:  # noqa: BLE001 - a checkpoint failure must not block the edit
            pass

    return _auto


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
