# Four Controls - First Flight Evidence

Date: 2026-07-18 (Asia/Dubai)

## Flight

- Disposable project: `.four-controls-flight-project` in the Codex workspace.
- Workbench task: `T-f6a5a665`.
- Contract: Build; EFFORT Medium 8; ULTRA Off; FRAMEWORK None; LOOPS Off;
  model concurrency 1; machine concurrency 2.
- Contract hash:
  `f3122cc319d28ffd6cdc7fb0450c90fb0f4287e52e46cb731b4f281b3dc08413`.
- Scope: `cs-8c1f89ae`; final spend 1/8 (machine 1, source 0, decision 0).
- Wall clock from task creation to completion: about 273 seconds. Continue
  nudges: 0. One local orchestration timeout was resumed from durable state.

## Result

- The seeded `add` implementation subtracted its second operand.
- The harness recorded the write and a passing `python -m pytest -q` execution:
  1 passed in 0.02 seconds; execution `px-cbb071e6`.
- Receipt `cy-8b647cea` records the conclusion, decision, command, execution id,
  and fingerprint
  `906f5366f5693d95f927a9573f8644d9f19c25d937f0301606ebb7d521eefda1`.
- AC-1 is satisfied with the same server-owned execution evidence.
- Completion was permitted only after the required criterion passed.
- `git diff --check` passed. No functional defect was introduced by the flight.

## Fail-closed evidence

The first cycle pre-registered `python check.py`. The run passed, but that command
is not a recognized test/build/lint/typecheck verifier and the submitted evidence
kind was invalid. The server spent 0 credits and left AC-1 open. The cycle was
explicitly abandoned, then replaced by the recognized pytest cycle. This is the
expected safety behavior, not a hidden retry.

## Audit reconciliation

The audit log contains the four expected tool calls: edit `calculator.py`, run the
original check, write `test_calculator.py`, and run pytest. Task events also record
contract confirmation, both observations, abandoned cycle, one credit spend, gate
satisfaction, legal state transitions, and completion.

## Acceptance boundary

- Passed: real localhost HTTP creation, immutable contract, durable resume,
  permission/approval path, observations, ledger, receipt, gate, completion, live
  Workbench read endpoints, audit reconciliation, and process-health checks.
- Blocked in this Codex session: visual browser/computer-use execution. The bundled
  control runtime failed before executing any command with `failed to write kernel
  assets: The system cannot find the path specified`, including after reset.
- Pending by definition: the operator must personally read the ledger, receipt,
  criteria checklist, and audit log and record belief in the walkthrough. An agent
  cannot truthfully sign that human judgment on the operator's behalf.
