# Using the harness — the complete manual

Written for someone with zero context. Nothing assumed, nothing skipped.
If you read only this file you should be able to run the whole system.

Last verified: 2026-07-29 · commit `6a49dce` · 471 tests green · 68 tools live.

---

## 0. The one-paragraph version

ChatGPT is the brain. Your PC is the hands. A Tailscale Funnel is the wire
between them. You talk to ChatGPT like normal; ChatGPT calls tools that run on
YOUR machine, in YOUR folders, with YOUR Python. A local web page (the
Workbench) is your dashboard for watching and approving. No AI company API is
ever billed — the only cost is the ChatGPT subscription you already pay for.

---

## 1. Is it built? What percentage?

```
BUILT AND PROVEN                                             ~95%
├── 68 MCP tools                                     ✅ live, counted
├── 471 automated tests                              ✅ all green
├── Phases 0–8 of the Four Controls spec             ✅ complete
├── Workbench GUI (projects, sessions, approvals)    ✅ working
├── Tailscale Funnel + secret route                  ✅ ChatGPT connects
├── Contracts / credits / receipts                   ✅ flown live
├── Server-validated evidence                        ✅ refused 3 fake proofs
├── Operator-only acceptance gate                    ✅ blocked the AI live
└── Turn Ledger (resume in a new chat)               ✅ flown live

REMAINING                                                     ~5%
├── Phase 9 signature — the flight HAPPENED, the doc isn't ticked
├── MCP Apps `ui://` card spike — never attempted (nice-to-have)
└── 19 junk sessions cluttering the Workbench sidebar
```

**Answer: yes, you can do real coding work with it today.** The remaining 5% is
paperwork and polish, not function.

---

## 2. The mental model

```
   YOU                    THE INTERNET                  YOUR PC
   ───                    ────────────                  ───────

  ┌──────────┐                                    ┌────────────────────┐
  │ ChatGPT  │                                    │  harness engine    │
  │ phone /  │  ── MCP over HTTPS ──►  Tailscale  │  :8848             │
  │ web /    │      (68 tools)          Funnel ──►│  reads/writes your │
  │ desktop  │  ◄── tool results ────              │  actual files      │
  └──────────┘                                    └─────────┬──────────┘
       ▲                                                    │
       │  you type here                                     │ same process tree
       │                                          ┌─────────▼──────────┐
       └── you WATCH + APPROVE here ─────────────►│  Workbench GUI     │
                                                   │  localhost:8849    │
                                                   └────────────────────┘
```

Three facts that explain almost every behaviour:

1. **MCP carries tool calls, not conversation.** The server sees
   `run_command("pytest")`. It never sees what you and ChatGPT said. This is
   why the Turn Ledger exists (§9) — the model has to *publish* the
   conversation, because the server cannot capture it.
2. **The Workbench is localhost-only.** It is not on the funnel. Only someone
   sitting at your PC can reach it. That's what makes operator approval mean
   something.
3. **The model supplies prose, the server supplies facts.** ChatGPT writes the
   *reason*; the server writes the *command* and the *fingerprint*. A model
   can never author its own evidence.

---

## 3. Where everything lives on disk

This is the answer to "where are my sessions and projects?"

```
C:\Users\Lenovo\.chatgpt-code-harness\          ← THE STATE DIR (like ~/.claude)
│
├── tasks.db                    SQLite. Every task: goal, mode, contract,
│                               acceptance criteria, lifecycle. 26 rows today.
│
├── tasks\                      One folder per task, for things too big for SQL
│   └── T-df66550dbd02a833b86dc607\
│       ├── chat\
│       │   ├── turns.jsonl     ← THE TURN LEDGER. Published conversation.
│       │   ├── transcript.md   ← human-readable version of the same
│       │   └── open.json       ← the turn in progress, not yet published
│       └── effort\
│           └── cy-*.md         ← effort receipts (one per cycle)
│
├── sessions\<16-hex>\meta.json  MCP connection sessions (plumbing, not chats)
│
├── worktrees\                  Isolated git copies for forked/parallel work
├── workspaces\                 (scratch)
├── memory\                     remember/recall storage
│
├── roots.json                  ← THE FOLDERS THE MODEL IS ALLOWED TO TOUCH
├── allowed_commands.json       ← "always allow this exact command here"
├── secret_route.txt            ← the secret path in your public URL
├── connector.jsonl             ← log of every ChatGPT connection
├── audit.jsonl                 ← log of every tool call
└── engine.pid
```

**Important difference from Codex / Claude Code:**

```
Claude Code   ~/.claude/projects/<slug>/<uuid>.jsonl   = the raw chat transcript
Codex         ~/.codex/sessions/...                     = the raw chat transcript
THIS HARNESS  tasks\<id>\chat\turns.jsonl               = a PUBLISHED SUMMARY
```

Claude Code and Codex own the chat window, so they save every word for free.
This harness does not own the chat window — ChatGPT does, and ChatGPT does not
hand it over. So instead of a raw transcript you get a **deliberately published
ledger**: what you asked, what was answered, what was decided, what's next.
Less detail, but it survives a dead chat, which a raw transcript in someone
else's product does not.

Your **code** lives wherever you made it (e.g. `C:\Users\Lenovo\Music\testing
projects\tests\big test`). The harness does not copy or move your project —
unlike Codex Cloud, which works on a copy in OpenAI's sandbox.

---

## 4. Starting it — every time, in order

### The short way: double-click `start-harness.bat`

It runs all four steps below in order and **stops at the first failure with the
actual fix on screen**. `stop-harness.bat` shuts it down again (tunnel first,
then the engine).

The long way is below, because when the `.bat` stops you need to know what it
was doing.

### Step 1 — Tailscale must be logged in

```powershell
tailscale status
```

* Shows a list of machines → good.
* Says `Logged out` or `NoState` → the **network is blocking Tailscale**.
  Public Wi-Fi, guest Wi-Fi and some mobile hotspots do this by policy
  (they filter the VPN control servers by name in the TLS handshake).
  Nothing you can configure fixes it. Use home Wi-Fi.
  Log back in with `tailscale up`.

### Step 2 — Open the tunnel

```powershell
.\scripts\funnel.ps1
```

Prints your public MCP URL. Looks like:

```
https://desktop-fdce9ak.taila47816.ts.net/<secret-route>/mcp
```

### Step 3 — Start the engine + Workbench

```powershell
python -m harness up
```

Starts the MCP engine on `:8848`, starts the Workbench on `:8849`, and opens
`http://127.0.0.1:8849` in your browser.

### Step 4 — Prove ChatGPT can actually reach you

```powershell
.\scripts\check-funnel.ps1
```

This is not optional and it is not cosmetic. `tailscale funnel status` reads
local config and will cheerfully say "Funnel on" while the ingress has no route
to your machine. Probing your own `*.ts.net` name from your own PC is answered
*inside* the tailnet and never touches the public path. `check-funnel.ps1`
connects to the real public ingress IPs the way OpenAI does. Green = ChatGPT
can connect. Anything else = it can't, no matter what the other commands say.

### Step 5 — Connect ChatGPT

ChatGPT → **Settings → Connectors → Add** → paste the URL from Step 2.

> **The cache trap.** ChatGPT caches a connector's tool menu per URL. If you
> add or rename a tool, editing the existing connector is **not enough** — it
> keeps serving the old menu. Rotate `secret_route.txt` and add a **brand new
> connector**. This is why you once saw 66 tools when the server had 68.
> "I rechecked the connector" from ChatGPT means it made a *call*, not that it
> re-read the *menu*. The only proof is a fresh `tools/list` from agent
> `openai-mcp/*` in `connector.jsonl`.

---

## 5. Adding a project — the "drag a folder" equivalent

In Cursor/Codex/Claude Code you point at a folder and go. Here there is one
extra step, on purpose: **a folder the model can touch must be approved by
you, at your PC, first.** That approval list is `roots.json`.

```
   Workbench  http://127.0.0.1:8849
   ┌──────────────────────────────────────────┐
   │  [＋]  ← "Add project" (top of sidebar,   │
   │         and the button at the bottom)     │
   └──────────────────────────────────────────┘
                    │
                    ▼   pick the folder
            written into roots.json
                    │
                    ▼
        ChatGPT can now open it. In chat:

        "Open C:\path\to\my project and start a task:
         <what you want done>"
```

ChatGPT will call `open_workspace` (orientation: git branch, status, recent
commits, project type, structure, any AGENTS.md/CLAUDE.md rules) and
`start_task` (binds folder + goal + permission mode, returns a `task_id`).

Two other ways in:

* `register_project` — an existing folder you already have.
* `create_project` — a brand-new folder; git-inits it with a first commit so
  worktrees work immediately.

**By default files land directly in your project folder**, exactly like Codex
and Claude Code. Isolated copies are opt-in (§8).

---

## 6. The daily loop

```
1-4. double-click start-harness.bat   (or run the four steps in §4 by hand)
5. Workbench: [＋] add project (first time only)
6. ChatGPT:   "Open <path> and start a task: <goal>"
7. ...code, chat, iterate...
8. Workbench: watch Activity / Changes / approve anything pending
9. Before the chat gets long:  "publish_turn"
10. Done:  "finish_task with result <...>"
```

That's it. Steps 1–4 are ~20 seconds once you know them.

---

## 7. Permission modes — the Approve / Plan / Auto / Bypass question

All six live in the **New session** dialog and in the mode dropdown on a running
session. ChatGPT can also set them via `start_task(permission_mode=...)` — but
only up to the ceiling (see below the table).

```
THIS HARNESS       ≈ CLAUDE CODE        ≈ CODEX          WHAT IT ACTUALLY DOES
──────────────────────────────────────────────────────────────────────────────
read_only          (no direct equiv)    read-only        Look. Touch nothing.

plan               Plan mode            plan             Read + think + write
                                                          you a plan. No edits,
                                                          no commands.

build_ask          default mode         (approval        Every edit and command
                   (asks each time)      prompts)         asks YOU first.

auto_workspace     acceptEdits          auto /           Edits + local commands
                   (+ allowed tools)     workspace-write  run free. Network,
                                                          installs, git push,
                                                          deploys, DB writes,
                                                          external MCP calls
                                                          still ASK. ★ default

bypass_sandboxed   (no equiv)           (no equiv)       Everything runs, but
                                                          inside Docker with
                                                          network=none. Falls
                                                          back to auto_workspace
                                                          if Docker isn't there.

full               bypassPermissions    full-access      No brakes.
                   (--dangerously-…)     (--yolo)
```

### The ceiling — why the last two say "operator only"

```
HARNESS_MAX_MODE  (default: auto_workspace)
        │
        ├── ChatGPT may request anything up to this line.
        │   Above it, start_task REFUSES — it names the ceiling rather
        │   than silently clamping, so the model plans around the powers
        │   it actually has.
        │
        └── YOU are above the line. The Workbench is localhost-only, so
            picking `full` there IS the operator speaking. The choice is
            recorded as `operator_elevated`, or the server would clamp it
            straight back on the next tool call.

Equivalent from a terminal:
    python -m harness tasks set-mode <task_id> full
```

`bypass_sandboxed` is greyed out unless `HARNESS_SANDBOX=docker`. That is not a
permission question — without a container there is no sandbox to rely on, so
the server would only degrade it back to `auto_workspace`. Showing it as
selectable would be a lie.

`auto_workspace` is the one you want almost always. Here's *why* it's safer
than "auto" elsewhere — it doesn't just check "is this a command?", it
classifies **what the command reaches for**:

```
run_command("pytest")            → COMMAND_SAFE       → runs
run_command("npm run build")     → unrecognized       → runs (or asks, if
                                                        HARNESS_ARBITRARY_
                                                        COMMANDS=ask)
run_command("git push")          → GIT_REMOTE_WRITE   → ASKS YOU
run_command("pip install x")     → PACKAGE_INSTALL    → ASKS YOU
run_command("curl …")            → NETWORK            → ASKS YOU
run_command("terraform apply")   → DEPLOYMENT         → ASKS YOU
run_command("psql … DROP …")     → DATABASE_MUTATION  → ASKS YOU
mcp_call(<some other server>)    → EXTERNAL_CALL      → ASKS YOU
```

**Honesty note, copied from the source:** this classifier is *hardening, not a
security boundary*. A regex cannot know what `python -c "..."` does. The real
boundaries are the mode table and the Docker sandbox. The code says so in a
comment — it does not pretend.

### Where you click to approve

```
Workbench → right-hand INSPECTOR panel
   ┌──────────┬─────────┬──────────┬───────┬─────────────┐
   │ Activity │ Changes │ Terminal │ Files │ Approvals ③ │  ← badge = waiting
   └──────────┴─────────┴──────────┴───────┴─────────────┘
                                              │
                                              ▼
                                    [ Approve ]  [ Deny ]
                                    [ ] remember this command
```

Tick **remember** and that *exact* command in *that exact project* never asks
again — it's written to `allowed_commands.json`. Exact match, whitespace
normalized, per-project. Allowing `npm run generate` in project A allows
nothing else, nowhere else. And that file lives in the state dir, **outside
every project root**, so the model's own file tools physically cannot write it.
The AI cannot grant itself permissions.

There's also a red **needs attention** pill in the top bar so you don't have to
sit staring at the Approvals tab.

---

## 8. Forking — two branches from the middle of one session

You asked exactly the right question. There are **two** different tools, for
two different situations.

```
SITUATION A — "try approach X and approach Y, keep both, compare"
────────────────────────────────────────────────────────────────
  fork_task(task_id, goal="try it with a hash map instead")

  T-original ──┬── keeps its worktree, untouched, still runnable
               └── T-fork ── NEW worktree from the SAME base commit
                             copies goal + acceptance criteria + plan

  In chat:  "Fork this task and try the recursive approach instead."
            Then talk to whichever task_id you want.


SITUATION B — "same task, but do the risky bit somewhere safe"
──────────────────────────────────────────────────────────────
  create_worktree(name, base=<branch or commit>)

  A git worktree = a second checkout of the same repo, on its own branch,
  in its own folder. Your main checkout is never touched.

  In chat:  "Make a worktree called risky-refactor and work there."
```

You can also choose isolation up front, in the New session dialog:

```
   Where files go
   ┌───────────────────────────────────────────────┐
   │ ● In the project folder (recommended)         │  ← like Codex/Claude Code
   │ ○ Isolated copy (for parallel experiments)    │  ← worktree
   └───────────────────────────────────────────────┘
```

And there's a third, stronger idea — **ULTRA candidates** (§10) — where the
harness *requires* N genuinely different attempts before anything can be
accepted.

---

## 9. When ChatGPT gets slow — the Turn Ledger

This is a real, unavoidable problem. ChatGPT's chat UI degrades after roughly
15+ long messages. Nothing in this repo can fix that; it's OpenAI's client.

What the harness does instead is make the slowdown **cheap to escape**.

### publish_turn, every WH question

```
WHAT   A tool that writes one entry into the task's Turn Ledger:
       what you asked · what was answered · decisions made · what's next.

WHO    ChatGPT calls it. Not you. You never type `publish_turn(...)` —
       you say "publish the turn" in plain English and it makes the call.

WHERE  ~/.chatgpt-code-harness/tasks/<task_id>/chat/turns.jsonl
       (a readable copy lands next to it as transcript.md)

WHEN   After a stretch of real work, before starting the next stretch.
       In practice: when the chat starts feeling slow, or before you close it.

WHY    Because the server CANNOT see your conversation. MCP carries a tool
       name and a JSON object — that is the whole wire. If ChatGPT does not
       deliberately hand the conversation over, it does not exist anywhere
       outside that one chat window, and when the window dies, so does it.

HOW    You:      "publish_turn — summarise what we just did"
       New chat: "resume_task T-<id>"

CATCH  What it writes is the MODEL's account of the conversation, labelled
       `model_published`. It is a memo, not a recording. Nothing in chat/
       can ever satisfy a gate or spend a credit — precisely because the
       model wrote it.
```

```
        THE PROBLEM                        THE FIX
        ───────────                        ───────

   chat gets slow                    every so often, ChatGPT calls
        │                                  publish_turn(...)
        ▼                                      │
   you start a new chat                        ▼
        │                            tasks\<id>\chat\turns.jsonl
        ▼                             ┌──────────────────────────┐
   ✗ new chat knows NOTHING           │ what you asked           │
     ✗ what you were building        │ what was answered        │
     ✗ what was decided              │ decisions made           │
     ✗ what's next                   │ what should happen next  │
                                      └──────────────────────────┘
                                                 │
   ✓ in the new chat you type:                   │
     "resume_task T-<id>"  ──────────────────────┘
                │
                ▼
     ChatGPT reads the whole ledger back and carries on.
```

**What to do when it lags:**

```
1. In the slow chat:  "publish_turn — summarise what we just did"
2. Copy the task_id   (it's in every reply, and in the Workbench)
3. Open a NEW ChatGPT chat
4. Type:  "resume_task T-df66550dbd02a833b86dc607"
5. Carry on. Nothing lost.
```

If `publish_turn` genuinely can't be written, `discard_turn(reason)` records
the *hole* in the ledger — so a gap is visible rather than silent.

**Two safety rules worth knowing:**

* `finish_task` refuses if there is observed-but-unpublished work. You cannot
  finish a task whose ledger has a blind spot. (One exception, hard-won: the
  `finish_task` call itself is discounted, or it would deadlock on its own
  invocation.)
* Nothing in `chat/` can ever satisfy a gate or spend a credit. It's the
  model's own words — labelled `model_published`, never treated as evidence.

---

## 10. Contracts — the part no other tool has

When you create a session in the Workbench, you set a **contract**. It's locked
at creation (`Confirm & lock`) and the model works inside it.

```
┌─ EFFORT ─── procedure credits ────────────────────────────────┐
│  Off · Low 2 · Med 8 · High 16 · XHigh 32 · Max 50            │
│                                                                │
│  A budget of AUDITED WORK CYCLES, not model depth.             │
│  Each cycle: begin_cycle(question, verification_plan)          │
│              → work → complete_cycle(evidence)                 │
│              → spends 1 credit, writes a receipt to disk       │
│  Out of credits? request_extension() — YOU approve, one-shot.  │
│  ⚠ This does NOT change how hard ChatGPT thinks. Set that      │
│    in ChatGPT's own model picker.                              │
└────────────────────────────────────────────────────────────────┘

┌─ ULTRA ──── sequential candidates ────────────────────────────┐
│  Off · 2 · 3 · 5 · 8 · Custom (max 64)                        │
│  Forces N genuinely different attempts before acceptance.      │
│  "Don't take your first idea."                                 │
└────────────────────────────────────────────────────────────────┘

┌─ LOOPS ──── bounded refinement ───────────────────────────────┐
│  Off · 2 · 5 · 10 · Custom (max 100)                          │
│  begin_refinement_pass / complete_refinement_pass              │
│  "Keep improving — but you get N passes, then stop."           │
│  Stops the infinite-polish spiral.                             │
└────────────────────────────────────────────────────────────────┘

┌─ FRAMEWORK ─── None · AOCS Omega ─────────────────────────────┐
│  Optional methodology routing.                                 │
└────────────────────────────────────────────────────────────────┘

┌─ TASK TYPE ─── Build · Review · Plan · Research ──────────────┐
└────────────────────────────────────────────────────────────────┘
```

### Acceptance criteria and the operator gate

```
set_acceptance_criteria(task_id, [
    {id: "AC-1", text: "pytest passes",              kind: "machine"},
    {id: "AC-2", text: "the slug reads well to me",  kind: "operator"},
])

  AC-1  machine   → satisfy_criterion with a real execution id.
                    The SERVER re-checks it (see below).

  AC-2  operator  → the model calls satisfy_criterion and gets:
                        [OPERATOR_REQUIRED]
                    Only a click in the local Workbench can tick it.
                    Not reachable from the funnel. Not reachable by the model.
                    Ever.
```

### How the server validates evidence

The model hands over an `exec_id` and a reason. The server then checks, on its
own records:

```
  did the harness itself observe this execution?        ✅ else reject
  did it exit 0?                                        ✅ else reject
  is it fresh (not a stale old run)?                    ✅ else reject
  is it owned by THIS task?                             ✅ else reject
  have the files changed since it ran?                  ✅ else reject
  is it a RECOGNIZED verification command,
     or explicitly operator-approved?                   ✅ else reject
```

Live, in the big test, this refused three things:

```
  ✗ pytest that exited 1        "a failure is not proof"
  ✗ a borrowed old exec_id      "not owned"
  ✗ echo done (exit 0)          "not a recognized verification command"
```

Running a command is not permission to call it proof.

---

## 11. All 68 tools, grouped

```
PROJECT & TASK LIFECYCLE (14)
├── create_project           make a new folder, git-init, register
├── register_project         adopt an existing folder
├── open_workspace           enter a folder + get orientation
├── start_task               bind folder + goal + mode → task_id
├── task_status              where is this task?
├── list_tasks               everything on the go
├── advance_task             move through the lifecycle
├── set_task_goal            change the goal
├── create_subtask           break work down
├── fork_task                two approaches side by side
├── resume_task              pick up in a NEW chat
├── finish_task              close it — needs proof
├── cancel_task              abandon it
└── session_status           connection + mode + budget

CONTRACTS, EVIDENCE, GOVERNANCE (10)
├── set_acceptance_criteria  define what "done" means
├── satisfy_criterion        prove one — server re-checks
├── begin_cycle              open an audited effort cycle
├── complete_cycle           close it, spend a credit, write a receipt
├── abandon_cycle            close it without spending
├── begin_refinement_pass    open a LOOPS pass
├── complete_refinement_pass close it
├── get_effort_status        credits left
├── request_extension        ask YOU for more
└── record_framework_routing methodology choice

TURN LEDGER (2)
├── publish_turn             save this turn so a new chat can resume
└── discard_turn             record a gap honestly

FILES (8)
├── read_file · write_file · edit_file · apply_edits · apply_patch
├── list_dir · glob · read_image

SEARCH & CODE INTELLIGENCE (6)
├── grep                     content search
├── repo_map                 structural overview
├── lsp_definition · lsp_hover · lsp_references · lsp_symbols
                             real language-server jump-to-def etc.

SHELL & PROCESSES (6)
├── run_command              one-shot, permission-classified
├── start_process            long-running (dev server, watcher)
├── read_process · write_process · stop_process · list_processes

GIT & VERSION CONTROL (8)
├── git_diff · git_commit · open_pr
├── create_worktree · list_worktrees · remove_worktree
├── create_checkpoint · restore_checkpoint · list_checkpoints

DIAGNOSTICS (1)
└── diagnostics_check        type errors / lint

NOTEBOOKS (2)
└── notebook_read · notebook_edit

MEMORY (3)
└── remember · recall · forget

TODOS (2)
└── write_todos · list_todos

SKILLS (2)
└── list_skills · load_skill

FEDERATION — other MCP servers (3)
├── mcp_servers              what else is connected
├── mcp_tools                what can they do
└── mcp_call                 call one (always asks below `full`)
```

---

## 12. Complete comparison — everything each tool does

> My knowledge of the other tools has a May 2026 cutoff and they all ship
> weekly. Treat the ✅/❌ as accurate-as-of-then, not eternal.

### What THEY have that this harness does NOT

```
FEATURE                        CC   CODEX  CURSOR  OPENCODE  HARNESS
─────────────────────────────────────────────────────────────────────
Inline tab autocomplete        ❌    ❌      ✅      ❌         ❌
IDE integration / inline diff  ✅    ✅      ✅      ~          ❌
Terminal TUI                   ✅    ✅      ❌      ✅         ❌
Sub-agents / parallel agents   ✅    ~       ✅      ✅         ❌ (fork only)
Model choice (multi-provider)  ❌    ❌      ✅      ✅         ❌
Local-speed (no round trip)    ✅    ✅      ✅      ✅         ❌
Raw full chat transcript saved ✅    ✅      ✅      ✅         ❌ (ledger)
Codebase embedding index       ❌    ❌      ✅      ❌         ❌
Team / multi-user              ~     ✅      ✅      ~          ❌
Cloud delegation (runs w/o PC) ✅    ✅      ✅      ❌         ❌
Slash commands / hooks         ✅    ~       ~       ✅         ❌
Web search built in            ✅    ~       ✅      ~          ~ (ChatGPT's)
Mature, supported, many users  ✅    ✅      ✅      ✅         ❌ (n=1, you)
```

### What THIS HARNESS has that none of them do

```
FEATURE                                       CC  CODEX CURSOR OPENCODE HARNESS
───────────────────────────────────────────────────────────────────────────────
Server-VALIDATED evidence
  (AI's claim re-checked against the
   server's own execution records)            ❌   ❌     ❌     ❌       ✅
Acceptance criteria as a hard gate            ❌   ❌     ❌     ❌       ✅
Operator-ONLY criterion the AI
  structurally cannot satisfy                 ❌   ❌     ❌     ❌       ✅
Audited effort credits + receipts on disk     ❌   ❌     ❌     ❌       ✅
One-shot operator-approved extensions         ❌   ❌     ❌     ❌       ✅
Enforced N-candidate exploration (ULTRA)      ❌   ❌     ❌     ❌       ✅
Bounded refinement passes (LOOPS)             ❌   ❌     ❌     ❌       ✅
Provenance labelling on every fact
  (operator/model_reported/model_published/
   machine_observed)                          ❌   ❌     ❌     ❌       ✅
Drive your real PC from a PHONE               ❌   ❌     ❌     ❌       ✅
Works from ANY ChatGPT client                 ❌   ❌     ❌     ❌       ✅
Command classifier by REACH
  (network/install/deploy/db as classes)      ~    ~      ❌     ❌       ✅
Allowlist the model cannot write to           ~    ~      ❌     ❌       ✅
You own and can change every rule             ❌   ❌     ❌     ✅       ✅
£0 marginal cost on an existing sub           ~    ✅     ❌     ❌       ✅
```

### Shared ground (everyone does these)

```
read/write/edit files · run shell commands · grep/glob search · git ops ·
run tests · multi-step agentic loops · MCP client · project rules file
(CLAUDE.md / AGENTS.md) · session resume · permission modes · todo tracking
```

### The honest bottom line

```
Claude Code / Codex CLI  — FASTER. Local, no round trip, purpose-built agent
                            models, mature. If you're at your desk doing a big
                            refactor, they beat this.

Cursor                   — BEST for typing code yourself with AI help.
                            Autocomplete is a different category. Not a
                            competitor to this; a complement.

OpenCode                 — most similar in spirit (open, yours, hackable) but
                            you pay per token to a provider, and it has no
                            governance layer.

THIS HARNESS             — SLOWER and rougher, but the only one where "done"
                            has to be PROVEN to a server rather than asserted
                            by a model, and the only one you can drive from
                            your phone against your real machine.
```

`£0` needs one honesty caveat: **Codex CLI can also sign in with a ChatGPT
subscription.** "Code on my own machine with my ChatGPT sub" is no longer
unique. The governance layer and the any-client access are what's unique.

---

## 13. Troubleshooting — four failures that all look identical

Every one of these presents to you as "ChatGPT can't connect." They have
completely different causes and completely different fixes. Diagnose in order.

```
① CONNECTOR CACHE
   Symptom: connects fine, but the tool count is wrong / a tool is "missing"
   Cause:   ChatGPT cached the tool menu for that connector URL
   Fix:     rotate secret_route.txt, add a BRAND NEW connector
   Proof:   fresh tools/list from openai-mcp/* in connector.jsonl

② ENGINE DOWN
   Symptom: mcp_network_error; [Errno 10048] on startup
   Cause:   engine not running, or an old one still holding :8848/:8849
   Fix:     python -m harness up   (kill the stale process if the port is held)
   Check:   check-funnel.ps1 line 1 says "engine :8848 listening : True"

③ FUNNEL DEREGISTERED
   Symptom: check-funnel.ps1 fails; `tailscale funnel status` says "Funnel on"
            ← IT IS LYING. It reads local config, not the actual ingress.
   Fix:     tailscale funnel --https=443 off; tailscale funnel --bg 8848
   Note:    the URL does not change.

④ THE NETWORK BLOCKS TAILSCALE
   Symptom: tailscale status → "Logged out" / "NoState"
   Cause:   public/guest Wi-Fi and some hotspots filter VPN control endpoints
            by the hostname in the TLS handshake (SNI), and silently drop them.
            Signature: TCP connects, TLS handshake times out.
   Fix:     NONE from your side. Use a network that permits it. Home works.
```

**The trap that fooled me once:** probing `desktop-fdce9ak.taila47816.ts.net`
from your own PC returns HTTP 200 even when the public path is dead — MagicDNS
answers it inside the tailnet (IP `100.66.47.70`) and it never leaves. That is
why `check-funnel.ps1` resolves the **public** IPs via Google DNS and sets SNI
manually. Never trust a localhost or MagicDNS probe as proof of public reach.

---

## 14. Hard limits — things that will never work

Not bugs. Architecture.

```
✗ The server can never read your conversation.
    MCP carries tool calls and a JSON argument object. That's the wire.
    Everything the model "tells" the harness about the chat is published
    by the model, on purpose, and is labelled as such.

✗ A rendered ChatGPT reply can never be read back.
    Even if the MCP Apps `ui://` card lands, it's a sandboxed iframe.

✗ One user, one machine. Not a team product.

✗ Round-trip latency is permanent. Every tool call goes
    ChatGPT → OpenAI → internet → Tailscale → your PC → back.

✗ ChatGPT is not an agent-tuned model. It follows tool instructions less
    reliably than Claude Code's or Codex's models. Be explicit.

✗ Chat lag after ~15 messages is OpenAI's client. The Turn Ledger makes it
    survivable, not absent.
```

---

## 15. Copy-paste phrases for ChatGPT

```
START
  Open C:\path\to\project and start a task: <what you want>.
  Use permission mode auto_workspace.

CONTRACT
  Set acceptance criteria: AC-1 "pytest passes" (machine),
  AC-2 "the output reads well to me" (operator).

WORK
  <just talk normally>

PARALLEL
  Fork this task and try <the other approach> instead.
  Make a worktree called <name> and work there.

BEFORE THE CHAT GETS SLOW
  publish_turn — summarise what we just did and what's next.

NEW CHAT
  resume_task T-<id>

FINISH
  finish_task on T-<id> with result "<what you built>" and the pytest evidence.

WHEN IT REFUSES
  Read the refusal. It names the exact reason. It is almost always right.
```

---

## 16. Every refusal message, and what it means

```
[OPERATOR_REQUIRED]
   → An operator-kind criterion. Go tick it in the Workbench. Only you can.

[EVIDENCE_INVALID] … rejected: execution is missing, stale, or not owned
   → The exec_id doesn't belong to this task, or the files changed after it ran.
     Re-run the verification now, cite the new id.

[EVIDENCE_INVALID] … command is not a recognized verification
   → `echo done` isn't a test. Run an actual test command.

[TURN_UNPUBLISHED]
   → You have observed work not in the ledger. Call publish_turn first.

Task is new; move it to review_ready
   → Lifecycle order. advance_task before finish_task.

no server-valid evidence references — <reasons>
   → Since the fix, this always names WHY each reference failed. Read it.

Not completed: contracted tasks require valid proof for every required
criterion. Still open: AC-2 (open).
   → It did the work. It cannot sign off. That's the design working.
```

---

## 17. What's actually left to build

```
✔ Phase 9 — signed 2026-07-29. See docs/specs/four-controls-progress.md.
✗ MCP Apps `ui://` card — DESCOPED by the operator. Not needed.
✗ Controlled benchmark arms — NOT RUN, and recorded as not run.
    There is no measured claim that the four controls improve outcomes,
    only that they are enforced as specified. Don't let anyone say otherwise.

Open, cosmetic:
  · Archive the junk sessions in the Workbench sidebar.
```

Nothing on that list blocks you from using it today.
