# Codex-style Harness Workbench Implementation Plan

> **For future Codex/Claude sessions:** execute this plan in order using strict RED-GREEN-REFACTOR. Read `docs/WORK_SESSION.md` first; update it after every completed slice.

**Goal:** Turn the localhost Harness Cockpit into a Codex-style operator workbench while ChatGPT remains the only model and message-entry surface.

**Status (2026-07-16):** Implemented and verified through automated, live MCP,
packaging, and responsive browser gates. See `docs/WORK_SESSION.md` for exact
evidence and the two external limitations (native pointer capture and Docker).

**Architecture:** Preserve the model-free, pure-Python, no-build product boundary. Keep Starlette as the local operator API and use browser-native ES modules/CSS for a maintainable desktop shell. Persistent domain state (projects, tasks, pinning) belongs in SQLite; ephemeral per-window layout state (pane widths, open visual tabs) belongs in localStorage. The Cockpit remains localhost-only and unreachable from the public MCP route.

**Quality bar:** A slice is complete only when ownership is clear, state has one authoritative home, failure behavior is explicit, keyboard/accessibility behavior exists, focused tests passed, the full suite remains green, and the real UI was exercised. Do not hide platform limitations or call advisory command classification a sandbox.

**Reference patterns researched:**

- OpenAI Codex: projects contain threads; multiple tasks remain independently inspectable; diff review is a dedicated panel; worktrees isolate parallel work.
- T3 Code: resizable sidebar with persisted width, minimum main-content width, pointer capture, and a generous invisible resize target.
- OpenCode: explicit layout state, project/session hierarchy, session tabs, independent scrolling, notification/status affordances, and reusable resize primitives.
- Claude Code: pinned, scheduled, and recent session groups plus an integrated right-side preview/review surface.
- Cursor/VS Code: docked utility panels, visible tab strips, keyboard-accessible separators, and independently scrollable panes.

---

## Product contract

1. ChatGPT owns prompts, model output, and the conversation.
2. The Cockpit owns projects, task/session navigation, modes, files, approvals, diffs, command history, and resumability.
3. Desktop layout at >= 1100 px: resizable left navigation, central task workspace, resizable right inspector.
4. Compact layout: right inspector collapses/overlays before the central workspace becomes unusable; the left navigation becomes an overlay on narrow screens.
5. Every pane scrolls independently. The page body never becomes the accidental scroller.
6. Project and session pins persist in SQLite. Pane sizes and open UI tabs persist per browser window.
7. The right inspector exposes Activity, Changes, Terminal history, Files, and Approvals. It is observational/operator UI, not a second model chat box.
8. Existing MCP behavior and public secret route remain backward compatible.

## Hard problems and decisions

### HP-1: ChatGPT cannot be embedded as a controllable model surface

The ChatGPT quota is available only through ChatGPT's own UI. The Cockpit may open/copy a resume prompt but must not impersonate or automate the conversation. This is a product constraint, not a missing frontend feature.

### HP-2: Local Windows execution is not a hard sandbox

Tests/builds execute repository code. A regex saying `pytest` is safe does not prevent that code from reading host files. This plan improves honesty and approval behavior, neutralizes raw hook-bearing Git paths, and verifies Docker when available, but does not claim host isolation unless a real sandbox backend is active.

### HP-3: Browser UI state and durable task state must not mix

Pane dimensions and open visual tabs are presentation state; pins, task lineage, task status, approvals, and worktree identity are domain state. Mixing these creates cross-window races and stale UI. They remain separate by design.

### HP-4: Engine restart safety needs activity, not only lifecycle labels

Models can use a task while leaving it in `new`. Restart protection therefore combines lifecycle state, recent engine activity, pending approvals, and readiness probing.

### HP-5: Rich desktop UX without introducing a Node build chain

The repository deliberately ships one Python product. The frontend uses small browser-native ES modules at `harness/cockpit/static/*.mjs`; package-data tests guarantee they ship in the wheel. A framework migration is deferred until complexity demonstrates that it is cheaper than this boundary.

---

## Phase 0 - Baseline and continuity

### Task 0.1: Durable cross-session handoff

**Files:**

- Create: `docs/WORK_SESSION.md`
- Create: `docs/plans/2026-07-16-codex-workbench-redesign.md`

**Acceptance:** A new session can resume by reading two small files and running the recorded verification command. The handoff contains the current commit, working tree state, completed slices, RED/GREEN evidence, blockers, and exactly one next step.

### Task 0.2: Protect the baseline

**Commands:**

```powershell
git status --short --branch
python -B -m pytest tests -q -p no:cacheprovider --basetemp "$env:TEMP\harness-baseline-<unique>"
```

**Expected:** clean baseline; 279 tests pass before changes.

---

## Phase 1 - Backend integrity fixes

### Task 1.1: Persist fork lineage

**Files:**

- Test: `tests/test_phase0.py`
- Modify: `harness/tasks/tools.py`

**RED:** Extend `test_fork_task_copies_goal_and_gets_own_worktree` to assert `child.parent_id == parent.id`; the Cockpit test later asserts the serialized state.

**GREEN:** Pass `parent_id=src.id` to `TaskStore.create_task` in `fork_task`.

### Task 1.2: Coalesce duplicate pending approvals

**Files:**

- Test: `tests/test_task_store.py`
- Modify: `harness/tasks/store.py`

**RED:** Adding the same non-empty `(task_id, action, request_hash)` twice while pending returns the same approval ID and leaves one pending row. Different hashes remain independent.

**GREEN:** Add schema migration v3 with a partial unique index and make `add_approval` select/return the existing pending row transactionally.

### Task 1.3: Preserve safe Windows toolchain environment

**Files:**

- Test: `tests/test_executor.py`
- Modify: `harness/executor.py`

**RED:** On Windows-like environment input, `APPDATA`, `LOCALAPPDATA`, active `VIRTUAL_ENV`/`CONDA_PREFIX`, and non-secret Python environment selectors survive; cloud tokens do not.

**GREEN:** Add only toolchain/location keys required for interpreter and user-site discovery. Re-run a real `python -m pytest` through the harness.

### Task 1.4: Make restart protection activity-aware and readiness-aware

**Files:**

- Test: `tests/test_supervisor.py`
- Test: `tests/test_cockpit.py`
- Modify: `harness/cockpit/supervisor.py`
- Modify: `harness/cockpit/server.py`

**RED:** A recently active `new` task requires confirmation. A restart response is not `ok` until the child health probe succeeds or returns an explicit timeout error.

**GREEN:** Track recent engine activity in the Cockpit, include pending approvals, and add bounded readiness polling after child restart.

### Task 1.5: Harden the health and operator surface

**Files:**

- Test: `tests/test_security.py`
- Test: `tests/test_cockpit.py`
- Modify: `harness/middleware.py`
- Modify: `harness/cockpit/server.py`

**RED:** Invalid Host receives no engine metadata; invalid/foreign chat URLs are rejected; the Cockpit sends CSP, frame, and content-type protections.

**GREEN:** Return minimal health data before auth, validate `https://chatgpt.com/...`, and apply narrow response headers compatible with same-origin static modules/SSE.

### Task 1.6: Remove raw Git-hook ambiguity

**Files:**

- Test: `tests/test_permissions.py`
- Test: `tests/test_exec_boundary.py`
- Modify: `harness/permissions.py`
- Modify: `harness/server.py`
- Modify: Doctor copy in `harness/__main__.py`

**RED:** Raw `git commit` cannot auto-run through `run_command`; the dedicated Git tool still commits with hooks disabled.

**GREEN:** Route or reject hook-capable raw Git mutations with guidance to the dedicated tool. Keep the documentation honest about the local executor.

---

## Phase 2 - Durable navigation state

### Task 2.1: Add project and session pin state

**Files:**

- Test: `tests/test_task_store.py`
- Test: `tests/test_cockpit.py`
- Modify: `harness/tasks/model.py`
- Modify: `harness/tasks/store.py`
- Modify: `harness/cockpit/server.py`

**Contract:**

```json
POST /api/project/pinned {"project_id":"P-...","pinned":true}
POST /api/task/pinned    {"task_id":"T-...","pinned":true}
```

Project pin uses a migrated `projects.pinned` column; task pin uses a backward-compatible Pydantic field in task JSON. State responses include both values.

### Task 2.2: Return task-scoped event history

**Files:**

- Test: `tests/test_cockpit.py`
- Modify: `harness/cockpit/server.py`

**Contract:** `GET /api/task/events?task_id=T-...&limit=200` returns confined durable history so switching tasks does not display another task's feed.

---

## Phase 3 - Frontend architecture refactor

### Task 3.1: Introduce browser-native module boundaries

**Files:**

- Create: `harness/cockpit/static/api.mjs`
- Create: `harness/cockpit/static/state.mjs`
- Create: `harness/cockpit/static/layout.mjs`
- Create: `harness/cockpit/static/render.mjs`
- Create: `harness/cockpit/static/app.mjs`
- Modify: `harness/cockpit/static/index.html`
- Retire after parity: `harness/cockpit/static/cockpit.js`
- Test: `tests/test_packaging.py`
- Test: `tests/test_cockpit.py`

**Ownership:** `api.mjs` performs transport only; `state.mjs` owns state transitions; `layout.mjs` owns resizers/local presentation persistence; `render.mjs` produces and wires views; `app.mjs` owns boot/SSE orchestration.

**Gate:** Do not remove the existing script until project creation, session creation, mode changes, fork, upload, restore, approvals, diff, and SSE parity are verified.

### Task 3.2: Split the visual system

**Files:**

- Modify: `harness/cockpit/static/cockpit.css`

Keep a single packaged stylesheet initially, but organize it into tokens, shell, navigation, workspace, inspector, components, states, accessibility, and responsive sections. Avoid decorative complexity; this is a dense professional tool.

---

## Phase 4 - Codex-style desktop shell

### Task 4.1: Three-pane shell with independent scrolling

**DOM contract:**

```html
<div class="workbench">
  <aside id="navPane">...</aside>
  <div role="separator" id="navResize"></div>
  <main id="taskPane">...</main>
  <div role="separator" id="inspectorResize"></div>
  <aside id="inspectorPane">...</aside>
</div>
```

Every nested flex/grid owner uses `min-width:0` and `min-height:0`; only `.nav-scroll`, `.task-scroll`, and `.inspector-body` use `overflow:auto`.

### Task 4.2: Accessible persisted resizers

**Behavior:** Pointer capture; 8px hit target; visual 1px rule; clamp left pane 220-480px and right pane 320-720px while preserving at least 520px central content; persist only on drag end; Arrow keys resize by 16px; Home resets; double-click resets; `aria-valuenow` stays current.

### Task 4.3: Collapse and responsive behavior

Desktop collapse controls remain keyboard reachable. Below 1100px the right pane starts collapsed; below 760px navigation becomes an overlay with backdrop and Escape-to-close. Window resizing must never strand an invisible focused control.

---

## Phase 5 - Project/session navigation and tabs

### Task 5.1: Sidebar information architecture

Order: New session, search, Pinned, Projects. Each project expands to its sessions; each session has status, relative update time, pin action, and selected state. The tree has independent vertical scrolling and a fixed footer/status region.

### Task 5.2: Search and stable sorting

Pinned projects/sessions sort first, then updated descending. Search matches project name, session title, goal, and task ID without mutating collapsed state.

### Task 5.3: Multi-session visual tabs

Selecting a session opens/focuses a task tab. Tabs are closable presentation state persisted in localStorage. Closing a tab never deletes/cancels the task. Missing/deleted task IDs are pruned during state refresh.

---

## Phase 6 - Right inspector dock

### Task 6.1: Inspector tab model

Tabs: Activity, Changes, Terminal, Files, Approvals. Preserve the active inspector tab per browser. Show counts only when meaningful.

### Task 6.2: Task-scoped activity

Merge durable task events with live SSE by event ID, dedupe, cap at 400, and never show events from another selected task.

### Task 6.3: Changes and terminal history

Changes uses the existing escaped diff renderer. Terminal is read-only command/run history from task telemetry, including exit code and test evidence; it does not create a second command execution bypass.

### Task 6.4: Files and approvals

Files show pinned/changed files and retain drag-and-drop upload. Approvals remain operator-only, exact-request-bound, and visible globally and per selected task.

---

## Phase 7 - Verification and release gate

### Task 7.1: Focused and full automated tests

Run each new regression test in RED and GREEN. Final command:

```powershell
python -B -m pytest tests -q -p no:cacheprovider --basetemp "$env:TEMP\harness-final-<unique>"
```

Then build a wheel from a clean archive, install it into an isolated environment, assert every static module is packaged, and run CLI help/import smoke tests.

### Task 7.2: Live backend/MCP test

Launch isolated state/project roots. Exercise task creation, worktree isolation, write/read, idempotency, secrets, approvals, fork lineage, pin persistence, SSE, restart confirmation/readiness, and persistence across restart. Stop all test processes and verify ports close.

### Task 7.3: Browser real-user matrix

At 1440x900, 1100x760, and 760x900:

1. Add/open project.
2. Create two sessions and switch via sidebar and task tabs.
3. Pin/unpin project and session; reload and verify persistence.
4. Drag both resizers; reload and verify dimensions.
5. Verify independent vertical scroll in all three panes.
6. Collapse/reopen navigation and inspector.
7. Exercise Activity, Changes, Terminal, Files, Approvals.
8. Upload a file, fork a task, change mode, copy resume prompt.
9. Check keyboard navigation, visible focus, Escape behavior, and no horizontal page overflow.

### Task 7.4: Windows Computer Use matrix

Resize/maximize/restore the real browser window, drag pane separators with the pointer, use wheel scrolling over each pane, use keyboard separators, and verify native folder picker behavior. Record screenshots and any controller/runtime limitation honestly.

### Task 7.5: Handoff to Claude Code

Update `docs/WORK_SESSION.md` with commits, changed files, rationale, test evidence, screenshots, known limitations, and the next unresolved item. Do not push unless explicitly requested.

---

## Definition of done

- Requested Codex-like layout behaviors are implemented and survive reload/window resize.
- Pinning and fork lineage are durable and tested.
- Previously confirmed approval, restart, environment, raw-Git, and health issues are resolved or explicitly documented as an unavoidable platform boundary.
- Full tests and clean-wheel installation pass.
- Live MCP and Cockpit flows pass using isolated state.
- Browser and Windows real-user checks pass, or a tooling blocker is recorded without substituting fake evidence.
- `git status` contains only intentional changes, and `docs/WORK_SESSION.md` enables a new session to resume immediately.
