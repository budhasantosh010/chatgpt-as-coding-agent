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

### The short way: double-click `start-tailscale.bat`

It runs all four steps below in order and **stops at the first failure with the
actual fix on screen**. `stop-tailscale.bat` shuts it down again (tunnel first,
then the engine).

The long way is below, because when the `.bat` stops you need to know what it
was doing.

### If this network blocks Tailscale: also double-click `start-ngrok.bat`

Some public, guest and hotspot networks filter Tailscale by policy and nothing
on your side fixes it (§13, failure ④). ngrok is a **second door to the same
harness** — not a second harness:

```
      ChatGPT                                two roads,
         |                                   one building
   +-----+-----+
   v           v
 funnel      ngrok
   |           |
   +-----+-----+
         v
  localhost:8848        <- same engine, same tasks, same files,
                           same state dir, same approved roots
```

Nothing migrates when you switch. The same task you started this morning over
the funnel is the same task this afternoon over ngrok.

**One-time setup:** claim a *reserved* domain at dashboard.ngrok.com → Domains
(a rotating URL is useless here — a ChatGPT connector is glued to one URL),
install ngrok, put the bare hostname in `.env` as `HARNESS_PUBLIC_HOST=`,
restart the engine, then add the second URL from `python -m harness url` as its
**own** ChatGPT connector. Full steps: README §2, *The second door*.

**Daily:** on a network that blocks Tailscale, double-click **`start-ngrok.bat`
on its own** — it starts the engine itself and never calls Tailscale. (Do not
reach for `start-tailscale.bat` there: its step 1 gates on `tailscale status` and
will stop before the engine ever starts.) To have both doors open on a good
network, run `start-tailscale.bat` first, then `start-ngrok.bat`.

You end up with two connectors in ChatGPT and pick whichever works today.

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
1-4. double-click start-tailscale.bat   (or run the four steps in §4 by hand)
4b.  OR double-click start-ngrok.bat   (if Tailscale is blocked - starts the
                                       engine itself, no Tailscale needed)
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

## 13. Troubleshooting — the failures that all look identical

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
   Fix:     Nothing fixes TAILSCALE here. Use the second door instead:
            start-ngrok.bat  (§4). Different company, different endpoints,
            so a filter aimed at Tailscale does not see it.

⑤ NGROK SAYS "ONLINE" BUT CHATGPT GETS 403
   Symptom: check-ngrok.ps1 → "HTTP 403 ... host not allowed"
   Cause:   the engine was started BEFORE HARNESS_PUBLIC_HOST was set.
            Config is read at startup only.
   Fix:     stop-ngrok.bat AND stop-tailscale.bat, then start the door you want.
            Confirm: python -m harness doctor → "second public door"

⑥ NGROK RETURNS A WEB PAGE INSTEAD OF JSON
   Symptom: check-ngrok.ps1 → "HTTP 200 text/html" / browser warning
   Cause:   ngrok's free-tier interstitial answered instead of the harness.
            ChatGPT cannot click through it.
   Fix:     check-ngrok.ps1 prints the three options. Simplest is to use
            the funnel door on a network that allows it.
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

---

## 18. The second door (ngrok) — the whole story

*Added 2026-08-25. Nothing above this line was changed or removed.*

### What it is, in one picture

```
                       ChatGPT
                          |
          +---------------+---------------+
          |                               |
          v                               v
   Tailscale Funnel                     ngrok            <- TWO ROADS
          |                               |
          +---------------+---------------+
                          |
                          v
                   localhost:8848                        <- ONE ENGINE
                          |
        tasks · workspaces · evidence · git · your files  <- ONE SET OF STUFF
```

**Not two harnesses. Two entrances to one building.** The task you started this
morning over Tailscale is the same task this afternoon over ngrok. Nothing
copies, nothing syncs, nothing migrates.

### Why it exists

Some networks — café, hotel, guest wifi, some hotspots — **block Tailscale on
purpose**. They read the name inside the encrypted handshake and silently drop
anything heading for a VPN service. Nothing you configure fixes it. That is
failure ④ in §13, and until now it had no remedy. ngrok is a different company
those filters don't recognise.

### The one requirement that decides everything: a RESERVED domain

```
 EPHEMERAL (ngrok's default)              RESERVED (what you need)
 ---------------------------              -----------------------
 Mon  a3f9-81-2-x.ngrok.app               Mon  yourname.ngrok-free.dev
 Tue  7c2e-81-2-x.ngrok.app   <- new!     Tue  yourname.ngrok-free.dev   <- same
 Wed  b81d-81-2-x.ngrok.app   <- new!     Wed  yourname.ngrok-free.dev   <- same

 = rebuild the ChatGPT connector DAILY    = set it up once, forever
```

A ChatGPT connector is **bound to one URL and caches its tool menu per URL** —
it cannot be re-pointed (see §13 failure ①). So a rotating URL means rebuilding
the connector every single day. Claim a reserved domain at
dashboard.ngrok.com → **Domains**. Free accounts get one.

### Installing ngrok — the part that will bite you

```
  ✗ DO NOT `winget install` and stop there.
      winget carries 3.3.1. ngrok REFUSES free-tier agents below 3.20.0.
      The error says "authentication failed" (ERR_NGROK_121) — your authtoken
      is fine. It is the VERSION. Reading only the first two words costs you
      an evening.

  ✗ DO NOT run `ngrok update`.
      It swaps the binary mid-flight; if your antivirus objects you are left
      with a PATH entry pointing at a file Windows refuses to open, and even
      `ngrok version` fails.

  ✓ DO download from ngrok's own CDN into a folder of its own:
      https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip
      -> C:\Users\<you>\tools\ngrok

  ✓ DO verify the signature BEFORE running it:
      Get-AuthenticodeSignature "C:\Users\<you>\tools\ngrok\ngrok.exe"
      expect:  Status   = Valid
               Signer   = CN="ngrok, Inc."
               Issuer   = DigiCert Trusted G4 Code Signing
```

**If Windows Defender blocks it** (it may flag it as
`Trojan:Win32/Kepavll!rfn`): on this machine that was a **verified false
positive** — the binary carries a DigiCert *Extended Validation* certificate,
meaning DigiCert legally verified ngrok, Inc. as a registered company. If you
add an exclusion, scope it to **that one folder**, and do it in this order:

```
   exclude one folder  ->  download  ->  VERIFY SIGNATURE  ->  then run
                                         ^
                                         the exclusion does not make it safe.
                                         It makes the EVIDENCE READABLE — the
                                         block was why you couldn't check.
```

An exclusion hiding an *unverified* binary is worse than the block it removed.

### Setup, once

```
 1. claim the reserved domain (dashboard.ngrok.com -> Domains)
 2. install + verify as above
 3. ngrok config add-authtoken <your token>
 4. put the BARE hostname in .env  (no https://, no port, no path):
        HARNESS_PUBLIC_HOST=yourname.ngrok-free.dev
    ^ NOT HARNESS_ALLOWED_HOSTS. That one REPLACES the default list and will
      403 your own Workbench at 127.0.0.1:8849.
 5. restart the engine — config is read at startup ONLY
 6. python -m harness url   -> prints BOTH URLs
 7. add the ngrok URL as its OWN ChatGPT connector (never edit the old one)
```

### Daily

```
   start-ngrok.bat        <- that's it
```

It starts the engine itself and **never calls Tailscale**, so it works on the
networks that break the funnel. (Do not reach for `start-tailscale.bat` there —
its step 1 gates on `tailscale status` and stops before the engine ever starts.)

Want both doors on a good network? `start-tailscale.bat`, then `start-ngrok.bat`.

To close just this door: `.\scripts\stop-ngrok.ps1` — the funnel is untouched.

### When it doesn't work

`start-ngrok.bat` ends by sending a **real MCP `initialize` down the real public
path**, because "ngrok online" only proves the agent reached ngrok's edge — it
says nothing about whether the harness accepted what arrived. The check names
which failure happened; see §13 ⑤ and ⑥.

### Where the full reasoning lives

Every decision behind this — including the ones that look like inconsistencies
worth cleaning up, and why cleaning them up would break something — is recorded
in **[docs/specs/second-door-decision-log.md](specs/second-door-decision-log.md)**.
The two install blockers and how they were settled are in
**[docs/specs/ngrok-defender-deadlock.md](specs/ngrok-defender-deadlock.md)**.

### What is still not proven

```
 [x] works over the real internet — real handshake, real file created
 [ ] NOT yet tested on a network that actually blocks Tailscale.
     The reason it exists is still unexercised.
 [ ] the free-tier interstitial was not observed — that is not the same
     as ruled out.
 [ ] this is not a security improvement. A second public entrance is a
     second public entrance. Every gate is exactly as it was.
```

---

## 19. "Neither door works after I changed WiFi"

*Added 2026-08-31. Nothing above this line was changed or removed.*

The first real diagnosis of a both-doors-down report. The reported symptom and
the actual cause had nothing to do with each other, which is the reason this
section exists.

### What was reported

> "check why it is not running, both the tailscale and ngrok are not running.
> I changed the wifi and this is on another network but it's not picking both"

The natural reading is *the new network broke the tunnels*. It had not. The new
network was innocent.

### What was actually true

```
                    ChatGPT
             +---------+---------+
             v                   v
      Tailscale Funnel         ngrok
      ON. Network clean.       NOT RUNNING -- nobody
      netcheck: UDP yes,       ever started it. It is
      no captive portal,       not a service and does
      DERP Dubai 15ms.         not survive a reboot.
             +---------+---------+
                       v
                localhost:8848
                DEAD  <-- the ONLY real fault
```

**One dead engine presents as two dead tunnels.** That is the whole lesson.
Because both doors lead to the same room, an empty room makes every door look
broken, and the operator reasonably blames the thing that changed — the WiFi.

`tailscale funnel status` still cheerfully printed `Funnel on`. It was telling
the truth: the funnel *was* on. A funnel with no backend returns **502**, and a
502 from a public URL is indistinguishable from a dead tunnel unless you look.

### The distinguishing test — 502 vs. no answer

This is the fastest way to tell the two apart, and it costs one command:

```
  curl the PUBLIC url:

    HTTP 502          -> the tunnel is FINE. The engine is down.
                         Fix the engine. Do not touch the tunnel.

    timeout / refused -> the tunnel is down (or the network blocks it).
                         Now the network is a fair suspect.

    HTTP 403          -> engine is up, tunnel is up, and the harness
                         REJECTED the Host. Engine was started before
                         HARNESS_PUBLIC_HOST was set. Restart the engine.
```

A 502 is the tunnel reporting *"I got through to your machine and nothing
answered."* It is evidence the tunnel works.

> **Refined by testing, 2026-08-31 — see [§21](#21-what-flying-diagnosebat-actually-changed).**
> The *first* probe after the engine dies can be a connection **reset** rather
> than a 502, because tailscaled still holds a pooled connection to the dead
> process. Every probe after that is a clean 502. So the rule above is right,
> but it is not what makes the diagnosis safe — **checking the engine before
> interpreting any public symptom is.**

### Why the engine was down

No crash. Checked and ruled out:

```
  Windows Event Log, Application, last hour   -> no error, no fault
  python.exe processes                        -> gone entirely
  cmd.exe windows                             -> gone (orphan conhosts left)
  engine.pid                                  -> STALE: held 9628, a dead PID
```

The engine runs in a console window. **Closing that window kills the harness.**
`stop-tailscale.bat` does the same thing deliberately. There is no service, no
auto-restart, and no supervisor — by design, but it means the harness is exactly
as alive as its window.

`engine.pid` is not a liveness check. It records the PID that *last started*,
and nothing clears it on exit. A present `engine.pid` proves nothing.

### The second trap: a local probe can lie about ngrok

After the tunnel was confirmed live, a PowerShell check kept timing out while a
Python one returned `HTTP 200`. Both hit the same URL, seconds apart.

The tiebreaker was ngrok's own counter — the only witness that cannot be argued
with:

```
  http://127.0.0.1:4040/api/tunnels   ->   conns: 1,  http: 1

  Still ONE, after two "failed" probes. The failing requests never
  reached ngrok's edge at all. So the tunnel was never the problem.
```

The cause, isolated:

```
  curl -4  https://<reserved>.ngrok-free.dev/   ->  HTTP 200,  0.14s
  curl -6  https://<reserved>.ngrok-free.dev/   ->  timeout,  15s
```

**IPv6 to ngrok's edge is broken on this network.** ngrok publishes AAAA records,
PowerShell 5.1's `Invoke-WebRequest` prefers IPv6 and does not fall back quickly;
`curl` and Python do Happy Eyeballs and drop to IPv4 in milliseconds. Same URL,
same instant, opposite verdicts — purely a difference in which tool you asked.

**This does not affect ChatGPT, and the reason matters.** ChatGPT's request goes
from *OpenAI's servers* to *ngrok's edge*. It never crosses the operator's WiFi
inbound. The only thing the laptop needs is its own **outbound** connection to
ngrok, which was established and live the whole time.

```
   OpenAI servers ---> ngrok edge ---> [outbound tunnel] ---> laptop
   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^                            ^^^^^^
   this leg never touches your WiFi                          only this
                                                             leg is yours
```

So: a local IPv6 fault makes *your own testing* fail while the product works.
Diagnose ngrok with `curl`, or with `scripts/check-ngrok.ps1` (which shells out
to Python for exactly this reason), never with bare `Invoke-WebRequest`.

### The fix, in order

```
  1. Start the engine.        Verify :8848 AND :8849 are listening.
  2. Probe LOCAL first.       http://127.0.0.1:8848/<secret>/mcp -> 200
                              If local fails, no tunnel can succeed.
  3. Probe the FUNNEL.        Already on; nothing to restart.
  4. Start ngrok.             scripts/ngrok.ps1 -- it is not automatic.
  5. Probe NGROK.             scripts/check-ngrok.ps1  (exit 0)
```

Working outward from the engine finds this in one pass. Starting at the tunnel
sends you to reconfigure the one part that was never broken.

### What to carry forward

**A shared dependency turns one failure into N symptoms.** Two doors, one engine:
kill the engine and you get two independent-looking faults, both pointing away
from the cause. When several things break at once, look for what they share
before you look at what changed.

**"Status: on" is intent; a request is evidence.** `tailscale funnel status` said
on, and was correct, and was useless. Only an end-to-end request distinguished
*configured* from *working* — the same lesson the fork bug, F1/F2, F3, the ngrok
version floor and the unpinned `mcp` each taught. Sixth entry in that list.

**When two tools disagree, neither is the witness — find the third.** PowerShell
said dead, Python said alive. ngrok's own request counter settled it, and pointed
at the measuring instrument rather than the thing measured.

---

## 20. `diagnose.bat` — the answer to "why can't ChatGPT connect?"

*Added 2026-08-31. Nothing above this line was changed or removed.*

§19 was a diagnosis done by hand. This is that diagnosis turned into a file you
double-click, so it never has to be redone from memory.

```
  diagnose.bat        READ-ONLY. Starts nothing, stops nothing, changes
                      nothing. Safe to run while ChatGPT is mid-task.
```

### What it prints

```
  [1] ENGINE          is the engine even alive? pid, and both ports
  [2] LOCAL path      does the engine answer a real MCP initialize?
  [3] TAILSCALE door  funnel config, THEN an actual probe
  [4] NGROK door      agent running? then an actual probe

  VERDICT             the part worth reading
```

Then one of five verdicts, each with the fix attached:

```
  both doors WORKING    -> prints the connector URLs
  ENGINE IS DOWN        -> and says so even when the doors return 502
  PORT MISMATCH         -> local dead, a door alive: the tunnel forwards
                           somewhere the config does not name
  no public door open   -> engine healthy, 403 / interstitial / not started
  config unreadable     -> wrong folder, or Python not on PATH
```

### Why it checks outward from the engine

Because **one engine sits behind both doors.** Kill it and both doors fail at
once, which reads like the network broke. Checking inward from the tunnel sends
you reconfiguring the one part that was never at fault. §19 is the full account
of that exact wrong turn.

The verdict it exists to deliver:

```
   502 from a public URL  ->  THE TUNNEL IS FINE. The engine is down.
```

### Two things it is careful about

**`engine.pid` is not a liveness check.** It records what last *started* and
nothing clears it on exit. When the recorded PID is not running, `diagnose`
says so out loud rather than trusting the file.

**"Funnel on" is intent, not proof.** The script prints the config line, then
prints — in the same breath — that only the probe below it is evidence.

### The measurement bug found while building it

The first working version took **2 minutes 3 seconds** to answer. It was right,
just unusable. The cause was not the harness:

```
  ngrok publishes AAAA records. getaddrinfo returns IPv6 first.
  Python tries addresses IN ORDER with no Happy Eyeballs fallback.
  On a network where IPv6 to the edge is broken, every probe burned
  the full timeout on each v6 address before reaching a working v4 one.

      before  2m 03s          after  3.6s          same verdict
```

Fixed by pinning `socket.getaddrinfo` to `AF_INET` for the probes. **This does
not weaken the check** — ChatGPT reaches the tunnel from OpenAI's servers, never
across this machine's Wi-Fi, so local IPv6 was never on the path being tested.
Pinning v4 makes the probe a *closer* match to what ChatGPT experiences.

`scripts/check-ngrok.ps1` had the identical defect, which means step `[3/3]` of
`start-ngrok.bat` had been stalling ~2 minutes on this network. Same fix.
`check-funnel.ps1` needed none: it already resolves A records only and connects
to those addresses directly, which is why the funnel probe was always fast.

Also removed while in there: both check scripts hardcoded
`C:\Python313\python.exe`. That breaks on the next Python upgrade and on every
other machine, and it fails *looking like a dead tunnel* rather than a missing
interpreter. Both now call `python`.

### How to test it yourself

The failure path is the part that matters, and you can exercise it for real:

```
  1. diagnose.bat            -> expect both doors WORKING
  2. stop-tailscale.bat        -> stops the engine, LEAVES ngrok running
  3. diagnose.bat            -> expect ENGINE IS DOWN, and the doors
                                reporting 502 rather than a timeout
  4. start-tailscale.bat       -> back up
  5. diagnose.bat            -> WORKING again
```

Step 3 is the whole point: **502, not timeout.** That is the tunnel telling you
it reached your machine and found nobody home. If you see a timeout there
instead, the tunnel really is down and the network is a fair suspect again.

---

## 21. What flying `diagnose.bat` actually changed

*Added 2026-08-31. Nothing above this line was changed or removed.*

§20 shipped with one branch untested — the 502 case needed a really-stopped
engine. It was then flown properly: engine killed, tunnels deliberately left up,
every branch driven through real states rather than reasoned about.

**Four bugs surfaced, three of which would have given confidently wrong advice.**
That is the whole argument for flying it, written out once more.

### The runs

| # | State forced | Expected | What happened |
|---|---|---|---|
| 1 | everything up | both WORKING | pass, 2.8s |
| 2 | engine killed, tunnels left up | ENGINE DOWN + 502 | pass — **and found bugs A, B, D** |
| 3 | engine trusting a bogus `PUBLIC_HOST` | ngrok 403 explained | pass — **confirmed fix C** |
| 4 | ngrok agent stopped | "start ngrok" | **failed — bug B** |
| 5 | rerun of 4 after fix | ERR_NGROK_3200 named | pass |

### Bug A — "502 = tunnel fine" was not the whole truth

§19 says a dead engine makes the funnel return 502. The **first** probe after the
engine dies can instead be a **connection reset** — tailscaled still holds a
pooled connection to the corpse. Every probe after that is a clean 502.

```
  engine killed
    probe 1   ConnectionResetError     <- stale pooled connection
    probe 2   502
    probe 3   502   ... consistently
```

The verdict was right anyway, and *why* it was right is the point: `diagnose`
checks the engine **before** interpreting any public symptom. Had it reasoned
backwards from "reset means the tunnel is down", it would have blamed the
network — the exact error §19 exists to prevent. **Checking order was doing the
work, not the 502 rule.**

### Bug B — ngrok's 404 was read as *your* 404

With the agent stopped, ngrok's edge answers:

```
  The endpoint <domain> is offline.
  ERR_NGROK_3200                        HTTP 404
```

The first version reported *"tunnel fine, but the secret route is wrong — the
ChatGPT connector needs rebuilding."* **Completely wrong, and expensive**: it
sends you rebuilding a connector that was never broken, when the fix is to start
ngrok.

A status code does not say who answered. Now the actual error code is carried
through and matched:

```
  ERR_NGROK_3200   endpoint offline  -> no agent serving. Start ngrok.
                                        Route and connector are FINE.
  ERR_NGROK_8012   agent up, upstream unreachable
                                     -> tunnel fine. The ENGINE is down.
```

Both otherwise arrive as a bare 404 and 502 — **status codes the harness itself
produces for entirely different reasons.**

### Bug C — a door's explanation was hidden by the other door working

The 403 / interstitial explanations only printed when **both** doors were down.
But the most common ngrok fault — a 403 from an engine started before
`HARNESS_PUBLIC_HOST` was set — usually happens while the funnel is perfectly
healthy. So the one case most likely to occur was the one guaranteed to print
`ngrok door: down` and nothing else.

Each door now explains itself regardless of what the other is doing.

### Bug D — a silent parse failure that read as "we skipped it"

The probe printed five fields on success and four on a connection error, while
the reader required five. A door that *refused the connection* therefore showed:

```
      public  not checked
```

Which reads as "we didn't look" rather than "it slammed the door". Worst kind of
bug in a diagnostic: it hides exactly when something is wrong.

### One more trap, avoided rather than hit

ngrok's 502 body is **HTML** for browser-ish clients and **text/plain** for a
JSON client. Sniffing content-type alone would have flagged it as the free-tier
interstitial — a third wrong answer. Matching on the error code sidesteps it.

### The measurement, again

```
  check-ngrok.ps1   before  >120s        after  2.9s
  diagnose.ps1      before  2m 03s       after  2.8s
```

Same verdicts throughout. The only thing that changed was how long it took to
say them.

### What is still not proven

- The **`ERR_NGROK_8012` branch is defensive, not flown.** Reaching it needs the
  agent forwarding to a port the engine is not on, and in every ordinary layout
  the engine check fires first and exits before that message can print.
- **"No public door at all"** was not flown. Reaching it means taking the funnel
  down, and the funnel is under a hard do-not-touch rule on this project.
- The harness's own **404** (genuinely wrong secret route) was not flown; only
  ngrok's lookalike was.

Three branches read but not flown, named here so nobody mistakes this section for
a claim of full coverage.

---

## 22. The bug that only a real user could find

*Added 2026-08-31. Nothing above this line was changed or removed.*

`diagnose.bat` was flown through every branch (§21) and each one gave a correct
answer. Then the operator ran it for the first time and said:

> **"I don't know if it is working or not here."**

The output they were looking at was *right*. It correctly found the engine down,
correctly explained why, and correctly named the fix. **And it still failed**,
because the person reading it could not tell what it was telling them.

### Why a correct answer read as noise

```
  [1] ENGINE      DOWN     DOWN     STALE          <- looks like errors
  [2] LOCAL       HTTP 0                           <- looks like errors
  [3] TAILSCALE   502                              <- looks like errors
  [4] NGROK       NOT RUNNING   404                <- looks like errors

  VERDICT ... eight lines of prose ...
  ... then a wall of three URLs ...
  Press any key to continue . . .                  <- the last thing on screen
```

Three things went wrong at once:

- **A screen of `DOWN` / `HTTP 0` / `404` reads as "the tool broke."** Someone
  who does not already know the tool cannot tell a *finding* from a *failure*.
- **The verdict was prose, not a signal.** Eight lines of explanation with no
  single word saying yes or no.
- **The answer was not last.** A terminal leaves you looking at whatever printed
  most recently, and that was three URLs and `Press any key`. The most useful
  line had already scrolled away.

### The fix

Every exit path now ends — **last, after everything else** — in one box:

```
  ##################################################
  ##
  ##   NOT WORKING - ChatGPT cannot connect right now.
  ##
  ##   DO THIS:  double-click start-ngrok.bat
  ##
  ##################################################
```

Green when it works, red when it does not, and always the final thing on screen.
Five exit paths, five banners: `WORKING`, `NOT WORKING`, `PORT MISMATCH`, and
`COULD NOT CHECK` (which says explicitly that it is *not* a harness fault, so a
missing Python does not get read as a broken tunnel).

All five were flown: engine down, port mismatch, and the healthy path driven
through real states, not reasoned about.

### The lesson, which is not a small one

**A diagnostic that is correct but unreadable has not done its job.** §21 proved
every branch produced the right answer. It could not have caught this, because
the failure was not in the logic — it was in whether a human could act on the
output. Correctness and usability are separate properties and need separate
tests.

Note also *how* it was caught. Not by the author, who knew what every line meant
and therefore could not see the problem. It took one person with no context
reading it cold — which is the same standard this project's documentation is
held to, now applied to its tools.

```
   2026-08-31   every branch correct   operator still could not read it
```

Seventh entry in the flight-lesson list, and the first where a green flight was
itself the thing that missed the bug.

---

## 23. Four files, one per door per direction

*Added 2026-08-31. Nothing above this line was changed or removed.*

The operator asked for the simplest possible surface: **click a file, it does
everything.** One start and one stop per door, nothing else to remember.

```
  start-tailscale.bat     open the Tailscale door
  stop-tailscale.bat      close it

  start-ngrok.bat         open the ngrok door
  stop-ngrok.bat          close it

  diagnose.bat            "is it working?"   read-only, safe any time
```

`start-harness.bat` and `stop-harness.bat` are gone — renamed to the
`-tailscale` pair. They were never "the harness", they were the Tailscale door,
and the old name implied that stopping Tailscale stopped everything.

### The rule that makes two stop files safe

There is **one engine behind both doors**. So a stop file that always killed the
engine would silently kill the *other* door too:

```
  ngrok open, Tailscale open
        |
        +-- stop-tailscale.bat  ... also kills the engine?
                                    then ngrok dies too, for no reason,
                                    and presents as "both doors dead" --
                                    the exact fault section 19 is about
```

So: **the engine is stopped by the LAST door to close, never the first.**

```
  close one door, other still open   ->  engine stays up  (says so on screen)
  close the last door                ->  engine stops with it
```

That lives in `scripts/engine-stop-if-idle.ps1`, shared by both stop files, so
the two can never disagree.

Each start file is the mirror: it starts the engine if it is not running and
**reuses it if it is**, so opening the second door never disturbs the first.

`start-tailscale.bat` also now starts the engine *before* opening the funnel.
A funnel opened over a dead engine answers 502 — which reads as a broken tunnel
and sends you debugging the one part that was fine.

### The bug this cleanup uncovered

Testing `stop-tailscale.bat` produced this:

```
  Turning off Tailscale Funnel for port 8848 ...
  Error: the CLI for serve and funnel has changed.
  Done. The public URL is no longer reachable.      <-- A LIE
```

`tailscale funnel <port> off` **was removed from the Tailscale CLI.** The old
`stop-funnel.ps1` ran it, ignored the non-zero exit, and printed "Done" anyway.

**The funnel stayed open every single time anyone ran the old stop script.**

This is the worst class of bug in a stop script: it hands you a false belief
about the state of a *public entrance to your machine*. You think the door is
shut. It is not.

It also produced a beautifully confusing second-order effect. The lie flowed
into `engine-stop-if-idle.ps1`, which saw a funnel still marked "on", and
therefore **correctly** declined to stop the engine. A correct decision, from a
correct rule, fed a false input — which is the hardest kind of fault to trace,
because every component you inspect looks right.

Fixed two ways:

```
  1. `tailscale funnel reset`   -- the current spelling
  2. VERIFY, then report        -- re-read the status and only claim
                                   success if the funnel is actually off
```

**A stop script that cannot prove it stopped anything is just a hopeful
message.** Every stop path now checks and says so.

### The URL does not change

Worth stating plainly, because `reset` sounds destructive. The funnel hostname
is a property of the tailnet, not of the funnel config, and `funnel.ps1`
recreates exactly the same mapping. Verified by round-trip: closed, reopened,
and the same `desktop-fdce9ak.taila47816.ts.net` URL came back working. Your
ChatGPT connector never needs rebuilding.

### All four flown

| File | State it was run from | Result |
|---|---|---|
| `stop-ngrok.bat` | both doors open | ngrok closed, **engine left up** |
| `stop-tailscale.bat` | last door open | funnel closed **and verified**, engine stopped |
| `start-tailscale.bat` | everything stopped | engine + funnel up, **same URL** |
| `start-ngrok.bat` | engine already running | **reused** the engine, ngrok up |

Ending state: one engine, one ngrok agent, both doors returning a real MCP
handshake, `diagnose.bat` green.

### Addendum — two more things, found after §23 was written

**`timeout` cannot be used in the engine-wait loop.** `timeout /t 1 /nobreak`
reads the console directly and aborts with *"Input redirection is not
supported"* whenever stdin is not a real console — scripted runs, CI, anything
piped. The loop still worked, but it printed four lines of red `ERROR` text that
look exactly like a real failure. Replaced with `ping -n 2 127.0.0.1 >nul`,
which is redirect-safe. Verified side by side in an isolated batch file:
`timeout` errors, `ping` does not.

A double-click never hit this. It only appears when a *script* runs the
launcher — which is to say, it only ever lied to the person testing it.

**Tailscale's own suggested "off" command is also stale.** When the funnel
starts, Tailscale prints `To disable the proxy, run: tailscale funnel
--https=443 off`. That spelling is as dead as the one in §23. Use
`tailscale funnel reset`. The stale hint inside `start-tailscale.bat` was
corrected too.

### Known issue, unresolved: Tailscale daemon stuck in `NoState`

During this testing the Tailscale backend wedged:

```
  tailscale status        # Health check:
                          #   - Tailscale is starting. Please wait.
                          unexpected state: NoState

  BackendState  NoState        TailscaleIPs  null
  HaveNodeKey   true           AuthURL       ""      <- not a logout
  Service       Running                              <- not a crash
```

`HaveNodeKey: true` with no `AuthURL` means it is **not** logged out and does
not need re-authentication. The service is running. The backend simply never
finished starting. Neither `tailscale up` (exit 0, no output) nor
`tailscale down` + `up` cleared it.

**Honest note on cause:** this appeared during a session that ran
`tailscale funnel reset` and `tailscale funnel --bg 8848` repeatedly while
testing the stop/start pair. That is not proof it was the trigger, and the
mechanism is unknown — but it is the obvious correlation and is recorded rather
than quietly omitted.

The fix needs an elevated service restart, which is an operator action:

```
  Run PowerShell as Administrator:
      Restart-Service Tailscale
  Then:  tailscale status        (expect BackendState "Running")
         start-tailscale.bat
```

**The ngrok door carried the whole load throughout.** With Tailscale completely
dead, `diagnose.bat` reported `WORKING - ChatGPT can connect (ngrok)` and the
harness stayed usable. That is precisely the scenario the second door was built
for — and the first time it has been needed for real rather than rehearsed.
