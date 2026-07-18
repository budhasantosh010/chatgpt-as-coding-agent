# SPEC — The Four Independent Controls (EFFORT / ULTRA / FRAMEWORK / LOOPS)

- **Version:** 1.0 (2026-07-18)
- **Status:** LOCKED for build. Design converged over three adversarial review rounds
  (operator ⇄ GPT ⇄ Claude). Do not redesign while building.
- **Builder:** Codex (or any coding agent). **Spec author/auditor:** Claude. **Approver:** the operator.
- **Repo:** chatgpt-as-coding-agent (this repo). Python MCP server (`harness/`), FastMCP,
  SQLite store, Workbench GUI on localhost:8849.

---

## 0. How the builder must use this document

1. **Build exactly what is written.** If something seems wrong or impossible, do NOT
   silently improvise: write the problem + your proposed change into
   `docs/specs/DEVIATIONS.md` and stop that sub-item until the operator answers.
2. **Build in phases (§18), in order.** A phase is done only when its acceptance
   criteria pass AND its listed tests are green AND the full existing suite
   (314 tests at time of writing) stays green.
3. **Back-compat is law:** with every new control set to Off/absent, the harness must
   behave byte-for-byte like today. Existing tests are the proof.
4. Follow the repo's existing style: pydantic models with defaulted fields (JSON-blob
   storage makes this backward compatible), dataclass Config with `HARNESS_*` env vars
   validated in `__post_init__`, ordered SQLite migrations in `harness/tasks/store.py`,
   tool functions returning plain strings with `Error: [CODE] message` on failure.
5. Never call any model-provider API. This project's founding law is £0.

---

## 1. Background the builder must know (established facts, not opinions)

- The "brain" is the operator's personal ChatGPT (chatgpt.com, Developer-Mode MCP
  connector → this server via Tailscale Funnel + secret route). The server is "hands".
- **Empirical fact (audit-verified 2026-07-17/18):** this ChatGPT surface has ONE
  reasoning stream. Asked to spawn subagents it role-plays them in strict A-B-A-B
  turns with zero speedup. Real parallelism exists only at the OS level
  (`start_process`). Therefore: model concurrency = 1 on the current host
  (config value, not hardcoded dogma — a future host may differ).
- The model's hidden thinking budget is controlled ONLY by the human using ChatGPT's
  own model/effort picker. Nothing in this server can change it, and nothing in this
  spec pretends to.
- **The metering truth this whole design rests on:** Codex/Claude Code meter tokens
  because the *provider* reports usage externally to the model. Here, any "how much I
  thought" number would be self-reported by the same model being measured — and this
  project has already caught the model overclaiming once (Test 2). Therefore **credits
  are validated by the server from things the server itself observed**, never from
  model claims alone.
- Approvals machinery that already exists and works (reuse, don't rebuild): approvals
  table + `_gate_with_wait` in `harness/server.py` holds a tool call open up to
  `approval_wait_seconds` (90s from env) while the operator clicks Approve/Deny in the
  Workbench; deny is terminal `Error: [APPROVAL_DENIED]`.
- Completion machinery that already exists (reuse, don't rebuild): tasks carry
  `acceptance_criteria` (set via `set_acceptance_criteria`), and `finish_task`
  demands evidence. That is the "completion gates" side of this spec.

---

## 2. Locked glossary (one meaning per word — no drift allowed)

| Term | Meaning (the ONLY meaning) |
|---|---|
| **EFFORT** | Ceiling of validated deliberation cycles one attempt may spend. NOT model thinking depth. |
| **credit** | Permission for one deliberation cycle. Spent, never earned. Ceiling, never quota. |
| **deliberation cycle** | question → evidence → conclusion → decision, validated by the server. |
| **receipt** | The stored record of one completed cycle (file on disk + DB row). |
| **receipt tier** | MACHINE (execution result) > SOURCE (code fact w/ refs) > DECISION (judgment). |
| **completion gates** | Acceptance criteria + verification evidence. The ONLY thing that means "done". |
| **ULTRA** | Orchestration of N rival solution attempts. NOT an effort level. Never called "ultracode". |
| **candidate** | One rival attempt at the goal, built in its own worktree via `fork_task`. |
| **model concurrency** | How many model reasoning streams run at once. Currently 1. From config. |
| **machine concurrency** | How many OS processes run at once via `start_process`. Genuinely parallel. |
| **FRAMEWORK** | Optional reasoning doctrine the model follows (today: AOCS Omega). Never auto-enabled. |
| **LOOPS** | Maximum evidence-gated improvement passes over the current best result. |
| **Run Contract** | The four controls' locked configuration, stored ON the task, confirmed by the operator. |
| **observation** | Something the server itself recorded: a file read, a command run, a diff, an exit code. |
| **Chinese whispers** | Information loss between parties. This spec exists to make it zero. |

What each control is **NOT** (say this in every user-facing doc):
- EFFORT is not the ChatGPT picker and cannot raise hidden thinking. Both knobs together = max quality.
- ULTRA is not parallel model minds on this host. Candidates are sequential; machines are parallel.
- FRAMEWORK is not magic; it is a doctrine the model must *record* following.
- LOOPS is not blind repetition; a pass without a new target + measured delta is rejected.

---

## 3. The four controls — locked definitions

```
 EFFORT     Off | Low 2 | Medium 8 | High 16 | XHigh 32 | Max 50   (credits per attempt)
 ULTRA      Off | Auto | 2 | 3 | 5 | 8 | Custom(advanced)          (candidates)
 FRAMEWORK  None | AOCS Omega                                      (doctrine)
 LOOPS      Off | 2 | 5 | 10 | Custom                              (max refinement passes)
```

- Every row independent. Every combination legal. Everything Off = today's behavior.
- The numbers 2/8/16/32/50 are **unvalidated defaults** stored in config (§4.3),
  displayed as "deliberation credits", never as "tokens". Phase 19 calibrates them.
- The rules the four rows share: ceilings not quotas; early stop always allowed when
  gates pass; exhaustion never implies completion; extension only via operator approval.

---

## 4. Data model changes

### 4.1 Task model (`harness/tasks/model.py`)

Add to `Task` (pydantic, all defaulted → old rows load unchanged):

```python
# --- Run Contract (four controls). Locked once operator_confirmed is True. ---
run_contract: dict = Field(default_factory=dict)
```

`run_contract` canonical shape (empty dict = no contract = everything Off):

```json
{
  "contract_version": 1,
  "task_type": "build",              // build | review | plan | research
  "effort_level": "high",            // off | low | medium | high | xhigh | max
  "credit_ceiling": 16,              // resolved from config profile at confirm time
  "ultra_enabled": true,
  "candidate_count": 3,              // 0 when ultra_enabled false; "auto" resolved to int ≤3 at confirm
  "machine_concurrency": 4,          // advisory for the model; display honesty
  "model_concurrency": 1,            // COPIED from config at confirm; display-only truth
  "framework": "aocs_omega",         // none | aocs_omega
  "max_loops": 2,                    // 0 = loops off
  "early_stop": true,                // always true in v1; field exists for the future
  "operator_confirmed": true,
  "confirmed_at": "2026-07-18T12:00:00Z",
  "contract_hash": "sha256-hex-of-canonical-json-without-this-field"
}
```

`contract_hash` = sha256 over the canonical JSON (sorted keys, no whitespace) of every
field EXCEPT `contract_hash` itself. Recompute-and-compare on read; mismatch →
`Error: [CONTRACT_TAMPERED]` and the task refuses effort/loop tools until the operator
re-confirms in the Workbench.

### 4.2 SQLite migration v6 (`harness/tasks/store.py` `_MIGRATIONS`)

```sql
-- v6: four-controls ledger. Credits are SPENT against a ceiling; every spend has a
-- receipt validated from server observations. Loops are evidence-gated passes.
CREATE TABLE credits (
    credit_id   TEXT PRIMARY KEY,          -- "cy-" + hex
    task_id     TEXT NOT NULL,
    fingerprint TEXT NOT NULL,             -- dedup key, unique per task
    tier        TEXT NOT NULL,             -- machine | source | decision
    status      TEXT NOT NULL,             -- open | spent | rejected | abandoned
    question    TEXT NOT NULL,
    receipt_path TEXT DEFAULT '',
    opened      TEXT NOT NULL,
    closed      TEXT DEFAULT ''
);
CREATE UNIQUE INDEX idx_credits_task_fp ON credits(task_id, fingerprint)
    WHERE status = 'spent';
CREATE INDEX idx_credits_task ON credits(task_id);

CREATE TABLE loop_passes (
    pass_id     TEXT PRIMARY KEY,          -- "lp-" + hex
    task_id     TEXT NOT NULL,
    pass_number INTEGER NOT NULL,
    input_state_hash TEXT NOT NULL,
    target_weakness  TEXT NOT NULL,
    directive        TEXT NOT NULL,
    repeat_key  TEXT NOT NULL,             -- hash(input_state_hash + norm(weakness) + norm(directive))
    status      TEXT NOT NULL,             -- open | improved | no_gain | worse | abandoned
    verification_plan TEXT DEFAULT '',
    output_state_hash TEXT DEFAULT '',
    delta_summary TEXT DEFAULT '',
    opened      TEXT NOT NULL,
    closed      TEXT DEFAULT ''
);
CREATE UNIQUE INDEX idx_loops_repeat ON loop_passes(task_id, repeat_key)
    WHERE status IN ('open','improved','no_gain','worse');
CREATE INDEX idx_loops_task ON loop_passes(task_id);
```

Observations reuse the existing `events` table (indexed by task) with new event types
(§7) — no new table needed.

### 4.3 Config additions (`harness/config.py`)

```python
# Deliberation-credit ceilings per effort level. Harness-procedure budgets, NOT
# model tokens. Unvalidated defaults — calibrate via benchmarks before trusting.
effort_profiles: dict = field(default_factory=lambda: {
    "low": 2, "medium": 8, "high": 16, "xhigh": 32, "max": 50})
# Model reasoning streams available on the current host. 1 = personal ChatGPT
# (empirically verified). A future host/backend may raise it; the UI reads this.
model_concurrency: int = 1
# Max fraction of a task's SPENT credits that may be decision-tier receipts,
# by task_type. Build work must be mostly machine/source-backed; review/plan
# work is legitimately judgment-heavy.
decision_caps: dict = field(default_factory=lambda: {
    "build": 0.2, "review": 0.8, "plan": 0.8, "research": 0.8})
```

Env: `HARNESS_EFFORT_PROFILES` (JSON), `HARNESS_MODEL_CONCURRENCY` (int),
`HARNESS_DECISION_CAPS` (JSON). Validate in `__post_init__`: profiles values are
positive ints; model_concurrency ≥ 1; caps in (0, 1]. `python -m harness doctor`
prints all three.

---

## 5. The Run Contract — lifecycle

```
 OPERATOR (Workbench)                          MODEL (ChatGPT)
 ────────────────────                          ───────────────
 1. New Session dialog: pick the 4 rows
 2. See the estimate (§13.3)
 3. Click Confirm  ──► contract locked onto
    the task (operator_confirmed, hash)
                                               4. start_task / resume_task response
                                                  INCLUDES the contract summary
                                                  (pull — no new tool needed)
                                               5. Executes under the contract
                                               6. Mid-run wants more? →
                                                  request_extension(...)  ──► approvals
 7. Approve/Deny click (approval-wait          ◄── tool call held open ≤90s,
    holds the model's call open)                   exactly like command approvals
```

Rules:
- **Confirmed contracts are immutable.** No tool, endpoint, or model action may edit a
  confirmed `run_contract` except the extension flow below. Cockpit "edit" before
  confirm is fine; after confirm the endpoint returns HTTP 409.
- **Pull-based, never push:** the 4-row configuration happens in the Workbench with no
  clock running. The held-call mechanism is used ONLY for quick mid-run decisions
  (extensions, risky commands) that fit inside the 90s window.
- **Extension flow:** `request_extension(task_id, kind, amount, reason)` where kind ∈
  `credits | loops | candidates`. Creates an approval row (action =
  `effort_extension:<kind>:+<amount>`), goes through `_gate_with_wait`. On approve the
  server applies the delta to the contract, appends an audit event
  `contract_extended` with old/new hash, and recomputes `contract_hash`. This is the
  ONLY legal contract mutation.
- **Chat-created tasks** (start_task from ChatGPT, no Workbench dialog): contract is
  empty = all Off = today's behavior. The operator may attach + confirm a contract
  later from the task page, but only while the task is not COMPLETED/FAILED/CANCELLED.
- **Subtasks and forks inherit the parent's contract** (copy at creation), each with
  its own fresh ledger. A candidate fork therefore gets the same per-attempt ceiling.

---

## 6. The credit ledger — the heart of the build

### 6.1 The economy (spent, not minted)

```
 Contract confirmed with effort_level=high
        │
        ▼
 Ledger: ceiling 16, spent 0, remaining 16
        │
        ▼
 Model opens ONE cycle at a time  ──►  works  ──►  closes it with a receipt
        │                                              │
        │                              server validates (§6.3)
        │                                              │
        │                    valid & new → spent += 1  │  invalid/duplicate → rejected,
        ▼                                              ▼  spend stays, reason returned
 remaining hits 0 → no new cycles. Options: request_extension / finish via gates /
 stop incomplete. NEVER "done because budget is gone".
```

- Exactly **one open cycle per task** at a time (`Error: [CYCLE_OPEN]` otherwise).
  The queue rule is unaffected: machine jobs launched inside a cycle keep running.
- Credits gate **cycles**, not tool calls. Reads/searches/commands outside a cycle
  still work (op-level leases are deliberately deferred, §16). Enforcement = the
  ceiling on validated cycles + the completion gates + the skill protocol.

### 6.2 Tool surface (add to `harness/tasks/tools.py`, register in `server.py`)

All return plain strings. Errors use the repo's `Error: [CODE] message` convention.

```
begin_cycle(task_id, question, purpose="") -> str
  Opens cycle. Returns: "Cycle cy-a1b2 opened. Effort high: spent 7/16, 1 open."
  Errors: [EFFORT_OFF] [NO_CREDITS] [CYCLE_OPEN] [CONTRACT_TAMPERED] [TASK_NOT_FOUND]

complete_cycle(task_id, cycle_id, conclusion, decision, evidence) -> str
  evidence: list of refs (§6.3 shapes). Validates → spends or rejects (no spend).
  Success: "Credit spent (machine tier). 8/16. Receipt: effort/cy-a1b2.md"
  Reject:  "Error: [RECEIPT_REJECTED] duplicate fingerprint — this exact
            question+evidence+conclusion was already credited as cy-99ff."
  Other codes: [RECEIPT_WEAK] (no valid evidence at all)
               [DECISION_CAP] (cap for task_type reached — bring machine/source evidence)

abandon_cycle(task_id, cycle_id, reason) -> str        # no spend; logged
get_effort_status(task_id) -> str
  "Effort high 8/16 spent (machine 5, source 2, decision 1; cap 3). Open cycle: none.
   Gates: 2/4 satisfied. Loops: pass 1/2 open. Contract hash OK."
request_extension(task_id, kind, amount, reason) -> str   # §5 approval flow
begin_refinement_pass / complete_refinement_pass          # §10
record_framework_routing(task_id, activated, skipped, reason) -> str   # §11
```

### 6.3 Receipt validation — exact algorithm

Evidence reference shapes the model may submit in `evidence`:

```json
{"kind": "execution", "exec_id": "px-3f2a"}                       // a run_command/start_process this task ran
{"kind": "diff",      "note": "extracted validator into own module"}
{"kind": "source",    "file": "harness/server.py", "lines": "120-141", "fact": "..."}
{"kind": "decision",  "what": "rejected caching approach", "why": "invalidation unsolvable here"}
```

Validation (server-side, in order):

```
1. FRESHNESS+OWNERSHIP
   execution → exec_id must exist in this task's observations (§7) and have been
               recorded AFTER this cycle opened. Else the ref is invalid.
   diff      → the task's observed tree_hash must have CHANGED since cycle open.
   source    → file must appear in this task's read-log (§7) — the model actually
               read it through the harness — and still exist. Lines optional but
               recommended. (Read may predate the cycle; facts don't expire.)
   decision  → structurally complete (both fields non-empty). Honor-system by
               design; that's why it's capped.

2. TIER = strongest valid ref present:
   any valid execution/diff → machine
   else any valid source    → source
   else any valid decision  → decision
   else                     → reject [RECEIPT_WEAK]  ("I thought hard" counts as nothing)

3. DEDUP fingerprint = sha256( normalize(question) + normalize(conclusion)
                               + sorted(evidence identity strings) )
   normalize = lowercase, collapse whitespace. Already spent for this task →
   reject [RECEIPT_REJECTED] naming the earlier credit.
   Additionally for execution refs: an exec_id may back at most ONE spent credit
   (re-running nothing new mints nothing — rerun dedup is via execution
   fingerprints in §7).

4. DECISION CAP: if tier == decision:
   allowed = ceil(decision_caps[task_type] * credit_ceiling)
   if decision-tier spent count >= allowed → reject [DECISION_CAP].

5. SPEND: insert row (status=spent), write the receipt FILE, return the one-line
   summary. The full receipt never enters the chat (§6.4).
```

### 6.4 Receipt storage — the context-rot guard

Full receipts go to
`<state_dir>/tasks/<task_id>/effort/<credit_id>.md`:

```markdown
# cy-a1b2 — machine tier — spent 2026-07-18T12:41:03Z
Question: Is refresh ordering the cause of the auth failure?
Evidence: execution px-3f2a (pytest tests/test_auth.py — exit 1 → captured repro)
Conclusion: refresh_token() runs after the expired token is reused; repro R-3 fails.
Decision: reorder refresh before the protected call; rerun R-3.
```

Tool responses carry ONE line only. Rationale: at Max (50 credits), in-chat receipts
would burn the very context window the effort is meant to protect. The Workbench task
page lists receipts from disk.

### 6.5 What credits honestly are (must appear in the skill + README)

An odometer and a speed limit, not an engine. They bound and audit procedure; they
cannot deepen hidden thinking (only the ChatGPT picker does) and cannot fully stop a
determined model doing shallow-but-novel cycles. Paired with completion gates and the
audit trail, that is exactly the guarantee promised — no more, and no less. Never
oversell this in any UI string or doc.

---

## 7. Observations log — what the server records so §6.3 can check receipts

Append to the existing `events` table (existing helper for task events), with types:

```
obs_read   {path, content_sha256}                    on every successful read_file
obs_exec   {exec_id, command, cwd, tree_hash, exit_code, duration_s, runner}
                                                     on run_command completion and
                                                     start_process termination
obs_diff   {tree_hash_before, tree_hash_after}       after every successful write/edit
                                                     batch (debounce with the existing
                                                     auto-checkpoint timer is fine)
```

- `exec_id`: reuse the process id for `start_process` (`px-…`); generate one for
  `run_command`.
- **execution fingerprint** (rerun detection) = sha256(command + cwd + tree_hash).
  Same fingerprint with same exit code as an already-credited execution → that
  exec_id cannot back a new credit. Same command after the tree CHANGED is new
  evidence (that's how fail→pass gets its receipt).
- **tree_hash** definition: git workspace → sha256(HEAD sha + `git status --porcelain`
  output + `git diff HEAD` output). Non-git → sha256 of (path, size, mtime) tuples of
  files the task has touched. Compute lazily and cache per tool-call; never let
  hashing add noticeable latency (>150ms on the repo itself → memoize harder).
- Only tasks with an ACTIVE effort contract need observations recorded (skip the
  overhead otherwise — measure, and if the cost is trivial, record always for audit
  value; note the choice in DEVIATIONS.md).

---

## 8. Completion gates — the separation rule (already mostly built)

```
 CREDITS  = how much work MAY be attempted        (this spec builds)
 GATES    = what must be TRUE before "done"       (already exists: acceptance_criteria
                                                   + finish_task evidence)
 credits exhausted ≠ done          gates passed = done (even with credits left over)
```

Builder changes here are tiny:
- `finish_task` must NOT read the ledger. Done is gates-only. (Add a test proving a
  task finishes with credits unspent, and a test proving exhausted-credits +
  unmet-criteria does not finish.)
- `get_effort_status` displays gates state alongside spend (read-only convenience).

---

## 9. ULTRA workflow (orchestration only — no effort, no AOCS inside it)

- Selector: `Off | Auto | 2 | 3 | 5 | 8 | Custom`. Auto resolves at confirm time to
  the model's proposed 2–3 (recorded in the contract before work starts). Custom is
  behind an "Advanced" disclosure with the wall-clock warning (§13.3).
- Candidates are built **sequentially** (model_concurrency 1) via `fork_task`, one
  worktree each; machine verification runs in **parallel** across candidate worktrees
  via `start_process`. The UI and skill must always show both numbers separately.
- **Enforcement:** when a confirmed contract has `ultra_enabled`, the server counts
  candidate forks for that task; `fork_task` beyond `candidate_count` returns
  `Error: [CANDIDATE_LIMIT] contract allows N — request_extension(kind="candidates")`.
  When ULTRA is Off, `fork_task` behaves exactly as today.
- The candidate procedure itself (forced-diverse strategies, APPROACH.md, no-reopen
  rule, pre-registered rubric, executed-repro red team, blind-ish judge + cold-judge
  option, DECISION.md, STATE.md checkpoints) is **skill text**, not server code —
  it lives in `docs/skills/harness-ultra.md` (§14), rewritten to contain ONLY
  orchestration (no effort tiers, no AOCS coupling).
- Naming: user-facing = "ULTRA WORKFLOW". The word "ultracode" must not appear in
  UI strings or skill text (collision with Claude Code's feature).

---

## 10. LOOPS engine

Lifecycle per pass (tools in §6.2):

```
begin_refinement_pass(task_id, target_weakness, directive, verification_plan)
  Server checks: contract has loops; pass_number ≤ max_loops; repeat_key =
  sha256(current tree_hash + norm(weakness) + norm(directive)) not already used
  → else Error: [LOOP_REPEAT] "identical state+weakness+directive already ran as lp-07"
  Records input_state_hash = tree_hash at open.

complete_refinement_pass(task_id, pass_id, outcome, evidence)
  outcome ∈ improved | no_gain | worse. Requires ≥1 machine-tier evidence ref
  (same shapes and validation as §6.3) — a delta claim without an executed check
  is rejected. Records output_state_hash + delta_summary.
  worse → the skill instructs revert to previous best (server records; git does the revert).
```

Early stop — the model must stop opening passes when ANY of:
gates pass · two consecutive `no_gain` · last outcome `worse` · budget exhausted ·
operator stop. The server enforces the countable ones (max_loops, the no-repeat
index, the two-consecutive-no-gain check → `Error: [LOOP_PLATEAU]`); the skill
teaches the rest.

**Forbidden stopping rule (from the AOCS-Evolution doc): "loop until 100%
confidence".** A model can be 100% confident and 100% wrong. Evidence-based stops
only. This sentence goes verbatim into the loops skill.

---

## 11. FRAMEWORK row

- Values: `none | aocs_omega`. Never auto-enabled by any other row (the v1 coupling
  bug this whole redesign fixes).
- When `aocs_omega`: the start_task/resume response tells the model to load the
  `my-aocs-omega` skill IN FULL (paged `load_skill` offsets) and then call
  `record_framework_routing(task_id, activated=[...], skipped=[...], reason="...")`
  before implementation starts. Routing is stored as a task event and shown on the
  task page. No routing recorded → `get_effort_status` shows "FRAMEWORK: declared
  but unrecorded" (visible nag, not a hard block).
- The model self-selects which AOCS modules apply — freedom WITH a written record,
  so the choice is auditable.

---

## 12. Server wiring (`harness/server.py`)

- Register the new tools with docstrings that teach the protocol in-line (models read
  tool descriptions; that's a free protocol channel).
- `start_task` / `resume_task` / `task_status` responses: when a confirmed contract
  exists, append a compact contract block:

```
RUN CONTRACT (locked, hash 3f2a…): effort high — 16 credits (spent 0) · ultra 3
candidates (machine concurrency 4, model 1) · framework aocs_omega · loops max 2.
Protocol: open ONE cycle before significant work (begin_cycle), close it with
evidence (complete_cycle). Done = acceptance criteria + evidence, never budget
exhaustion. Receipts are files; keep chat lean.
```

- Effort/loop/extension tools all pass through the existing per-task mode gates like
  every other tool (they are state-mutating: available from `plan` mode and above,
  never in `read_only`).

---

## 13. Workbench UI (`harness/cockpit/`)

### 13.1 New Session dialog — the four rows (operator's sketch, made honest)

```
┌──────────────────────────────────────────────────────────────────┐
│ EFFORT      [Off] [Low 2] [Med 8] [High 16] [XHigh 32] [Max 50]  │
│             deliberation credits (harness procedure budget —      │
│             set ChatGPT's own picker for real thinking depth)     │
│ ULTRA       [Off] [Auto] [2] [3] [5] [8] [Custom ▸advanced]      │
│             model streams: 1 · machine parallel: [Auto][2][4][8] │
│ FRAMEWORK   [None] [AOCS Omega]                                  │
│ LOOPS       [Off] [2] [5] [10] [Custom]                          │
│ TASK TYPE   [Build] [Review] [Plan] [Research]                   │
│──────────────────────────────────────────────────────────────────│
│ ESTIMATE: ≤ 112 credits total · sequential candidates — expect    │
│ a long run and several "continue" nudges · uses real quota        │
│                        [ Confirm & Lock ✓ ]   [ Cancel ]          │
└──────────────────────────────────────────────────────────────────┘
```

Estimate formula (display only, server does not enforce a total pool in v1):
`ceiling × max(1, candidates) × (1 + max_loops) + (ceiling if ultra else 0)` (judge
reserve). Show "several continue nudges" whenever the estimate > 30 credits — the
"continue tax" is real and must be visible before confirm, not discovered after.

### 13.2 Endpoints

- `api_new_task`: accept the new fields; build + confirm the contract atomically on
  Confirm & Lock.
- `api_set_contract` (POST, task page): attach/confirm a contract on a chat-created
  task; 409 if one is already confirmed or task is terminal.
- `api_effort_status` (GET): ledger + receipts list (from disk) + loops history for
  the task page: credits meter (`spent/ceiling` with per-tier counts), gates
  checklist, loop passes, contract block with hash, extension approvals appearing in
  the existing approvals UI (they're ordinary approvals — zero new approval UI).
- Bump the static cache-bust (`?v=` in index.html) as the repo always does.

### 13.3 Same-code-area cleanups (queued work, ride along in this phase)

Archive/delete for sessions and projects (operator-requested earlier): archive =
soft-flag hiding from default lists; delete = existing data untouched on disk, row
removed after an explicit confirm dialog. Keep light-theme default. No other visual
redesign in this build.

---

## 14. Skills split (docs + `~/.agents/skills` operative copies)

Replace the single coupled `harness-ultra` v2 with three single-purpose skills
(repo copies in `docs/skills/`, operative copies installed to
`~\.agents\skills\my-skills\<name>\SKILL.md`):

1. **harness-effort.md** — the spend protocol: the economy diagram, cycle discipline
   (one at a time; open before significant work; close with evidence), the three
   tiers with GOOD/BAD receipt examples, honesty text from §6.5, "ceiling not quota",
   "done = gates". Step 0 stays: remind the user to raise ChatGPT's own picker — the
   only true compute lever.
2. **harness-ultra.md** — orchestration ONLY: contract-echo, BRIEF.md recon
   distillation, sequential forced-diverse candidates in worktrees (no-reopen rule),
   parallel machine verification + pre-registered rubric, executed-repro red team
   ("a finding without an executed repro is reported as 'unverified', never as a
   bug"), blind-ish judge + COLD JUDGE fresh-chat option, DECISION.md, STATE.md
   RESUME-HERE checkpoints. Delete all effort-tier and AOCS references.
3. **harness-loops.md** — pass protocol, directive menu (repair / challenge
   assumption / simplify / robustness / performance / close verification gap),
   no-repeat rule, early-stop list, the forbidden-confidence-rule sentence verbatim.
4. **my-aocs-omega** — untouched. Loaded only when FRAMEWORK says so.

Each skill ends with: "The laws (one stream; start_process for slow jobs; queue rule
— never wait idle; reality is the only judge) apply at every level."

---

## 15. Edge cases — decided now so nobody improvises later

| # | Situation | Decision |
|---|---|---|
| 1 | `complete_cycle` with no open cycle | `Error: [NO_OPEN_CYCLE]` |
| 2 | `begin_cycle` on effort-Off task | `Error: [EFFORT_OFF] effort tools need a confirmed contract` |
| 3 | Credits hit 0 mid-task | New cycles refused; reads/commands still work; model told: extend, finish via gates, or checkpoint STATE.md and stop |
| 4 | `finish_task` with credits left | Fine. Gates decide. |
| 5 | Exhausted credits, failing tests | NOT done. Extend or stop incomplete. |
| 6 | Extension while operator is away | Held ≤90s, then pending approval + retry message — exactly like command approvals today |
| 7 | Model claims a source it never read via harness | Ref invalid (read-log check) → may downgrade tier or reject |
| 8 | Two evidence refs, one invalid | Ignore invalid ref, validate on the rest; note ignored refs in the receipt |
| 9 | Duplicate receipt | Rejected, no spend, names the earlier credit |
| 10 | Same test re-run, code unchanged | Same execution fingerprint → cannot back a new credit |
| 11 | Same test after an edit | Tree changed → new fingerprint → valid evidence (fail→pass lives here) |
| 12 | Contract tampering (hash mismatch) | Effort/loop tools refuse with `[CONTRACT_TAMPERED]`; task page shows re-confirm button |
| 13 | Restart / new chat mid-run | Everything is in SQLite + receipt files; resume_task + get_effort_status restore full state |
| 14 | Fork/subtask of contracted task | Inherits contract copy, fresh ledger, same ceiling |
| 15 | fork_task beyond candidate_count | `[CANDIDATE_LIMIT]` → extension flow |
| 16 | ULTRA on, EFFORT off | Legal. Candidates run without ledgers (orchestration without metering) |
| 17 | Loops on, EFFORT off | Legal. Passes still need machine-tier deltas; no credit accounting |
| 18 | Windows | Hashing/paths must work on Windows (this is the primary platform); tests must not assume POSIX |
| 19 | Non-git workspace | tree_hash fallback (§7); diff receipts still valid |
| 20 | Operator kills a run | Existing cancel path; ledger keeps its history for audit |

---

## 16. What must NOT be built (deferred on purpose — do not "helpfully" add)

Per-operation credit leases · contract versioning (v1/v2 chains) · per-role effort
overrides · AOCS scope selectors · auto-triage/reserve allocation · semantic no-op
detection beyond fingerprints · total-run credit pool enforcement (estimate display
only) · AOCS Evolution (blocked until its stopping rule is replaced) · any
model-provider API call · any UI pretending to control ChatGPT's native effort.
Each exists in the design history; each is deliberately postponed until real usage
shows it is needed. Adding them now is a spec violation.

---

## 17. Invariants — each becomes at least one test

1. All controls Off ⇒ behavior identical to today (full existing suite green).
2. No code path calls a model-provider API (£0).
3. `finish_task` never reads the credit ledger.
4. A confirmed contract cannot be mutated except via an approved extension.
5. Every spent credit has ≥1 server-validated evidence ref; pure narration spends nothing.
6. Duplicate fingerprints never spend twice.
7. Decision-tier spends never exceed the task-type cap.
8. Full receipts never appear in tool responses (one-line summaries only).
9. `fork_task` under an ultra contract cannot exceed candidate_count without approval.
10. A loop pass with an already-used repeat_key is rejected.
11. UI/skills never claim >1 model stream, never say "ultracode", never call credits "tokens".
12. Credits exhausted ≠ COMPLETED (state machine cannot reach COMPLETED that way).

---

## 18. Build phases — order, acceptance, tests

**Phase 0 — Skills split (docs only, no code).**
Write the three skills (§14), update README's controls section to the four-row truth,
delete the coupled tier table from the old skill. Accept: docs build/read cleanly;
old harness-ultra marked superseded.

**Phase 1 — Contract.**
Task field, config additions, confirm flow (api_new_task + api_set_contract), hash,
inheritance, contract block in task responses. Tests: `tests/test_run_contract.py` —
lock/409-on-edit, hash tamper detection, inheritance on fork/subtask, chat-created
tasks default Off, doctor prints profiles.

**Phase 2 — Observations + credit ledger.**
§7 events, migration v6, the five effort tools, validation algorithm, receipt files,
decision caps, extension approvals. Tests: `tests/test_effort_ledger.py` — spend on
machine/source/decision paths; duplicate rejection; freshness rejection (exec before
cycle open); read-log rejection; cap rejection; exhaustion; extension approve/deny
via the existing approval-wait test harness; invariant 3; invariant 8; Windows-safe
tree_hash; one-open-cycle rule.

**Phase 3 — Loops.**
Both tools, repeat index, plateau rule, machine-evidence requirement. Tests:
`tests/test_loops.py` — repeat rejection, plateau stop, worse→history preserved,
max_loops enforcement, loops-without-effort legal.

**Phase 4 — ULTRA enforcement.**
Candidate counting on fork_task, `[CANDIDATE_LIMIT]`, extension kind=candidates.
Tests in `tests/test_ultra_contract.py` incl. ultra-off unchanged behavior.

**Phase 5 — Workbench.**
Four-row dialog, estimate line, task-page meters/receipts/loops, api_effort_status,
archive/delete cleanups, cache-bust. Tests: `tests/test_cockpit.py` additions
(endpoint contracts, 409s); manual operator walkthrough scripted in
`docs/specs/four-controls-walkthrough.md` (write it in this phase).

**Phase 6 — Benchmarks (never skip).**
`bench/` with five fixed tasks on a seeded fixture repo: small targeted bug ·
multi-file feature · regression with misleading symptom · refactor task ·
security-sensitive fix. Each defines objective pass/fail + the measurement table
(correctness, tests passed, credits spent by tier, wall-clock, "continue" nudges,
defects introduced). Protocol: change ONE variable per comparison; n=1 operator
means results are rough tuning, not science — record them anyway in
`bench/results.md`. The 2/8/16/32/50 profiles may be retuned ONLY from this data.

**Definition of done for the whole feature:** all phases' tests green + full suite
green + walkthrough completed by the operator + one real contracted run (any small
task, effort=medium) whose ledger, receipts, and audit log the operator has read and
believes.

---

## 19. Message to the builder about honesty (bind these into your outputs)

Report what IS: if a test fails, say so with output; if you deviated, DEVIATIONS.md;
if a phase is partial, say which items remain. Never present the imitation as the
real thing: candidates are sequential; roles are one model changing stance; credits
are procedure, not thinking. The operator audits transcripts against the audit log —
overclaims get caught here (they have been before).
