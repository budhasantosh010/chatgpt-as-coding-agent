# The Complete Manual — read this first

This explains **the whole system**, in plain words, with nothing hidden.
If you finish this page you know everything the person who built it knows.

Every simple word has the **real technical word in (brackets)** next to it, so
when someone asks you the "official" term, you have it. That way nothing gets
lost when you explain it to someone else.

---

## 1. What is this thing?

ChatGPT can **think** but it cannot **touch** your computer. It can't open your
folders, save a file, or run a program.

This project gives ChatGPT hands.

```
   ChatGPT  =  the BRAIN   — thinks, decides, writes the code
   Harness  =  the HANDS   — opens files, saves them, runs them
```

Picture a **brilliant architect on the phone** and a **builder in your house**:

```
   ┌─────────────┐       phone call        ┌──────────────┐
   │  ARCHITECT  │ ──────────────────────▶ │   BUILDER    │
   │  (ChatGPT)  │  "put a window here"    │ (the harness │
   │  far away,  │ ◀────────────────────── │  on YOUR pc) │
   │  no hands   │  "done — here's a photo"└──────┬───────┘
   └─────────────┘                                │
                                                  ▼
                                          YOUR REAL FILES
```

The architect never touches the house. It phones instructions to the builder,
and the builder does the real work. **That is the entire idea.**

> Real words: the harness is an **MCP server**. **MCP (Model Context Protocol)**
> is just the shared language ChatGPT and the harness both speak.
>
> **Important:** this harness has **no AI inside it**. It never calls OpenAI or
> Anthropic. ChatGPT is the only brain. The harness is dumb hands — it only does
> exactly what it's told, and only what it's allowed.

---

## 2. The whole system in one picture

```
   INTERNET                                      YOUR LAPTOP
 ┌──────────┐   secret link   ┌────────────┐   door 8848   ┌──────────────┐
 │ ChatGPT  │ ──────────────▶ │  Tailscale │ ────────────▶ │   HARNESS    │
 │ (brain)  │ ◀────────────── │   Funnel   │ ◀──────────── │   (hands)    │
 └──────────┘                 │  (tunnel)  │               └──────┬───────┘
                              └────────────┘                      │
                                                                  ▼
                                                    ┌─────────────────────────┐
                                                    │  WALL 1: ROOTS (where)  │
                                                    │  WALL 2: MODE  (what)   │
                                                    └───────────┬─────────────┘
                                                                ▼
                                                          YOUR PROJECT FILES
```

The pieces:

```
Tailscale Funnel ─ a private tunnel that pokes ONE tiny hole from the internet
                   to your laptop, so ChatGPT can reach the harness.

Secret route ───── a huge random password baked INTO the web link:
                   https://your-pc.ts.net/Xy7qA9...random.../mcp
                                          └── this gibberish IS the password ──┘
                   Wrong/absent password → the door doesn't even open (404).

Door 8848 ──────── the "port" the harness listens on, on your laptop only.
```

---

## 3. THE MOST IMPORTANT IDEA: two separate walls

This is the thing everyone gets confused about. There are **two independent
walls**, and they do completely different jobs.

```
   WALL 1 — ROOTS  answers:  "WHERE is ChatGPT allowed to be?"
   WALL 2 — MODE   answers:  "WHAT is ChatGPT allowed to do there?"
```

Like a hotel:

```
   ROOT  = which ROOMS your keycard opens.        (WHERE)
   MODE  = what you're allowed to DO in the room. (WHAT)
           look only? / rearrange furniture? / knock down a wall?
```

**They are checked separately, every single time:**

```
   ChatGPT asks: "write to C:\Windows\system32\evil.dll"
        │
        ├── WALL 2 (mode): "auto_workspace allows writing"  ✅ passes
        │
        └── WALL 1 (roots): "that path is NOT inside an allowed root" ❌ BLOCKED
                                                                   
   Result: BLOCKED. Even though the mode said yes.
```

### 🔑 The rule you must never forget

```
 ┌──────────────────────────────────────────────────────────────────┐
 │  NO MODE — not full, not bypass — EVER lets ChatGPT out of the   │
 │  roots. Modes only change WHAT it can do INSIDE the rooms you     │
 │  already unlocked. The roots wall is always on, for every mode.   │
 └──────────────────────────────────────────────────────────────────┘
```

> Real words: Wall 1 is **path confinement** (`resolve_read` / `resolve_write` →
> `resolve_in_roots` in `security.py`). Wall 2 is the **permission policy**
> (`policy.py` + `permissions.py`). They're different code and run independently.

---

## 4. The MODE dial — what each one means, exactly

```
 read_only ──▶ plan ──▶ build_ask ──▶ auto_workspace ──▶ full ──▶ bypass_sandboxed
 └── less power ─────────────────────────────────────────────── more power ──┘
                            ▲                    ▲
                     normal setting         THE CEILING
                     (ChatGPT's default)    ChatGPT CANNOT reach these two
                                            by itself — only YOU can grant them
```

Exactly what each mode allows:

| Mode | Read files | Write/edit files | Run commands | Risky stuff (push, install, internet) | Call other MCP servers |
|---|---|---|---|---|---|
| `read_only` | ✅ | ❌ no | ❌ no | ❌ no | list only |
| `plan` | ✅ | ❌ no | ❌ no | ❌ no | list only |
| `build_ask` | ✅ | ⏸ asks you | ⏸ asks you | ⏸ asks you | ⏸ asks you |
| `auto_workspace` ← **normal** | ✅ | ✅ auto | ✅ auto | ⏸ **asks you** | ⏸ asks you |
| `full` | ✅ | ✅ auto | ✅ auto | ✅ **auto, no asking** | ✅ auto |
| `bypass_sandboxed` | ✅ | ✅ auto | ✅ auto | ✅ **auto, no asking** | ✅ auto |

**`read_only` vs `plan`** — same permissions today. The difference is *intent*:
`plan` tells ChatGPT "investigate and give me a plan"; `read_only` says "just
look." Neither can change anything.

### What does `bypass_sandboxed` actually do? (your exact question)

```
 bypass_sandboxed  =  "STOP ASKING ME FOR APPROVAL — I'm relying on the
                       Docker container to keep things safe instead."
```

What it does **NOT** do:

```
 ❌ It does NOT let ChatGPT out of your roots.       (Wall 1 still on!)
 ❌ It does NOT give access to other folders.
 ❌ It does NOT turn off secret-file blocking.
 ❌ It does NOT turn off output secret-scrubbing.
```

**So yes — to answer you directly: `bypass_sandboxed` still works ONLY inside
your allowed folders.** It only removes the "⏸ may I?" step.

`full` and `bypass_sandboxed` allow the same things. The difference is *why*:

```
 full             = "I trust this, just do it on my real machine."
 bypass_sandboxed = "Don't ask, BUT you must be locked in a Docker box."
                     ↳ The harness ENFORCES this: if HARNESS_SANDBOX is not
                       'docker', bypass_sandboxed is REFUSED / downgraded to
                       auto_workspace. You can't have "don't ask" without the box.
```

---

## 5. How to CHANGE the mode (three ways)

### Way 1 — ChatGPT picks it when starting a job (up to the ceiling)

You just say it in plain English:

> "Start a task in `C:\...\my-app`, goal: X, **permission_mode: plan**."
> "Start a task in `C:\...\my-app`, goal: X, **permission_mode: auto_workspace**."

ChatGPT may choose: `read_only`, `plan`, `build_ask`, `auto_workspace`.
If it tries `full` or `bypass_sandboxed`, the harness **refuses**:

```
 Error: permission_mode 'full' is above this server's ceiling ('auto_workspace')
```

### Way 2 — YOU grant extra power to an existing job (this is how you get `full`)

```powershell
python -m harness tasks list                     # find the task id, e.g. T-9cbcece7
python -m harness tasks set-mode T-9cbcece7 full
```

That's the **only** way to reach `full` / `bypass_sandboxed`. It requires your
keyboard on your machine. ChatGPT physically cannot do it — there is no tool for it.

> To use `bypass_sandboxed`, Docker must be on (`HARNESS_SANDBOX=docker` in
> `.env`), otherwise the harness quietly runs it as `auto_workspace` instead.

### Way 3 — change the ceiling itself (advanced, rarely)

The ceiling lives in your `.env` file in the repo folder:

```
HARNESS_MAX_MODE=auto_workspace     ← default. Raise to 'full' to let ChatGPT
                                      pick full by itself (NOT recommended).
```
Restart the server after changing `.env`.

---

## 6. How do I SEE which mode it's in? (you have no buttons here)

Other tools (Claude Code, Codex) have a UI with a mode button. **Here, ChatGPT
is the UI, and ChatGPT has no button.** So the mode lives on the **task**, and
you look at it from your keyboard:

```powershell
python -m harness tasks list
```
```
TASK ID        STATE        MODE (effective)         GOAL
------------------------------------------------------------------------
T-9cbcece7     new           auto_workspace          Read my-aocs-omega

* = operator-elevated above the ceiling.  Server ceiling: auto_workspace
```

"**effective** mode" = the mode it's *actually* running at after the ceiling is
applied. If a task asked for `full` but the ceiling clamped it, you'll see:
`auto_workspace (asked full)`. A `*` means you elevated it yourself.

Or ask ChatGPT: *"show me task_status for T-xxxx"* — it prints the mode too.

---

## 7. How do I SEE what's happening live? (the "CLI moving" view)

Open a spare PowerShell window and run:

```powershell
python -m harness watch
```

You get a **live feed** of every single thing ChatGPT does, as it does it:

```
TIME      WHAT   MODE             TOOL               TARGET   (TASK)
----------------------------------------------------------------------------
12:27:30  READ   [auto_workspace] list_skills                    (T-9cbcece7)
12:27:38  READ   [auto_workspace] load_skill        my-aocs-omega (T-9cbcece7)
12:28:05  READ   [auto_workspace] read_file         app.py        (T-9cbcece7)
12:40:09  EXEC   [auto_workspace] run_command       python app.py (T-9cbcece7)
```

Reading it:
```
 WHAT  → READ (looked), WRITE (changed a file), EXEC (ran a command)
 MODE  → what power it had at that moment
 TOOL  → which of the 51 tools it used
 TARGET→ the file/command it acted on
 TASK  → which job it belongs to
```

Ctrl+C to stop watching. It doesn't affect ChatGPT — it's just a window into
the **audit log** (`audit.jsonl`), a permanent record of everything ever done.

You also see raw activity in **Window 1** (where `run.ps1` runs), but that's
technical server noise. `harness watch` is the readable version.

---

## 8. WHERE IS EVERYTHING STORED? (complete map)

There are **two separate places**: your *stuff* and the harness's *notes*.

### A) Your project files — exactly where you put them

```
C:\Users\Lenovo\Music\testing projects\      ◀── a ROOT you unlocked
   ├── watch-demo\
   │     └── index.html                      ◀── YOUR real files, normal folders
   └── my-website\
         └── app.py
```
Nothing is hidden or moved. They're ordinary files you can open in any editor.

### B) The harness's notes — the "state directory"

Everything the harness remembers lives in **one folder**:

```
C:\Users\Lenovo\.chatgpt-code-harness\        ◀── THE STATE DIR (all harness memory)
│
├── secret_route.txt      ← your permanent secret password for the ChatGPT link
├── roots.json            ← the list of folders you unlocked  (harness roots add)
├── audit.jsonl           ← EVERY tool call ever made (what `harness watch` reads)
├── tasks.db              ← ⭐ THE SESSIONS DATABASE (all tasks/jobs live here)
│                            + tasks.db-wal / tasks.db-shm (its scratch files)
│
├── memory\               ← ⭐ THE MEMORIES
│    ├── global.json          ← facts that apply EVERYWHERE
│    ├── proj-<hash>.json     ← facts about ONE project
│    └── task-T-xxxx.json     ← facts about ONE job
│
├── sessions\             ← the per-folder activity journal
│    └── <hash-of-folder>\
│          ├── events.jsonl   ← what happened in this folder, in order
│          └── meta.json      ← which folder this is
│
├── worktrees\            ← ⭐ private photocopies of your project, one per task
│    └── watch-demo-a1b2c3d4\
│          └── task-T-9cbcece7\   ← THIS is where that task actually edits files
│
├── workspaces\           ← default sandbox folder (used only if you set no roots)
└── skills\               ← optional: global skills you drop here
```

**In one line each:**

| Question | Answer |
|---|---|
| Where are **sessions/tasks** stored? | `~\.chatgpt-code-harness\tasks.db` (a SQLite database) |
| Where are **memories** stored? | `~\.chatgpt-code-harness\memory\*.json` |
| Where are **project files** stored? | Wherever you told it — e.g. `C:\Users\Lenovo\Music\testing projects\...` (plus a per-task copy under `worktrees\`) |
| Where's the **activity log**? | `~\.chatgpt-code-harness\audit.jsonl` |
| Where's the **unlocked folder list**? | `~\.chatgpt-code-harness\roots.json` |

> `~` means `C:\Users\Lenovo`. You can move this whole folder by setting
> `HARNESS_STATE_DIR` in `.env`. **Keep the path SHORT** — Windows dies past 260
> characters and worktrees will fail.
>
> **Why is harness memory kept outside your project?** So it never pollutes your
> repo or gets committed to git by accident.

---

## 9. Sessions / tasks / worktrees — what they really are

A **session** here is called a **task**. It's one job with a memory.

```
   You: "start a task in C:\...\watch-demo, goal: build a watch"
        │
        ▼
   Harness does 4 things:
   ┌──────────────────────────────────────────────────────────┐
   │ 1. registers the project      (remembers the folder)      │
   │ 2. makes a task_id            → T-9cbcece7                │
   │ 3. makes a WORKTREE           → a private photocopy        │
   │ 4. saves it all in tasks.db   → survives restarts forever  │
   └──────────────────────────────────────────────────────────┘
```

**What's a worktree?** A private photocopy of your project on its own git branch,
so two jobs never scribble on each other's work:

```
   your real folder:          watch-demo\        (untouched, safe)
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
   Task A works in:                 Task B works in:
   worktrees\watch-demo-a1b2\       worktrees\watch-demo-a1b2\
              task-T-aaa\                      task-T-bbb\
   (its own copy + branch)          (its own copy + branch)

   → Task A CANNOT break Task B's files. That's real isolation.
```

The **task_id** (`T-9cbcece7`) is the job's name tag. ChatGPT must clip it to
every action, so the harness knows which job — and therefore which folder and
which mode — applies.

```
   Tool call WITH task_id     → uses that task's worktree + that task's mode ✅
   Tool call WITHOUT task_id  → falls into the shared "no-task" session,
                                which is READ-ONLY on purpose ⛔
                                (so a forgotten name tag can never write)
```

**That's why you always tell ChatGPT: "pass the task_id to every call."**

**Continue a job later, even in a brand-new chat:**
> "Resume task T-9cbcece7 and keep going."

Everything (goal, plan, files changed, commands run) is in `tasks.db`, so it
survives closing the chat, closing the window, and rebooting.

---

## 10. Reading files from OTHER folders (your `.agents\skills` question)

Two different needs, two different answers.

### Case A: it's a SKILL → already works, do nothing! ✨

The harness **automatically** scans these places for skills, no setup, no roots:

```
   <your project>\.harness\skills\      ← skills that live with the project
   <your project>\.agents\skills\
   <your project>\.claude\skills\
   C:\Users\Lenovo\.agents\skills\      ← ⭐ YOUR GLOBAL SKILL LIBRARY
   C:\Users\Lenovo\.claude\skills\
   <state dir>\skills\
```

Your file **`C:\Users\Lenovo\.agents\skills\my-skills\my-aocs-omega\SKILL.md`**
sits inside `~\.agents\skills`, so **it is already found automatically.** (It
searches all subfolders.) Just say to ChatGPT:

> "Call `list_skills`, then `load_skill` with `my-aocs-omega`."

Your `harness watch` output already proves this worked:
```
12:27:30  READ  list_skills
12:27:38  READ  load_skill    my-aocs-omega   ← it already read your skill!
```

> A **skill** = a markdown file (`SKILL.md`) that teaches ChatGPT a procedure.
> It's a deliberate, narrow door: only `.md` skill files, only from those exact
> folders, read-only. It does not open those folders for general access.

### Case B: it's a normal folder of code you want ChatGPT to read/edit

Then you must **unlock it as a root** — that's the only way:

```powershell
python -m harness roots add "C:\Users\Lenovo\Documents\other-project"
python -m harness roots list
#  ↑ then RESTART Window 1 (Ctrl+C, run .\scripts\run.ps1 again)
```

You can unlock a **parent** folder to cover everything inside it:
```
   roots add "C:\Users\Lenovo\Music\testing projects"
        │
        └── unlocks EVERY project inside it, forever, in one go ✅
```

**Safety advice:**
```
   ✅ GOOD:  C:\Users\Lenovo\Music\testing projects     (a work area)
   ⚠️  RISKY: C:\Users\Lenovo                            (your whole user folder)
   ❌ NO:    C:\                                        (your entire drive)
```

---

## 11. Sub-agents — the honest truth

Other harnesses "spawn sub-agents" (the AI makes copies of itself to work in
parallel). **This harness does not, and cannot. Here's exactly why:**

```
   To spawn an AI sub-agent, the harness would have to CALL AN AI ITSELF.
   That means an API key, and that means paying per token — the exact thing
   this project exists to avoid. The whole point is: use your normal ChatGPT
   subscription, no API bills.

   The harness has NO model inside it. Zero. It cannot think.
   Therefore: no autonomous sub-agents. Not "not yet" — by design.
```

What you get **instead** is subtasks — the same ChatGPT working through a
checklist of child jobs:

```
   Parent task: "Build login system"    (T-parent)
        ├── subtask: database table     (T-child1)
        ├── subtask: signup page        (T-child2)
        └── subtask: tests              (T-child3)

   ↑ ONE ChatGPT works these one at a time, and can resume any of them later.
     They share the parent's worktree. Nothing runs in parallel by itself.
```

> Say: *"create a subtask under T-parent for the database table."*
>
> This is written honestly in the tool's own description so ChatGPT never
> pretends otherwise.

---

## 12. The daily runbook

```
┌─ ONE TIME EVER (fresh laptop only) ────────────────────────┐
│  pip install -e .          (in the repo folder)             │
│  copy .env.example .env    (optional; edit settings)        │
└─────────────────────────────────────────────────────────────┘

┌─ ONLY WHEN OPENING A NEW AREA ─────────────────────────────┐
│  python -m harness roots add "C:\path\to\area"              │
│  ...then restart Window 1                                   │
└─────────────────────────────────────────────────────────────┘

┌─ EVERY CODING SESSION ─────────────────────────────────────┐
│  Window 1:  .\scripts\run.ps1      → wait "Uvicorn running" │  keep open
│  Window 2:  .\scripts\funnel.ps1   → wait "Available on..." │  keep open
│  Window 3:  python -m harness url  → copy link (1st time)   │  closeable
│  Window 4:  python -m harness watch → see it work live      │  optional
└─────────────────────────────────────────────────────────────┘

┌─ IN CHATGPT ───────────────────────────────────────────────┐
│  1. Developer Mode ON (Settings→Connectors→Advanced)        │
│  2. Add custom connector, paste the link, auth = None        │
│     (one time only — the link never changes)                 │
│  3. Warm-up:  "open_workspace C:\...  read-only"             │
│  4. Work:     "start a task in C:\...\app, goal X,           │
│                give me the task_id, use it on every call"    │
└─────────────────────────────────────────────────────────────┘
```

### When ChatGPT says "⏸ APPROVAL REQUIRED"

That's the system working, not an error:

```
   ChatGPT: "⏸ APPROVAL REQUIRED — git push. Approve A-99."
        │
        ▼
   YOU:  python -m harness approvals list
         python -m harness approvals approve A-99      (or: deny A-99)
        │
        ▼
   You: "retry" → ChatGPT runs it once.
```
An approval is **one-shot** and locked to that **exact** command. Approving
`pip install react` does NOT allow `pip install anything-else`.

---

## 13. Every operator command (your keyboard only — ChatGPT can't run these)

```powershell
python -m harness doctor        # health check: is everything set up right?
python -m harness url           # print the ChatGPT connector link
python -m harness watch         # ⭐ live feed of what ChatGPT is doing
python -m harness serve         # start the harness (what run.ps1 does)

python -m harness roots list                    # which folders are unlocked
python -m harness roots add "C:\path"           # unlock a folder  (restart after)
python -m harness roots remove "C:\path"        # lock it again    (restart after)

python -m harness tasks list                    # ⭐ all jobs + their real modes
python -m harness tasks set-mode T-xxx full     # ⭐ grant power above the ceiling

python -m harness approvals list                # what's waiting for your yes/no
python -m harness approvals approve A-xx        # allow it, once
python -m harness approvals deny A-xx           # refuse it

python -m harness worktrees prune               # delete copies of finished jobs
python -m harness stdio                         # use from Claude Desktop etc.
```

---

## 14. Gotchas that will bite you

```
⚠️  THE SERVER LOADS CODE ONCE, AT STARTUP.
    If you change .env, add a root, or pull new code — the RUNNING server
    still has the OLD version in memory. You MUST restart Window 1
    (Ctrl+C, then .\scripts\run.ps1). This is the #1 source of "why isn't
    my change working?"

⚠️  NO DEVELOPER MODE = NO TOOLS.
    Without ChatGPT's Developer Mode on, ChatGPT only sees search/fetch and
    none of the 51 coding tools. It will look broken.

⚠️  NO task_id = READ-ONLY.
    If ChatGPT forgets the task_id, writes get denied on purpose. Tell it:
    "pass the task_id to every call." (Check with `harness watch` — you'll
    literally see "(no task)" in the feed.)

⚠️  WINDOWS 260-CHARACTER PATH LIMIT.
    Keep HARNESS_STATE_DIR short (the default ~\.chatgpt-code-harness is fine).
    Deep paths make git worktrees fail with "$GIT_DIR too big".

⚠️  CLOSING WINDOW 1 OR 2 = CHATGPT LOSES ITS HANDS.
    Both must stay open the whole time you're coding.
```

---

## 15. What this is NOT (honest limits — no pretending)

```
❌ It is NOT a sandbox by default.
   `run_command` runs as YOU on YOUR machine. The command classifier that
   spots "git push" is a HELPER, not a wall — a regex cannot understand what
   arbitrary code does (`python -c "..."` will always slip past it).
   The REAL walls are: the roots, the mode, and Docker.
   → For untrusted code: set HARNESS_SANDBOX=docker in .env.
   → To fail-closed on anything unrecognized: HARNESS_ARBITRARY_COMMANDS=ask

❌ Docker does NOT contain everything (yet).
   With HARNESS_SANDBOX=docker: run_command, start_process and diagnostics run
   inside the container. Internal git and ripgrep still run on your machine
   (with repo hooks disabled, which closes the dangerous part). `doctor` says so.

❌ Secret scrubbing is not magic.
   It hides well-known key shapes (AWS/GitHub/OpenAI keys...) from ChatGPT's
   view. It cannot know that "hunter2" is your password. Scope your roots.

❌ No autonomous sub-agents. (See section 11 — by design, forever.)

✅ It IS: a personal coding harness where ChatGPT does real work on real files,
   inside folders you chose, at a power level you control, with a full record
   of everything it did.
```

---

## 16. The one-paragraph summary

You run a small program (**the harness**) on your laptop. A private tunnel
(**Tailscale Funnel**) lets ChatGPT reach it through a secret link. ChatGPT
thinks; the harness does. **Two walls** protect you: **roots** decide *where*
(you unlock folders with `harness roots add`), and **modes** decide *what*
(ChatGPT can pick up to `auto_workspace`; only *you* can grant `full`).
Work happens inside **tasks** — each with a `task_id`, its own private copy of
your project (**worktree**), and permanent memory in `tasks.db`. Risky actions
make ChatGPT **ask you first**. You can watch every move live with
`harness watch`. Nothing is hidden from you, and nothing has an AI in it except
ChatGPT itself.
