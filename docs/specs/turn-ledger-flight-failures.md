# Turn Ledger first flight — 2026-07-28

Task `T-87586236a04f2236574706c8`, project `harness test 1`, build `b6c863c`,
connector `asdk_app_6a68c445…` (route rotated the same day).

## Verdict

**The Turn Ledger passed.** Three turns published; a brand-new chat called
`resume_task` and reported what was done, what was decided, and what happens
next without reading any code. That was the objective of the flight.

**The EFFORT cycle failed.** Not one of the three cycles could be completed.
Every `complete_cycle` was refused with `[EVIDENCE_INVALID]`, and all three
cycles were abandoned. Working code and a green pytest run could not be
converted into a spent credit.

Two findings are recorded below. F1 is the blocker; F2 is why it took three
cycles to notice. **Both are fixed** in `evidence.py` (4 new tests, suite
469 green) — but fixed is not flown. The re-flight is still owed.

---

## F1 — `verification_plan` is prose on the way in and command strings on the way out

**What happened.** `python -m pytest -q` ran through the harness, exited 0, and
was observed as `px-8ce92306`. `complete_cycle` cited it and was refused with
`[EVIDENCE_INVALID] no server-valid evidence references`. Repeated for
`px-b5383f32`, `px-a265f4b6`, `px-b2dd9af5` — every execution in the task.

**Where.** [harness/tasks/tools.py:748](harness/tasks/tools.py:748) hands
`cycle["verification_plan"].splitlines()` to `validate_evidence`, which at
[harness/evidence.py:154](harness/evidence.py:154) turns those lines into
`planned` — a set of pre-registered **commands** — and rejects any execution
whose command is not in it at [evidence.py:197](harness/evidence.py:197).

**Why it happens.** `begin_cycle` accepts `verification_plan` as a free-text
string ("run pytest and confirm the tests pass"). Nothing in the tool schema
says it must be exact shell command strings, one per line. So the plan lines
never equal the normalized command, and every execution is discarded.

**The worse case.** `verification_plan` defaults to `""`. `"".splitlines()` is
`[]`, which is *not* `None`, so `planned` becomes an **empty set** and the
`is not None` guard at `evidence.py:156` does not skip the check. A cycle
opened without a plan therefore rejects **every possible** execution
reference. The only way to pass is to guess that a plan line must be the
verbatim command — which the July 22 flight happened to do.

**Who it affects.** Every `complete_cycle` and every
`complete_refinement_pass` ([tools.py:858](harness/tasks/tools.py:858) has the
same line), i.e. the entire credit-spending path — the core of the product.

**When it was introduced.** Predates the Turn Ledger; `b6c863c` did not touch
`evidence.py`. It was masked because the one prior live flight guessed right.

**Solution (one line).** Treat `verification_plan` as prose: pass `None` when
it contains no line that parses as a command, and only enforce pre-registration
against lines that actually look like commands.

---

## F2 — `[EVIDENCE_INVALID]` throws away the diagnosis it already computed

**What happened.** The refusal said only "no server-valid evidence references".
ChatGPT could not tell whether the exec id was wrong, stale, unowned, or
un-pre-registered, so it cycled through evidence formats, burned two extra
cycles, and concluded the harness had an "evidence-registration bug" it could
not name.

**Where.** [harness/evidence.py:281](harness/evidence.py:281) — `if not valid:
raise ValueError(...)`. The `ignored` list, built through the whole function
with a precise `reason` per reference, is discarded at the raise.

**Why it matters.** Every other refusal in this system tells the model exactly
what is wrong. This one does not, so the model's only recovery strategy is
guessing — which is what turned one bug into three abandoned cycles.

**Solution (one line).** Include the per-reference `reason` list in the
`[EVIDENCE_INVALID]` message.

---

## Not a failure, recorded for accuracy

- ChatGPT called `publish_turn` **unprompted** after each stretch of work; the
  `harness-turns` skill was sufficient. The open compliance question is closed.
- `[NO_OPEN_TURN]` fired correctly when asked to publish an already-published
  turn.
- The gate did its job: three cycles' work reached the ledger despite none of
  them completing.
- The model wrote `FAILURE_DOCUMENTATION.md` into the test project. That file
  is model-authored prose, not evidence, and is not the source for this record —
  everything above is read from `tasks.db` events and `chat/turns.jsonl`.
