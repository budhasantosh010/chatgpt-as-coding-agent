"""MCP server: registers each pure tool as a thin, typed FastMCP tool.

Each wrapper does four things: resolve the caller's per-session context, enforce
the capability (permission gate), call the pure tool logic, and normalize
expected errors into a readable message the model can act on. Adding a tool =
write the pure fn in ``tools/`` + one wrapper here.
"""

from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .config import Config
from .context import HarnessContext, HarnessServer
from .hooks import ToolCall
from .permissions import action_for, decide as decide_action
from .policy import Capability, Decision
from .scrub import scrub_text
from .security import SecurityError
from .tools import files, git, memory, process, search, shell, skills, workspace, worktree
from .tools import todos as todos_tool
from .tasks import tools as tasktools

# Single source of truth for which capability each tool needs. Tools that change
# state (checkpoints write a git ref; memory/todos write JSON) are mutations, not
# reads, so read_only must deny them. Anything absent defaults to READ.
_TOOL_CAPS: dict[str, Capability] = {
    "create_checkpoint": Capability.WRITE,
    "remember": Capability.WRITE,
    "forget": Capability.WRITE,
    "write_todos": Capability.WRITE,
}


def capability_for(tool: str) -> Capability:
    return _TOOL_CAPS.get(tool, Capability.READ)

_EXPECTED_ERRORS = (
    SecurityError,
    ValueError,
    FileNotFoundError,
    IsADirectoryError,
    NotADirectoryError,
    PermissionError,
    OSError,
)

_INSTRUCTIONS = """\
This server is a local coding harness. You are the coding agent; these tools are \
your hands on the user's machine.

Start every task by calling open_workspace(path) to select the project and get \
oriented (git state, structure, and any AGENTS.md / CLAUDE.md rules — follow \
those rules). After that, paths may be given relative to the workspace.

Typical loop: inspect with read_file / list_dir / glob / grep, snapshot with \
create_checkpoint before risky edits, change code with write_file / edit_file, \
then verify with run_command (tests, build, typecheck). Review with git_diff and \
undo with restore_checkpoint if needed. run_command runs the machine's shell \
(PowerShell on Windows). If a turn ends mid-task, call session_status() next time \
to see what was already done.
"""


def _session_key(ctx: Context | None) -> str:
    """Best-effort per-connection key so concurrent conversations stay isolated.
    Falls back to a single shared 'default' session when the transport provides
    no distinguishing id (harmless for single-user use)."""
    if ctx is None:
        return "default"
    try:
        request = getattr(ctx.request_context, "request", None)
        if request is not None:
            for header in ("mcp-session-id", "x-session-id"):
                value = request.headers.get(header)
                if value:
                    return value
    except Exception:  # noqa: BLE001 - never let key extraction break a tool call
        pass
    return "default"


def _scrub_server(server: HarnessServer, text: str) -> str:
    """Scrub server-scoped tool output (task tools that don't run in a single
    HarnessContext) so they share the same redaction guarantee."""
    if getattr(server.config, "scrub_output", False):
        scrubbed, n = scrub_text(text)
        if n:
            return f"{scrubbed}\n[harness: redacted {n} secret(s) from this output]"
    return text


def _finalize(hc: HarnessContext, text: str) -> str:
    """Last gate every string passes through before leaving the process. Scrubs
    known secret formats even on the error path (the success path also scrubs via
    the post-hook; this guarantees errors are never an exfiltration hole)."""
    cfg = getattr(hc, "config", None)
    if cfg is not None and getattr(cfg, "scrub_output", False):
        scrubbed, n = scrub_text(text)
        if n:
            return f"{scrubbed}\n[harness: redacted {n} secret(s) from this output]"
    return text


def _gate(hc: HarnessContext, capability: Capability, tool: str, command: str | None) -> str | None:
    """Decide whether a call proceeds under the active permission mode, refining
    EXECUTE by classifying the command (auto_workspace lets local commands run
    but asks for network/remote/deploy). Returns None to proceed, or an
    approval-required message string to return to the caller. Raises on DENY."""
    action = action_for(capability, command)
    decision = decide_action(hc.policy.mode, action)
    if decision is Decision.ALLOW:
        return None
    if decision is Decision.DENY:
        raise SecurityError(
            f"'{action.value}' is denied in '{hc.policy.mode}' mode. Only the "
            "operator can change the mode locally."
        )
    # ASK — allow only if the operator has granted a one-shot approval.
    store = getattr(hc, "store", None)
    if store is None or not getattr(hc, "task_id", None):
        raise SecurityError(
            f"'{action.value}' needs approval, but this call has no task_id (start a "
            "task so approvals can be tracked)."
        )
    granted = store.grantable_approval(hc.task_id, action.value)
    if granted:
        store.consume_approval(granted["id"])
        return None
    aid = store.add_approval(hc.task_id, action.value, f"{tool}: {(command or '')[:120]}")
    return (
        f"⏸ APPROVAL REQUIRED — '{action.value}' is not auto-allowed in "
        f"'{hc.policy.mode}' mode.\nThe operator must approve on the machine:\n"
        f"    python -m harness approvals approve {aid}\n"
        f"Then retry the same call. (Deny with: python -m harness approvals deny {aid})"
    )


async def _call(hc: HarnessContext, capability: Capability | None, fn, *args) -> str:
    """Enforce permissions (mode + action class + approvals), run lifecycle hooks
    around the pure tool, and normalize expected errors. The tool name is
    ``fn.__name__`` and the session key is ``hc.key`` — so hooks attach here
    without touching the wrappers. Every return path, including normalized errors
    and approval prompts, goes through scrubbing."""
    hooks = getattr(hc, "hooks", None)
    try:
        if capability is not None:
            command = args[0] if (capability is Capability.EXECUTE and args and isinstance(args[0], str)) else None
            gate = _gate(hc, capability, fn.__name__, command)
            if gate is not None:
                return _finalize(hc, gate)
        if hooks is None:
            return await fn(hc, *args)
        call = ToolCall(tool=fn.__name__, capability=capability, session_key=hc.key, args=args, context=hc)
        await hooks.run_pre(call)  # may raise HookVeto (a SecurityError)
        result = await fn(hc, *args)
        call.result = result if isinstance(result, str) else str(result)
        return await hooks.run_post(call)
    except _EXPECTED_ERRORS as exc:
        return _finalize(hc, f"Error: {exc}")


def build_mcp(config: Config, server: HarnessServer) -> FastMCP:
    mcp = FastMCP(
        name="chatgpt-code-harness",
        instructions=_INSTRUCTIONS,
        stateless_http=config.stateless_http,
        json_response=config.json_response,
        streamable_http_path=config.mcp_path,
        host=config.host,
        port=config.port,
        # The SDK's built-in Host check is exact-match only, so it would reject
        # every *.ts.net Funnel hostname (the pothole Spectre hit). We disable it
        # here and let SecurityMiddleware enforce Host/Origin — it supports the
        # .ts.net wildcard, plus the secret route, bearer token, and rate limit.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    # ---- orientation (READ) ------------------------------------------------

    @mcp.tool()
    async def open_workspace(path: str, task_id: str | None = None, ctx: Context = None) -> str:
        """Open a project directory as the active workspace and return orientation:
        git branch/status/recent commits, detected project type, top-level
        structure, and any AGENTS.md / CLAUDE.md rules. Call this first. The path
        must be inside an approved workspace root."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, workspace.open_workspace, path)

    @mcp.tool()
    async def session_status(task_id: str | None = None, ctx: Context = None) -> str:
        """Show the current workspace's git changes and the recent actions taken
        in this session. Use it to resume a task after a turn ends."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, workspace.session_status)

    @mcp.tool()
    async def read_file(path: str, offset: int | None = None, limit: int | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Read a text file. offset (1-based start line) and limit (line count)
        page through large files. Binary files are not returned."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, files.read_file, path, offset, limit)

    @mcp.tool()
    async def list_dir(path: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """List the entries of a directory (defaults to the active workspace)."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, files.list_dir, path)

    @mcp.tool()
    async def glob(pattern: str, path: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Find files by glob pattern (e.g. '**/*.py'), newest first, relative to
        the workspace or a given path."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, search.glob_files, pattern, path)

    @mcp.tool()
    async def grep(
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        ignore_case: bool = False,
        context: int = 0,
        output_mode: str = "content",
        task_id: str | None = None,
        ctx: Context = None,
    ) -> str:
        """Search file contents with a regex (ripgrep). output_mode: 'content'
        (matching lines, default), 'files_with_matches', or 'count'. Optionally
        filter files with a glob and add context lines."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(
            hc, Capability.READ, search.grep, pattern, path, glob, ignore_case, context, output_mode
        )

    # ---- mutation (WRITE) --------------------------------------------------

    @mcp.tool()
    async def write_file(path: str, content: str, expected_sha: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Create or overwrite a file with the given content. Parent directories
        are created as needed. Pass expected_sha (from the read_file header) to be
        rejected if the file changed since you read it (avoids clobbering)."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.WRITE, files.write_file, path, content, expected_sha)

    @mcp.tool()
    async def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False, expected_sha: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Replace an exact string in a file. old_string must match exactly
        (including whitespace) and be unique unless replace_all=true. Pass
        expected_sha (from read_file) to reject the edit if the file changed."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.WRITE, files.edit_file, path, old_string, new_string, replace_all, expected_sha)

    @mcp.tool()
    async def apply_edits(edits: list, task_id: str | None = None, ctx: Context = None) -> str:
        """Apply many file changes atomically (all-or-nothing, auto rollback on
        failure). Each edit is {path, content} to write, {path, old_string,
        new_string, replace_all?} to edit, or {path, delete:true}. Use for
        multi-file refactors so the tree never ends up half-changed."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.WRITE, files.apply_edits, edits)

    # ---- execution (EXECUTE) -----------------------------------------------

    @mcp.tool()
    async def run_command(command: str, cwd: str | None = None, timeout: int = 120, task_id: str | None = None, ctx: Context = None) -> str:
        """Run a shell command (PowerShell on Windows, bash on POSIX) with the
        workspace as the default working directory. Returns exit code + output.
        Use for tests, builds, git, package managers."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.EXECUTE, shell.run_command, command, cwd, timeout)

    # ---- review + safety net (git) -----------------------------------------

    @mcp.tool()
    async def git_diff(path: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Show the workspace's current git changes (status + diff vs HEAD).
        Optionally limit to a path. Review what changed before committing."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, git.git_diff, path)

    @mcp.tool()
    async def create_checkpoint(label: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Snapshot the whole workspace so it can be restored later. Cheap and
        private (stored in a git ref; does not touch your branch, history, or
        staging). Call before a risky batch of edits."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, capability_for("create_checkpoint"), git.create_checkpoint, label)

    @mcp.tool()
    async def list_checkpoints(task_id: str | None = None, ctx: Context = None) -> str:
        """List snapshots created with create_checkpoint in this workspace."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, git.list_checkpoints)

    @mcp.tool()
    async def restore_checkpoint(checkpoint_id: str, task_id: str | None = None, ctx: Context = None) -> str:
        """Revert the working tree to a checkpoint, including removing files
        added since it was taken. Use it to undo edits that went wrong."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.WRITE, git.restore_checkpoint, checkpoint_id)

    # ---- worktrees (isolation) ---------------------------------------------

    @mcp.tool()
    async def create_worktree(name: str, base: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Create a git worktree on a new branch for isolated work, then
        open_workspace the returned path. Risky changes never touch your main
        checkout. Optionally branch from `base` (a branch/commit)."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.WRITE, worktree.create_worktree, name, base)

    @mcp.tool()
    async def list_worktrees(task_id: str | None = None, ctx: Context = None) -> str:
        """List git worktrees for the current repository."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, worktree.list_worktrees)

    @mcp.tool()
    async def remove_worktree(name: str, force: bool = False, task_id: str | None = None, ctx: Context = None) -> str:
        """Remove a task worktree created with create_worktree. Refuses if it has
        uncommitted changes unless force=true (which discards them)."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.WRITE, worktree.remove_worktree, name, force)

    # ---- memory (READ — harness metadata, safe in any mode) ----------------

    @mcp.tool()
    async def remember(text: str, key: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Save a fact to remember for this workspace across sessions (a decision,
        gotcha, or convention you discovered). Pass a stable key to update an
        existing note instead of adding a new one."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, capability_for("remember"), memory.remember, text, key)

    @mcp.tool()
    async def recall(query: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """List remembered facts for this workspace, optionally filtered by a
        query substring."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, memory.recall, query)

    @mcp.tool()
    async def forget(key: str, task_id: str | None = None, ctx: Context = None) -> str:
        """Delete a remembered fact by its id (shown in recall)."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, capability_for("forget"), memory.forget, key)

    # ---- skills (READ — loadable capability docs) --------------------------

    @mcp.tool()
    async def list_skills(task_id: str | None = None, ctx: Context = None) -> str:
        """List available skills (loadable how-to docs) discovered in the
        workspace and your global skill library, by name and description."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, skills.list_skills)

    @mcp.tool()
    async def load_skill(name: str, task_id: str | None = None, ctx: Context = None) -> str:
        """Load the full content of a skill by name (from list_skills) when you
        need its procedure. Pull skills on demand rather than guessing."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, skills.load_skill, name)

    # ---- background processes (EXECUTE / READ) -----------------------------

    @mcp.tool()
    async def start_process(command: str, cwd: str | None = None, wait: float = 1.0, task_id: str | None = None, ctx: Context = None) -> str:
        """Start a long-running command (dev server, test --watch) in the
        background and return its id + initial output. Poll it with read_process.
        Use this instead of run_command for anything that doesn't exit quickly."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.EXECUTE, process.start_process, command, cwd, wait)

    @mcp.tool()
    async def read_process(process_id: str, wait: float = 0.0, task_id: str | None = None, ctx: Context = None) -> str:
        """Return new output from a background process since the last read.
        Optionally wait a few seconds for more output first."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, process.read_process, process_id, wait)

    @mcp.tool()
    async def write_process(process_id: str, input: str, task_id: str | None = None, ctx: Context = None) -> str:
        """Send a line of input to a background process's stdin."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.EXECUTE, process.write_process, process_id, input)

    @mcp.tool()
    async def stop_process(process_id: str, task_id: str | None = None, ctx: Context = None) -> str:
        """Terminate a background process by id."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.EXECUTE, process.stop_process, process_id)

    @mcp.tool()
    async def list_processes(task_id: str | None = None, ctx: Context = None) -> str:
        """List background processes and their status."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, process.list_processes)

    # ---- planning (READ — harness metadata) --------------------------------

    @mcp.tool()
    async def write_todos(todos: list, task_id: str | None = None, ctx: Context = None) -> str:
        """Set the task plan as a list of steps. Each item is a string, or an
        object {content, status} where status is pending|in_progress|completed.
        Replaces the current list. Use for any multi-step task so it survives
        turn resets."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, capability_for("write_todos"), todos_tool.write_todos, todos)

    @mcp.tool()
    async def list_todos(task_id: str | None = None, ctx: Context = None) -> str:
        """Show the current task plan and how many steps are complete."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, todos_tool.list_todos)

    # ---- tasks (Codex-style engineering units; the isolation handle) -------

    def _task_call(fn, *args) -> str:
        try:
            return _scrub_server(server, fn(server, *args))
        except _EXPECTED_ERRORS as exc:
            return _scrub_server(server, f"Error: {exc}")

    @mcp.tool()
    async def start_task(project_path: str, goal: str, permission_mode: str = "auto_workspace", title: str = "", ctx: Context = None) -> str:
        """Begin a task: bind a workspace + goal + permission mode and get a
        task_id. Pass that task_id to every subsequent tool call so the task's
        work is isolated from other conversations and resumable. permission_mode:
        plan | build_ask | auto_workspace | bypass_sandboxed | full | read_only."""
        return _task_call(tasktools.start_task, project_path, goal, permission_mode, title)

    @mcp.tool()
    async def list_tasks(status: str | None = None, ctx: Context = None) -> str:
        """List tasks (optionally by state: new/planning/implementing/…/completed)."""
        return _task_call(tasktools.list_tasks, status)

    @mcp.tool()
    async def task_status(task_id: str, ctx: Context = None) -> str:
        """Show a task's goal, state, plan, acceptance criteria, changed files,
        and recent events. Use to resume or review."""
        return _task_call(tasktools.task_status, task_id)

    @mcp.tool()
    async def resume_task(task_id: str, ctx: Context = None) -> str:
        """Reload a task's state to continue it in a new conversation."""
        return _task_call(tasktools.resume_task, task_id)

    @mcp.tool()
    async def set_task_goal(task_id: str, goal: str, ctx: Context = None) -> str:
        """Update a task's goal."""
        return _task_call(tasktools.set_task_goal, task_id, goal)

    @mcp.tool()
    async def set_acceptance_criteria(task_id: str, criteria: list, ctx: Context = None) -> str:
        """Set the checklist that defines 'done' for this task (list of strings)."""
        return _task_call(tasktools.set_acceptance_criteria, task_id, criteria)

    @mcp.tool()
    async def advance_task(task_id: str, to_state: str, ctx: Context = None) -> str:
        """Move a task to a new lifecycle state (new→discovering→planning→
        implementing→validating→repairing→review_ready→completed; or blocked)."""
        return _task_call(tasktools.advance_task, task_id, to_state)

    @mcp.tool()
    async def finish_task(task_id: str, result: str = "", ctx: Context = None) -> str:
        """Mark a task completed (must be review_ready first) with a result note."""
        return _task_call(tasktools.finish_task, task_id, result)

    @mcp.tool()
    async def cancel_task(task_id: str, reason: str = "", ctx: Context = None) -> str:
        """Abandon a task, recording why."""
        return _task_call(tasktools.cancel_task, task_id, reason)

    @mcp.tool()
    async def register_project(path: str, name: str = "", ctx: Context = None) -> str:
        """Register a project directory so tasks can be grouped under it."""
        return _task_call(tasktools.register_project, path, name)

    # ---- health (unauthenticated, no secrets) ------------------------------

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request):  # noqa: ANN001
        from starlette.responses import JSONResponse

        return JSONResponse({
            "status": "ok",
            "name": "chatgpt-code-harness",
            "mode": config.mode,
            "sessions": len(server.session_keys),
        })

    return mcp
