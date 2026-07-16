# Active Work Session - Codex-style Harness Workbench

**Last updated:** 2026-07-16 18:07 Asia/Dubai (Codex)

## Resume protocol

1. Read this file.
2. Read `docs/plans/2026-07-16-codex-workbench-redesign.md`.
3. Run `git status --short --branch` and compare it with the checkpoint below.
4. Continue the single `NEXT STEP`; do not restart research or re-plan completed work.
5. After each RED/GREEN slice, update this file before doing the next slice.

This file is deliberately compact so chat compaction or a new session does not require replaying the conversation.

## User intent that must not drift

- Build in this repository: `C:\Users\Lenovo\Music\Startups\Chatgpt as a Harness\Chatgpt as a harness built with Claude Code`.
- ChatGPT remains the model/message surface. The local Cockpit should otherwise behave like a polished Codex-style coding workbench.
- Highest-impact scope: resizable/collapsible panes, multiple visual task/inspector tabs, independent vertical scrolling, project/session pinning and navigation, responsive window resizing, backend reliability fixes, and real-user E2E verification.
- Apply a billion-dollar-company CTO architecture gate. Refactor when ownership/state/testability are unclear, but avoid low-impact churn.
- Be token-efficient and preserve continuity in repository files.

## Baseline

- Branch: `main`
- Baseline commit: `095e1b5f8ecc7d596c397bee75c3117c24bf8277`
- Baseline remote: `origin/main` at the same commit
- Baseline automated tests: `279 passed, 1 warning in 103.76s`
- Baseline wheel: built, installed, imported, CLI-smoked; 57 MCP tools present
- Initial working tree before this plan: clean

## Reference research completed

- Inspected current official OpenAI Codex product material and fresh Codex manual.
- Inspected `openai/codex`, `anomalyco/opencode`, and `pingdotgg/t3code` through the GitHub connector.
- Read T3 Code's resizable sidebar/width hook and OpenCode's layout/sidebar/resize primitives.
- Inspected the two user screenshots and the complete current Cockpit HTML/JS/CSS plus its Starlette API and tests.

## Confirmed pre-existing defects to fix

1. Safe test commands execute repository code on the host under the local executor; this is not a hard sandbox.
2. Raw `git commit` through `run_command` can use repository hooks even though the dedicated Git adapter disables them.
3. The restricted Windows environment broke `pytest`/Python user-site resolution in the live harness.
4. Recently used tasks left in `new` do not trigger restart confirmation; restart returns before engine readiness.
5. Identical pending approvals are duplicated.
6. `fork_task` emits lineage events but does not persist `parent_id`.
7. `/health` exposes avoidable metadata before the normal Host/Origin gate.
8. Fresh Browser and Computer Use automation previously failed to initialize with `failed to write kernel assets ... (os error 3)`; retry after implementation and report honestly.

## Completed in this redesign

- [x] Reference UI/UX and repository research
- [x] Current architecture inspection
- [x] Durable implementation plan created
- [x] Backend integrity slice
- [x] Durable project/session pinning and task-scoped event API
- [x] Frontend modularization into native ES modules
- [x] Initial three-pane desktop shell and independent scrollers
- [x] Initial pinning/search/task tabs and right inspector dock
- [x] Frontend checkpoint parity and package-data coverage
- [x] Responsive/collapse/accessibility shell contracts
- [x] Search/sorting/activity/terminal/files contracts
- [x] Automated full-suite and clean-wheel verification
- [x] Isolated live backend/MCP verification
- [x] Desktop, constrained, and compact browser verification
- [x] Windows Computer Use attempted; native capture failed before input

## Current checkpoint

- Backend integrity, durable pins, task-scoped events, modular frontend parity,
  responsive shell, navigation/tabs, and all inspector views are implemented.
- Frontend ownership is split into `api.mjs`, `state.mjs`, `layout.mjs`,
  `render.mjs`, and `app.mjs`; legacy `cockpit.js` is deleted.
- Final full suite: `305 passed, 1 warning in 93.84s`.
- All five `.mjs` modules pass `node --check`; `git diff --check` passes.
- A real isolated MCP/Cockpit runtime verified task creation, isolated worktrees,
  exact approval/retry behavior, fork lineage, scoped stable event IDs, durable
  pins, minimal health, supervisor readiness, and state after restart.
- Live MCP testing found and fixed an unsafe idempotency-key collision: the same
  operation ID with different arguments now fails closed with
  `IDEMPOTENCY_CONFLICT`; exact retries still return the cached result.
- Live browser testing found and fixed three integration-only UI defects:
  missing `commands` in `/api/state` crashed Terminal, periodic refresh reset the
  center scroll position, and hidden grid items collapsed the center pane to zero.
- The LSP definition flake was traced to asynchronous indexing; bounded
  `0.2/0.5/1.0` backoff now covers repeated empty results. All 8 LSP tests pass.
- Browser E2E verified desktop `1440x900`, constrained `1280x720`, and exact
  compact `759x900`: multi-session tabs, search, mode changes, fork, pin/unpin,
  all inspector views, independent pane scrolling, scroll persistence, navigation
  drawer/backdrop/Escape/focus return, inspector overlay, collapse/reopen,
  keyboard resizing/persistence, and no horizontal overflow.
- Final clean wheel:
  `release-artifacts-20260716-final/chatgpt_code_harness-0.1.0-py3-none-any.whl`
  with SHA-256 `a3f86bc58028731775f253874ab7f25b22b3b71e9d836a8ba82d7aff28df3298`.
  Its manifest has exactly seven Cockpit assets and no legacy script. A brand-new
  venv passes dependency, import, asset, and CLI-help smoke checks.
- Added-line security scan: zero hardcoded-secret, shell-injection, eval/exec,
  pickle, or SQL-interpolation matches. Ruff reports the same 29 findings on
  clean `HEAD` and the finished tree, so this change adds no lint regression.
- The isolated live-audit supervisor and engine were stopped; ports 8948 and
  8949 were verified closed.
- No commits or pushes were created.

## NEXT STEP

Hand this diff and this file to Claude Code for the requested independent review.
If the environment becomes available, run the two remaining external checks:
native pointer dragging in a capturable browser window and Docker-backed hard
sandbox execution. No planned product implementation slice remains.

## Blockers

- The local executor is still not a hard OS sandbox. Docker Desktop's Linux daemon
  was unavailable, so container-backed isolation was not exercised.
- Synthetic browser drag did not move the separator. Keyboard resizing and width
  persistence pass, but native pointer drag remains unverified because Windows
  Computer Use failed before input with
  `SetIsBorderRequired failed: No such interface supported (0x80004002)`.
- The independent-reviewer subagent required by the review skill could not run
  because this session explicitly forbids subagents. Security, tests, lint-baseline,
  packaging, live MCP, and browser gates were run; the final review is not independent.
