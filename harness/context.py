"""HarnessContext — the per-server runtime object injected into every tool.

No module-level global: it's created once in the composition root (``app.py``),
stored in the MCP server lifespan, and passed to tools explicitly. That keeps
tools unit-testable and leaves the door open to multiple concurrent sessions
later without touching tool code.

Responsibility split:
    * PermissionPolicy (capability/mode gate) is enforced by the server wrapper.
    * HarnessContext enforces the *path* gate: confinement to workspace roots and
      secret-file blocking.
"""

from __future__ import annotations

import os
from pathlib import Path

from .config import Config
from .policy import PermissionPolicy
from .security import (
    SecurityError,
    assert_readable,
    assert_writable,
    is_within,
    resolve_in_roots,
)
from .session import Session


class HarnessContext:
    """Per-session mutable state: which workspace is active, cwd, and the
    workspace journal. One of these exists per connected session, created by
    HarnessServer. Config/policy are shared; workspace/cwd are private to the
    session so concurrent conversations never corrupt each other."""

    def __init__(self, config: Config, key: str = "default", processes=None,
                 executor=None, hooks=None, store=None):
        self.config = config
        self.key = key
        self.task_id: str | None = None
        self.policy = PermissionPolicy(config.mode)
        self.active_workspace: Path | None = None
        self.cwd: Path | None = None
        self.session: Session | None = None
        self.processes = processes  # shared ProcessManager (may be None in tests)
        self.executor = executor    # shared Executor backend (may be None in tests)
        self.hooks = hooks          # shared HookManager (may be None in tests)
        self.store = store          # shared TaskStore (for approvals; may be None)
        self.lsp = None             # shared LSPManager (set by HarnessServer)

    # ---- workspace ----------------------------------------------------------

    def set_workspace(self, path_str: str) -> Path:
        candidate = Path(os.path.realpath(str(Path(path_str).expanduser())))
        if not candidate.exists() or not candidate.is_dir():
            raise SecurityError(
                f"Workspace path does not exist or is not a directory: {candidate}"
            )
        if not any(is_within(candidate, root) for root in self.config.workspace_roots):
            allowed = ", ".join(str(r) for r in self.config.workspace_roots)
            raise SecurityError(
                f"Workspace {candidate} is outside the approved roots. "
                f"Add it to HARNESS_WORKSPACE_ROOTS. Allowed: {allowed}"
            )
        # Flag a workspace switch so open_workspace can warn. Until task_id
        # isolation lands (Phase 1), concurrent conversations share this context,
        # so a switch to a *different* workspace may be another chat colliding.
        prev = self.active_workspace
        self._switched_from = prev if (prev is not None and prev != candidate) else None
        self.active_workspace = candidate
        self.cwd = candidate
        self.session = Session(self.config.state_dir, candidate)
        return candidate

    def require_workspace(self) -> Path:
        if self.active_workspace is None:
            raise SecurityError("No active workspace. Call open_workspace(path) first.")
        return self.active_workspace

    # ---- path gate ----------------------------------------------------------

    def resolve_read(self, path_str: str) -> Path:
        real = resolve_in_roots(path_str, self.config.workspace_roots, base=self.active_workspace)
        assert_readable(real, self.config.secret_globs)
        return real

    def resolve_write(self, path_str: str) -> Path:
        real = resolve_in_roots(path_str, self.config.workspace_roots, base=self.active_workspace)
        assert_writable(real, self.config.secret_globs)
        return real

    # ---- session ------------------------------------------------------------

    def log(self, event_type: str, **data) -> None:
        if self.session is not None:
            self.session.log(event_type, **data)


class HarnessServer:
    """Process-wide shared state: immutable config plus a registry of per-session
    contexts. This is what makes the harness safely concurrent — each session key
    gets its own workspace/cwd/journal, while config is shared read-only.

    A second transport, multiple ChatGPT conversations, or future stateful
    sessions all slot in here without touching tool code.
    """

    def __init__(self, config: Config):
        from .executor import build_executor
        from .federation import FederationManager
        from .hooks import (
            HookManager,
            make_audit_hook,
            make_autocheckpoint_hook,
            make_autoformat_hook,
            make_rules_hook,
            make_scrub_hook,
            make_telemetry_hook,
        )
        from .processes import ProcessManager
        from .tasks.store import TaskStore

        from .events import EventBus, make_event_hook
        from .lsp import LSPManager

        self.config = config
        self.processes = ProcessManager()
        self.executor = build_executor(config)
        self.tasks = TaskStore(config.state_dir / "tasks.db")
        self.federation = FederationManager(config.mcp_servers)
        self.lsp = LSPManager()
        self.hooks = HookManager()
        # Live event bus: cockpit feed (via the optional supervisor sink) +
        # replayable ring buffer. Registered first so every call is seen even if
        # a later pre-hook vetoes it.
        self.events = EventBus(config.event_sink, config.event_token)
        self.hooks.on_pre(make_event_hook(self.events))
        if config.audit_log:
            self.hooks.on_pre(make_audit_hook(config.state_dir / "audit.jsonl"))
        if config.auto_checkpoint:
            self.hooks.on_pre(make_autocheckpoint_hook(config.auto_checkpoint_interval))
        if config.user_hooks:
            from .userhooks import make_user_post_hook, make_user_pre_hook
            self.hooks.on_pre(make_user_pre_hook(config))  # may veto (Phase 7)
        # Telemetry BEFORE scrub so it sees the raw (unredacted) result markers.
        self.hooks.on_post(make_telemetry_hook(self.tasks))
        self.hooks.on_post(make_rules_hook())          # path-scoped rules (6.1)
        if config.auto_format:
            self.hooks.on_post(make_autoformat_hook())  # 6.2
        if config.user_hooks:
            self.hooks.on_post(make_user_post_hook(config))  # Phase 7 post
        # Scrub LAST so it redacts secrets from rule bodies / hook output too.
        if config.scrub_output:
            self.hooks.on_post(make_scrub_hook())
        self._sessions: dict[str, HarnessContext] = {}

    def session_for(self, key: str | None) -> HarnessContext:
        key = key or "default"
        ctx = self._sessions.get(key)
        if ctx is None:
            ctx = HarnessContext(
                self.config, key=key, processes=self.processes,
                executor=self.executor, hooks=self.hooks, store=self.tasks,
            )
            ctx.lsp = self.lsp
            # The no-task fallback is a SHARED session (stateless HTTP can't tell
            # conversations apart), so it must not inherit the operator's mode.
            # Default read_only: reads work, mutations require starting a task.
            ctx.policy = PermissionPolicy(self.config.no_task_mode)
            self._sessions[key] = ctx
        return ctx

    def context_for(self, task_id: str | None, session_key: str) -> HarnessContext:
        """Resolve the context a tool call runs in. With an explicit task_id the
        context is bound to that task (its workspace + permission mode) and keyed
        by the task — so two conversations with different tasks are isolated. This
        is the fix for the shared-'default' collision. Without a task_id, fall
        back to the per-connection session (the legacy, non-isolated path)."""
        if not task_id:
            return self.session_for(session_key)
        key = f"task:{task_id}"
        ctx = self._sessions.get(key)
        if ctx is None:
            ctx = HarnessContext(
                self.config, key=key, processes=self.processes,
                executor=self.executor, hooks=self.hooks, store=self.tasks,
            )
            ctx.lsp = self.lsp
            self._sessions[key] = ctx
        # (Re)bind to the task's current workspace + permission mode each call, so
        # a resumed task restores its state even after a restart.
        task = self.tasks.get_task(task_id)
        if task is None:
            raise SecurityError(f"Unknown task_id {task_id!r}. Use start_task or list_tasks.")
        # Terminal tasks are frozen: a completed/cancelled/failed task must not
        # keep mutating the workspace. (task_status / resume_task stay readable —
        # they are server-scoped and don't come through here.)
        from .tasks.model import _TERMINAL

        if task.status in _TERMINAL:
            raise SecurityError(
                f"Task {task_id} is {task.status.value} and read-only. Start a new "
                "task (start_task) to continue working, or resume a non-terminal one."
            )
        ctx.task_id = task_id
        # The ceiling is enforced HERE, not just in start_task, so it is
        # authoritative over legacy task rows, direct DB edits, and subtask
        # inheritance. Only operator elevation (local CLI) rides above it.
        from .policy import effective_mode

        mode = effective_mode(
            task.permission_mode,
            operator_elevated=task.operator_elevated,
            ceiling=self.config.max_mode,
            sandbox=self.config.sandbox,
        )
        if mode != task.permission_mode and getattr(ctx, "_clamp_logged", None) != mode:
            ctx._clamp_logged = mode  # log the clamp once per context, not per call
            self.tasks.add_event(task_id, "mode_clamped",
                                 stored=task.permission_mode, effective=mode)
        ctx.policy = PermissionPolicy(mode)
        active = task.worktree_path or task.workspace_path
        if str(getattr(ctx, "active_workspace", "")) != str(active):
            ctx.set_workspace(str(active))
        return ctx

    @property
    def session_keys(self) -> list[str]:
        return list(self._sessions)
