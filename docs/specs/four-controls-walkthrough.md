# Four Controls - Operator Walkthrough

This is the repeatable real-user acceptance check for the locked Run Contract.
Record the date, build/commit, task id, and any defect in the table at the end.

## Before starting

1. Start the Workbench with `python -m harness up` and open the printed
   localhost URL.
2. Add a small disposable Git project containing at least one test.
3. Keep the browser developer console open. A console error is a failure.

## A. Workbench shell

- Resize the left project/session pane and right inspector pane. Refresh and
  verify both widths persist.
- Pin and unpin one project and one session. Verify pinned items stay first.
- Open several sessions as center-pane tabs; switch and close a tab without
  deleting its session.
- Scroll a long project/session list, the center workspace, and the inspector.
  Each pane must scroll independently without hiding its controls.

## B. Lock a contract

1. Click **New session** and enter a goal.
2. Select EFFORT Medium (8), ULTRA 2, FRAMEWORK None, LOOPS 2, TASK TYPE Build.
3. Verify the estimate says at most 72 procedure credits, one model stream, two
   machine jobs in parallel, and warns about continue nudges.
4. Click **Confirm & lock** once.
5. Verify the task page immediately shows the same four values and a contract
   hash. Refresh; values and hash must be unchanged.
6. Create a second task with custom ULTRA and LOOPS values. Verify the locked
   contract uses the entered bounded integers, not the word `custom`.

## C. Exercise the contract

1. Add at least one machine acceptance criterion.
2. Call `get_effort_status`; verify the root scope starts at 0/8.
3. Open one cycle with a concrete question and pre-registered test command.
4. Make the small change, run that exact test through the harness, and complete
   the cycle using the recorded execution id.
5. Verify the Workbench shows 1/8, a machine-tier receipt, and a regenerable
   receipt Markdown file. Reusing the same execution for another credit must fail.
6. Satisfy the criterion with valid evidence. `finish_task` must refuse before
   the gate passes and succeed only after every required gate passes and the
   latest relevant verification is green.
7. Run one refinement pass. Verify its input/output state and outcome appear.
   Repeating the same directive against unchanged state must fail.
8. For an operator-kind criterion or pass, verify the model cannot confirm it;
   only the local Workbench **Confirm** button can.

## D. Safety and honesty

- On a read-only task, directly call every new mutating MCP tool. Each must return
  `PERMISSION_DENIED`; status/receipt reads must still work.
- Verify ULTRA creates candidates sequentially and never claims parallel model
  workers. Only machine checks may run in parallel.
- Verify credits are described as procedure/audit credits, never model tokens or
  proof of quality. Exhausting credits must not mark the task done.
- Verify no browser console error, server traceback, stuck process, orphaned Git
  probe, or unexplained background CPU remains after the walkthrough.

## E. Before you trust any of it: the connector actually has the tools

ChatGPT caches its tool menu against the connector URL. Deleting and re-adding
the connector does **not** clear that cache, so a server change can be invisible
for weeks while everything looks healthy locally.

1. Ask a fresh chat to list the connector's tools and give a total.
2. Compare against `tools/list` on the server itself.
3. If they disagree, check `state_dir/connector.jsonl` for a `tools/list` line
   from an `openai-mcp/*` agent. No such line means ChatGPT never re-read the
   menu, and nothing you change locally can reach it.
4. The fix is a new URL: rename `state_dir/secret_route.txt` and restart. The
   engine mints a fresh route and the Tailscale funnel is untouched (it forwards
   :443 to the port regardless of path). Re-add the connector with the new URL.

## Acceptance record

| Field | Result |
|---|---|
| Date / build | 2026-07-22, commit `3be5866` |
| Task id | `T-3d4f7a8f7dd72c5aa0b4a00b` |
| Contract hash | `9ef0b729af` — unchanged across the run |
| Connector tool surface (E) | **Pass.** 51/66 before route rotation, 66/66 after; `tools/list` from `openai-mcp/1.0.0` recorded at 20:17:26Z |
| Contract lock (B) | **Pass.** build / Medium 8 / ULTRA Off / LOOPS Off, immutable after confirm |
| Ledger and receipts (C1-C5) | **Pass.** 0/8 → 1/8 on one machine-tier credit; receipt `cy-e95aa66d2b250055d16dbef0.md` written |
| Evidence enrichment | **Pass.** Model supplied `exec_id` + `reason` only; server wrote `command` and `execution_fingerprint` |
| Reused execution (C5) | **Pass.** Real `px-8dccd639` replayed into a later cycle → `EVIDENCE_INVALID` |
| Fabricated execution | **Pass.** `px-deadbeef` → `EVIDENCE_INVALID` |
| Workspace confinement (D) | **Pass.** Write to `~\Desktop` → `PERMISSION_DENIED`, and the refusal is in `audit.jsonl` |
| Abandoned cycle | **Pass.** Closed with no credit spent; ledger stayed 1/8 |
| Audit fidelity | **Pass.** 9 flight calls, 9 audit rows, same order; 4 refusals also recorded |
| Workbench render | **Pass.** UI independently shows 1/8, hash, 1 receipt, gates 0/1, 1 file changed, 1 test run |
| Browser console / server log | **Pass.** No console errors; no traceback; 433 tests green |
| Gate honesty | **Pass.** Criterion stayed `0/1` after the credit was spent — passing a test does not self-award the gate |
| **Not run this session** | Shell/resize checks (A); `satisfy_criterion` and the `finish_task` refusal (C6); refinement passes (C7); operator-kind confirmation (C8); read-only denial of *every* mutating tool (D1); ULTRA candidates (D2) |
| Defects found | None in the harness. One test-design defect on our side: `complete_cycle` with no cycle open returns `NO_OPEN_CYCLE` and never reaches the evidence check — a double-spend probe must be run against an **open** cycle or it proves nothing |
| Operator believes the evidence | Pending operator sign-off |

The feature is not fully accepted until the operator has filled this record and
personally read the first-flight ledger, receipts, gates, and audit log.

## First recorded run

Real ChatGPT over the Developer-Mode connector, no model-provider API involved.
Seeded defect: `add()` in `calc.py` returned `a - b`.

```
20:22:25  resume_task
20:22:31  set_acceptance_criteria      AC-1, machine, required
20:22:36  begin_cycle                  cy-e95aa66d…   scope 0/8
20:22:43  read_file calc.py
20:22:45  read_file test_calc.py
20:22:52  edit_file calc.py            a - b  ->  a + b
20:22:59  run_command                  pytest -q  ->  1 passed   px-8dccd639
20:23:09  complete_cycle               credit spent, scope 1/8
20:23:15  get_effort_status            1/8, criteria 0/1, contract hash OK
```

The receipt records what the server observed, not what the model reported:

```json
{
  "kind": "execution",
  "exec_id": "px-8dccd639",
  "reason": "pytest passes after the fix",
  "command": "python -m pytest test_calc.py -q",
  "execution_fingerprint": "7a6b7649c8da87e1203230af13c89d734f5ff973a044d537bce980c274f7eb2c"
}
```

The reuse guard is a time window, not a used-id blacklist — `evidence.py` requires
`_fresh(event, opened_at, started=True)`, so an execution must begin after the
cycle opens. Evidence from an earlier cycle can never qualify, including evidence
that was never spent.
