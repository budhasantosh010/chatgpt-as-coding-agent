# Four Controls — Clarifications and Deviations

## D-001 — LOOPS source delta input

- Spec conflict: §10 requires a changed conclusion in `delta_summary`, but the
  specified `complete_refinement_pass` signature has no `delta_summary` input.
- Resolution used: add `delta_summary=""` as an optional final parameter. Source
  passes require it to be non-empty; existing callers and all other kinds remain
  backward compatible.
- Scope: Phase 7 only. No other contract behavior is changed.

## D-002 - Named credit extensions preserve the candidate base

- Approval consumption and the approved extension are one SQLite transaction.
  A root-scope extension updates the root ceiling and contract base/hash. A named
  candidate-scope extension updates only that candidate pot; later candidates
  retain the operator-confirmed base ceiling.
- This prevents one candidate approval from silently funding future candidates.

## D-003 - Visual runtime unavailable in this Codex environment

- The bundled browser/computer runtime fails before JavaScript execution with
  `failed to write kernel assets: The system cannot find the path specified`.
- Backend, HTTP integration, renderer assertions, JavaScript syntax, first-flight,
  and full regression tests pass. Visual drag/resize confirmation remains an
  explicit operator gate and is not reported as passed.
