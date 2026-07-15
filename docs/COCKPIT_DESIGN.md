# Cockpit — design brief (DECIDED 2026-07-15, not yet built)

**Status:** decided. The user discussed this with GPT; after exploring and
rejecting alternatives (a GUI embedded inside ChatGPT via "MCP Apps", a hybrid
of both, forking t3code's React codebase), both GPT and this brief converged on
the same architecture: **a local-only cockpit on :8849, our own code, ChatGPT
stays the untouched brain.** Decisions recorded inline below (see §7).

**Body decision:** build our own single-page cockpit (vanilla HTML+JS served by
Python, as proposed in §6) — do NOT fork t3code. t3code's screens are wired to
its own provider engine (Codex/Claude sessions, token streams); rewiring them to
our task/audit model costs more than drawing the same layout ourselves, and
would drag Node+npm into a pure-Python project. We copy t3code/Codex's *layout*
as design inspiration only. If the cockpit proves itself and wants more polish
later, the front-end can be rebuilt in React on top of the identical API.
**Goal:** give the harness the Codex-style GUI feel — project folders, chat
sessions underneath them, a mode selector, drag-and-drop files — without losing
the one thing that makes this project exist (free ChatGPT chat).

---

## 1. What the user actually asked for

Verbatim: *"add a folder project then keep chatting with multiple sessions
underneath it and then be able to select the plan mode and drag and drop files"*
and *"which folder belongs to which project, which chat session belongs to which
session"*.

That is precisely the Codex GUI shape:

```
   📁 PROJECT (a folder)
      ├── 📄 files            ← drag & drop to add
      └── 💬 chat sessions    ← many, underneath the project
            └── each with a MODE selector (plan / build / …)
```

## 2. The hard constraint (this decides the whole design)

```
 ┌──────────────────────────────────────────────────────────────────┐
 │ ChatGPT's chat quota is reachable ONLY by a human typing into    │
 │ chatgpt.com. There is no API for it.                             │
 │                                                                   │
 │   custom chat box  ⟺  a different brain  ⟺  quota burn or £/token│
 │   free ChatGPT     ⟺  you type in ChatGPT's own box               │
 │                                                                   │
 │ → Every GUI (t3code, OpenWebUI, Pi TUI) drives a CLI/API that     │
 │   costs quota or money. t3code wraps Codex CLI = Codex quota.     │
 │ → THEREFORE: the chat box stays in ChatGPT. Everything else is    │
 │   fair game for a GUI.                                            │
 └──────────────────────────────────────────────────────────────────┘
```

Good news: the chat box is ~20% of what was asked for. Folders, projects,
sessions, modes, files, diffs, approvals — all 80% — are ours to build.

## 3. 🔴 CRITICAL SECURITY CONSTRAINT (do not get this wrong)

The Tailscale Funnel exposes **all of port 8848** to the public internet. The
MCP endpoint is protected only because it sits behind a secret path.

```
 ❌ WRONG: serve the cockpit at 8848/ui
    → it is INTERNET-REACHABLE.
    → worse: ChatGPT could (in principle) be steered to call its own approval
      buttons → the model approves itself → our single best security property
      (approvals decided out-of-band, beyond the model's reach) is DESTROYED.

 ✅ RIGHT: the cockpit is a SEPARATE, LOCALHOST-ONLY server.
      port 8849, bound to 127.0.0.1, NEVER funneled, no route from the internet.
```

```
        INTERNET                          YOUR LAPTOP ONLY
   ┌────────────┐  funnel   ┌──────────────────┐        ┌──────────────────┐
   │  ChatGPT   │ ────────▶ │ :8848  MCP       │        │ :8849  COCKPIT   │
   │  (the brain)│          │  (the hands)     │◀──────▶│  (the operator)  │
   └────────────┘           └──────────────────┘  same  └──────────────────┘
        ▲                                          DB/state       ▲
        │                                                          │
   ChatGPT can reach 8848 ONLY.            YOU can reach 8849 ONLY.
   It can NEVER reach 8849.                It is not on the internet.
```

The operator console must remain physically unreachable by the model. Non-negotiable.

## 4. Mapping: Codex GUI → what we already have

Almost nothing new is needed in the engine. It's a UI over existing primitives.

| Codex GUI thing | Our existing primitive | Status |
|---|---|---|
| Add a project folder | `roots add` + `register_project` | ✅ exists (CLI only) |
| Project list | `tasks.db` `projects` table | ✅ exists |
| Chat sessions under a project | **tasks** (`start_task`, parent/child) | ✅ exists |
| Which session belongs to which project | `task.project_id` | ✅ exists |
| Mode selector per session | `task.permission_mode` + `tasks set-mode` | ✅ exists (CLI only) |
| See what it's doing | `audit.jsonl` (`harness watch`) | ✅ exists (CLI only) |
| Approve risky action | `approvals approve` | ✅ exists (CLI only) |
| See changes | `git_diff` / checkpoints | ✅ exists |
| File tree | filesystem under a root | ✅ trivially readable |
| **Drag file INTO a project** | *(plain file copy)* | 🆕 new (cockpit does it directly) |
| **Attach files to a session's context** | — | 🆕 new (`pinned_files` on task) |
| **Open this session in ChatGPT** | — | 🆕 new (copy/deep-link prompt) |

**Conclusion: the Cockpit is ~90% a front-end over the CLI we already have.**

## 5. Proposed UI

```
┌─ HARNESS COCKPIT ───────────────────────── localhost:8849 ─────────────┐
│                                                                         │
│  PROJECTS                    │  SESSIONS in "watch-demo"                │
│  ┌────────────────────────┐  │  ┌───────────────────────────────────┐  │
│  │ 📁 watch-demo       ▓▓ │  │  │ 💬 T-9cb  build the watch          │  │
│  │ 📁 my-website          │  │  │    [ auto_workspace ▾ ]  ▶ Open    │  │
│  │ 📁 snake-game          │  │  │ 💬 T-4ab  fix the gear bug         │  │
│  │                        │  │  │    [ plan ▾ ]            ▶ Open    │  │
│  │  ⬇ drop a folder here  │  │  │ 💬 T-7zz  write tests   ✓ done     │  │
│  │     to add a project   │  │  │                                     │  │
│  └────────────────────────┘  │  │      [ + New session ]              │  │
│                              │  └───────────────────────────────────┘  │
│  FILES in watch-demo         │  ⚡ LIVE ACTIVITY                        │
│  ┌────────────────────────┐  │  ┌───────────────────────────────────┐  │
│  │ 📄 index.html          │  │  │ 12:40 WRITE index.html   T-9cb    │  │
│  │ 📄 style.css           │  │  │ 12:41 EXEC  python -m http.server │  │
│  │ 📁 assets/             │  │  │ 12:41 READ  style.css             │  │
│  │  ⬇ drop files here     │  │  └───────────────────────────────────┘  │
│  └────────────────────────┘  │  ⏸ NEEDS YOU                            │
│                              │  ┌───────────────────────────────────┐  │
│  📊 DIFF (T-9cb)             │  │ git push origin main   (T-9cb)    │  │
│  ┌────────────────────────┐  │  │        [ Approve ]   [ Deny ]     │  │
│  │ + <div class="gear">   │  │  └───────────────────────────────────┘  │
│  │ - <div class="cog">    │  │                                          │
│  │        [ Restore ⟲ ]   │  │                                          │
│  └────────────────────────┘  │                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### What each interaction does, exactly

```
 DROP A FOLDER on "Projects"
   → cockpit calls roots.add(path) + register_project(path)
   → ⚠️ roots need a server restart today. Cockpit shows "Restart engine"
      button (it can restart the 8848 process itself), OR we make roots
      hot-reloadable for the FILE-backed list only. ← OPEN QUESTION (§7)

 DROP A FILE on "Files"
   → cockpit copies the file into the project folder. Plain file operation.
     No ChatGPT involved. This is the "insert a file inside it" ask.

 CLICK "+ New session"
   → cockpit calls start_task(project, goal, mode) → gets T-xxxx
   → shows a ready-to-paste prompt (or a chatgpt.com deep link) with the
     task_id + folder already baked in. ONE click, then you just talk.

 CHANGE THE MODE DROPDOWN
   → cockpit calls the same code path as `harness tasks set-mode`.
   → NOTE: the ceiling still applies. Choosing `full` from the cockpit is
     legitimate operator elevation (you're at your own keyboard) — this is
     exactly why the cockpit MUST be localhost-only (§3).

 CLICK "Approve"
   → same code path as `harness approvals approve <id>`.

 CLICK "Restore ⟲"
   → restore_checkpoint. Visual undo.
```

## 6. What must be built (honest scope)

```
 NEW CODE
 ├── harness/cockpit/server.py    localhost-only Starlette app on :8849
 ├── harness/cockpit/api.py       JSON endpoints over EXISTING functions:
 │                                 projects, tasks, set-mode, approvals,
 │                                 roots add/remove, diff, restore, file ops
 ├── harness/cockpit/stream.py    SSE feed tailing audit.jsonl (live activity)
 ├── harness/cockpit/static/      one HTML page + vanilla JS (NO build step,
 │                                 no npm — keep the "one Python process" rule)
 ├── harness/__main__.py          new command:  python -m harness ui
 └── Task model                   + pinned_files: list[str]   (file attach)

 REUSED AS-IS (no changes)
 └── TaskStore, roots.json, audit.jsonl, approvals, checkpoints, git_diff,
     policy/ceiling logic. The cockpit is a VIEW, not a new engine.
```

Deliberately **not** using React/npm — the project's identity is "one pure-Python
process, no Node." A single static HTML+JS page keeps that promise.

## 7. Open questions (argue about these)

```
 Q1. ROOTS HOT-RELOAD
     Today roots are frozen at startup, on purpose: a hot-reload watcher is a
     self-service escalation surface for a model that has run_command.
     But drag-a-folder wants instant effect.
     Options: (a) cockpit restarts the engine (clean, 2s blip)
              (b) roots.json re-read on each path check, ONLY for the
                  file-backed list, never env  (needs a threat re-think)
              (c) keep restart, make it one button.
     → ✅ DECIDED (2026-07-15): (c)/(a) — restart button in the cockpit.
       The frozen-at-startup rule is what guarantees the model can never
       gain new territory mid-session; hot-reload trades that guarantee
       for saving one click. Bad trade.

 Q2. DEEP LINK vs COPY BUTTON
     Does https://chatgpt.com/?q=<prefilled> reliably prefill the composer?
     If yes → near-zero friction. If no → clipboard copy button.
     → NEEDS TESTING (5 min).

 Q3. PINNED FILES — what does "attach a file to a chat" mean for us?
     ChatGPT can already read any file via read_file. So "attach" =
     (a) put the paths in the generated prompt, or
     (b) store pinned_files on the task so resume_task/task_status surface
         them, so ChatGPT reads them itself.
     → LEANING: both. (a) is instant, (b) survives session restarts.

 Q4. IS THE COCKPIT WORTH IT vs JUST USING t3code+Codex?
     Honest framing: t3code gives a full single-window GUI TODAY for zero
     build effort — but it drives Codex CLI and burns the quota this project
     exists to avoid. The Cockpit costs a build but keeps the £0 brain.
     → ✅ DECIDED (2026-07-15): build the Cockpit, keep the £0 brain.
       GPT independently reached the same conclusion ("T3-derived local
       cockpit: YES; MCP GUI inside ChatGPT: NO; hybrid: NO; t3code
       unchanged: NO"). Also decided: our own page, not a t3code fork
       (see the Body decision at the top of this doc).

 Q5. DOES THE COCKPIT NEED AUTH?
     It's localhost-only, so anything on your machine can reach it.
     Probably fine for a personal tool. Add a token if paranoid.
```

## 8. What this does NOT give you

```
 ❌ Typing your message in the cockpit. You type in ChatGPT. Forever.
    (Unless you accept a different brain = quota/bills.)
 ❌ Streaming ChatGPT's thinking into the cockpit. We only see TOOL CALLS,
    because that's all that reaches our server. The reasoning stays in ChatGPT.
 ✅ Everything else you asked for.
```

## 9. The honest verdict

```
 The Cockpit closes ~80% of the gap between "terminal commands" and "Codex GUI":
 projects, sessions-under-projects, mode dropdowns, drag-drop folders AND files,
 live activity, one-click approvals, visual diffs. No terminal.

 The remaining 20% — typing in a native chat box — is not a build problem.
 It is the price of the free brain. Any tool that closes it charges you
 per token or eats your Codex quota.
```
