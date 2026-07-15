# Roadmap — what gets built, in what order, and why (v2, corrected 2026-07-15)

v1 of this file was cross-examined by GPT; its critique was verified against the
actual code (not accepted on trust — same treatment its audit got). Most of its
corrections were right, one was stale, one was understated, and one of its own
earlier answers turned out wrong. This v2 is the merged, corrected plan.
Verification record: see §5 at the bottom.

Read [MANUAL.md](MANUAL.md) for how the system works today and
[COCKPIT_DESIGN.md](COCKPIT_DESIGN.md) for the GUI design.

---

## 0. The t3code question, settled (with precision)

```
 "FORK t3code"  = take their CODE   ← the COMPLICATED option
 "MODEL t3code" = copy their LOOK   ← cheap (not "zero" — see below)

 t3code's screens are welded by "cables" to ITS engine (Codex/Claude
 provider sessions, token streams). Forking = cutting every weld and
 re-welding to our engine, inside a codebase we didn't write, in a
 stack (Node/npm/React) this project doesn't use.
```

**Precision fixes (from GPT, accepted):**
- Copying a *layout* is free, but a real GUI still costs real work beyond
  layout: loading states, live updates, error handling, stale data, dialogs,
  reconnect-after-restart. That's why the cockpit is sized MEDIUM, not SMALL.
  The accurate claim: *building our own focused cockpit is far cheaper than
  adapting t3code's runtime, because we build only the screens and behavior
  our harness needs.*
- "Never fork" is about the *wholesale* fork. t3code is MIT-licensed; after our
  API is stable, selectively adapting an isolated component (a diff renderer,
  a panel layout) is allowed **if** adapting is genuinely cheaper than
  rebuilding. Caveat: their components are React; this only becomes relevant
  if the front-end is ever rebuilt in React. For v1 (vanilla HTML+JS) it's moot.

---

## 1. Verdict on every gap from COMPARISON.md §13

| # | Gap | Verdict | Size | Why |
|---|-----|---------|------|-----|
| 1 | LSP / code intelligence | **BUILD (after cockpit + launcher)** | LARGE | Biggest brain-boost for ChatGPT: "where is this DEFINED / who CALLS it" instead of text search. JS/TS + Python first. |
| 2 | User-configurable hooks | **BUILD (late)** | **MEDIUM/HIGH** | Upgraded from SMALL (GPT was right): executable hooks are an attack surface — the model must never be able to edit a hook it triggers. Needs operator-only config *outside the roots*, timeout, output cap, env allowlist, audit entries, failure policy. |
| 3 | Plugins / marketplace | **SKIP** | — | Personal tool, one user. |
| 4 | Session fork / branch | **BUILD (last)** | SMALL | `fork_task`: copy task + fresh worktree from same base → compare two approaches. |
| 5 | Per-domain network allowlist | **LATER** | MEDIUM | Only matters for untrusted repos under Docker. |
| 6 | OS-native sandbox | **LATER (research)** | — | Reclassified from SKIP (GPT was right that "impossible" was too strong). Honest detail it skipped: Windows Sandbox is a full disposable VM — slow start, ephemeral, historically one instance — a poor fit for per-command sandboxing. Docker stays the practical answer now; researching native isolation later costs nothing. |
| 7 | Path-scoped rules | **BUILD** | SMALL | Load rule files only when touched files match their globs. |
| 8 | Diff review | **SPLIT** | — | Two different things (GPT's framing, adopted): **visual diff** (see what changed) = Cockpit panel. **Code review** (is the change correct?) = ChatGPT's job via `git_diff` + a review skill/prompt we write. Both documented, neither forgotten. |
| 9 | Sandbox internal git/rg | **LATER** | MEDIUM | Hardening; hooks already neutralized (`no_hooks`). |
| 10 | Session share link | **SKIP** | — | Privacy surface, no payoff for one user. |
| 11 | Auto-format after edit | **BUILD** | SMALL | Post-WRITE hook running the project's formatter. |
| 12 | Semantic / embedding index | **SKIP (revisit)** | LARGE | Needs an embedding model; a LOCAL one keeps £0 but is heavy. Revisit only if grep+LSP feel insufficient. |

**Out of scope while the harness stays model-free and subscription-only**
(wording per GPT, adopted — more precise than "impossible forever"):
autonomous sub-agents, agent teams, background agents, batch fan-out, LLM
command classifier. Any of these requires an AI *inside* the harness. If the
no-model rule ever changes (local model, user-supplied key), this section gets
re-evaluated — until then, not on any roadmap.

---

## 2. The corrected build order

```
 PHASE 0 — COCKPIT READINESS (backend facts the GUI will display)
 │   a GUI cannot fix wrong backend behavior; it only makes it prettier
 │
 ├── finish_task: evidence must include a PASSING run — today a recorded
 │     FAILED test satisfies the check (tools.py:217 tests presence, not truth)
 ├── create_project: start_task refuses a folder that doesn't exist
 │     (tools.py:21) — add "create folder (+ optional git init)" for new work
 ├── isolation clarity: shared-checkout tasks already say so in the start_task
 │     reply — surface it as an explicit flag the cockpit can badge
 ├── cockpit API skeleton: localhost-only :8849 + SSE event stream
 └── DECISION NEEDED (user): default for unrecognized commands.
       Today: allow (runs without asking; knob HARNESS_ARBITRARY_COMMANDS=ask
       exists). GPT wants ask-by-default = safer but interrupts constantly.
       This is a values call about YOUR daily friction — not decided here.
 
 PHASE 1 — COCKPIT CORE
 ├── project sidebar ("Add Project" button → Python opens the NATIVE Windows
 │     folder picker — NOT browser drag-drop; see §3 why that can't work)
 ├── tasks underneath each project · New Task · Resume Task
 ├── mode selector per task (ceiling still applies; elevation is legitimate
 │     here because the cockpit is operator-only)
 ├── task goal/status · Copy-resume-prompt · Open-ChatGPT button
 └── SECURITY: Origin check + session token on every cockpit request (§3)
 
 PHASE 2 — COCKPIT SUPERVISION
 ├── live activity feed (SSE over audit.jsonl)
 ├── changed files · visual diff · checkpoints · restore
 ├── approve / deny buttons · test results
 ├── drag files INTO a task (this drag-drop IS possible — content upload)
 └── open project/worktree in VS Code / Explorer
 
 PHASE 3 — REMOVE TERMINAL FRICTION (before LSP — GPT was right)
 ├── one command / one shortcut: start engine + funnel + open cockpit
 ├── health status · restart button (this is the roots-restart button too —
 │     the cockpit must supervise the engine process anyway, so launcher and
 │     restart-button are the SAME feature)
 └── stop everything cleanly
 
 PHASE 4 — LSP        (JS/TS + Python: definition, references, hover, symbols)
 PHASE 5 — QUALITY    (path-scoped rules · auto-format · formatter detection)
 PHASE 6 — HOOKS      (operator-defined, sandboxed, audited — the hard version)
 PHASE 7 — FORK TASK
 
 LATER   network allowlist · sandboxed git/rg · native Windows sandbox research
 SKIP    plugins · share links · semantic index (revisit)
```

Why the launcher moved before LSP: the user's stated pain is terminals. A
cockpit that still requires three PowerShell windows to start has not solved
the stated pain. (GPT's correction; verified against the user's own words.)

---

## 3. Two hard facts the cockpit design must respect

**Fact 1 — browsers never reveal folder paths.** A web page that receives a
dropped folder gets its *contents*, never its absolute path (`C:\...`), and
even Chrome's directory-picker API returns an opaque handle, not a path.
Registering a project root requires the *path*. So "drag a folder to add a
project" is **physically impossible in a plain browser page** — stronger than
GPT's "not as easy as implied". The correct v1: **Add Project button → the
local Python backend opens the native Windows folder dialog → real path
returned.** Dragging *files* into a project is fine (that's content upload).

**Fact 2 — localhost is not private from your browser.** Any website you
visit can make your browser fire requests at `http://127.0.0.1:8849`. With
approve/deny and set-mode-full buttons living there, a malicious page could
click them for you (CSRF). *Both GPT ("probably fine without auth") and the
original design (Q5 "probably fine") got this wrong.* The cockpit MUST:
require a random session token on every state-changing request (delivered when
you open the cockpit locally), reject requests whose `Origin` isn't the
cockpit itself, and never accept simple GET/POST side effects. Cheap to build,
non-negotiable — this is the same "approvals beyond the model's reach"
property, extended to "beyond any random webpage's reach."

---

## 4. Status

- Nothing in this file is built yet. **Phase 0 starts on the user's GO.**
- One open decision for the user (Phase 0): unknown-command default —
  keep `allow` (less friction) or flip to `ask` (safer, more interruptions).

---

## 5. Verification record (GPT's 10 corrections, judged against code)

| # | GPT's correction | Verdict | Evidence |
|---|---|---|---|
| 1 | "zero complexity" overclaim | **VALID** (wording) | layout copy is free; GUI behavior isn't — cockpit was already sized MEDIUM |
| 2 | "never fork" too absolute | **PARTLY** | MIT reuse allowed later; moot for vanilla-JS v1 (their components are React) |
| 3a | finish_task accepts failed-test evidence | **CONFIRMED** | `tasks/tools.py:217` checks evidence *presence*, not test *success* |
| 3b | can't create a new project folder | **CONFIRMED** | `tasks/tools.py:21` rejects non-existent paths; no create_project exists |
| 3c | shared-workspace isolation unclear | **PARTLY** | `start_task` already returns "shared checkout" note; will surface as flag |
| 3d | "one Linux test still fails" | **STALE / UNVERIFIED** | 217/217 pass here; GPT audited an old zip before — it must name the test |
| 3e | arbitrary commands allowed by default | **CONFIRMED as fact, disputed as "must-fix"** | `config.py:134` — deliberate documented personal-tool default; knob exists; user's values call |
| 4 | browser folder drag-drop unreliable | **VALID + UNDERSTATED** | browsers never expose absolute paths at all — impossible, not just unreliable |
| 5 | one-click launcher missing | **VALID** | merged as Phase 3; unifies with the restart-button we already decided |
| 6 | "Windows has no sandbox" too strong | **PARTLY** | relabelled SKIP→LATER/research; Windows Sandbox practicalities noted; Docker stays the now-answer |
| 7 | user hooks aren't small | **VALID** | upgraded MEDIUM/HIGH, moved late, security requirements listed |
| 8 | "impossible forever" wording | **VALID** | now "out of scope while model-free" |
| 9 | visual diff ≠ code review | **ALREADY COVERED, now explicit** | v1 already said "reviewing brain is ChatGPT via git_diff"; split adopted |
| 10 | tasks ≠ ChatGPT chats naming | **VALID** | cockpit UI will say "Tasks", with Copy-resume-prompt / optional linked chat URL |

Plus one blindspot **both** GPT and v1 missed, found in this pass:
**cockpit CSRF** (§3 Fact 2) — it decisively answers COCKPIT_DESIGN Q5: yes,
the cockpit needs auth (token + Origin check), localhost alone is not a wall.
