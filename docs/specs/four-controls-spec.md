# SPEC — The Four Independent Controls (EFFORT / ULTRA / FRAMEWORK / LOOPS)

- **Version:** 1.2 (2026-07-18) — **CORRECTED + RELOCKED** after final Codex review.
- **Revision history:**
  - v1.0 — initial locked spec (commit 87563dd).
  - v1.1 — pre-build review by Codex + GPT found 8 real defects; all fixed here:
    (1) budget scopes — subtasks can no longer mint fresh budgets; (2) concurrency-safe
    storage — revision CAS + separate run_contracts table (the cockpit and the MCP
    engine are two processes doing whole-blob task writes on one SQLite file; verified
    lost-update risk); (3) evidence hardening — execution relevance rule, per-file
    write observations, untracked-file hash hole closed; (4) per-criterion completion
    (verified: today `finish_task` accepts one free-form evidence sentence for any
    number of criteria — harness/tasks/tools.py finish_task); (5) loop verification
    kinds per task type (v1.0 self-contradicted); (6) judge budget defined as the
    root scope; (7) "Auto" candidates removed (deferred — a locked contract must not
    let the model pick its own workload); (8) archive/delete extracted to a future
    spec of its own (still on the operator's pending list — extracted, not cancelled).
  - v1.2 — final Codex review removed four remaining builder ambiguities: (1) command
    permission and verification evidence are separate decisions — ordinary command
    approval never makes a command proof; (2) this document contains the complete
    canonical Run Contract instead of referring back to v1.0; (3) EFFORT Off creates
    no credit scope (SQLite never stores “infinity”); (4) every related task carries
    an explicit `contract_id` pointing to the same shared locked contract.
- **Status:** LOCKED for build. Do not redesign while building.
- **Builder:** Codex (or any coding agent). **Spec author/auditor:** Claude. **Approver:** the operator.
- **Repo:** chatgpt-as-coding-agent (this repo). Python MCP server (`harness/`), FastMCP,
  SQLite store, Workbench GUI on localhost:8849.

---

## 0. How the builder must use this document

1. **Build exactly what is written.** If something seems wrong or impossible, do NOT
   silently improvise: write the problem + your proposed change into
   `docs/specs/DEVIATIONS.md` and stop that sub-item until the operator answers.
   (This process already worked twice: the v1.0→v1.1 and v1.1→v1.2 corrections came
   from exactly this kind of pre-build review.)
2. **Build in phases (§18), in order.** A phase is done only when its acceptance
   criteria pass AND its listed tests are green AND the full existing suite
   (314 tests at time of writing) stays green.
3. **Back-compat is law:** with every new control set to Off/absent, the harness must
   behave byte-for-byte like today. Existing tests are the proof. Where this spec
   strengthens existing behavior (completion, storage), the strictness is gated on
   "a confirmed Run Contract exists" so uncontracted tasks behave exactly as today.
4. Follow the repo's existing style: pydantic models with defaulted fields, dataclass
   Config with `HARNESS_*` env vars validated in `__post_init__`, ordered SQLite
   migrations in `harness/tasks/store.py`, tool functions returning plain strings
   with `Error: [CODE] message` on failure.
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
- **Architecture fact that shapes §4:** the Workbench cockpit and the MCP engine are
  TWO PROCESSES, each with its own `HarnessServer`/`TaskStore` on the same SQLite
  file (see `harness/cockpit/server.py` constructing its own `HarnessServer`). WAL
  prevents corruption, not lost updates: two whole-JSON read-modify-write saves can
  silently erase each other's fields. §4.4 fixes this BEFORE anything valuable
  (a contract, a ledger) is stored on tasks.
- Approvals machinery that already exists and works (reuse, don't rebuild): approvals
  table + `_gate_with_wait` in `harness/server.py` holds a tool call open up to
  `approval_wait_seconds` (90s from env) while the operator clicks Approve/Deny in the
  Workbench; deny is terminal `Error: [APPROVAL_DENIED]`.
- Completion machinery that exists today is WEAKER than "done" should be:
  `finish_task` rejects only when the latest recorded test failed, and accepts a
  free-form `evidence` string when no test was recorded — one sentence can "cover"
  any number of criteria. §8 replaces this for contracted tasks.

---

## 2. Locked glossary (one meaning per word — no drift allowed)

| Term | Meaning (the ONLY meaning) |
|---|---|
| **EFFORT** | Ceiling of validated deliberation cycles one attempt may spend. NOT model thinking depth. |
| **credit** | Permission for one deliberation cycle. Spent, never earned. Ceiling, never quota. |
| **credit scope** | The budget pot. One ATTEMPT = one scope. Subtasks share their parent's scope. |
| **deliberation cycle** | question → evidence → conclusion → decision, validated by the server. |
| **receipt** | The stored record of one completed cycle. DB row is the truth; the .md file is a view. |
| **receipt tier** | MACHINE (execution/write result) > SOURCE (code fact w/ refs) > DECISION (judgment). |
| **completion gates** | Per-criterion evidence verification (§8). The ONLY thing that means "done". |
| **ULTRA** | Orchestration of N rival solution attempts. NOT an effort level. Never called "ultracode". |
| **candidate** | One rival attempt, created via `fork_task(candidate=True)`, with its own worktree and—when EFFORT is On—its own credit scope. |
| **root scope** | With EFFORT On, the main attempt's scope. It also funds orchestration + judging. With EFFORT Off, no root scope exists. |
| **model concurrency** | How many model reasoning streams run at once. Currently 1. From config. |
| **machine concurrency** | How many OS processes run at once via `start_process`. Genuinely parallel. |
| **FRAMEWORK** | Optional reasoning doctrine the model follows (today: AOCS Omega). Never auto-enabled. |
| **LOOPS** | Maximum evidence-gated improvement passes over the current best result. |
| **Run Contract** | The four controls' locked configuration, in its own table, confirmed by the operator. |
| **contract ID** | The explicit link from every related task to the same locked Run Contract. |
| **observation** | Something the server itself recorded: a read, an execution, a per-file write. |
| **revision** | Integer version on every task row; all writes are compare-and-swap guarded. |
| **Chinese whispers** | Information loss between parties. This spec exists to make it zero. |

What each control is **NOT** (say this in every user-facing doc):
- EFFORT is not the ChatGPT picker and cannot raise hidden thinking. Both knobs together = max quality.
- ULTRA is not parallel model minds on this host. Candidates are sequential; machines are parallel.
- FRAMEWORK is not magic; it is a doctrine the model must *record* following.
- LOOPS is not blind repetition; a pass without a new target + measured delta is rejected.

---

## 3. The four controls — locked definitions

```
 EFFORT     Off | Low 2 | Medium 8 | High 16 | XHigh 32 | Max 50   (credits per SCOPE)
 ULTRA      Off | 2 | 3 | 5 | 8 | Custom(advanced)                 (candidates; no Auto in v1)
 FRAMEWORK  None | AOCS Omega                                      (doctrine)
 LOOPS      Off | 2 | 5 | 10 | Custom                              (max refinement passes)
 TASK TYPE  Build | Review | Plan | Research                       (drives caps + loop kinds)
```

- Every row independent. Every combination legal. Everything Off = today's behavior.
- The numbers 2/8/16/32/50 are **unvalidated defaults** stored in config (§4.3),
  displayed as "deliberation credits", never as "tokens". Phase 9 calibrates them.
- "Auto" candidates is REMOVED from v1 (deferred, §16): the operator locks the
  contract, so the model must not pick its own workload after locking, and no honest
  deterministic server rule exists yet.
- Shared rules: ceilings not quotas; early stop always allowed when gates pass;
  exhaustion never implies completion; extension only via operator approval.

---

## 4. Data model changes

### 4.1 Task model (`harness/tasks/model.py`)

Add to `Task` (pydantic, all defaulted → old rows load unchanged):

```python
# Explicit link to the ONE locked contract shared by this task family.
# Empty = uncontracted task = all controls Off = legacy behavior.
contract_id: str = ""
# Budget pot this task spends from. Empty = no effort contract in play.
# Assigned at contract confirm (root scope) and INHERITED BY COPY by ordinary
# subtasks/forks. Only candidate forks and the contract itself create scopes.
credit_scope_id: str = ""
# Structured acceptance criteria (contracted tasks only; §8). Uncontracted tasks
# keep using the legacy acceptance_criteria list[str] exactly as today.
criteria_v2: list = Field(default_factory=list)
```

The Run Contract does **NOT** live in the task JSON blob (v1.0 mistake): it is
operator-owned, immutable domain state, and the blob is model-mutated and
race-exposed. It gets its own table (§4.2).

### 4.2 SQLite migration v6 (`harness/tasks/store.py` `_MIGRATIONS`)

```sql
-- v6a: optimistic concurrency for tasks. Two processes (engine + cockpit) write
-- these rows; every write must be revision-guarded or a stale save silently
-- erases newer fields. (Verified risk, not theoretical.)
ALTER TABLE tasks ADD COLUMN revision INTEGER NOT NULL DEFAULT 0;

-- v6b: Run Contracts — operator-owned, one per task, immutable once confirmed.
CREATE TABLE run_contracts (
    contract_id   TEXT PRIMARY KEY,          -- "rc-" + hex
    root_task_id  TEXT NOT NULL UNIQUE,
    contract_json TEXT NOT NULL,
    contract_hash TEXT NOT NULL,
    confirmed_at  TEXT NOT NULL,
    revision      INTEGER NOT NULL DEFAULT 0
);

-- v6c: credit scopes and the ledger. Spends are keyed by SCOPE (the budget pot),
-- receipts live IN the row (crash-safe); the .md file is a regenerable view.
CREATE TABLE credit_scopes (
    scope_id   TEXT PRIMARY KEY,          -- "cs-" + hex
    contract_id TEXT NOT NULL,
    task_id    TEXT NOT NULL,             -- the task that OWNS the pot (root or candidate)
    kind       TEXT NOT NULL,             -- root | candidate
    ceiling    INTEGER NOT NULL,
    created    TEXT NOT NULL
);
CREATE TABLE credits (
    credit_id   TEXT PRIMARY KEY,          -- "cy-" + hex
    scope_id    TEXT NOT NULL,
    task_id     TEXT NOT NULL,             -- task that opened the cycle (may be a subtask)
    fingerprint TEXT NOT NULL,
    tier        TEXT NOT NULL,             -- machine | source | decision
    status      TEXT NOT NULL,             -- open | spent | rejected | abandoned
    question    TEXT NOT NULL,
    verification_plan TEXT DEFAULT '',     -- commands pre-registered at begin_cycle
    receipt_json TEXT DEFAULT '',          -- SOURCE OF TRUTH, written in the spend txn
    receipt_path TEXT DEFAULT '',          -- generated .md view (regenerable)
    opened      TEXT NOT NULL,
    closed      TEXT DEFAULT ''
);
CREATE UNIQUE INDEX idx_credits_scope_fp ON credits(scope_id, fingerprint)
    WHERE status = 'spent';
CREATE INDEX idx_credits_scope ON credits(scope_id);
CREATE INDEX idx_credits_task ON credits(task_id);

-- v6d: refinement passes.
CREATE TABLE loop_passes (
    pass_id     TEXT PRIMARY KEY,          -- "lp-" + hex
    task_id     TEXT NOT NULL,
    pass_number INTEGER NOT NULL,
    verification_kind TEXT NOT NULL,       -- machine | source | operator | mixed
    input_state_hash TEXT NOT NULL,
    target_weakness  TEXT NOT NULL,
    directive        TEXT NOT NULL,
    repeat_key  TEXT NOT NULL,
    status      TEXT NOT NULL,             -- open | improved | no_gain | worse | abandoned
                                           --   | pending_operator (operator kind)
    verification_plan TEXT DEFAULT '',
    output_state_hash TEXT DEFAULT '',
    delta_summary TEXT DEFAULT '',
    opened      TEXT NOT NULL,
    closed      TEXT DEFAULT ''
);
CREATE UNIQUE INDEX idx_loops_repeat ON loop_passes(task_id, repeat_key)
    WHERE status IN ('open','improved','no_gain','worse','pending_operator');
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
# Max fraction of a scope's SPENT credits that may be decision-tier receipts,
# by task_type. Build work must be mostly machine/source-backed; review/plan
# work is legitimately judgment-heavy.
decision_caps: dict = field(default_factory=lambda: {
    "build": 0.2, "review": 0.8, "plan": 0.8, "research": 0.8})
```

Env: `HARNESS_EFFORT_PROFILES` (JSON), `HARNESS_MODEL_CONCURRENCY` (int),
`HARNESS_DECISION_CAPS` (JSON). Validate in `__post_init__`: profiles values are
positive ints; model_concurrency ≥ 1; caps in (0, 1]. `python -m harness doctor`
prints all three.

### 4.4 Concurrency-safe task writes (BUILD FIRST — everything else sits on this)

- `save_task` becomes revision-guarded:
  `UPDATE tasks SET data=?, status=?, revision=revision+1, updated=? WHERE id=? AND revision=?`.
  Zero rows updated → the caller gets `Error: [TASK_CONFLICT] task changed since it
  was read — reload and retry`. Internal policy: reload + reapply ONCE automatically
  for single-field changes; if it conflicts again, surface the error.
- Add targeted store methods used by cockpit endpoints instead of whole-blob saves:
  `set_task_mode`, `set_task_pinned`, `set_task_chat_url`, `set_task_status`,
  `pin_task_file` — each implemented as reload→patch-one-field→CAS-save loop inside
  the store, so no endpoint ever writes a stale full JSON again.
- `run_contracts` and the ledger tables are written ONLY through their own atomic
  store methods (insert-once semantics for contracts; single-transaction spends).

---

## 5. The Run Contract — lifecycle and budget scopes

```
 OPERATOR (Workbench)                          MODEL (ChatGPT)
 ────────────────────                          ───────────────
 1. New Session dialog: pick the rows
 2. See the estimate (§13.3)
 3. Click Confirm ──► contract rc-XXXX inserted
    (immutable), task.contract_id set.
    EFFORT On: root scope cs-XXXX created
    and task.credit_scope_id set.
    EFFORT Off: no credit scope is created.
                                               4. start_task / resume_task response
                                                  INCLUDES the contract summary (pull)
                                               5. Executes under the contract
                                               6. Mid-run wants more? →
                                                  request_extension(...) ──► approvals
 7. Approve/Deny click (approval-wait          ◄── tool call held open ≤90s,
    holds the model's call open)                   exactly like command approvals
```

### 5.1 Budget scope rules (fixes the v1.0 unlimited-subtask hole)

```
 RUN
 ├── root task ──────────────── scope cs-A (ceiling 16)   ← also funds judge/synthesis
 │    ├── ordinary subtask ──── shares cs-A               ← NO new budget, ever
 │    ├── ordinary fork ─────── shares cs-A               ← NO new budget, ever
 │    └── deeper subtask ────── shares cs-A
 ├── candidate fork #1 ──────── scope cs-B (ceiling 16)   ← fork_task(candidate=True)
 └── candidate fork #2 ──────── scope cs-C (ceiling 16)
```

- `create_subtask` and plain `fork_task` COPY the parent's `credit_scope_id`.
  Spends from any task in a scope count against the ONE shared ceiling.
- Every subtask, plain fork, and candidate fork also COPIES the parent's
  `contract_id`. Contract lookup is direct by `task.contract_id`; never guess by
  walking parent links and never duplicate the contract row.
- `fork_task(..., candidate=True)`: legal only under a confirmed contract with
  `ultra_enabled`; counted against `candidate_count`
  (`Error: [CANDIDATE_LIMIT]` beyond it → extension flow). With EFFORT On it creates
  a NEW scope with the same ceiling, kind=candidate; with EFFORT Off it creates no scope.
- `fork_task(candidate=True)` without an ultra contract →
  `Error: [NOT_ULTRA] this task's contract has no candidates — plain fork shares
  the existing budget`.
- **With EFFORT On, judging/orchestration budget = the root scope.** There is no
  separate judge pot; the estimate formula (§13.3) already counts the root scope. If
  judging starves it, use `request_extension(kind="credits")`. With EFFORT Off,
  judging is unmetered because no credit scopes exist.
- Loop passes run in the root task and, when EFFORT is On, spend from the root scope.

### 5.2 Contract rules

- Canonical contract JSON (complete; builders must not consult v1.0):

  ```json
  {
    "contract_version": 1,
    "task_type": "build",
    "effort_level": "high",
    "credit_ceiling": 16,
    "ultra_enabled": true,
    "candidate_count": 3,
    "machine_concurrency": 4,
    "model_concurrency": 1,
    "framework": "aocs_omega",
    "max_loops": 2,
    "early_stop": true,
    "operator_confirmed": true,
    "confirmed_at": "2026-07-18T12:00:00Z",
    "contract_hash": "sha256-hex-of-canonical-json-without-this-field"
  }
  ```

  Legal values: `task_type = build|review|plan|research`;
  `effort_level = off|low|medium|high|xhigh|max`; `framework = none|aocs_omega`;
  `candidate_count` is an integer (`0` when ULTRA is Off; Auto is illegal);
  `max_loops = 0` when LOOPS is Off. When EFFORT is Off, `credit_ceiling = 0` and
  **no credit scope exists**. `contract_hash` = sha256 of canonical JSON (sorted
  keys, no whitespace) excluding the hash field. Recompute on read;
  mismatch → `Error: [CONTRACT_TAMPERED]`, effort/loop tools refuse, task page
  offers re-confirm.
- **Immutable once confirmed.** The only legal mutation is the extension flow:
  `request_extension(task_id, kind, amount, reason)`, kind ∈ `credits | loops |
  candidates` → approval row (`effort_extension:<kind>:+<amount>`) →
  `_gate_with_wait` → on approve, approval consumption and the mutation occur in
  one transaction and append a `contract_extended` audit event. Limits and root
  credit extensions rewrite contract_json + hash. A named candidate credit
  extension raises only that ONE scope (parameter `scope_id`) so later candidates
  still inherit the operator-confirmed base ceiling.
- **Chat-created tasks**: no contract = all Off = today's behavior. The operator may
  attach + confirm later from the task page while the task is non-terminal.
- `request_extension(kind="credits")` on an EFFORT-Off contract returns
  `Error: [EFFORT_OFF]`. Enabling a disabled control requires a new operator-confirmed
  contract before work starts; an extension cannot silently switch EFFORT on mid-run.
- Pull-based always. The held call is ONLY for quick mid-run approvals.

---

## 6. The credit ledger

### 6.1 The economy (spent, not minted)

```
 Contract confirmed, effort high → root scope: ceiling 16, spent 0
        │
        ▼
 Model opens ONE cycle at a time (per task) ──► works ──► closes with a receipt
        │                                                     │
        │                                     server validates (§6.3)
        │                                                     │
        │                     valid & new → scope.spent += 1  │  invalid/duplicate →
        ▼                                                     ▼  rejected, no spend
 scope exhausted → no new cycles anywhere in the scope. Options: request_extension /
 finish via gates / stop incomplete. NEVER "done because budget is gone".
```

- One open cycle per TASK (`[CYCLE_OPEN]`); subtasks in the same scope each may have
  one open cycle, all draining the shared pot.
- Credits gate cycles, not tool calls. Reads/searches/commands outside a cycle still
  work (op-level leases deliberately deferred, §16).

### 6.2 Tool surface (add to `harness/tasks/tools.py`, register in `server.py`)

```
begin_cycle(task_id, question, purpose="", verification_plan="") -> str
  verification_plan: newline-separated commands the model INTENDS to use as proof.
  Pre-registration records intent but does NOT by itself make a command valid proof.
  Returns: "Cycle cy-a1b2 opened. Scope cs-A (high): spent 7/16."
  Errors: [EFFORT_OFF] [NO_CREDITS] [CYCLE_OPEN] [CONTRACT_TAMPERED] [TASK_NOT_FOUND]

complete_cycle(task_id, cycle_id, conclusion, decision, evidence) -> str
  Success: "Credit spent (machine tier). Scope cs-A: 8/16. Receipt: effort/cy-a1b2.md"
  Errors: [NO_OPEN_CYCLE] [RECEIPT_REJECTED] [RECEIPT_WEAK] [DECISION_CAP]

abandon_cycle(task_id, cycle_id, reason) -> str        # no spend; logged
get_effort_status(task_id) -> str
  "Scope cs-A high 8/16 (machine 5, source 2, decision 1/3 cap). Open cycle: none.
   Criteria: 2/4 satisfied. Loops: pass 1/2. Contract hash OK. Candidates: 1/3 used."
request_extension(task_id, kind, amount, reason, scope_id="") -> str
begin_refinement_pass / complete_refinement_pass          # §10
record_framework_routing(task_id, activated, skipped, reason) -> str   # §11
satisfy_criterion(task_id, criterion_id, evidence) -> str              # §8
```

### 6.3 Receipt validation — exact algorithm

Evidence reference shapes:

```json
{"kind": "execution", "exec_id": "px-3f2a"}
{"kind": "diff",      "write_ids": ["ev-88", "ev-89"], "note": "extracted validator"}
{"kind": "source",    "file": "harness/server.py", "lines": "120-141", "fact": "..."}
{"kind": "decision",  "what": "rejected caching approach", "why": "invalidation unsolvable here"}
```

Validation (server-side, in order):

```
1. FRESHNESS + OWNERSHIP + VERIFICATION ELIGIBILITY
   execution → exec_id exists in this task's (or same-scope tasks') observations,
               recorded AFTER this cycle opened, AND passes V1 or V2 below.

               IMPORTANT — permission and proof are different questions:
                 permission: "may this command run?"
                 verification: "may this result count as evidence?"
               A normal package/arbitrary-command approval answers ONLY permission.
               It NEVER makes the result valid evidence.

               V1. RECOGNIZED VERIFICATION. Add a dedicated
                   `classify_verification_command()` containing ONLY test, build,
                   lint, typecheck, and diagnostic commands. Do NOT reuse
                   `permissions.classify_command()` — its safe tier intentionally
                   includes non-proof commands such as echo, ls/dir, pwd,
                   Get-ChildItem, Get-Location, whoami, and git status/log.
                   The exact command must also match one pre-registered in this
                   cycle's verification_plan (normalized exact match).

               V2. CUSTOM VERIFICATION. A non-recognized command may count only
                   after a SEPARATE operator approval whose action is
                   `verification_evidence` and whose detail binds task_id, cycle_id,
                   question, exact command, and the stated reason it proves the
                   question. This is separate from any approval needed to RUN it.
                   Trivial observation commands (echo, ls/dir, pwd, whoami,
                   Get-ChildItem, Get-Location, git status/log) are never eligible
                   custom verification, even if permitted to run.

               Logical relevance beyond V1/V2 remains human-audit territory; the
               server must say this honestly rather than claiming semantic proof.
   diff      → every write_id is an obs_write event (§7) recorded after cycle open;
               at least one has after_sha256 ≠ before_sha256.
   source    → file appears in this task's obs_read log (the model actually read it
               through the harness); receipt stores the read-time content hash.
               Reads may predate the cycle; facts don't expire.
   decision  → structurally complete (both fields non-empty). Honor-system by
               design; that's why it's capped.

2. TIER: any valid execution/diff → machine; else any valid source → source;
   else any valid decision → decision; else reject [RECEIPT_WEAK].

3. DEDUP fingerprint = sha256(normalize(question) + normalize(conclusion)
                              + sorted(evidence identity strings)); scope-wide.
   Already spent in this scope → [RECEIPT_REJECTED] naming the earlier credit.
   An exec_id may back at most ONE spent credit. Execution fingerprints (§7)
   stop unchanged-rerun evidence.

4. DECISION CAP: tier==decision and decision-spends ≥
   ceil(decision_caps[task_type] × ceiling) → [DECISION_CAP].

5. SPEND — single DB transaction: credit row status=spent WITH receipt_json
   (source of truth). After commit, generate the .md view file; if file writing
   fails, the spend stands and the file regenerates on next read (§6.4).
```

### 6.4 Receipt storage — crash-safe, context-lean

- Truth: `credits.receipt_json`, written atomically with the spend.
- View: `<state_dir>/tasks/<task_id>/effort/<credit_id>.md`, generated from the row,
  regenerable at any time (Workbench regenerates missing files on listing).
- Tool responses carry ONE line. Full receipts never enter the chat — at Max
  (50 credits) in-chat receipts would burn the context window the effort protects.

### 6.5 What credits honestly are (must appear in the skill + README)

An odometer and a speed limit, not an engine. They bound and audit procedure; they
cannot deepen hidden thinking (only the ChatGPT picker does) and cannot fully stop a
determined model doing shallow-but-novel cycles. Paired with per-criterion gates and
the audit trail, that is exactly the guarantee promised — no more, no less. Never
oversell this in any UI string or doc.

---

## 7. Observations log — what the server records so §6.3 can check receipts

Append to the existing `events` table, with types:

```
obs_read   {path, content_sha256}                       every successful read_file
obs_exec   {exec_id, command, cwd, tree_hash, exit_code, duration_s, runner}
                                                        run_command completion and
                                                        start_process termination
obs_write  {path, before_sha256, after_sha256, tracked} PER FILE, every successful
                                                        write/edit batch
```

- `exec_id`: reuse the process id for `start_process` (`px-…`); generate for
  `run_command`.
- **execution fingerprint** (rerun detection) = sha256(command + cwd + tree_hash).
  Same fingerprint + same exit code as an already-credited execution → cannot back a
  new credit. Same command after the tree CHANGED is new evidence (fail→pass lives
  there).
- **tree_hash** (used for exec fingerprints and loop repeat-keys): git workspace →
  sha256(HEAD sha + `git status --porcelain` output + `git diff HEAD` output
  + **content sha256 of every untracked file listed in porcelain** — closes the
  v1.0 hole where editing an untracked file left the hash unchanged. Cap: untracked
  files > 5 MB hash by (path, size, mtime)). Non-git → sha256 over
  (path, size, mtime, content sha256) of files the task has touched.
  Compute lazily, memoize per tool call; if hashing costs > 150ms on this repo,
  memoize harder and note it in DEVIATIONS.md.
- Record observations for ALL tasks (they're cheap events and improve the audit
  trail); only contracted tasks USE them for validation.

---

## 8. Completion gates — per-criterion verification (replaces the v1.0 overclaim)

**Verified current behavior (why this section exists):** today `finish_task`
(harness/tasks/tools.py) rejects only when the latest recorded run FAILED, and when
no run exists it accepts any non-empty free-form `evidence` string — one sentence can
"satisfy" ten criteria. Good enough for uncontracted tasks; not for contracted ones.

### 8.1 Structured criteria (contracted tasks only)

At contract confirm, legacy `acceptance_criteria` strings convert to `criteria_v2`:

```json
{"id": "AC-1", "text": "invalid credentials return 401", "required": true,
 "status": "open",                    // open | satisfied | failed | waived
 "verification_kind": "machine",      // machine | source | operator | mixed
 "evidence_refs": [], "verified_at": ""}
```

- `set_acceptance_criteria` on a contracted task appends new AC-ids (never silently
  rewrites satisfied ones; editing a satisfied criterion resets it to open).
- `satisfy_criterion(task_id, criterion_id, evidence)`: evidence shapes + validation
  IDENTICAL to §6.3 (same code path). One execution may legitimately satisfy several
  criteria — the same exec_id is allowed across criteria (the one-credit-per-exec
  dedup applies to credit spending only, not to criteria).
- `verification_kind: operator` criteria are satisfied ONLY from the Workbench
  (operator click, §13) — for subjective criteria ("the UI looks right").
- Criteria satisfaction does NOT cost credits (checking your work must never compete
  with doing it). Cycles and criteria may cite the same evidence.

### 8.2 finish_task rule

```
 Contracted task:  every required criterion satisfied with valid evidence
                   AND latest relevant verification not failing
                   AND no pending operator-kind criterion
                   → COMPLETED. Free-form evidence string = notes only.
 Uncontracted task: today's behavior, unchanged (back-compat law §0.3).
```

`get_effort_status` and the task page show the AC checklist with per-criterion
evidence links.

---

## 9. ULTRA workflow (orchestration only — no effort, no AOCS inside it)

- Selector: `Off | 2 | 3 | 5 | 8 | Custom` (Custom behind "Advanced" with the
  wall-clock warning §13.3). No Auto in v1 (§3).
- Candidates are built **sequentially** (model concurrency 1) via
  `fork_task(candidate=True)`, one worktree each and—when EFFORT is On—one fresh
  credit scope each; machine
  verification runs in **parallel** across candidate worktrees via `start_process`.
  UI and skill always show both numbers separately.
- Enforcement: candidate count (§5.1), `[CANDIDATE_LIMIT]`, extension
  kind=candidates. ULTRA Off → `fork_task` behaves exactly as today.
- The candidate procedure (forced-diverse strategies, APPROACH.md, no-reopen rule,
  pre-registered rubric, executed-repro red team, blind-ish judge + cold-judge
  option, DECISION.md, STATE.md checkpoints) is **skill text**
  (`docs/skills/harness-ultra.md`, §14), not server code.
- Judging spends from the ROOT scope (§5.1). The estimate already funds it.
- Naming: user-facing = "ULTRA WORKFLOW". The word "ultracode" must not appear in
  UI strings or skill text.

---

## 10. LOOPS engine

```
begin_refinement_pass(task_id, target_weakness, directive, verification_plan,
                      verification_kind="") -> str
  verification_kind defaults by task_type: build → machine;
  review/plan/research → source; explicit "operator" allowed for subjective work.
  Checks: contract has loops; pass_number ≤ max_loops; repeat_key =
  sha256(tree_hash + norm(weakness) + norm(directive)) unused
  → else Error: [LOOP_REPEAT] naming the earlier pass.
  Records input_state_hash.

complete_refinement_pass(task_id, pass_id, outcome, evidence) -> str
  outcome ∈ improved | no_gain | worse.
  Evidence must validate (§6.3 shapes/rules) AT the declared kind:
    machine  → ≥1 valid execution/diff ref
    source   → ≥1 valid source ref AND a changed conclusion recorded in delta_summary
    operator → pass enters status=pending_operator; completes only when the
               operator confirms in the Workbench (approval-style button)
    mixed    → ≥1 machine-or-source ref
  worse → skill instructs revert to previous best (git does the revert; server records).
```

Early stop — enforced where countable: max_loops; the repeat index; two consecutive
`no_gain` → `Error: [LOOP_PLATEAU]` on the next begin. Taught in the skill: stop when
gates pass, when outcome is `worse`, when budget is exhausted, when the operator says
stop.

**Forbidden stopping rule (from the AOCS-Evolution doc): "loop until 100%
confidence".** A model can be 100% confident and 100% wrong. Evidence-based stops
only. This sentence goes verbatim into the loops skill.

---

## 11. FRAMEWORK row

- Values: `none | aocs_omega`. Never auto-enabled by any other row.
- When `aocs_omega`: start_task/resume response instructs loading `my-aocs-omega`
  IN FULL (paged `load_skill` offsets), then
  `record_framework_routing(task_id, activated=[...], skipped=[...], reason="...")`
  before implementation. Stored as a task event, shown on the task page. Missing
  routing → `get_effort_status` shows "FRAMEWORK: declared but unrecorded" (visible
  nag, not a hard block).

---

## 12. Server wiring (`harness/server.py`)

- Register the new tools with protocol-teaching docstrings (models read tool
  descriptions — that's a free protocol channel).
- `start_task` / `resume_task` / `task_status`: when a confirmed contract exists,
  append the compact contract block (contract summary, scope spends, AC checklist
  state, protocol reminder — one short paragraph, §6.4 leanness applies).
- Effort/loop/criterion/extension tools pass through the per-task mode gates like
  every other tool (state-mutating: `plan` mode and above, never `read_only`).

---

## 13. Workbench UI (`harness/cockpit/`)

### 13.1 New Session dialog — the four rows

```
┌──────────────────────────────────────────────────────────────────┐
│ EFFORT      [Off] [Low 2] [Med 8] [High 16] [XHigh 32] [Max 50]  │
│             deliberation credits (harness procedure budget —      │
│             set ChatGPT's own picker for real thinking depth)     │
│ ULTRA       [Off] [2] [3] [5] [8] [Custom ▸advanced]             │
│             model streams: 1 · machine parallel: [Auto][2][4][8] │
│ FRAMEWORK   [None] [AOCS Omega]                                  │
│ LOOPS       [Off] [2] [5] [10] [Custom]                          │
│ TASK TYPE   [Build] [Review] [Plan] [Research]                   │
│──────────────────────────────────────────────────────────────────│
│ ESTIMATE: ≤ 128 credits total · sequential candidates — expect    │
│ a long run and several "continue" nudges · uses real quota        │
│                        [ Confirm & Lock ✓ ]   [ Cancel ]          │
└──────────────────────────────────────────────────────────────────┘
```

### 13.2 Endpoints

- `api_new_task`: accepts the new fields; on Confirm & Lock creates task + contract
  row atomically, plus a root scope only when EFFORT is On.
- `api_set_contract` (POST): attach/confirm on a chat-created non-terminal task;
  409 if already confirmed.
- `api_effort_status` (GET): scopes + spends by tier, receipts list (regenerating
  missing .md views), AC checklist, loop history, contract block + hash.
- `api_satisfy_criterion_operator` (POST): the operator-kind satisfy/confirm button;
  also confirms `pending_operator` loop passes.
- Extension approvals ride the existing approvals UI unchanged.
- All cockpit task mutations switch to the targeted CAS store methods (§4.4).
- Bump the static cache-bust (`?v=`) as the repo always does.

### 13.3 Estimate (display only — no total-pool enforcement in v1)

`total = ceiling × (1 root + candidate_count) × (1 + max_loops)`.
Show "several continue nudges" when total > 30 — the continue-tax must be visible
before confirm. Show machine vs model concurrency honestly.

**Removed from this build (v1.1):** archive/delete of sessions/projects. It needs its
own spec (cascade semantics, orphaned sessions/worktrees/receipts, restore,
accidental-deletion protection, FK relationships that don't exist yet). It remains on
the operator's pending list — extracted, not cancelled.

---

## 14. Skills split (docs + `~/.agents/skills` operative copies)

Replace the coupled `harness-ultra` v2 with three single-purpose skills
(repo copies in `docs/skills/`, operative copies in
`~\.agents\skills\my-skills\<name>\SKILL.md`):

1. **harness-effort.md** — the spend protocol: economy diagram, cycle discipline
   (one at a time; open before significant work; pre-register verification commands;
   close with evidence), the three tiers with GOOD/BAD receipt examples, honesty
   text (§6.5), "ceiling not quota", "done = per-criterion gates". Step 0 stays:
   remind the user to raise ChatGPT's own picker — the only true compute lever.
2. **harness-ultra.md** — orchestration ONLY: contract echo, BRIEF.md recon
   distillation, sequential forced-diverse candidates (candidate=True forks,
   no-reopen rule), parallel machine verification + pre-registered rubric,
   executed-repro red team ("a finding without an executed repro is reported as
   'unverified', never as a bug"), blind-ish judge + COLD JUDGE fresh-chat option,
   DECISION.md, STATE.md RESUME-HERE checkpoints. No effort tiers, no AOCS.
3. **harness-loops.md** — pass protocol, directive menu (repair / challenge
   assumption / simplify / robustness / performance / close verification gap),
   verification kinds by task type, no-repeat rule, early-stop list, the
   forbidden-confidence-rule sentence verbatim.
4. **my-aocs-omega** — untouched. Loaded only when FRAMEWORK says so.

Each skill ends with: "The laws (one stream; start_process for slow jobs; queue rule
— never wait idle; reality is the only judge) apply at every level."

---

## 15. Edge cases — decided now so nobody improvises later

| # | Situation | Decision |
|---|---|---|
| 1 | `complete_cycle` with no open cycle | `Error: [NO_OPEN_CYCLE]` |
| 2 | `begin_cycle` on effort-Off task | `Error: [EFFORT_OFF]` |
| 3 | Scope hits 0 mid-task | New cycles refused scope-wide; reads/commands still work; extend, finish via gates, or checkpoint STATE.md and stop |
| 4 | `finish_task` with credits left | Fine. Gates decide. |
| 5 | Exhausted credits, criteria unmet | NOT done. Extend or stop incomplete. |
| 6 | Extension while operator away | Held ≤90s, then pending approval + retry message |
| 7 | Source ref to a file never read via harness | Ref invalid (obs_read check) |
| 8 | Two evidence refs, one invalid | Ignore invalid, validate on the rest, note ignored refs in receipt |
| 9 | Duplicate receipt fingerprint (scope-wide) | Rejected, no spend, names the earlier credit |
| 10 | Same command re-run, tree unchanged | Same execution fingerprint → cannot back a new credit |
| 11 | Same command after an edit | Tree changed → new fingerprint → valid (fail→pass lives here) |
| 12 | Contract hash mismatch | `[CONTRACT_TAMPERED]`; effort/loop tools refuse; re-confirm button |
| 13 | Restart / new chat mid-run | SQLite + receipt_json survive; resume_task + get_effort_status restore state |
| 14 | Ordinary subtask/fork of contracted task | Inherits contract reference and SHARES the parent's scope — never a new budget |
| 15 | `fork_task(candidate=True)` beyond candidate_count | `[CANDIDATE_LIMIT]` → extension |
| 16 | `candidate=True` without ultra contract | `[NOT_ULTRA]` |
| 17 | ULTRA on, EFFORT off | Legal: candidates share the contract but NO credit scopes exist; orchestration is unmetered |
| 18 | Loops on, EFFORT off | Legal: passes validated at their declared kind; no credit accounting |
| 19 | `[TASK_CONFLICT]` on save | Store retries once (reload+reapply single-field); second conflict surfaces the error |
| 20 | Untracked file edited | Included in tree_hash + obs_write → invisible-change hole closed |
| 21 | Operator-kind criterion or pass | Waits for Workbench click; never satisfiable by the model |
| 22 | Windows | Primary platform; hashing/paths/tests must not assume POSIX |
| 23 | Non-git workspace | tree_hash fallback (§7); diff receipts still valid via obs_write |
| 24 | Operator kills a run | Existing cancel path; ledger and receipts keep full history for audit |

---

## 16. What must NOT be built (deferred on purpose — do not "helpfully" add)

Per-operation credit leases · contract versioning chains · per-role effort
overrides · AOCS scope selectors · "Auto" candidate selection (until a deterministic
server rule is designed and approved) · auto-triage/reserve allocation · semantic
relevance judgment beyond §6.3 V1–V2 · total-run credit pool enforcement (estimate
display only) · archive/delete (own future spec) · AOCS Evolution (blocked until its
stopping rule is replaced) · any model-provider API call · any UI pretending to
control ChatGPT's native effort. Adding any of these now is a spec violation.

---

## 17. Invariants — each becomes at least one test

1. All controls Off ⇒ behavior identical to today (full existing suite green).
2. No code path calls a model-provider API (£0).
3. `finish_task` never reads the credit ledger (criteria gates are separate).
4. A confirmed contract cannot be mutated except via an approved extension.
5. Every spent credit has ≥1 server-validated evidence ref; pure narration spends nothing.
6. Duplicate fingerprints never spend twice within a scope.
7. Decision-tier spends never exceed the task-type cap.
8. Full receipts never appear in tool responses (one-line summaries only).
9. `fork_task(candidate=True)` cannot exceed candidate_count without approval.
10. A loop pass with an already-used repeat_key is rejected.
11. UI/skills never claim >1 model stream, never say "ultracode", never call credits "tokens".
12. Credits exhausted ≠ COMPLETED (the state machine cannot reach COMPLETED that way).
13. An ordinary subtask/fork NEVER creates a new credit scope or budget.
14. Every task write is revision-guarded; a stale whole-blob save cannot silently win
    (test: two TaskStore instances on one DB file, interleaved writes, no lost field).
15. `receipt_json` commits in the same transaction as the spend; the .md file is a
    regenerable view whose loss loses nothing.
16. On a contracted task, COMPLETED requires every required criterion individually
    satisfied with validated evidence; a free-form evidence string alone never completes it.
17. Execution evidence must pass V1 (dedicated verification classifier + pre-registration)
    or V2 (separate evidence approval); ordinary command approval never counts as proof,
    and trivial observation commands such as `echo hello` can never back a credit.
18. Every contracted task has a non-empty `contract_id`; every task in its family points
    to the same contract row. EFFORT-Off tasks have an empty `credit_scope_id` and no
    credit-scope row.

---

## 18. Build phases — order, acceptance, tests

**Phase 0 — Spec corrections. DONE (this document, v1.2).**

**Phase 1 — Concurrency-safe storage (the floor everything stands on).**
tasks.revision + CAS save_task, targeted setters, cockpit endpoints switched over,
run_contracts table + atomic store methods. Tests: `tests/test_store_concurrency.py`
— two TaskStore instances on one DB file: interleaved whole-task saves conflict
instead of losing fields; targeted setters merge cleanly; contract row survives any
task-blob write; [TASK_CONFLICT] retry-once behavior.

**Phase 2 — Completion foundation.**
criteria_v2 conversion at confirm, satisfy_criterion (validation shared with §6.3 —
build the evidence validator here as a reusable module), operator-satisfy endpoint,
strict contract-gated finish_task. Tests: `tests/test_completion_gates.py` — prose
evidence completes an UNcontracted task (back-compat) but never a contracted one;
per-criterion satisfaction; operator-kind waits; invariant 16.

**Phase 3 — Observations & fingerprints.**
obs_read/obs_exec/obs_write events, tree_hash incl. untracked files, execution
fingerprints. Tests: `tests/test_observations.py` — untracked-file edit changes the
hash; write batches produce per-file before/after hashes; rerun-unchanged detection;
Windows paths.

**Phase 4 — EFFORT (scopes + ledger).**
credit_scopes, the five effort tools, §6.3 validation on the Phase-2 validator,
receipt_json + .md views, decision caps, extensions via approvals. Tests:
`tests/test_effort_ledger.py` — spend paths per tier; V1/V2 verification rules
(`echo hello` rejection even after ordinary command approval); scope sharing across
subtasks (invariant 13); contract sharing across the full task family; EFFORT-Off
creates no scope; freshness;
dedup; caps; exhaustion scope-wide; extension approve/deny; crash-safety (row
without file regenerates); invariants 3, 5–8, 12, 15, 17.

**Phase 5 — ULTRA enforcement.**
candidate=True forks, conditional scopes (EFFORT On only), [CANDIDATE_LIMIT]/[NOT_ULTRA], extension
kind=candidates. Tests: `tests/test_ultra_contract.py` incl. ultra-off unchanged
fork_task and plain-fork-shares-scope.

**Phase 6 — FRAMEWORK.** Routing record + nag. Tests in `tests/test_framework_row.py`.

**Phase 7 — LOOPS.** Both tools, kinds, repeat index, plateau, pending_operator.
Tests: `tests/test_loops.py` — kind-mismatched evidence rejected; source-kind loop
legal for research task; plateau; max_loops; loops-without-effort legal.

**Phase 8 — Workbench + skills.**
Four-row dialog (no Auto), estimate, meters/receipts/AC checklist/loop history,
operator-satisfy buttons, cache-bust; write + install the three skills (§14); update
README to the four-row truth; mark old harness-ultra superseded. Tests:
`tests/test_cockpit.py` additions; manual walkthrough scripted in
`docs/specs/four-controls-walkthrough.md`.

**Phase 9 — Benchmarks + first flight (never skip).**
`bench/` with five fixed tasks on a seeded fixture repo (small targeted bug ·
multi-file feature · regression with misleading symptom · refactor · security-
sensitive fix), objective pass/fail + measurement table (correctness, tests passed,
credits by tier, wall-clock, continue-nudges, defects introduced). One variable per
comparison; n=1 = rough tuning, not science; results in `bench/results.md`. The
2/8/16/32/50 profiles may be retuned ONLY from this data.

**Definition of done for the whole feature:** all phases' tests green + full suite
green + walkthrough completed by the operator + one real contracted run (small task,
effort=medium) whose ledger, receipts, criteria checklist, and audit log the operator
has personally read and believes.

---

## 19. Message to the builder about honesty (bind these into your outputs)

Report what IS: if a test fails, say so with output; if you deviated, DEVIATIONS.md;
if a phase is partial, say which items remain. Never present the imitation as the
real thing: candidates are sequential; roles are one model changing stance; credits
are procedure, not thinking. The operator audits transcripts against the audit log —
overclaims get caught here (they have been, twice: the model in Test 2, and this
spec's own v1.0).
