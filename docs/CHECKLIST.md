# THE CHECKLIST — tick one by one until done (created 2026-07-15)

This is the single execution list, merged from three rounds of adversarial
review (Claude ↔ GPT, every claim verified against code). Rationale lives in
[ROADMAP.md](ROADMAP.md) and [COCKPIT_DESIGN.md](COCKPIT_DESIGN.md); this file
is only for DOING. Tick a box only when the item is built AND tested.

Verification notes for round 3 are at the bottom (§ Verification record).

---

## PHASE 0 — MAKE THE BACKEND TRUE (a GUI must not display lies)

- [ ] **0.1 finish_task honesty** — completion requires *passing* evidence:
      a recorded FAILED test run must not satisfy the evidence check
      (today `tasks/tools.py:217` checks presence, not success).
- [ ] **0.2 create_project** — create folder + `git init` + initial commit.
      ⚠ CONFINED: may only create *inside an existing root* (otherwise it's a
      path-escape vector). Creating outside roots = cockpit/operator flow only.
- [ ] **0.3 worktree isolation enforced, not badged** —
      `isolation="workspace"` becomes an ASK (operator approval via the
      existing approval machinery), not a silent choice ChatGPT can make;
      non-git folder → suggest create_project/git init or require approval.
- [ ] **0.4 fix the Linux hook test** — add `chmod 0o755` to the hook file in
      `tests/test_terminal_and_hooks_gates.py:139` (confirmed: git skips
      non-executable hooks on Linux; invisible on Windows).
- [ ] **0.5 CI matrix** — GitHub Actions: windows-latest + ubuntu-latest;
      build wheel, install OUTSIDE the source tree, run pytest. Both green at
      the same commit = cross-platform claims become proof, permanently.
- [ ] **0.6 COMMAND_SAFE tier** — today NOTHING maps to safe
      (`permissions.py:44-64`: only risk patterns exist; everything else →
      ARBITRARY, so ask-mode would nag on `pytest`/`npm test` too). Classify
      common test/build/run commands + the project commands auto-detected by
      open_workspace as safe.
- [ ] **0.7 remembered approvals** — "always allow this exact command in this
      project", stored OPERATOR-SIDE in state_dir (never in the workspace —
      the model must not be able to write its own allowlist).
- [ ] **0.8 flip default to ask** — `HARNESS_ARBITRARY_COMMANDS=ask` becomes
      the default ONLY after 0.6 + 0.7 exist (before them it's unbearable;
      after them it's safe AND quiet).
- [ ] **0.9 structured event bus** — every action emits
      `{event_id, task_id, type, time, data}` → in-process bus → SSE feed
      AND audit.jsonl sink. The audit file stays the durable record; the GUI
      does not tail-parse it as its primary channel.

## PHASE 1 — THE SUPERVISOR (`python -m harness up`)

- [ ] **1.1 one supervisor process** that: serves the cockpit on
      127.0.0.1:8849, spawns the engine (8848) as a CHILD process, and
      starts/checks the Tailscale funnel. Cockpit's "restart engine" =
      supervisor restarting a child — no process ever kills itself.
- [ ] **1.2 restart/stop controls** with a BUSY WARNING first: restarting
      kills in-flight ChatGPT tool calls and every background process
      (dev servers) — show "task active / N processes running" before acting.
- [ ] **1.3 health monitoring** — engine + funnel status, auto-restart on
      crash, visible connection state.
- [ ] **1.4 native Windows folder picker** lives in the supervisor
      (browsers can NEVER reveal a dropped folder's absolute path — settled).
- [ ] **1.5 session-token minting** for the cockpit (see 3.1).

## PHASE 2 — COCKPIT CORE

- [ ] **2.1 project sidebar** + [Add Project] → native picker → confirm →
      roots.json + "Restart engine" button.
- [ ] **2.2 tasks under each project** — New Task, Resume Task; UI says
      "Tasks" (a harness task ≠ a ChatGPT sidebar chat — never conflate).
- [ ] **2.3 mode selector** per task (ceiling applies; cockpit elevation is
      legitimate operator action; exact typed confirmation for full/bypass).
- [ ] **2.4 isolation control** — worktree default; shared = advanced +
      warning (pairs with 0.3).
- [ ] **2.5 goal/status view** + Copy-resume-prompt + Open-ChatGPT button
      (+ optional linked chat URL field).

## PHASE 3 — COCKPIT SUPERVISION (the watching-and-approving half)

- [ ] **3.1 CSRF protection, complete** — bind 127.0.0.1 only; NEVER funnel
      8849; deny CORS by default; accept only the cockpit's exact Origin;
      block missing/null-Origin mutations; CSRF token in a CUSTOM HEADER
      (never the URL); mutations via POST only, zero state-changing GETs;
      audit every cockpit mutation.
- [ ] **3.2 SSE live feed — resolve the token collision**: browsers'
      EventSource cannot send custom headers, so 3.1's header rule would make
      the live feed impossible. Resolution: the SSE endpoint is READ-ONLY and
      is protected by a SameSite=Strict session cookie + Origin check (or a
      short-lived one-time stream ticket); mutations keep the header token.
      Support `Last-Event-ID` reconnection.
- [ ] **3.3 changed files + visual diff** panel (viewing; the *code review*
      itself stays ChatGPT's job via git_diff + a review prompt/skill).
- [ ] **3.4 approvals UI** — approve/deny with the same request-hash binding
      as the CLI.
- [ ] **3.5 checkpoints + restore** buttons.
- [ ] **3.6 test-results panel** (from task telemetry).
- [ ] **3.7 drag FILES into a project/task** (content upload — this drag-drop
      is the possible kind).
- [ ] **3.8 open in VS Code / Explorer** buttons.

## PHASE 4 — ONE-CLICK PRODUCT

- [ ] **4.1 desktop shortcut / system tray** for `harness up`.
- [ ] **4.2 auto-open cockpit** in the browser on start.
- [ ] **4.3 clean shutdown** of engine + funnel + processes.
- [ ] **4.4 static frontend packaged** with the wheel.

## PHASE 5 — LSP

- [ ] **5.1 TypeScript/JavaScript** language server integration.
- [ ] **5.2 Python** language server integration.
- [ ] **5.3 tools**: definition, references, hover, workspace symbols,
      diagnostics.

## PHASE 6 — QUALITY

- [ ] **6.1 path-scoped rules** (rule files loaded only for matching globs).
- [ ] **6.2 formatter detection + auto-format** post-WRITE hook.
- [ ] **6.3 formatting telemetry.**

## PHASE 7 — CONTROLLED HOOKS (the hard version, deliberately late)

- [ ] **7.1 operator-only hook config OUTSIDE the roots** (the model must
      never be able to edit a hook it triggers).
- [ ] **7.2 timeout, output cap, env allowlist, sandbox policy.**
- [ ] **7.3 audit entries + failure policy.**

## PHASE 8 — FORK TASK

- [ ] **8.1 fork_task** — copy goal/context, fresh worktree from the same
      base commit, compare approaches side by side.

## LATER (deliberate, not forgotten)
per-domain network allowlist · git/rg inside the sandbox · native Windows
sandbox research · semantic index (only if grep+LSP prove insufficient)

## SKIP (decided, with reasons in ROADMAP.md)
plugins/marketplace · public share links · anything requiring a model inside
the harness (out of scope while the harness stays model-free)

---

## Verification record — round 3 (GPT's six corrections, checked)

| # | GPT's correction | Verdict | Evidence |
|---|---|---|---|
| 1 | full CSRF checklist | **ADOPTED** | extends the CSRF finding; GPT also retracted its earlier "auth probably unnecessary" |
| 2 | Linux test failure is real | **GPT RIGHT — I WAS WRONG** | `tests/test_terminal_and_hooks_gates.py:139` writes the hook without chmod 0o755; git skips non-executable hooks on Linux; my 217/217 was run on the one platform where the bug is invisible. The "stale zip" dismissal was bad reasoning — the test file itself was checkable all along. |
| 3 | badge isn't enforcement | **ADOPTED with nuance** | auto already prefers worktrees; the real holes are silent `isolation="workspace"` and non-git folders → now an ASK (0.3) |
| 4 | adaptive command policy | **ADOPTED, with a fact GPT missed** | its plan assumes a "known safe command" tier that DOESN'T EXIST: `permissions.py` maps nothing to COMMAND_SAFE — everything unmatched is ARBITRARY, so flipping to ask today would nag on `pytest` too. Order matters: build 0.6+0.7, THEN flip (0.8). |
| 5 | separate supervisor | **ADOPTED as clarification** | v2 was ambiguous about processes; resolved as ONE supervisor process serving the cockpit + engine/funnel as children — no self-restart paradox, no fourth component |
| 6 | event bus, not audit-tailing | **ADOPTED** | standard separation; audit.jsonl stays the durable sink (0.9) |

New blindspots caught in this round (both reviewers had missed):
- **SSE × CSRF collision** (3.2): "token in custom header" + "EventSource
  can't set headers" are incompatible without an explicit resolution.
- **Restart-while-busy** (1.2): an engine restart kills background dev
  servers and in-flight tool calls — needs a warning, not just a button.
- **create_project confinement** (0.2): folder creation must be root-bounded
  or it becomes an escape hatch.
- **Remembered-approvals storage** (0.7): must live operator-side, or the
  model can author its own allowlist.
