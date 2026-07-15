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

## Quickstart

```powershell
# 1. Point it at the folders ChatGPT may touch
copy .env.example .env
#    edit .env: set HARNESS_WORKSPACE_ROOTS=C:\path\to\your\projects

# 2. Sanity-check config + environment
python -m harness doctor

# 3. Run the server (localhost only)
python -m harness serve          # or: .\scripts\run.ps1

# 4. In another terminal, expose it to ChatGPT and print the URL
.\scripts\funnel.ps1             # runs `tailscale funnel` + prints the MCP URL
```

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
same 51 tools, no Tailscale or secret route needed (the process boundary is the
trust boundary).

## The tools ChatGPT sees (51)

**Tasks (the isolation handle)** — `start_task(project, goal, permission_mode)`
returns a `task_id` you thread through every call so concurrent conversations
stay isolated; `list_tasks`, `task_status`, `resume_task`, `set_task_goal`,
`set_acceptance_criteria`, `advance_task`, `finish_task`, `cancel_task`,
`create_subtask`, `register_project`.

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
are **operator-only**, granted locally with `python -m harness tasks set-mode`.
Tool calls **without** a `task_id` run in a shared read-only fallback session,
so a forgotten handle can't silently write.

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
  __main__.py    CLI: serve / doctor / url
  config.py      12-factor config (env + .env), persisted secret route
  context.py     HarnessContext — injected into every tool (no globals)
  policy.py      Capability + PermissionPolicy — the one place modes are decided
  security.py    path confinement / secret globs / command denylist (isolated, tested)
  session.py     per-workspace event log (resume support)
  proc.py        one async subprocess impl (non-blocking) + shell_argv
  executor.py    Executor port: LocalExecutor (default) / DockerExecutor (sandbox)
  hooks.py       pre/post-tool hooks (audit, output scrubbing, future policy)
  scrub.py       secret-content redaction (a post-tool hook)
  middleware.py  pure-ASGI security shell (SSE-safe)
  server.py      FastMCP: thin typed tool wrappers + capability + lifecycle hooks
  tools/         files / search / shell / workspace — pure async logic over hc
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
and (on a git repo) a **separate physical worktree**, so two tasks on one project
never edit the same files. Without a `task_id`, calls share a read-only fallback
session.

**Roadmap (deliberately later):** git itself running inside the container (today
it runs on host with hooks/config neutralized), full Windows process-tree kill,
richer sandbox backends. Autonomous LLM sub-agents are N/A by design — the harness
has no model; it offers subtasks instead.

## Development

```powershell
python -m pytest tests -q     # 216 tests across security, tasks, permissions/approvals, isolation, code-intel, federation, …
python -m harness doctor      # validate config + environment
```
