# THE CHECKLIST — tick one by one until done (created 2026-07-15)

This is the single execution list, merged from three rounds of adversarial
review (Claude ↔ GPT, every claim verified against code). Rationale lives in
[ROADMAP.md](ROADMAP.md) and [COCKPIT_DESIGN.md](COCKPIT_DESIGN.md); this file
is only for DOING. Tick a box only when the item is built AND tested.

Verification notes for round 3 are at the bottom (§ Verification record).

---

## PHASE 0 — MAKE THE BACKEND TRUE (a GUI must not display lies)

- [x] **0.1 finish_task honesty** — a recorded FAILED run can never satisfy
      completion; only a passing last-run or explicit evidence when no runs
      exist. `tasks/tools.py finish_task`; tested in test_phase0 +
      test_task_telemetry (rejects-failing).
- [x] **0.2 create_project** — `create_project(path, name)`: confined to an
      existing root, `git init` + README + initial commit, registers it.
      MCP tool + tested (inits git, refused outside roots, refused non-empty).
- [x] **0.3 worktree isolation enforced, not badged** —
      `isolation="workspace"` now returns an ASK (one-shot operator approval)
      before it runs; `auto` non-git fallback still just flags in the reply.
      `_shared_checkout_gate`; tested both paths.
- [x] **0.4 fix the Linux hook test** — `chmod(0o755)` added to both hook
      writers in test_terminal_and_hooks_gates.py.
- [x] **0.5 CI matrix** — `.github/workflows/ci.yml`: ubuntu + windows pytest,
      plus a wheel job importing from outside the source tree.
- [x] **0.6 COMMAND_SAFE tier** — positive fullmatch tier in permissions.py
      (pytest/tox/linters/npm test/cargo/go/local git…), metachar-guarded so
      `pytest; evil` can't ride in. Tested safe vs unsafe.
- [x] **0.7 remembered approvals** — `harness/allowlist.py` (state-dir, exact,
      per-project) + `harness commands allow/list/revoke` + `approvals approve
      --remember`. Gate consults it. Tested end-to-end through `_gate`.
- [x] **0.8 flip default to ask** — `arbitrary_commands` default now `"ask"`
      (config.py + doctor confirms). Safe because 0.6/0.7 landed first.
- [x] **0.9 structured event bus** — `harness/events.py` EventBus
      ({event_id,time,type,task_id,data}) + ring buffer + `since()` replay +
      optional HTTP sink; registered as a pre-hook. Tested ids/replay + that
      real tool calls reach it. audit.jsonl unchanged as the durable sink.

**Bonus this pass:** 8.1 `fork_task` (MCP tool + tested) — small and it shared
the tasks/tools.py surface, so it landed with Phase 0.

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

- [x] **8.1 fork_task** — copy goal/criteria/plan, fresh worktree from the same
      base, compare approaches. Landed early with Phase 0 (MCP tool + tested).

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
