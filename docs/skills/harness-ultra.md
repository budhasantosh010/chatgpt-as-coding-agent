---
name: harness-ultra
description: Effort levels (QUICK/STANDARD/DEEP/ULTRA) + the deep-quality pipeline for the chatgpt-code-harness — validated one-brain architecture; sequential AOCS roles, parallel machine verification, cooperative multitasking. v2, informed by how ultracode/Ultra/ultrareview actually work.
---

# Harness Ultra v2 — effort levels & the deep pipeline

You are operating through the chatgpt-code-harness MCP connector. These laws
were established by audit-verified experiments (2026-07-17); never violate or
overclaim against them:

- There is exactly ONE reasoning stream (you). "Parallel subagents" on this
  surface are roleplay — NEVER claim parallel thinking or isolated sub-minds.
- Machines DO run in parallel: use `start_process` for anything slow.
  `run_command` blocks — never use it for slow jobs.
- THE QUEUE RULE — never wait idle: while any machine job runs, think/work on
  the next item. Call `read_process` only when you have nothing left to think
  about.
- Reality is the only judge: a passing test outranks any amount of agreement.
  A failing test means NOT DONE, no matter how confident the reasoning.

## Step 0 (every DEEP/ULTRA run): the one real compute lever

Tell the user once: "Set ChatGPT's own model/effort picker to its highest
thinking level for this chat." That picker is the ONLY control that increases
actual model compute (provider effort = trained thinking-token budget). This
skill's tiers change your PROCEDURE and rigor — they cannot change the hidden
thinking budget. Both levers together = maximum quality.

## Effort tiers (the user picks one per task; no tier given → STANDARD)

| Tier | AOCS depth | What you do |
|---|---|---|
| QUICK | 0 | One Specialist pass + run the directly relevant test. Typos, small fixes. |
| STANDARD | 1 | Specialist → implement → full test suite + `git_diff` self-review. |
| DEEP | 2 | Explorer (read first) → Specialist → Red Team attack on your own work (with executed repros, see below) → fix → parallel machine checks (tests + lint + typecheck via `start_process`, simultaneously; think while they run) → Judge verdict vs acceptance criteria. |
| ULTRA | 3 | The full pipeline below. Requires the confirm step. |

## THE ULTRA PIPELINE (our ultracode — one brain, best-of-N, machine-parallel)

1. **CLASSIFY & CONTRACT.** Restate the task; classify Type 1/2/3 and risk;
   choose N candidates (default 2, max 3). Write testable success criteria and
   the EXACT verification commands into `ultra/CONTRACT.md` and
   `set_acceptance_criteria`. Then show the user an estimate (roughly N× a
   normal solve, in time and quota) and WAIT for their explicit go — the
   analog of ultracode's Large-workflow warning. Remind them about the picker
   (Step 0).
2. **RECON & BRIEF.** Read the relevant code ONCE; distill everything needed
   into `ultra/BRIEF.md` (facts, constraints, entry points, risks). All later
   phases work from the brief, not from re-reading the world — this keeps
   context lean (our analog of "intermediate results live in script
   variables").
3. **SEQUENTIAL CANDIDATES — artifact-isolated, forced-diverse.** For each
   candidate i: `fork_task` (own worktree); implement under a MANDATED
   distinct strategy (candidate 2 must differ materially: different algorithm,
   layer, or library — TMR discipline); write `APPROACH.md` in its worktree
   including self-declared weak points; commit. RULE: once candidate i is
   committed, do not reopen its diff while building i+1 (procedural
   separation — say honestly that it is procedural, not true blindness).
4. **PARALLEL MACHINE VERIFICATION — the genuinely parallel step.** In EVERY
   candidate worktree simultaneously: `start_process` build + tests + lint +
   the CONTRACT's verification commands. While the machines run (queue rule):
   write the judging RUBRIC now, BEFORE seeing any results — pre-registration
   prevents grading to fit the winner you secretly prefer.
5. **RED TEAM WITH EXECUTED REPROS.** Adversarial pass per candidate. Every
   claimed defect needs a repro script ACTUALLY RUN via `start_process`/
   `run_command`. A finding without an executed repro is reported as
   "unverified", never as a bug — the reproduce-before-report rule that makes
   ultrareview trustworthy.
6. **JUDGE — blind-ish, rubric-bound.** Present the candidates to yourself as
   A/B (order shuffled, authorship notes stripped) with their machine verdicts
   attached; score strictly against the pre-registered rubric; pick a winner
   or an explicit hybrid. State the limitation: the judge shares the stream
   that wrote the candidates. HIGH-STAKES OPTION — offer the user the COLD
   JUDGE: they open a fresh ChatGPT chat that loads only this skill's judge
   step plus the anonymized diffs/verdicts; a fresh context is the only real
   blindness available at £0.
7. **SYNTHESIZE & PROMOTE.** Merge the winner (or winner + specific stolen
   pieces from losers, each re-verified) into the project; rerun the full
   CONTRACT verification; write `ultra/DECISION.md` (what won, why, what the
   losers contributed, residual UNVERIFIED risks); keep losing worktrees until
   the user confirms; `finish_task` with real evidence.
8. **CHECKPOINT CONTINUOUSLY.** After every phase, append to `ultra/STATE.md`
   with a RESUME-HERE block (phase done, next step, key facts) — so if the
   chat/context dies, a fresh chat resumes mid-run with
   `resume_task` + reading STATE.md.

## Honesty contract (include in every ULTRA report)

REAL here: parallel machine verification; worktree artifact isolation;
executed-repro gating; N genuinely different attempts; checkpoints; the
user's picker raising true compute; cold-judge isolation via a fresh chat.
IMITATION here: roles are one model changing stance; within-chat blindness is
procedural; sequential best-of-N pays with wall-clock time, not parallel
workers; tiers raise rigor, not the hidden thinking budget. Never present the
imitation as the real thing.

## Invocation contract

The user says: `ULTRA: <goal>` (or `QUICK:` / `STANDARD:` / `DEEP:`).
Start every level by opening a task (`start_task`), end with `finish_task`
carrying real evidence. For depth ≥ 2, load the `my-aocs-omega` skill IN FULL
(all pages via offset) when doctrine details are needed.
