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
- [ ] Phase 9 — Benchmarks and real-user flight

## RESUME HERE

- Current phase: Phase 9 acceptance — implementation complete, human/visual gate pending.
- Last verified checkpoint: fixed five-case benchmark pack and Medium first flight
  are recorded; post-audit hardening and final full regression suite passed.
- Phase 9 evidence: 3 benchmark-pack tests pass and all five untouched seed cases
  fail their intended objective checks; first-flight task `T-f6a5a665` completed
  with contract hash `f3122cc319d2...`, one machine credit, one valid receipt,
  pytest 1 passed, AC 1/1, and reconciled audit events. An independent review
  identified 22 safety/workflow gaps; fixes now cover atomic one-shot extensions,
  current-state evidence, canonical receipt identity, terminal immutability,
  isolated candidates, enforced machine concurrency, honest Workbench config,
  public criterion kinds, durable operator-loop outcomes, contract repair, and
  visible audit evidence. Focused suite: 113/113. Final full suite: 416 passed,
  1 deprecation warning in 99.72 seconds.
- Pending: the bundled browser/computer-use runtime failed before execution with a
  missing-assets error, controlled baseline/variant benchmark arms remain unrun,
  and the operator has not yet personally signed the walkthrough belief gate.
- Do not check Phase 9 or claim whole-feature acceptance until those explicit
  items are completed. Resume from this exact list; do not repeat Phases 0-8.

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
