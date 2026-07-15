# Project state & handoff

Single source of truth for what this is, how it's built, what's done, and what's
next. Read this first when resuming work.

## What it is

A local **MCP coding server** driven by **normal ChatGPT** (not Codex, not an API
key). ChatGPT is the reasoning loop; this server is the hands (read/write/edit/
search/shell + git + memory + skills + processes + worktrees). Reachable from
ChatGPT through a Tailscale Funnel + secret-route URL. Purpose: code with ChatGPT
like Claude Code / Codex, using ordinary ChatGPT usage instead of draining Codex.

No model-provider API is ever called from this server.

## Architecture (ports-and-adapters)

```
harness/
  app.py          composition root: config -> HarnessServer -> MCP -> secured app
  __main__.py     CLI: serve / doctor / url
  config.py       12-factor config; persisted secret route; adds worktrees root
  context.py      HarnessServer (shared config + SessionStore) + HarnessContext (per session)
  policy.py       Capability {READ,WRITE,EXECUTE} + PermissionPolicy (the one mode table)
  security.py     path confinement / secret-file denylist / command denylist
  session.py      per-workspace event journal (resume)
  proc.py         one async subprocess impl (env-aware, non-blocking) + shell_argv
  processes.py    ProcessManager for long-running background processes
  executor.py     Executor port: LocalExecutor (default) / DockerExecutor (sandbox)
  hooks.py        HookManager: pre/post-tool hooks (audit, scrub, future policy)
  scrub.py        redact secret formats from tool output (a post-tool hook)
  middleware.py   pure-ASGI security shell (secret route, Host/Origin, bearer, rate limit)
  server.py       FastMCP: per-session ctx + thin typed tool wrappers + capability + hooks
  tools/          files search shell workspace git memory skills todos process worktree
```

**The rule that makes it scale:** tool logic is pure functions over a
HarnessContext; each MCP tool is one thin wrapper declaring a capability. Adding
a tool = one function + one wrapper. Adding a permission mode = edit policy.py
only. Nothing else changes.

## Status: 57 tools, 276 tests, verified end-to-end (HTTP + stdio + live GUI). Cockpit + LSP + rules/hooks complete (see docs/CHECKLIST.md).

**Independent audit (2026-07-15), verified & closed.** ChatGPT red-teamed the
pushed `f7fe4e6`; I re-verified every claim against the code (3 parallel
explorers) — 12 of 13 findings were real. All are now fixed test-first. The
headline exploit — *ChatGPT could pick `full`/`bypass_sandboxed`, omit `task_id`,
share physical files, and slip approval boundaries* — is closed:

- **No self-escalation.** `start_task` is capped at `HARNESS_MAX_MODE` (default
  `auto_workspace`); `context_for` re-enforces it on every call (authoritative
  over legacy rows/subtasks). `full`/`bypass_sandboxed` are operator-only:
  `python -m harness tasks set-mode <id> <mode>`. `bypass_sandboxed` requires
  `sandbox=docker` or it degrades to `auto_workspace`.
- **No-task calls are read-only.** The shared fallback session runs at
  `HARNESS_NO_TASK_MODE` (default `read_only`), never the operator's mode;
  writes tell the model to `start_task`. Legacy: `HARNESS_NO_TASK_MODE=full`.
- **Physical isolation.** `start_task(isolation='auto')` creates & persists a
  per-task worktree on git repos; two tasks on one project edit disjoint files.
  `python -m harness worktrees prune` cleans terminal-task worktrees.
- **Approvals bind to the exact request** (sha over task/tool/action/args) and
  never cross tasks; **idempotency** is keyed `(task_id, tool, op_id)`.
- **Federation** (`mcp_call`) is gated: denied in read_only/plan, asks in
  auto_workspace, requires a task_id. **diagnostics_check** is EXECUTE (plan
  mode can't run checkers). **read_image** passes the gate + audit hooks.
- **git_commit** doesn't run repo hooks on the host by default (`no_hooks`);
  opt in with `HARNESS_COMMIT_HOOKS=true`. **Terminal tasks are frozen.**
- **Telemetry is real:** changed_files/commands/test_results/checkpoints/plan
  are populated from actual tool activity; `finish_task` wants evidence when
  acceptance criteria exist.
- **Packaging fixed:** `[tool.setuptools.packages.find]` ships `harness.tasks`
  (the wheel was broken). Linux path test fixed.

**Isolation:** identity is an explicit `task_id` the model threads through tool
calls, now backed by a real per-task worktree. Without a task_id, calls fall
back to a read-only shared session.

**Done — P0 hardening (security/correctness):** error-path scrubbing, run_command
env allowlist, grep secret-path policy, `.env`/`.git` blocking, capability
reclassification (read_only is truly read-only), unified execution boundary with
git hooks/filters neutralized, stale-write guard + auto-checkpoint, atomic state
writes, memory-id + worktree-collision fixes, per-owner process ownership.

**Done — P1 (Codex task architecture):** SQLite task store + migrations,
TaskState machine, task_id isolation, task lifecycle tools, tiered memory
(global/project/task, worktrees share project via git common-dir), enterprise
permission modes (plan/build_ask/auto_workspace/bypass_sandboxed) + 11 action
classes + command classifier + one-shot approval channel (`harness approvals`
CLI), operation_id idempotency, hardened Docker sandbox.

**Done — P2 (coding quality):** diagnostics_check (project checker), repo_map
(symbol index), apply_patch (unified diff via git apply).

**Done — P3 (extensibility):** MCP client federation (consume other MCP servers),
read_image (MCP image content), notebook read/edit, create_subtask, git_commit +
open_pr.

**Done — Tier 1 (parity with Claude Code / Codex):**
- memory: remember / recall / forget (per-workspace, auto-surfaced on open)
- skills: list_skills / load_skill (workspace + ~/.agents/skills)
- todos: write_todos / list_todos (survive turn resets; shown in session_status)
- background processes: start / read / write / stop / list_processes
- atomic multi-file patch: apply_edits (snapshot + rollback)
- worktree-per-task: create / list / remove_worktree
- ergonomics: glob noise-filter (skips node_modules), auto-detected project commands
- git safety: git_diff, create/list/restore_checkpoint (private ref, no branch pollution)

**Done — Tier 2/3 (hardening & extensibility):**
- lifecycle hooks (`hooks.py`): pre/post-tool hooks around every call, wired in
  server `_call` via `fn.__name__` + `hc.key` (zero churn to the tool wrappers). A
  pre-hook may veto (HookVeto); a post-hook may transform output. This is the
  extensibility backbone — new cross-cutting policy = register a hook.
- secret-content scrubbing (`scrub.py`): a post-tool hook redacts known
  credential formats (AWS/GitHub/OpenAI/Anthropic/Slack/Stripe/JWT/PEM keys…)
  from ALL tool output before it reaches ChatGPT. Toggle `HARNESS_SCRUB_OUTPUT`.
- audit log: a pre-tool hook appends every call to `state_dir/audit.jsonl`
  (what ChatGPT did, when, in which session). Toggle `HARNESS_AUDIT_LOG`.
- pluggable execution backend (`executor.py`): `Executor` port with
  `LocalExecutor` (default, dependency-free) and opt-in `DockerExecutor`
  (`HARNESS_SANDBOX=docker`) that runs commands in a throwaway container with
  only the workspace mounted and networking off. `spawn_argv` is the single seam
  both run_command AND start_process use — the sandbox has no silent hole.
- stdio transport: `python -m harness stdio` serves the same tool surface to
  local MCP clients (Claude Desktop, IDE extensions). No middleware needed — the
  process boundary is the trust boundary.

**Honest limits (still true after hardening):**
- The command classifier (`permissions.py`) is **advisory hardening, not a
  boundary** — a regex can't know what arbitrary shell code does (`python -c`,
  obfuscation, heredocs slip through; `tests/test_quality_fixes.py` pins known
  bypasses). The real boundaries are the mode table (deny/ask) and
  `HARNESS_SANDBOX=docker` with `network=none`. Set `HARNESS_ARBITRARY_COMMANDS=ask`
  to fail closed on unrecognized commands.
- Under `sandbox=docker`, `run_command`/`start_process`/`diagnostics` run in the
  container, but **internal git & ripgrep still run on the host** (hooks/config
  neutralized). `doctor` states this.
- Default config is permissive for a *personal* tool: `mode=full` (operator's own
  direct context), `sandbox=local`, bearer optional. Harden deliberately for
  untrusted repos.

**Roadmap — genuinely later (not built; deliberately):**
- Real per-project hardened container *images* + host→container path rewriting so
  git itself runs inside the sandbox (worktree gitdir pointers store absolute
  host paths → needs identical mount paths; hard on Windows).
- Full Windows process-tree kill (killing a PowerShell wrapper can leave a
  grandchild; documented limitation).
- richer sandbox backends (gVisor/Firecracker/remote) — a third Executor class.
- Roots hot-reload (restart-required today, by design — a watcher is a
  self-service escalation surface for a model with `run_command`).
- Not applicable by design: autonomous LLM sub-agents (the harness has no model —
  ChatGPT is the brain; we provide subtasks instead).

## Key decisions (don't relitigate)

- **No Pi, no TypeScript.** One pure-Python process. Rejected forking Pi (Node
  inside Python) as needless coupling/waste.
- **Transport gotcha (fixed):** the MCP SDK's built-in Host check is exact-match
  and rejects `*.ts.net` funnel hosts (Spectre hit this). We pass
  `transport_security(enable_dns_rebinding_protection=False)` and let our own
  SecurityMiddleware (with a `.ts.net` wildcard) gate Host/Origin. Also
  `json_response=True` + `stateless_http=True` to match the proven Spectre config.
- **Secret route** is the primary auth (256-bit path); optional bearer on top.
- Security is enforced in code, not by trusting the model. The default `local`
  backend + command denylist is a backstop, not a sandbox; real isolation is now
  available via `HARNESS_SANDBOX=docker` (opt-in so the default stays portable).
- **Extensibility goes through hooks, not wrapper edits.** Cross-cutting concerns
  (audit, scrub, telemetry, approvals) attach in `hooks.py`; the tool wrappers
  and `policy.py` stay untouched. Adding a tool is still one pure fn + one wrapper.

## Run & test

```
python -m pip install .            # or: pip install -r requirements.txt
python -m harness doctor           # validate config + environment
python -m harness serve            # HTTP server on 127.0.0.1:8848 (for ChatGPT)
python -m harness stdio            # stdio transport (for local MCP clients)
python -m harness approvals list   # operator approval queue (build_ask/auto_workspace)
python -m harness roots add <path> # approve a new workspace folder (restart to apply)
python -m harness tasks set-mode <id> <mode>   # operator-only mode elevation
python -m harness worktrees prune  # remove worktrees of finished tasks
python -m pytest tests -q          # 276 tests (needs pip install .[dev])

New env vars from the audit hardening: HARNESS_MAX_MODE (default auto_workspace),
HARNESS_NO_TASK_MODE (default read_only), HARNESS_COMMIT_HOOKS (default off),
HARNESS_ARBITRARY_COMMANDS (allow|ask, default allow).
```

See README.md for the full ChatGPT-connector + Tailscale setup.
