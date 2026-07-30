# chatgpt-code-harness

Code with your **ChatGPT** subscription the way you code with Claude Code or
Codex. ChatGPT is the brain; this is a local MCP server that gives it hands on
your machine, reachable through a Tailscale Funnel.

**No model-provider API is ever called.** The only cost is the ChatGPT
subscription you already pay for.

> ### 👉 New here? Read **[docs/USING-THE-HARNESS.md](docs/USING-THE-HARNESS.md)**
> The complete operator manual, written for zero prior context: what it is, how
> to start it, where everything is stored, how permissions work, how to fork,
> how to survive chat lag, all 68 tools, and an honest comparison against the
> alternatives — including where this is worse.

**Status:** all phases complete and signed (2026-07-29). 68 tools, 477 tests
green, flown end to end on a real project. What was *not* done is recorded in
[docs/specs/four-controls-progress.md](docs/specs/four-controls-progress.md) —
notably that the controlled benchmark arms were never run, so **nothing here
claims the controls improve outcomes**, only that they are enforced as specified.

---

## Table of contents

| # | Section | What's in it |
|---|---|---|
| 1 | [Quickstart](#1-quickstart--double-click-one-file) | Double-click one file and go |
| 2 | [Connect it to ChatGPT](#2-connect-it-to-chatgpt) | The connector, and the cache trap |
| 3 | [What makes this different](#3-what-makes-this-different) | Proof, gates, contracts |
| 4 | [The 68 tools](#4-the-tools-chatgpt-sees-68) | Grouped by job |
| 5 | [Permission modes](#5-permission-modes-and-the-ceiling) | Plan / ask / auto / bypass / full |
| 6 | [Surviving chat lag](#6-surviving-chat-lag--the-turn-ledger) | The Turn Ledger |
| 7 | [Run Contracts](#7-the-four-independent-run-contract-controls) | EFFORT · ULTRA · FRAMEWORK · LOOPS |
| 8 | [Security & threat model](#8-security--threat-model) | Boundaries, and honest limits |
| 9 | [Architecture](#9-architecture-and-how-to-extend-it) | Layout, how to add a tool |
| 10 | [Field-tested findings](#10-field-tested-july-2026-the-validated-architecture) | What parallelism really does here |
| 11 | [Troubleshooting](#11-troubleshooting) | Four failures that look identical |
| 12 | [Development](#12-development) | Tests, doctor |
| — | [Which doc is which](#which-doc-is-which) | Read this before trusting a doc |

---

```
ChatGPT  ──MCP over HTTPS──►  Tailscale Funnel  ──►  localhost:8848
                                                       │  secret route + Host/Origin gate
                                                       ▼
                                              chatgpt-code-harness
                                              read/write/edit/glob/grep/shell
                                                       ▼
                                              your approved workspace
```

## 1. Quickstart — double-click one file

```
start-harness.bat      ← starts everything
stop-harness.bat       ← shuts it down
```

`start-harness.bat` runs the four steps that have to happen in order, and
**stops at the first failure with that failure's actual fix on screen**:

```
[1/4] Tailscale logged in?          ✗ → this network blocks VPNs, use home Wi-Fi
[2/4] Open the funnel               → prints your public MCP URL
[3/4] Engine :8848 + Workbench :8849  → polls the port until it's really up
[4/4] check-funnel.ps1              → the ONLY step that tests the real
                                        public path ChatGPT uses
READY → opens http://127.0.0.1:8849
```

Step 4 is not cosmetic. `tailscale funnel status` reads local config and will
report a healthy funnel that routes nowhere, and probing your own `*.ts.net`
name from your own machine is answered inside the tailnet without ever leaving
the building. Both look green when nothing works.

<details>
<summary>By hand, if you prefer (or to see what the .bat is doing)</summary>

```powershell
tailscale status                 # must be logged in
.\scripts\funnel.ps1             # open the tunnel, print the MCP URL
python -m harness up             # engine + Workbench, opens the browser
.\scripts\check-funnel.ps1       # prove ChatGPT can actually reach you
```

`python -m harness up` starts **everything**: the operator GUI (the
**Workbench**) on `http://127.0.0.1:8849`, opens it in your browser, and runs
the MCP engine on :8848 as a child process.
</details>

```
 ┌──────────────────┐         ┌──────────────────┐
 │  WINDOW 1        │   MCP   │  THE ENGINE      │
 │  ChatGPT         │────────▶│  :8848 (child)   │
 │  (you type here, │ funnel  │  files/git/shell │
 │   the brain)     │         └────────┬─────────┘
 └──────────────────┘                  │ localhost only, never funneled
                              ┌────────▼─────────┐
                              │  WINDOW 2        │
                              │  THE WORKBENCH   │
                              │  :8849 — projects│
                              │  sessions, modes │
                              │  live activity,  │
                              │  approvals, diffs│
                              └──────────────────┘
```

**The Workbench gives you the Codex-style GUI:** a project sidebar, sessions
underneath each project, a permission-mode dropdown per session, a live feed of
what ChatGPT is doing right now, one-click approve/deny, visual diffs, and
drag-and-drop files. It is **localhost-only and never exposed through the
funnel** — approvals must stay beyond the model's reach, which is what makes an
operator-only acceptance gate mean anything.

Its inspector has five tabs — **Activity · Changes · Terminal · Files ·
Approvals** — and the Approvals tab carries a count badge, with a red pill in the
top bar, so you don't have to sit watching it.

(In the source tree the module is `harness/cockpit/` — same thing, older name.
See [docs/COCKPIT_DESIGN.md](docs/COCKPIT_DESIGN.md).)

<details>
<summary>First-run setup (once per machine)</summary>

```powershell
copy .env.example .env           # set HARNESS_WORKSPACE_ROOTS=C:\path\to\projects
python -m harness doctor         # sanity-check config + environment
```

A folder must be an **approved root** before the model can touch it. Add one
with the **[＋] Add project** button in the Workbench, or
`python -m harness roots add <path>`. The approved list lives in the state dir,
outside every workspace, so the model can never widen its own reach.
</details>

Then add it to ChatGPT (below) and tell ChatGPT: *"Open workspace
C:\path\to\project and start a task: ..."*.

## 2. Connect it to ChatGPT

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

> ### ⚠ The connector cache trap — read this before you debug anything
>
> ChatGPT caches a connector's **tool menu** per URL. If you add or rename a
> tool, **editing the existing connector is not enough** — it keeps serving the
> old menu, and you will see the wrong tool count with no error anywhere.
>
> The fix is to rotate `secret_route.txt` and add a **brand new connector**.
>
> Also: ChatGPT saying *"I rechecked the connector"* means it made a `tools/call`
> and counted from cache. `tools/call` ≠ `tools/list`. The only proof the menu
> was re-read is a fresh `tools/list` from agent `openai-mcp/*` in
> `<state_dir>/connector.jsonl`.

**Other MCP clients (Claude Desktop, IDE extensions):** run
`python -m harness stdio` and point the client at it as a stdio MCP server — the
same 68 tools, no Tailscale or secret route needed (the process boundary is the
trust boundary).

## 3. What makes this different

Every other coding agent works on **trust**: the model says "done, tests pass,"
and you believe it or check yourself. This one doesn't.

```
THE MODEL SUPPLIES              THE SERVER SUPPLIES
prose: an exec_id, a reason     the command, the fingerprint, the verdict
                                      │
     "I ran the tests, px-b3c91c7f" ──┤
                                      ▼
                        did the harness observe this run?   ✅ else reject
                        did it exit 0?                      ✅ else reject
                        is it fresh?                        ✅ else reject
                        is it owned by THIS task?           ✅ else reject
                        have files changed since?           ✅ else reject
                        is it a real verification command?  ✅ else reject
```

Live, against a model actively trying to close a task, this refused:

| Attempt | Refusal |
|---|---|
| `pytest` that exited 1 | a failure is not proof |
| a borrowed `exec_id` from another task | not owned |
| `echo done` (exit 0) | not a recognized verification command |

**Running a command is not permission to call it proof.**

And acceptance criteria come in two kinds:

```
AC-1  "pytest passes"          machine   → the server re-checks the evidence
AC-2  "this reads well to me"  operator  → [OPERATOR_REQUIRED]
                                            only a click in the local Workbench
                                            can ever satisfy it. Not reachable
                                            through the funnel. Not by the model.
```

In the signed flight the model did every other part of the work correctly and
**still could not mark the task done.** It waited for a human, because there was
no other path.

## 4. The tools ChatGPT sees (68)

**Orient (2)** — `open_workspace(path)` (call first: git state, structure,
project rules, suggested test/build commands, remembered facts),
`session_status()` (resume: git changes, todos, recent actions).

**Project & task lifecycle (14)** — `create_project` (new folder + git init,
confined to an approved root), `register_project`, `start_task(project, goal,
permission_mode)` → a `task_id` you thread through every call so concurrent
conversations stay isolated, `task_status`, `list_tasks`, `advance_task`,
`set_task_goal`, `create_subtask`, `fork_task` (same base, own worktree — two
approaches side by side), `resume_task` (pick up in a NEW chat), `finish_task`
(refuses without proof), `cancel_task`.

**Contracts, evidence, governance (10)** — `set_acceptance_criteria`,
`satisfy_criterion` (server re-validates), `begin_cycle` / `complete_cycle` /
`abandon_cycle` (audited credit cycles + receipts), `begin_refinement_pass` /
`complete_refinement_pass`, `get_effort_status`, `request_extension`
(operator-approved, one-shot), `record_framework_routing`.

**Turn Ledger (2)** — `publish_turn`, `discard_turn`. See §6.

**Inspect (8)** — `read_file`, `list_dir`, `glob` (skips node_modules & friends),
`read_image`, `write_file`, `edit_file`, `apply_edits` (atomic multi-file patch,
auto-rollback on failure), `apply_patch`.

**Search & code intelligence (6)** — `grep` (ripgrep), `repo_map` (structural
overview), and real LSP: `lsp_definition`, `lsp_references`, `lsp_hover`,
`lsp_symbols` — go-to-definition / find-references / types from a language
server, not text search. Auto-detects pyright/pylsp/typescript-language-server/
rust-analyzer/gopls; if none is installed it says exactly what to install.

**Execute (6)** — `run_command` (PowerShell on Windows). Background:
`start_process`, `read_process`, `write_process`, `stop_process`,
`list_processes` (dev servers, `test --watch`).

**Git, review & undo (9)** — `git_diff`, `git_commit`, `open_pr`,
`create_checkpoint`, `list_checkpoints`, `restore_checkpoint` (private git ref;
never touches your branch/history), `create_worktree`, `list_worktrees`,
`remove_worktree`.

**Diagnostics (1)** — `diagnostics_check` (type errors / lint).

**Notebooks (2)** — `notebook_read`, `notebook_edit`.

**Remember (3)** — `remember`, `recall`, `forget` (per-workspace memory,
auto-surfaced on open).

**Plan (2)** — `write_todos`, `list_todos` (survives turn resets, shown in
`session_status`).

**Extend (2)** — `list_skills`, `load_skill` (loadable how-to docs from the
workspace and `~/.agents/skills`; paged, so long doctrines arrive complete).

**Federation (3)** — `mcp_servers`, `mcp_tools`, `mcp_call` (other MCP servers;
calling one never auto-runs below `full`).

## 5. Permission modes and the ceiling

All six live in the Workbench — the **New session** dialog and the dropdown on a
running session.

| Mode | ≈ Claude Code | ≈ Codex | What it does |
|---|---|---|---|
| `read_only` | — | read-only | Look. Touch nothing. |
| `plan` | Plan mode | plan | Read + write you a plan. No edits, no commands. |
| `build_ask` | default | approval prompts | Every edit and command asks first. |
| **`auto_workspace`** ★ | acceptEdits | auto | Edits + local commands run free; network, installs, `git push`, deploys, DB writes and external MCP calls still ask. |
| `bypass_sandboxed` | — | — | No approvals, inside Docker with `network=none`. |
| `full` | bypassPermissions | full-access | No brakes. |

`auto_workspace` doesn't just ask "is this a command?" — it classifies **what the
command reaches for**:

```
pytest · npm run build      → runs
git push                    → ASKS   (touches a remote)
pip install x               → ASKS   (touches a registry)
curl …                      → ASKS   (touches the network)
terraform apply             → ASKS   (touches infrastructure)
psql … DROP …               → ASKS   (touches a database)
mcp_call(<other server>)    → ASKS   (can do anything)
```

### The ceiling

```
HARNESS_MAX_MODE  (default: auto_workspace)
   │
   ├── ChatGPT may request up to this line. Above it, start_task REFUSES and
   │   names the ceiling — rejection, not a silent clamp, so the model plans
   │   around the powers it actually has.
   │
   └── YOU are above the line. The Workbench is localhost-only, so choosing
       `full` there IS the operator speaking. The choice is recorded as
       `operator_elevated`, or `effective_mode()` would clamp it back on the
       next tool call and your decision would evaporate silently.

Same thing from a terminal:  python -m harness tasks set-mode <task_id> full
```

`bypass_sandboxed` renders **disabled** unless `HARNESS_SANDBOX=docker`. That's
not a permission question — with no container there is no sandbox to rely on, so
the server would only degrade it back to `auto_workspace`. Offering it would be
a lie.

Tool calls **without** a `task_id` run in a shared read-only fallback session, so
a forgotten handle can't silently write.

**Unrecognized commands ask by default** (`HARNESS_ARBITRARY_COMMANDS=ask`).
Everyday dev commands (`pytest`, `npm test`, linters, local git) are a positive
*safe tier* that always runs, so ask-mode is safe without being annoying. When
something new does ask, approve it once — or tick **remember** (or
`approvals approve <id> --remember`) to always allow that **exact** command in
that **one** project. The remembered list lives in the state dir, outside every
workspace root, so the model can never write its own allowlist.

## 6. Surviving chat lag — the Turn Ledger

ChatGPT's chat UI degrades after roughly 15+ long messages. Nothing here can fix
that — it's OpenAI's client. What the harness does is make escaping it free.

**Why this needs a feature at all:** MCP carries a tool name and a JSON argument
object. That is the entire wire. **The server has never seen a word of your
conversation and cannot.** So capture is impossible; the model must *publish*.

```
   In the slow chat:   "publish_turn — summarise what we just did"
                              │
                              ▼
        tasks/<task_id>/chat/turns.jsonl
        · what you asked   · what was answered
        · decisions made   · what's next
                              │
   In a BRAND NEW chat:  "resume_task T-<id>"  ──┘   nothing lost
```

Two guards worth knowing:

- `finish_task` refuses while observed work is unpublished — you cannot close a
  task whose ledger has a blind spot. (The finishing call itself is discounted,
  or the gate would deadlock on its own invocation.)
- **Nothing under `chat/` can satisfy a gate or spend a credit.** It is the
  model's own account, labelled `model_published` — a memo, not a recording.

If `publish_turn` genuinely can't be written, `discard_turn(reason)` records the
*hole*, so a gap is visible rather than silent.

## 7. The four independent Run Contract controls

The Workbench locks four separate choices **before** a run starts (`Confirm &
lock`). They form one Run Contract, inherited by forks. The only allowed change
afterwards is a one-shot operator-approved extension, recorded in the audit.

| Control | Options | What it bounds |
|---|---|---|
| **EFFORT** | `Off` `Low·2` `Med·8` `High·16` `XHigh·32` `Max·50` | An auditable credit ceiling. Each cycle spends one credit and writes a receipt to disk. |
| **ULTRA** | `Off` `2` `3` `5` `8` `Custom≤64` | Maximum isolated candidate implementations — "don't take your first idea." |
| **FRAMEWORK** | `None` `AOCS Omega` | Whether a methodology was deliberately selected. ULTRA never enables it implicitly. |
| **LOOPS** | `Off` `2` `5` `10` `Custom≤100` | Bounded refinement passes, with no-repeat and no-gain stopping brakes. |

> **EFFORT credits are an audit budget, not model depth.** They measure
> evidence-backed procedure. They do **not** increase ChatGPT's reasoning
> compute, and they never mean "done" — every required criterion still has to be
> proven. For hard problems also raise **ChatGPT's own model/effort picker**;
> that is the real compute control. The harness controls procedure, limits,
> evidence and audit.

Read the matching, deliberately separate skills when a row is enabled:

- [harness-effort](docs/skills/harness-effort.md) — credit cycles and receipts.
- [harness-ultra](docs/skills/harness-ultra.md) — candidate orchestration only.
- [harness-loops](docs/skills/harness-loops.md) — bounded refinement passes.
- [harness-turns](docs/skills/harness-turns.md) — publishing turns so a new chat
  can resume the task; model-published context, never evidence.

## 8. Security & threat model

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

## 9. Architecture (and how to extend it)

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

## 10. Field-tested (July 2026): the validated architecture

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

## 11. Troubleshooting

**Four different failures all present to you as "ChatGPT can't connect."** They
have completely different causes and completely different fixes. Diagnose in
this order — guessing costs more than checking.

| # | Symptom | Cause | Fix |
|---|---|---|---|
| ① | Connects fine, but the tool count is wrong or a tool is "missing" | ChatGPT cached the tool menu for that connector URL | Rotate `secret_route.txt`, add a **brand new** connector. Editing the old one does nothing. |
| ② | `mcp_network_error`; `[Errno 10048]` on startup | Engine not running, or a stale one still holds :8848/:8849 | `stop-harness.bat`, then `start-harness.bat` |
| ③ | `check-funnel.ps1` fails, but `tailscale funnel status` says "Funnel on" | **It's lying** — it reads local config, not the actual ingress | `tailscale funnel --https=443 off; tailscale funnel --bg 8848` (URL doesn't change) |
| ④ | `tailscale status` → `Logged out` / `NoState` | This network blocks Tailscale: public/guest Wi-Fi and some hotspots filter VPN control endpoints by TLS SNI and silently drop them. Signature: TCP connects, TLS handshake times out. | **None from your side.** Use a network that permits it. |

> **The trap that fooled us once:** probing your own `*.ts.net` name from your own
> machine returns HTTP 200 even when the public path is dead — MagicDNS answers
> it inside the tailnet and the request never leaves. That's why
> `check-funnel.ps1` resolves the **public** ingress IPs via Google DNS and sets
> SNI by hand. Never accept a localhost or MagicDNS probe as proof of public
> reach.

**Refusals are not failures.** They name their own reason and are almost always
right — `[OPERATOR_REQUIRED]`, `[EVIDENCE_INVALID] … not owned`,
`[TURN_UNPUBLISHED]`. Every one is decoded in
[docs/USING-THE-HARNESS.md §16](docs/USING-THE-HARNESS.md).

## 12. Development

```powershell
python -m pytest -q          # 477 tests: security, tasks, contracts, evidence,
                             # effort ledger, turn ledger, permissions/approvals,
                             # mode ceiling, isolation, cockpit, LSP, rules/hooks,
                             # federation, approval-wait, skills paging, …
python -m harness doctor     # validate config + environment
```

## Which doc is which

Three docs overlap because they were written at different times. **Trust them in
this order** — this table exists so a stale sentence in an old doc never
outranks a current one.

| Doc | Status | Authoritative for |
|---|---|---|
| **[docs/USING-THE-HARNESS.md](docs/USING-THE-HARNESS.md)** | ✅ **current** (2026-07-29) | Everything. Startup, disk layout, permission modes + the ceiling, approvals, forking, the Turn Ledger, all 68 tools, the comparison, refusal messages, hard limits. |
| [docs/MANUAL.md](docs/MANUAL.md) | ⚠️ older deep-dive | Still useful for the **full operator CLI command list**, `~/.agents/skills` loading, and gotchas. Its mode and startup sections predate the Workbench dropdown and the `.bat` launcher — prefer the doc above where they disagree. |
| [docs/COMPARISON.md](docs/COMPARISON.md) | ⚠️ stale (2026-07-16) | Historical detail and sources. It predates the Turn Ledger, Run Contracts and the signed flight. The current comparison is §12 of the doc above. |
| [docs/specs/four-controls-progress.md](docs/specs/four-controls-progress.md) | ✅ current | The signed acceptance record — **and what was deliberately not done.** |
| [docs/specs/turn-ledger-flight-failures.md](docs/specs/turn-ledger-flight-failures.md) | ✅ current | The three defects real flights found that green tests missed. |
| [docs/COCKPIT_DESIGN.md](docs/COCKPIT_DESIGN.md) | reference | Workbench design intent. |

## Honest summary

This is a **personal, single-operator tool**, primitive in places, with a
governance layer no other coding agent has. It is slower than Claude Code and
Codex CLI (every action is an internet round trip), has no editor integration or
autocomplete, and ChatGPT follows tool instructions less reliably than
purpose-built agent models. In exchange, "done" has to be **proven to a server**
rather than asserted by a model, some criteria are **structurally impossible**
for the model to sign off, and you can drive your real machine from your phone.

There is **no measured claim** that any of this improves outcomes — the
controlled benchmark arms were never run. What is proven is that the controls are
enforced exactly as specified, live, against a model that tried to get around
them.
