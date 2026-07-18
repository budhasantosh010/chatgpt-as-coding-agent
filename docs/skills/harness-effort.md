---
name: harness-effort
description: Run auditable EFFORT cycles through the chatgpt-code-harness credit ledger. Use when a confirmed Run Contract enables EFFORT and work must be bounded, evidence-backed, and resumable.
---

# Harness EFFORT

First remind the user once: raise ChatGPT's own model/effort picker for real
thinking depth. Harness credits change procedure and auditability, not hidden model
compute.

## Spend protocol

1. Call `get_effort_status` and read the locked ceiling and open cycle.
2. Before significant work, call `begin_cycle` with one concrete question and
   pre-register exact intended test/build/lint/typecheck commands.
3. Investigate one question at a time. Reads and checks may continue outside a
   cycle, but never manufacture work merely to spend credits.
4. Call `complete_cycle` with a conclusion, decision, and server-citable evidence.
   Abandon a stale direction without spending using `abandon_cycle`.
5. Stop early when the acceptance gates pass. A ceiling is a speed limit, not a
   quota. Exhaustion never means done; request an extension or stop incomplete.

## Evidence tiers

- Machine: a fresh recorded execution or changed write. Good: a pre-registered
  test run with its `exec_id`. Bad: narration, `echo`, `git status`, or a command
  merely approved to run.
- Source: a file actually read through the harness, with file, lines, fact, and
  its recorded content hash. Good: a cited implementation fact. Bad: a path never
  read through the harness.
- Decision: `what` and `why`, used only for real tradeoffs and subject to the
  task-type cap. Good: reject caching because invalidation is unsound here. Bad:
  "thought more" or repeated paraphrases.

Credits are an odometer and speed limit, not an engine. They bound and audit the
procedure; they cannot guarantee deep thought. Done is decided only by individually
verified acceptance gates. Full receipts stay in SQLite and regenerable Markdown
views, not chat context.

The laws (one stream; start_process for slow jobs; queue rule - never wait idle;
reality is the only judge) apply at every level.
