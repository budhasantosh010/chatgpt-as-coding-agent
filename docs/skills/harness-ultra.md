---
name: harness-ultra
description: Execute the locked ULTRA WORKFLOW through sequential, forced-diverse candidate forks and parallel machine verification. Use only when a Run Contract enables candidate_count above zero.
---

# Harness ULTRA WORKFLOW

Echo the locked contract before starting. This is orchestration only: do not add
EFFORT tiers or load AOCS unless their independent contract rows enable them.

1. Distill one reconnaissance pass into `ultra/BRIEF.md`: facts, constraints,
   entry points, risks, and exact acceptance commands.
2. Pre-register a judging rubric. Build candidates sequentially using
   `fork_task(candidate=True)`. Give each a materially different algorithm, layer,
   or dependency strategy and write its `APPROACH.md` with weak points.
3. After committing a candidate, do not reopen its diff while building the next.
   This is procedural separation, not true model blindness.
4. Launch build, tests, lint, typecheck, and contract checks in every candidate
   worktree with `start_process`. Machine verification is parallel; model reasoning
   remains one sequential stream.
5. Red-team each candidate. A claimed defect needs an executed reproduction. A
   finding without an executed repro is reported as `unverified`, never as a bug.
6. Judge anonymized A/B candidates against the pre-registered rubric and recorded
   machine verdicts. For high-stakes work, offer a COLD JUDGE: a fresh chat receiving
   only anonymized artifacts and the rubric.
7. Promote the winner or explicit hybrid, rerun the whole contract, and write
   `ultra/DECISION.md` with reasons, loser contributions, and residual risks.
8. Append a RESUME-HERE checkpoint to `ultra/STATE.md` after every phase: completed
   phase, next action, decisive facts, and active process IDs.

Honesty: worktree isolation and parallel machine checks are real. Candidate authors
and the in-chat judge remain one model stream; sequential candidates cost wall time.

The laws (one stream; start_process for slow jobs; queue rule - never wait idle;
reality is the only judge) apply at every level.
