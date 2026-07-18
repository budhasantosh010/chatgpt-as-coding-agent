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

## Acceptance record

| Field | Result |
|---|---|
| Date / build | Pending operator run |
| Task id | Pending |
| Contract hash | Pending |
| Shell and resize checks | Pending |
| Contract and estimate checks | Pending |
| Ledger, receipts, gates, loops | Pending |
| Read-only denial | Pending |
| Browser console / server log | Pending |
| Defects found | Pending |
| Operator believes the evidence | Pending |

The feature is not fully accepted until the operator has filled this record and
personally read the first-flight ledger, receipts, gates, and audit log.
