# Four Controls — Build Progress and Resume Record

This file is the durable checkpoint for Codex, Claude, GPT, and the operator.
Update it only with verified facts. A phase is checked only after its phase tests and
the full existing suite pass.

## Source of truth

- Specification: `docs/specs/four-controls-spec.md` v1.2
- Starting code commit: `184633a`
- Implementation method: strict test-first RED → GREEN → REFACTOR
- Backward compatibility: all controls Off/absent preserves existing behavior

## Phase checklist

- [x] Phase 0 — Specification corrected to v1.2
- [x] Phase 1 — Concurrency-safe storage and Run Contracts
- [x] Phase 2 — Per-criterion completion gates
- [x] Phase 3 — Observations and fingerprints
- [x] Phase 4 — EFFORT scopes, ledger, receipts, extensions
- [x] Phase 5 — ULTRA candidate enforcement
- [x] Phase 6 — FRAMEWORK routing
- [x] Phase 7 — LOOPS engine
- [x] Phase 8 — Workbench and split skills
- [x] Phase 9 — Real-user flight (signed 2026-07-29; benchmark arms descoped — see below)

## Phase 9 acceptance — signed 2026-07-29

Operator sign-off: the walkthrough belief gate was satisfied by the operator
personally, on the machine, on 2026-07-29. Evidence below is read back from
`tasks.db` and disk, not from anyone's account of it.

Second flight — a clean project (`…/testing projects/tests/big test`), driven
end to end from ChatGPT with no local prompting:

| Fact | Value | Source |
| --- | --- | --- |
| Task | `T-df66550dbd02a833b86dc607` | `tasks` |
| Lifecycle / result | `completed` · "stringkit complete" | `tasks` |
| Permission mode | `auto_workspace` | `tasks` |
| Contract | `rc-6348907979a90199334d515d` hash `99f47a4dedea18ae…` | `run_contracts` |
| Contract terms | build · EFFORT medium (ceiling 8) · ULTRA 2 · LOOPS 2 · FRAMEWORK none | `contract_json` |
| Confirmed at | 2026-07-28T21:14:48Z | `run_contracts` |
| Credit scope | `cs-a8efcfb2b49f8aba439bec2e` ceiling 8, 1 spent | `credit_scopes` |
| Receipt | `effort/cy-c0d5f09deebe739aa5403017.md` | disk |
| AC-1 (machine) | satisfied 2026-07-28T21:37:09Z | `criteria_v2` |
| AC-2 (operator) | satisfied 2026-07-29T17:02:04Z, from the Workbench | `criteria_v2` |
| Turn Ledger | 6 turns published | `chat/turns.jsonl` |
| Suite at signature | 476 passed, 1 deprecation warning, 88s | pytest |

What the flight proved that the suite could not. Three refusals fired against a
model actively trying to close the task:

- `pytest` exiting 1 was refused as proof — a failure is not evidence.
- A borrowed `exec_id` from another task was refused — not owned.
- `echo done` (exit 0) was refused — not a recognized verification command.

And the operator gate held: the model attempted AC-2 with a machine result and
got `[OPERATOR_REQUIRED]`. It completed every other part of the work and still
could not mark the task done. Only the local click closed it.

The flight also found three real defects that 471 green tests had missed, all
fixed and regression-tested before this signature:

- F1 — a prose `verification_plan` was split into "pre-registered commands", so
  an absent plan (`"".splitlines()` is `[]`, not `None`) rejected every
  execution. Fixed by `_pre_registered()` in `harness/evidence.py` (`a967e23`).
- F2 — `[EVIDENCE_INVALID]` discarded the per-reference reasons it had already
  computed, leaving the model guessing. Fixed in the same commit.
- F3 — `finish_task` deadlocked on its own invocation: the observation hook
  records the call before the tool runs, so the gate counted itself forever.
  Fixed with `ignoring={"finish_task"}` (`9eec0ce`).

Full write-up: `docs/specs/turn-ledger-flight-failures.md`.

### Descoped, not done — recorded so nobody later reads this as complete

- **Controlled baseline/variant benchmark arms: NOT RUN.** Phase 9 was accepted
  on the real-user flight alone. There is no measured claim anywhere that the
  four controls improve outcomes — only that they are enforced as specified.
  Any future "the controls make it better" claim needs these arms first.
- **Bundled browser/computer-use runtime: NOT FIXED.** It failed with a
  missing-assets error and was dropped from scope by the operator on
  2026-07-29 as unnecessary for this build.

## RESUME HERE

- All phases complete. The build is usable for real work.
- Open, non-blocking: archive the junk sessions in the Workbench sidebar.
- Do not repeat Phases 0-9. If Phase 9 is reopened, it is for the benchmark
  arms above, and only those.

## Decisions that must not drift

- Permission to run a command is not permission to count it as proof.
- One task family points to one `contract_id`.
- Ordinary subtasks and forks share their parent's credit scope.
- Candidate forks get separate scopes only when EFFORT is On.
- EFFORT Off means no credit scope exists.
- Credits never mean done; every required criterion must be proven.
- Model concurrency is configuration-owned; contracted machine-process
  concurrency is enforced atomically per task family.
- No model-provider API calls.
