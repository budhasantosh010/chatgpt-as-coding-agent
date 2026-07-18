# chatgpt-code-harness

> **New here? Read [docs/MANUAL.md](docs/MANUAL.md) first.** It explains the
> entire system in plain language with diagrams — what it is, where everything
> is stored, how permissions work, and how to run it day to day. Start there.
>
> Wondering how this compares to Codex / Claude Code / OpenCode / Cursor / Pi?
> See [docs/COMPARISON.md](docs/COMPARISON.md) — an honest, researched,
> feature-by-feature matrix including what we're missing.

Code with your **ChatGPT** account the way you code with Claude Code or Codex —
without draining your Codex allowance. ChatGPT is the reasoning loop; this is a
local MCP server that gives it hands on your machine (read / write / edit / search /
shell + workspace orientation), reachable through a Tailscale Funnel.

No model-provider API is ever called from here. ChatGPT does the thinking; the
harness does the file and terminal work.

```
ChatGPT  ──MCP over HTTPS──►  Tailscale Funnel  ──►  localhost:8848
                                                       │  secret route + Host/Origin gate
                                                       ▼
                                              chatgpt-code-harness
                                              read/write/edit/glob/grep/shell
                                                       ▼
                                              your approved workspace
```

## Quickstart — one command

```powershell
python -m harness up
```

That starts **everything**: the operator GUI (the **Cockpit**) on
`http://127.0.0.1:8849`, opens it in your browser, and runs the MCP engine on
:8848 as a child process. No more three terminals.

```
 ┌──────────────────┐         ┌──────────────────┐
 │  WINDOW 1        │   MCP   │  THE ENGINE      │
 │  ChatGPT         │────────▶│  :8848 (child)   │
 │  (you type here, │ funnel  │  files/git/shell │
 │   the brain)     │         └────────┬─────────┘
 └──────────────────┘                  │ localhost only, never funneled
                              ┌────────▼─────────┐
                              │  WINDOW 2        │
                              │  THE COCKPIT     │
                              │  :8849 — projects│
                              │  sessions, modes │
                              │  live activity,  │
                              │  approvals, diffs│
                              └──────────────────┘
```

**The Cockpit gives you the Codex-style GUI:** a project sidebar, chat sessions
underneath each project, a permission-mode dropdown per session, a live feed of
what ChatGPT is doing right now, one-click approve/deny, visual diffs, and
drag-and-drop files. It is **localhost-only and never exposed through the
funnel** — approvals must stay beyond the model's reach.
See [docs/COCKPIT_DESIGN.md](docs/COCKPIT_DESIGN.md).

<details>
<summary>Manual mode (the old three-terminal way, still supported)</summary>

```powershell
copy .env.example .env           # set HARNESS_WORKSPACE_ROOTS=C:\path\to\projects
python -m harness doctor         # sanity-check config + environment
python -m harness serve          # engine only (no GUI)
.\scripts\funnel.ps1             # expose to ChatGPT + print the MCP URL
```
</details>

Then add it to ChatGPT (below) and tell ChatGPT: *"Open workspace
C:\path\to\project and ..."*.

## Connect it to ChatGPT

You've done this with your Spectre bridge — same flow, new URL.

0. **Turn on Developer Mode first.** ChatGPT → **Settings → Connectors →
   Advanced → Developer mode**. Without it, ChatGPT only exposes the `search`/
   `fetch` tools of a connector and the coding tools are invisible. (Available on
   Plus/Pro/Business/Enterprise.)
1. Start the server + funnel, then run `python -m harness url` (or `funnel.ps1`)
   to get the public URL: `https://<machine>.<tailnet>.ts.net/<secret-route>/mcp`.
2. In ChatGPT: **Settings → Connectors → Create custom connector (MCP server)**.
3. Paste the exact URL from `harness url` (format is `.../<secret-route>/mcp` —
   don't rearrange it). Authentication: **None** — the secret route is the gate.
   (If you set `HARNESS_BEARER_TOKEN`, use the connector's token field instead.)
4. Scan tools → Create, enable the connector in a chat, and start a task. A safe
   first prompt is a read-only warm-up (`open_workspace` only) before any edits.

The secret route is a 256-bit random path, generated once and persisted in the
state dir, so the URL stays stable across restarts.

**Other MCP clients (Claude Desktop, IDE extensions):** run
`python -m harness stdio` and point the client at it as a stdio MCP server — the
same 57 tools, no Tailscale or secret route needed (the process boundary is the
trust boundary).

## The tools ChatGPT sees (57)

**Tasks (the isolation handle)** — `start_task(project, goal, permission_mode)`
returns a `task_id` you thread through every call so concurrent conversations
stay isolated; `list_tasks`, `task_status`, `resume_task`, `set_task_goal`,
`set_acceptance_criteria`, `advance_task`, `finish_task`, `cancel_task`,
`create_subtask`, `register_project`, `create_project` (new folder + git init,
confined to an approved root), `fork_task` (same base, own worktree — try two
approaches side by side).

**Code intelligence (LSP)** — `lsp_definition`, `lsp_references`, `lsp_hover`,
`lsp_symbols`: real go-to-definition / find-references / types from a language
server, not text search. Auto-detects pyright/pylsp/typescript-language-server/
rust-analyzer/gopls; if none is installed it says exactly what to install.

**Orient** — `open_workspace(path)` (call first: git state, structure, project
rules, suggested test/build commands, remembered facts), `session_status()`
(resume: git changes, todos, recent actions).

**Inspect** — `read_file`, `list_dir`, `glob` (skips node_modules & friends),
`grep` (ripgrep).

**Change** — `write_file`, `edit_file`, `apply_edits` (atomic multi-file patch,
auto-rollback on failure).

**Execute** — `run_command` (shell: PowerShell on Windows). Background:
`start_process`, `read_process`, `write_process`, `stop_process`,
`list_processes` (dev servers, `test --watch`).

**Review & undo** — `git_diff`, `create_checkpoint`, `list_checkpoints`,
`restore_checkpoint` (private git ref; never touches your branch/history).

**Isolate** — `create_worktree`, `list_worktrees`, `remove_worktree`
(task-per-branch worktrees).

**Remember** — `remember`, `recall`, `forget` (per-workspace memory,
auto-surfaced on open).

**Extend** — `list_skills`, `load_skill` (loadable how-to docs from the
workspace and `~/.agents/skills`).

**Plan** — `write_todos`, `list_todos` (survives turn resets, shown in
session_status).

Permission gates: read-only tools always work; `write`/`execute` tools follow
the task's permission mode. ChatGPT can request modes only up to the server
ceiling (`HARNESS_MAX_MODE`, default `auto_workspace`); `full`/`bypass_sandboxed`
are **operator-only**, granted locally with `python -m harness tasks set-mode`
or the Cockpit's mode dropdown. Tool calls **without** a `task_id` run in a
shared read-only fallback session, so a forgotten handle can't silently write.

**Unrecognized commands ask by default** (`HARNESS_ARBITRARY_COMMANDS=ask`).
Everyday dev commands (`pytest`, `npm test`, linters, local git) are a positive
*safe tier* that always runs, so ask-mode is safe without being annoying. When
something new does ask, approve it once — or tick **remember** (or
`approvals approve <id> --remember`) to always allow that **exact** command in
that **one** project. The remembered list lives in the state dir, outside every
workspace root, so the model can never write its own allowlist.

## Security & threat model

Reachable from the public internet through the Funnel, and it can write files and
run commands — so the boundaries are enforced in code, not by trusting the model:

- **Secret route** — 256-bit path; anything else returns 404. Primary auth.
- **Host / Origin allowlist** — blocks DNS-rebinding; only `*.ts.net` + localhost.
- **Optional bearer token** — defense in depth (`HARNESS_BEARER_TOKEN`).
- **Workspace confinement** — every path is realpath-resolved and must sit inside
  an approved root; symlink escapes are blocked. Verified over the wire in tests.
- **Secret-file blocking** — private keys, `.npmrc`, `.git-credentials`, etc. are
  refused for read and write, so they can't be exfiltrated to ChatGPT.
- **Secret-content scrubbing** — known credential formats (AWS/GitHub/OpenAI/
  Anthropic/Slack/Stripe/JWT/PEM keys…) are redacted from *all* tool output
  before it reaches ChatGPT, so a key embedded in a normal file or log doesn't
  leak. On by default (`HARNESS_SCRUB_OUTPUT`).
- **Command denylist** — catastrophic commands (`rm -rf /`, `mkfs`, force-push, …)
  are refused.
- **Optional container sandbox** — set `HARNESS_SANDBOX=docker` to run every
  `run_command` / `start_process` in a throwaway container with only the
  workspace mounted and networking off. Default stays local (no dependencies).
- **Audit log** — every tool call is appended to `<state_dir>/audit.jsonl`: a
  durable record of what ChatGPT did on your machine (`HARNESS_AUDIT_LOG`).
- **Mode gate** — `read_only` disables write/execute. **ChatGPT cannot change the
  mode**; only the operator can, locally.

**Honest limits.** With the default `local` backend the command classifier is
**advisory hardening, not a sandbox**: a regex can't know what arbitrary shell
code does (`python -c …`, obfuscation, and heredocs slip past it), so
`run_command` executes as your user. The real boundaries are the permission mode
(deny/ask) and `HARNESS_SANDBOX=docker` with networking off — flip that on for
untrusted repos, and set `HARNESS_ARBITRARY_COMMANDS=ask` to make anything
unrecognized require approval. Under docker, internal git and ripgrep still run
on the host (with repo hooks/config neutralized); `doctor` says so. Scrubbing is
high-signal pattern matching: it catches well-known key formats, not every
secret, so still scope `HARNESS_WORKSPACE_ROOTS` deliberately. Prefer a bearer
token in addition to the secret route for a write+exec server. This is a
**personal** tool with permissive defaults (`mode=full` for your own local
context) — not an unattended multi-tenant runtime.

## Architecture (and how to extend it)

Ports-and-adapters. Tool logic knows nothing about MCP or HTTP; the transport
knows nothing about tools. They meet at one typed seam.

```
harness/
  app.py         composition root: config -> context -> server -> secured app
  __main__.py    CLI: up / serve / stdio / doctor / url / watch / tasks / approvals /
                 commands / roots / worktrees
  config.py      12-factor config (env + .env), persisted secret route
  context.py     HarnessContext — injected into every tool (no globals)
  policy.py      Capability + PermissionPolicy — the one place modes are decided
  permissions.py action classes + command classifier (risk tiers AND a safe tier)
  allowlist.py   remembered per-project exact-command approvals (operator-only)
  security.py    path confinement / secret globs / command denylist (isolated, tested)
  session.py     per-workspace event log (resume support)
  events.py      structured live-event bus (ids + replay + push sink) for the cockpit
  proc.py        one async subprocess impl (non-blocking) + shell_argv
  executor.py    Executor port: LocalExecutor (default) / DockerExecutor (sandbox)
  hooks.py       pre/post-tool hooks (audit, events, checkpoints, telemetry,
                 path-scoped rules, auto-format, scrubbing)
  userhooks.py   OPERATOR-configured hooks from <state_dir>/hooks.json (sandboxed)
  rules.py       path-scoped project rules (surfaced when you touch matching files)
  lsp.py         Language Server Protocol client (real code intelligence)
  scrub.py       secret-content redaction (a post-tool hook)
  middleware.py  pure-ASGI security shell (SSE-safe)
  server.py      FastMCP: thin typed tool wrappers + capability + lifecycle hooks
  tools/         files / search / shell / workspace / codeintel — pure async logic
  cockpit/       the operator GUI: supervisor (spawns the engine), localhost API,
                 SSE feed, and a single static HTML/CSS/JS page (no npm)
```

**Add a tool** in two steps:
1. Write an `async def my_tool(hc, ...)` in the right `tools/` module.
2. Add a wrapper in `server.py`: declare its params + docstring (what ChatGPT
   reads) and its capability, e.g.
   `return await _call(hc, Capability.WRITE, files.my_tool, ...)`.

Nothing else changes — not config, not security, not transport.

**Add a permission mode** (e.g. Codex-style plan/build/ask): edit
`PermissionPolicy.decide` in `policy.py`. Tools never change; they only declare a
capability.

**Add a cross-cutting policy** (approvals, rate limits, extra redaction): register
a pre/post hook in `hooks.py`. It runs around every tool call — no wrapper edits.

**Done:** checkpoints/rollback (with auto-checkpoint before edits + stale-write
guard), background processes (per-owner), worktree-per-task, memory, skills,
todos, batch multi-file patch (in-process rollback), lifecycle hooks,
secret-content scrubbing on every return path, env allowlist, unified execution
boundary (git hooks/filters neutralized), optional Docker sandbox, stdio transport.

**Isolation:** pass a `task_id` (from `start_task`) to every tool call and
concurrent conversations are isolated — separate permission mode, process owner,
and their own tracked state. Since 2026-07-17 tasks work **in the project
folder by default** (like Codex/Claude Code; `HARNESS_DEFAULT_ISOLATION`);
request `isolation='worktree'` (or the session dialog's "Isolated copy") to get
a **separate physical worktree** so two tasks on one project never edit the
same files. Without a `task_id`, calls share a read-only fallback session.

**Roadmap (deliberately later):** git itself running inside the container (today
it runs on host with hooks/config neutralized), full Windows process-tree kill,
richer sandbox backends. Autonomous LLM sub-agents are N/A by design — the harness
has no model; it offers subtasks instead.

## Field-tested (July 2026): the validated architecture

The architecture below is not a plan — it is the outcome of three controlled
experiments run by the operator against the live system, each verified against
the harness's own flight recorder (`<state_dir>/audit.jsonl` timestamps):

| Experiment | Result |
|---|---|
| **Test 1 — sequential roles** | ✅ Two specialist roles ran strictly in order (separate tasks, zero interleaving); honest reporting. |
| **Test 2 — "spawn parallel subagents"** | ❌ **No native subagents on a personal ChatGPT surface.** One reasoning stream interleaved the two "subagents" in a strict A-B-A-B metronome (~13 s per call, zero overlap, zero speedup vs Test 1). Only the two OS test *processes* genuinely overlapped. The model's first report overclaimed ("Subagent B didn't know the codeword") and confessed single-stream when pressed — labels prove nothing; logs do. |
| **Test 3 — cooperative multitasking** | ✅ Told to never wait idle, the model started two 75-second jobs 13 s apart and wrote a design doc **during** their sleep window; one `read_process` per job at the end; 130 s total vs ~4 min if it had babysat. The queue works. |

The four layers that follow from that evidence:

```
 AOCS skill   = HOW to think      (Specialist → Red Team → Judge, quality gates,
                                   blackboard — a loadable markdown doctrine)
 THE QUEUE    = WHEN to think     (never idle: fill every machine-wait with the
                                   next task's thinking)
 MACHINES     = the parallel part (start_process: tests/builds/linters run
                                   concurrently; run_command blocks — one at a time)
 HARNESS + YOU = memory & safety  (tasks.db, audit log, approvals, diff review)
```

**What can and cannot be parallel here** (the one golden rule): *thinking* is
sequential — one model stream on chatgpt.com; *doing* is parallel — any number
of OS processes. The only real parallel *brains* at £0 are separate ChatGPT
chats, each a genuinely independent session (manual to orchestrate, so optional).

### Asking for "parallel work" (the magic phrase)

In Codex/Claude Code you'd say "spawn parallel subagents." Here that phrase
produces roleplay (see Test 2). Ask for the validated pattern instead:

> Use cooperative multitasking: split this into independent tasks; use
> start_process for anything slow and run those jobs simultaneously; never
> wait idle — while machines run, keep thinking on the next task; read each
> result when ready and reconcile at the end.

### The four independent Run Contract controls

The Workbench locks four separate choices before a run starts:

1. **EFFORT** (`Off`, `Low`, `Medium`, `High`, `X-High`, `Max`) sets an
   auditable credit ceiling. Credits measure evidence-backed procedure; they do
   not increase ChatGPT's hidden reasoning compute and they never mean "done".
2. **ULTRA WORKFLOW** (`Off`, `2`, `3`, `5`, `8`) sets the maximum number of
   isolated candidate implementations. Candidate thinking is sequential; only
   machine verification runs in parallel.
3. **AOCS FRAMEWORK** (`None`, `AOCS Omega`) records whether the separate
   framework was deliberately selected. ULTRA never enables it implicitly.
4. **LOOPS** (`Off`, `2`, `5`, `10`) sets a bounded number of evidence-checked
   refinement passes, with no-repeat and no-gain stopping brakes.

These values form one locked Run Contract and are inherited by forks. The only
allowed changes are one-shot operator-approved extensions recorded in the audit.
Read
the matching, deliberately separate skills when a row is enabled:

- [harness-effort](docs/skills/harness-effort.md) for credit cycles and receipts.
- [harness-ultra](docs/skills/harness-ultra.md) for candidate orchestration only.
- [harness-loops](docs/skills/harness-loops.md) for bounded refinement passes.

Also raise **ChatGPT's own model/effort picker** for hard tasks. That is the real
model-compute control; the harness controls procedure, limits, evidence, and audit.

### Also proven/added in the first real-user session (2026-07-17/18)

- **Tasks work IN the project folder by default** (`HARNESS_DEFAULT_ISOLATION=workspace`,
  like Codex/Claude Code). Isolated worktrees are opt-in per session ("Where
  files go" in the New Session dialog, or `isolation='worktree'`).
- **Approvals hold the tool call open** (~90 s, `HARNESS_APPROVAL_WAIT_SECONDS`)
  while the operator clicks Approve/Deny — the chat no longer breaks at every
  approval; Deny returns a terminal error the model must not retry.
- **Long skills load fully** — `load_skill(name, offset)` pages content so a
  55k-char doctrine arrives complete instead of silently truncated.
- **Background process buffers** are capped at 1 M chars per process (dashcam
  semantics: newest output wins) and are per-task-owned — one task cannot read
  another's processes.

## Development

```powershell
python -m pytest tests -q     # 314 tests across security, tasks, permissions/approvals, isolation, cockpit, LSP, rules/hooks, federation, approval-wait, skills paging, …
python -m harness doctor      # validate config + environment
```
