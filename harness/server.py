"""MCP server: registers each pure tool as a thin, typed FastMCP tool.

Each wrapper does four things: resolve the caller's per-session context, enforce
the capability (permission gate), call the pure tool logic, and normalize
expected errors into a readable message the model can act on. Adding a tool =
write the pure fn in ``tools/`` + one wrapper here.
"""

from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP, Image
from mcp.server.transport_security import TransportSecuritySettings

from .config import Config
from .context import HarnessContext, HarnessServer
from .hooks import ToolCall
from .permissions import Action, action_for, decide as decide_action
from .policy import Capability, Decision
from .scrub import scrub_text
from .security import SecurityError
from .tools import (
    codeintel, diagnostics, files, git, images, memory, notebook, process,
    repomap, search, shell, skills, vcs, workspace, worktree,
)
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
    # diagnostics_check EXECUTES the project's checker (tsc/eslint/cargo…), and
    # some checkers run project-controlled code (cargo build scripts). Plan mode
    # must not execute — it's an EXECUTE tool, not a read.
    "diagnostics_check": Capability.EXECUTE,
}


def capability_for(tool: str) -> Capability:
    return _TOOL_CAPS.get(tool, Capability.READ)


def _task_mutation_denial(server: HarnessServer, task_id: str) -> str | None:
    """Deny contracted state changes for a task whose ceiling is read-only."""
    task = server.tasks.get_task(task_id)
    if task is not None and task.permission_mode == "read_only":
        return (
            "Error: [PERMISSION_DENIED] contracted state changes require "
            "plan mode or above"
        )
    return None

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


def _request_hash(task_id: str, tool: str, action: str, detail: str) -> str:
    """Bind an approval to the exact request: task + tool + action + normalized
    arguments. An identical retry matches; anything else re-asks."""
    import hashlib

    norm = " ".join((detail or "").split())  # collapse whitespace
    return hashlib.sha256(f"{task_id}\0{tool}\0{action}\0{norm}".encode()).hexdigest()


def _gate(hc: HarnessContext, capability: Capability | None, tool: str, command: str | None,
          action=None, detail: str | None = None) -> str | None:
    """Decide whether a call proceeds under the active permission mode, refining
    EXECUTE by classifying the command (auto_workspace lets local commands run
    but asks for network/remote/deploy). Returns None to proceed, or an
    approval-required message string to return to the caller. Raises on DENY.
    Pass `action` explicitly for tools whose risk isn't captured by capability +
    command classification (e.g. federation's EXTERNAL_CALL)."""
    if action is None:
        action = action_for(capability, command)
    arbitrary = getattr(getattr(hc, "config", None), "arbitrary_commands", "allow")
    decision = decide_action(hc.policy.mode, action, arbitrary)
    if decision is Decision.ALLOW:
        return None
    if decision is Decision.DENY:
        hint = ""
        if not getattr(hc, "task_id", None):
            hint = (
                " You are in the shared no-task session, which is "
                f"'{hc.policy.mode}'. Call start_task(project_path, goal) and "
                "pass its task_id to every tool call to enable writes/commands."
            )
        raise SecurityError(
            f"'{action.value}' is denied in '{hc.policy.mode}' mode. Only the "
            "operator can change the mode locally." + hint
        )
    # ASK — allow only if the operator has granted a one-shot approval, or has
    # REMEMBERED this exact command for this project (checklist 0.7). The
    # remembered list lives in the state dir (operator-writable only).
    store = getattr(hc, "store", None)
    if action is Action.COMMAND_ARBITRARY and command:
        from . import allowlist

        workspaces = [getattr(hc, "active_workspace", None)]
        if store is not None and getattr(hc, "task_id", None):
            t = store.get_task(hc.task_id)
            if t is not None:
                workspaces += [t.workspace_path, t.worktree_path]
        if allowlist.is_allowed(hc.config.state_dir, workspaces, command):
            return None
    if store is None or not getattr(hc, "task_id", None):
        raise SecurityError(
            f"'{action.value}' needs approval, but this call has no task_id (start a "
            "task so approvals can be tracked)."
        )
    request = detail if detail is not None else (command or "")
    rhash = _request_hash(hc.task_id, tool, action.value, request)
    granted = store.grantable_approval(hc.task_id, action.value, rhash)
    if granted:
        store.consume_approval(granted["id"])
        return None
    # Full request text (not truncated): `approvals approve --remember` needs
    # the exact command to persist it to the per-project allowlist.
    aid = store.add_approval(hc.task_id, action.value, f"{tool}: {request}", rhash)
    return (
        f"⏸ APPROVAL REQUIRED — '{action.value}' is not auto-allowed in "
        f"'{hc.policy.mode}' mode.\nThe operator must approve on the machine:\n"
        f"    python -m harness approvals approve {aid}\n"
        f"Then retry the same call. (Deny with: python -m harness approvals deny {aid})"
    )


def _pending_approval_id(message: str) -> str | None:
    if "approvals approve " not in message:
        return None
    return message.split("approvals approve ", 1)[1].split()[0]


async def _gate_with_wait(hc: HarnessContext, capability: Capability | None, tool: str,
                          command: str | None, detail: str | None = None) -> str | None:
    """_gate, but instead of bouncing the model straight back with a retry
    message, hold the tool call open (bounded by approval_wait_seconds) while
    the operator clicks Approve/Deny in the Workbench or CLI. Approve → the
    call proceeds as if it had always been allowed (the chat never breaks).
    Deny → a terminal error the model must not retry (starts with "Error:" so
    idempotency never caches it). Timeout → the classic retry message."""
    import asyncio
    import time as _time

    message = _gate(hc, capability, tool, command, detail=detail)
    if message is None or "APPROVAL REQUIRED" not in message:
        return message
    wait = int(getattr(getattr(hc, "config", None), "approval_wait_seconds", 0) or 0)
    store = getattr(hc, "store", None)
    aid = _pending_approval_id(message)
    if wait <= 0 or store is None or aid is None:
        return message
    deadline = _time.monotonic() + wait
    while True:
        approval = store.get_approval(aid)
        status = (approval or {}).get("status")
        if approval is None:
            return message
        if status == "approved":
            # Re-run the gate: it consumes the fresh grant and returns None,
            # letting the original call proceed seamlessly.
            return _gate(hc, capability, tool, command, detail=detail)
        if status == "used":
            # A concurrent identical call consumed the grant first — not a
            # denial. Fall back to the classic retry message.
            return message
        if status not in ("pending",):
            return (
                f"Error: [APPROVAL_DENIED] The operator denied "
                f"'{tool}: {(detail or command or '')[:200]}'. Do not retry this "
                f"call; ask the user how to proceed."
            )
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            return message
        await asyncio.sleep(min(0.5, remaining))


async def _call(hc: HarnessContext, capability: Capability | None, fn, *args) -> str:
    """Enforce permissions (mode + action class + approvals), run lifecycle hooks
    around the pure tool, and normalize expected errors. The tool name is
    ``fn.__name__`` and the session key is ``hc.key`` — so hooks attach here
    without touching the wrappers. Every return path, including normalized errors
    and approval prompts, goes through scrubbing."""
    hooks = getattr(hc, "hooks", None)
    try:
        if capability is not None:
            # Only shell tools carry a classifiable command in args[0]; other
            # EXECUTE tools (diagnostics, process control) must not have a path
            # or process id misread as a command.
            command = (
                args[0]
                if (capability is Capability.EXECUTE
                    and fn.__name__ in ("run_command", "start_process")
                    and args and isinstance(args[0], str))
                else None
            )
            # Approval binding detail: the command for shell tools, else the
            # primary (usually path) argument — so an approval covers exactly
            # this request, not the whole action class.
            detail = command
            if detail is None and args and isinstance(args[0], str):
                detail = args[0]
            gate = await _gate_with_wait(hc, capability, fn.__name__, command, detail=detail or "")
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
        from .result import error_code_for

        return _finalize(hc, f"Error: [{error_code_for(str(exc))}] {exc}")


async def _pre(hc: HarnessContext, capability: Capability, tool_name: str,
               detail: str = "") -> str | None:
    """The gate + pre-hook half of _call, for tools whose return type isn't a
    string (read_image). Raises on DENY/veto; returns an approval message or
    None to proceed. Keeps such tools inside the same audit/permission path."""
    gate = _gate(hc, capability, tool_name, None, detail=detail)
    if gate is not None:
        return gate
    hooks = getattr(hc, "hooks", None)
    if hooks is not None:
        call = ToolCall(tool=tool_name, capability=capability, session_key=hc.key,
                        args=(detail,), context=hc)
        await hooks.run_pre(call)  # may raise HookVeto
    return None


async def _call_idem(hc: HarnessContext, capability: Capability, operation_id: str | None, fn, *args) -> str:
    """Like _call, but idempotent for side-effectful tools: if this operation_id
    already ran, return the recorded result instead of executing again. Guards
    against duplicate side effects on retries. Errors and approval prompts are
    NOT recorded (so they can be retried)."""
    store = getattr(hc, "store", None)
    tid = getattr(hc, "task_id", None)
    request_hash = ""
    if operation_id and store is not None and tid:
        import hashlib
        import json

        canonical = json.dumps(args, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), default=str)
        request_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        prev = store.get_operation(operation_id, tid, fn.__name__)
        if prev is not None:
            if not prev.get("request_hash") or prev["request_hash"] != request_hash:
                return _finalize(
                    hc,
                    "Error: [IDEMPOTENCY_CONFLICT] operation_id was already used "
                    "for a different or unverifiable request",
                )
            return _finalize(hc, prev["result"] + "\n[idempotent: cached result for this operation_id]")
    result = await _call(hc, capability, fn, *args)
    if (operation_id and store is not None and tid
            and not result.startswith("Error:") and "APPROVAL REQUIRED" not in result):
        store.record_operation(operation_id, tid, fn.__name__, result, request_hash)
    return result


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
    async def write_file(path: str, content: str, expected_sha: str | None = None, operation_id: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Create or overwrite a file with the given content. Parent directories
        are created as needed. Pass expected_sha (from the read_file header) to be
        rejected if the file changed since you read it (avoids clobbering).
        operation_id makes the write idempotent across retries."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call_idem(hc, Capability.WRITE, operation_id, files.write_file, path, content, expected_sha)

    @mcp.tool()
    async def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False, expected_sha: str | None = None, operation_id: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Replace an exact string in a file. old_string must match exactly
        (including whitespace) and be unique unless replace_all=true. Pass
        expected_sha (from read_file) to reject the edit if the file changed.
        operation_id makes the edit idempotent across retries."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call_idem(hc, Capability.WRITE, operation_id, files.edit_file, path, old_string, new_string, replace_all, expected_sha)

    @mcp.tool()
    async def apply_edits(edits: list, operation_id: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Apply many file changes as a batch (all-or-nothing, in-process rollback
        on failure). Each edit is {path, content} to write, {path, old_string,
        new_string, replace_all?} to edit, or {path, delete:true}; add
        {expected_sha} per edit to guard stale writes. operation_id makes the
        batch idempotent across retries."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call_idem(hc, Capability.WRITE, operation_id, files.apply_edits, edits)

    # ---- execution (EXECUTE) -----------------------------------------------

    @mcp.tool()
    async def run_command(command: str, cwd: str | None = None, timeout: int = 120, operation_id: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Run a shell command (PowerShell on Windows, bash on POSIX) with the
        workspace as the default working directory. Returns exit code + output.
        Use for tests, builds, git, package managers. Pass operation_id to make a
        one-shot command idempotent (a retry returns the cached result instead of
        running it again)."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call_idem(hc, Capability.EXECUTE, operation_id, shell.run_command, command, cwd, timeout)

    @mcp.tool()
    async def apply_patch(patch: str, expected_shas: dict | None = None, operation_id: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Apply a unified diff to the workspace (via git apply). Each target path
        is confinement/secret/.git-checked before applying. Good for large or
        multi-hunk changes expressed as a standard diff. Optionally pass
        expected_shas {path: sha} (from read_file headers) as a stale-write guard."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call_idem(hc, Capability.WRITE, operation_id, files.apply_patch, patch, expected_shas)

    @mcp.tool()
    async def read_image(path: str, task_id: str | None = None, ctx: Context = None) -> Image:
        """Read an image file (png/jpg/gif/webp/bmp) so you can SEE it — a
        screenshot, diagram, or UI mockup. Path is confinement + secret gated."""
        hc = server.context_for(task_id, _session_key(ctx))
        # Non-string return type, so it can't ride _call — but it still passes
        # the same permission gate and pre-hooks (audit) as every other tool.
        gate = await _pre(hc, Capability.READ, "read_image", detail=path)
        if gate is not None:
            raise SecurityError(gate)
        data, fmt = images.read_image_bytes(hc, path)
        return Image(data=data, format=fmt)

    @mcp.tool()
    async def notebook_read(path: str, task_id: str | None = None, ctx: Context = None) -> str:
        """Read a Jupyter notebook (.ipynb) as indexed cells with their source."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, notebook.notebook_read, path)

    @mcp.tool()
    async def notebook_edit(path: str, cell_index: int, source: str = "", mode: str = "replace", cell_type: str = "code", expected_sha: str | None = None, operation_id: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Edit a notebook cell. mode: 'replace' (set source), 'insert' (new cell
        before cell_index), 'delete'. Keeps the .ipynb valid. Pass expected_sha
        (from notebook_read's header) to reject the edit if the file changed."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call_idem(hc, Capability.WRITE, operation_id, notebook.notebook_edit, path, cell_index, source, mode, cell_type, expected_sha)

    # ---- version control actions (commit / PR) -----------------------------

    @mcp.tool()
    async def git_commit(message: str, add_all: bool = True, operation_id: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Stage (all changes by default) and commit with the user's real git
        identity + hooks. Use after review. Local only."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call_idem(hc, Capability.WRITE, operation_id, vcs.git_commit, message, add_all)

    @mcp.tool()
    async def open_pr(title: str, body: str = "", base: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Open a GitHub pull request via the gh CLI. This is a remote action, so
        in auto_workspace/build_ask modes it requires operator approval."""
        import shlex
        hc = server.context_for(task_id, _session_key(ctx))
        cmd = f"gh pr create --title {shlex.quote(title)} --body {shlex.quote(body or title)}"
        if base:
            cmd += f" --base {shlex.quote(base)}"
        return await _call(hc, Capability.EXECUTE, shell.run_command, cmd, None, 120)

    # ---- code intelligence (READ) ------------------------------------------

    @mcp.tool()
    async def diagnostics_check(path: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Run the project's detected linter/typechecker (ruff/tsc/eslint/cargo/
        go vet) and return errors. Call after edits to stop editing blind. This
        EXECUTES the checker, so it is unavailable in plan/read_only modes."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, capability_for("diagnostics_check"), diagnostics.diagnostics, path)

    @mcp.tool()
    async def repo_map(path: str | None = None, task_id: str | None = None, ctx: Context = None) -> str:
        """Compact symbol map (functions/classes per file) to locate code fast
        without reading everything."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, repomap.repo_map, path)

    @mcp.tool()
    async def lsp_definition(path: str, line: int, character: int = 0, task_id: str | None = None, ctx: Context = None) -> str:
        """Go to definition: where is the symbol at path:line:character DEFINED?
        Real code intelligence via a language server (exact, not text search).
        line is 1-based. Needs a language server installed (python/ts/js/rust/go)."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, codeintel.lsp_definition, path, line, character)

    @mcp.tool()
    async def lsp_references(path: str, line: int, character: int = 0, task_id: str | None = None, ctx: Context = None) -> str:
        """Find all references: every place that USES the symbol at
        path:line:character. line is 1-based. Use before renaming/changing an API."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, codeintel.lsp_references, path, line, character)

    @mcp.tool()
    async def lsp_hover(path: str, line: int, character: int = 0, task_id: str | None = None, ctx: Context = None) -> str:
        """Hover info: the type/signature/doc of the symbol at path:line:character
        (1-based line). Answers 'what type is this' without reading the source."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, codeintel.lsp_hover, path, line, character)

    @mcp.tool()
    async def lsp_symbols(path: str, task_id: str | None = None, ctx: Context = None) -> str:
        """Document symbols: the classes/functions/methods declared in a file,
        with line numbers — a precise outline from the language server."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, codeintel.lsp_symbols, path)

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
    async def remember(text: str, key: str | None = None, scope: str = "project", task_id: str | None = None, ctx: Context = None) -> str:
        """Save a fact across sessions (a decision, gotcha, or convention). scope:
        'project' (default; shared by the repo and its worktrees), 'global'
        (everywhere), or 'task' (this task only). Pass a stable key to update an
        existing note instead of adding a new one."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, capability_for("remember"), memory.remember, text, key, scope)

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
    async def load_skill(name: str, offset: int = 0, task_id: str | None = None, ctx: Context = None) -> str:
        """Load the full content of a skill by name (from list_skills) when you
        need its procedure. Long skills are paged: if the reply ends with a
        'skill continues' note, call again with the given offset until you have
        read ALL parts — never act on a half-read skill."""
        hc = server.context_for(task_id, _session_key(ctx))
        return await _call(hc, Capability.READ, skills.load_skill, name, offset)

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

    def _task_mutation_call(task_id: str, fn, *args) -> str:
        denied = _task_mutation_denial(server, task_id)
        if denied is not None:
            return _scrub_server(server, denied)
        return _task_call(fn, task_id, *args)

    async def _task_call_async(fn, *args) -> str:
        try:
            return _scrub_server(server, await fn(server, *args))
        except _EXPECTED_ERRORS as exc:
            return _scrub_server(server, f"Error: {exc}")

    async def _task_mutation_call_async(task_id: str, fn, *args) -> str:
        denied = _task_mutation_denial(server, task_id)
        if denied is not None:
            return _scrub_server(server, denied)
        return await _task_call_async(fn, task_id, *args)

    @mcp.tool()
    async def start_task(project_path: str, goal: str, permission_mode: str = "auto_workspace",
                         title: str = "", isolation: str = "", ctx: Context = None) -> str:
        """Begin a task: bind a workspace + goal + permission mode and get a
        task_id. Pass that task_id to every subsequent tool call so the task is
        resumable. By default the task works directly IN the project folder
        (like Codex/Claude Code) — the operator's configured default; leave
        isolation empty to use it. Files land where the user made the project;
        review changes with git_diff and commit when done. Pass
        isolation='worktree' only if the user wants an isolated private copy
        (e.g. trying two approaches in parallel). permission_mode: read_only |
        plan | build_ask | auto_workspace (the default and usual ceiling —
        full/bypass_sandboxed are operator-only, granted via
        `python -m harness tasks set-mode`)."""
        return await _task_call_async(tasktools.start_task, project_path, goal, permission_mode, title, isolation)

    @mcp.tool()
    async def create_subtask(parent_task_id: str, goal: str, title: str = "", ctx: Context = None) -> str:
        """Decompose a task into a child subtask (same project/workspace/mode).
        These are subtasks the same ChatGPT works through — the harness has no
        model of its own, so there are no autonomous LLM sub-agents."""
        return _task_call(tasktools.create_subtask, parent_task_id, goal, title)

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
        """Set done-gates. Items may be strings or objects with text,
        verification_kind (machine/source/operator/mixed), and required."""
        return _task_mutation_call(task_id, tasktools.set_acceptance_criteria, criteria)

    @mcp.tool()
    async def satisfy_criterion(
        task_id: str, criterion_id: str, evidence: list, ctx: Context = None
    ) -> str:
        """Satisfy one contracted acceptance criterion with server-valid evidence.
        Operator-kind criteria can only be confirmed from the local Workbench."""
        return _task_mutation_call(
            task_id, tasktools.satisfy_criterion, criterion_id, evidence
        )

    @mcp.tool()
    async def record_framework_routing(
        task_id: str, activated: list, skipped: list, reason: str,
        ctx: Context = None,
    ) -> str:
        """Record which declared AOCS parts were used or skipped and why."""
        return _task_mutation_call(
            task_id, tasktools.record_framework_routing, activated, skipped, reason
        )

    @mcp.tool()
    async def begin_cycle(task_id: str, question: str, purpose: str = "",
                          verification_plan: str = "", ctx: Context = None) -> str:
        """Open one auditable EFFORT cycle under the task's shared credit scope."""
        return _task_mutation_call(
            task_id, tasktools.begin_cycle, question, purpose, verification_plan
        )

    @mcp.tool()
    async def complete_cycle(task_id: str, cycle_id: str, conclusion: str,
                             decision: str, evidence: list, ctx: Context = None) -> str:
        """Validate a cycle receipt and atomically spend one credit."""
        return _task_mutation_call(
            task_id, tasktools.complete_cycle, cycle_id, conclusion, decision, evidence
        )

    @mcp.tool()
    async def abandon_cycle(task_id: str, cycle_id: str, reason: str,
                            ctx: Context = None) -> str:
        """Close an EFFORT cycle without spending a credit."""
        return _task_mutation_call(task_id, tasktools.abandon_cycle, cycle_id, reason)

    @mcp.tool()
    async def get_effort_status(task_id: str, ctx: Context = None) -> str:
        """Show the compact EFFORT ledger, criteria, and contract status."""
        return _task_call(tasktools.get_effort_status, task_id)

    @mcp.tool()
    async def request_extension(task_id: str, kind: str, amount: int, reason: str,
                                scope_id: str = "", ctx: Context = None) -> str:
        """Request an operator-approved contract extension; approval is one-shot."""
        result = _task_mutation_call(
            task_id, tasktools.request_extension, kind, amount, reason, scope_id
        )
        aid = _pending_approval_id(result)
        wait = int(server.config.approval_wait_seconds or 0)
        if aid is None or wait <= 0:
            return result
        import asyncio
        import time as _time

        deadline = _time.monotonic() + wait
        while _time.monotonic() < deadline:
            approval = server.tasks.get_approval(aid)
            status = (approval or {}).get("status")
            if status == "approved":
                return _task_mutation_call(
                    task_id, tasktools.request_extension, kind, amount, reason, scope_id
                )
            if status == "denied":
                return "Error: [APPROVAL_DENIED] the operator denied this extension"
            if status in {"used", None}:
                return result
            await asyncio.sleep(max(0.01, min(0.5, deadline - _time.monotonic())))
        return result

    @mcp.tool()
    async def begin_refinement_pass(
        task_id: str, target_weakness: str, directive: str,
        verification_plan: str, verification_kind: str = "", ctx: Context = None,
    ) -> str:
        """Open one bounded refinement pass with a declared evidence kind."""
        return await _task_mutation_call_async(
            task_id, tasktools.begin_refinement_pass, target_weakness, directive,
            verification_plan, verification_kind,
        )

    @mcp.tool()
    async def complete_refinement_pass(
        task_id: str, pass_id: str, outcome: str, evidence: list,
        delta_summary: str = "", ctx: Context = None,
    ) -> str:
        """Evidence-check and close a pass; operator-kind passes wait locally."""
        return await _task_mutation_call_async(
            task_id, tasktools.complete_refinement_pass, pass_id, outcome,
            evidence, delta_summary,
        )

    @mcp.tool()
    async def advance_task(task_id: str, to_state: str, ctx: Context = None) -> str:
        """Move a task to a new lifecycle state (new→discovering→planning→
        implementing→validating→repairing→review_ready→completed; or blocked)."""
        return _task_call(tasktools.advance_task, task_id, to_state)

    @mcp.tool()
    async def finish_task(task_id: str, result: str = "", evidence: str = "", ctx: Context = None) -> str:
        """Mark a task completed (must be review_ready first) with a result note.
        If the task has acceptance criteria, completion requires recorded test/
        diagnostic runs or an explicit evidence string describing verification."""
        return _task_call(tasktools.finish_task, task_id, result, evidence)

    @mcp.tool()
    async def cancel_task(task_id: str, reason: str = "", ctx: Context = None) -> str:
        """Abandon a task, recording why."""
        return _task_call(tasktools.cancel_task, task_id, reason)

    @mcp.tool()
    async def register_project(path: str, name: str = "", ctx: Context = None) -> str:
        """Register a project directory so tasks can be grouped under it."""
        return _task_call(tasktools.register_project, path, name)

    @mcp.tool()
    async def create_project(path: str, name: str = "", ctx: Context = None) -> str:
        """Create a NEW project folder (must be inside an approved root), git-init
        it with an initial commit so task worktrees work from the start, and
        register it. For existing folders use register_project."""
        return await _task_call_async(tasktools.create_project, path, name)

    @mcp.tool()
    async def fork_task(task_id: str, goal: str = "", title: str = "",
                        candidate: bool = False, ctx: Context = None) -> str:
        """Fork a task: a new task on the same project with its OWN worktree from
        the same base, copying goal/criteria/plan — try two approaches side by
        side. The original task is untouched."""
        if candidate:
            return await _task_mutation_call_async(
                task_id, tasktools.fork_task, goal, title, candidate
            )
        return await _task_call_async(tasktools.fork_task, task_id, goal, title, candidate)

    # ---- federation (consume other MCP servers) ----------------------------
    # Federated tools go through the same permission gate as everything else.
    # Listing servers/tools is EXTERNAL_READ; CALLING one is EXTERNAL_CALL,
    # which can do anything (browser, DBs, messages) and so never auto-runs
    # below full — auto_workspace/build_ask ask the operator first.

    def _federation_gate(hc, tool_name: str, detail: str, action) -> str | None:
        return _gate(hc, None, tool_name, detail, action=action)

    @mcp.tool()
    async def mcp_servers(task_id: str | None = None, ctx: Context = None) -> str:
        """List configured external MCP servers you can federate with."""
        try:
            hc = server.context_for(task_id, _session_key(ctx))
            gate = _federation_gate(hc, "mcp_servers", "", Action.EXTERNAL_READ)
            if gate is not None:
                return _finalize(hc, gate)
        except _EXPECTED_ERRORS as exc:
            return _scrub_server(server, f"Error: {exc}")
        names = server.federation.names()
        if not names:
            return ("No external MCP servers configured. Add them via "
                    "HARNESS_MCP_SERVERS or <state_dir>/mcp_servers.json.")
        return "# Federated MCP servers\n" + "\n".join(f"  - {n}" for n in names)

    @mcp.tool()
    async def mcp_tools(server_name: str, task_id: str | None = None, ctx: Context = None) -> str:
        """List the tools an external MCP server exposes."""
        try:
            hc = server.context_for(task_id, _session_key(ctx))
            gate = _federation_gate(hc, "mcp_tools", server_name, Action.EXTERNAL_READ)
            if gate is not None:
                return _finalize(hc, gate)
            tools = await server.federation.list_tools(server_name)
        except _EXPECTED_ERRORS as exc:
            return _scrub_server(server, f"Error: {exc}")
        except Exception as exc:  # noqa: BLE001 - external connection issues
            return _scrub_server(server, f"Error connecting to {server_name!r}: {exc}")
        body = "\n".join(f"  - {name}: {desc}" for name, desc in tools)
        return _scrub_server(server, f"# Tools on {server_name}\n{body}")

    @mcp.tool()
    async def mcp_call(server_name: str, tool: str, arguments: dict | None = None,
                       task_id: str | None = None, ctx: Context = None) -> str:
        """Call a tool on an external MCP server and return its output. Requires
        a task_id (external calls are tracked and approval-gated per task)."""
        import json as _json
        try:
            if not task_id:
                raise SecurityError(
                    "mcp_call requires a task_id — start_task first so external "
                    "calls are tracked and can be approved."
                )
            hc = server.context_for(task_id, _session_key(ctx))
            detail = f"{server_name}.{tool}({_json.dumps(arguments or {}, sort_keys=True)})"
            gate = _federation_gate(hc, "mcp_call", detail, Action.EXTERNAL_CALL)
            if gate is not None:
                return _finalize(hc, gate)
            out = await server.federation.call_tool(server_name, tool, arguments or {})
        except _EXPECTED_ERRORS as exc:
            return _scrub_server(server, f"Error: {exc}")
        except Exception as exc:  # noqa: BLE001 - external connection issues
            return _scrub_server(server, f"Error calling {tool!r} on {server_name!r}: {exc}")
        return _scrub_server(server, out)

    # ---- health (unauthenticated, no secrets) ------------------------------

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request):  # noqa: ANN001
        from starlette.responses import JSONResponse

        # This route intentionally bypasses the secret path so local process
        # supervisors can probe readiness. Keep the unauthenticated response
        # minimal: no mode, session count, route, or deployment metadata.
        return JSONResponse({"status": "ok"})

    return mcp
