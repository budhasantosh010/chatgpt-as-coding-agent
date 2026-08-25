# AGENTS.md — handoff for coding agents

**You are reading the entry point for any AI coding agent working on this
repository** — Codex, Claude Code, Cursor, opencode, Gemini CLI, Copilot, or a
future one. Read this file to the end before your first edit. It is the only
file guaranteed current; everything else is ranked for trust in §9.

Humans should read [README.md](README.md) first, then
[docs/USING-THE-HARNESS.md](docs/USING-THE-HARNESS.md).

---

## 1. What this project is, in one paragraph

A **local MCP server** that lets a normal **ChatGPT subscription** act as a
coding agent on this machine. ChatGPT is the brain; this server is the hands
(read / write / edit / search / shell / git / memory / skills / processes /
worktrees). ChatGPT reaches it over a Tailscale Funnel to a secret route. The
distinguishing feature is not the tools — it is the **governance layer on top of
them**: server-validated evidence, a task ledger, run contracts, and a
provenance rule about who is allowed to assert what.

```
  ChatGPT (the brain — not in this repo, no API key, no model call)
      |  MCP over HTTPS
      v
  Tailscale Funnel  -->  127.0.0.1:8848   the MCP engine
                          |                secret route + Host/Origin + rate limit
                          +-->  127.0.0.1:8849   the Workbench GUI (operator's eyes)
                          v
                    your approved workspace roots
```

## 2. Status — what is verified, what is reported, what is unmeasured

Keep these three apart. This project's design premise is that *who asserted a
thing* determines what it is worth; the status of the project itself is held to
the same standard.

| | Claim | Evidence |
|---|---|---|
| **machine-verified** | 68 MCP tools, **484 tests green** | `pytest tests -q`, exit 0, re-run 2026-08-25 |
| **machine-verified** | all phases through Phase 9 accepted | signed record with task / contract / receipt ids read back out of `tasks.db` — [docs/specs/four-controls-progress.md](docs/specs/four-controls-progress.md) |
| **operator-reported** | run daily against **multiple real projects**; working; no outstanding defects; *"98% there"* | the operator's own use, 2026-07-29 → 2026-08-25. Not instrumented, not a benchmark. Recorded because it is the strongest signal this project has, and labelled because it is not a measurement. |
| **unmeasured** | that any of the controls **improve outcomes** | **no such claim is made.** The controlled benchmark arms were specified and never run — see "Descoped, not done" in the progress doc. What is proven is that the controls are *enforced as specified*, not that enforcing them helps. |

**Practical consequence for you:** this is a **maintenance-and-extension**
codebase, not a build-it-out one. Default to small, tested, reversible changes.
If you believe something is broken, reproduce it with a failing test before
changing code. Three separate times a green suite missed a defect that a single
real flight caught (§10) — so the reverse also holds: a green suite is not
permission to refactor.

## 3. Hard rules — breaking any of these breaks the project's reason to exist

```
 [X] NEVER call a model-provider API.
       No OpenAI, no Anthropic, no Gemini, no local-LLM inference.
       There is no model in this repository and there must never be one.
       The whole point is GBP 0 beyond the ChatGPT subscription already paid
       for. If a task seems to need a model, the answer is "ChatGPT does that
       part."

 [X] NEVER change the Tailscale Funnel configuration.
       It is fixed and working, and ChatGPT connects THROUGH it. The funnel
       hostname and scripts/funnel.ps1 are off-limits unless the operator
       explicitly asks.

       The ngrok "second door" (HARNESS_PUBLIC_HOST, scripts/ngrok.ps1) is
       ADDITIVE and must stay that way: it adds one exact hostname to the
       allowed list and touches nothing the funnel uses. Never route the
       funnel through it, never make one a fallback for the other, and never
       widen the host check to a *.ngrok-free.dev wildcard -- that suffix is
       shared with every other ngrok tenant.

       Every decision behind it, and the alternative each one rejected, is in
       docs/specs/second-door-decision-log.md. Read it before touching
       middleware host handling, the tunnel scripts, or the .bat launchers --
       several of those choices look like inconsistencies worth cleaning up
       and are not.

 [X] NEVER use https or gh for the git remote. SSH ONLY.
       origin = git@github.com:budhasantosh010/chatgpt-as-coding-agent.git

 [X] NEVER add npm, React, or a build step to the Workbench.
       harness/cockpit/static/ is vanilla HTML + CSS + ES modules, served
       directly. Deliberate: no toolchain to rot, no node_modules.

 [X] NEVER let anything with a model provenance satisfy a gate.
       Model prose can never spend a credit or close an acceptance criterion.
       This is the load-bearing rule of the whole design. See §5(b).

 [X] NEVER let the model grant itself an elevated permission mode.
       bypass_sandboxed and full are operator-only. See §6.
```

Softer, but still expected:

- **Light theme is the default, permanently.** Do not add a dark default.
- **Never call the product feature "ultracode."** The control is named `ULTRA`.
- **Verify UI changes with real eyes on a running Workbench**, not by reading
  the code. `harness/cockpit/server.py` changes need a process restart to show.
- **Hand the operator the restart command; do not kill their engine.** They may
  have a live ChatGPT session attached to it.
- **Windows PowerShell 5.1 has no ternary (`? :`)** and no `&&` / `||` chaining.
  Use `if/else` and `;`. The `.bat` launchers already pin this in a comment.

## 4. Run it, test it

```bash
python -m pip install -e ".[dev]"
python -m harness doctor
python -m pytest tests -q
```

`doctor` validates config and environment — run it first whenever anything is
odd. The suite is 484 tests, about 105 seconds.

What the operator actually double-clicks:

```
start-harness.bat     tailscale check -> funnel -> engine (:8848 + :8849) -> verify
stop-harness.bat      funnel down, then kill whatever listens on 8848 / 8849
start-ngrok.bat       STANDALONE ngrok path: engine (start or reuse) -> ngrok
                      -> verify. Never calls Tailscale, deliberately:
                      start-harness.bat gates on `tailscale status`, so on a
                      network that blocks Tailscale it refuses before the
                      engine ever starts. Run both for two doors at once.
```

Two tunnels, one engine. `scripts/check-funnel.ps1` and `scripts/check-ngrok.ps1`
each send a real MCP `initialize` down the real public path, because every
cheaper check lies: `tailscale funnel status` reads local config, a MagicDNS
probe never leaves the tailnet, and `ngrok online` only means the agent reached
ngrok's edge.

CLI surface — **there is no `harness down`**, which is why `stop-harness.bat`
stops by port:

```
python -m harness {up, serve, stdio, doctor, url,
                   approvals, commands, tasks, watch, worktrees, roots}
```

| Command | Use it for |
|---|---|
| `up` | engine + Workbench together (the normal way) |
| `serve` / `stdio` | HTTP for ChatGPT / stdio for local MCP clients |
| `doctor` | config + environment validation |
| `watch` | live feed of what ChatGPT is doing right now |
| `approvals list\|approve\|deny` | the operator approval queue |
| `tasks list` / `tasks set-mode <id> <mode>` | see or elevate a task's mode |
| `roots add <path>` | approve a new workspace folder (**restart to apply**, by design) |
| `worktrees prune` | remove worktrees of finished tasks |

Config is 12-factor, every variable prefixed `HARNESS_`, all validated in
[harness/config.py](harness/config.py) — read that file rather than guessing a
name. The ones that change behaviour most: `HARNESS_MODE`, `HARNESS_MAX_MODE`,
`HARNESS_NO_TASK_MODE`, `HARNESS_SANDBOX`, `HARNESS_ARBITRARY_COMMANDS`,
`HARNESS_STATE_DIR`, `HARNESS_PUBLIC_HOST`.

One config trap worth knowing before you touch host handling:
`HARNESS_ALLOWED_HOSTS` **replaces** the default `["localhost", "127.0.0.1"]`
rather than extending it, so naming a tunnel there costs the operator access to
their own Workbench with a 403 that reads exactly like a dead tunnel. That is
why the second door has its own additive setting, why loopback is now allowed
unconditionally in `middleware.py`, and why `tests/test_second_door.py` pins
both.

## 5. The four concepts you must understand before editing anything

Skip these and you will "fix" something into meaninglessness.

### (a) The wall — MCP does not carry the conversation

```
   MCP gives the server:  a tool name  +  a JSON arguments object
   MCP does NOT give it:  the conversation, the reasoning, the plan
```

The server **cannot** see what ChatGPT said. Server-side capture is not merely
unimplemented — it is impossible over this transport. Every design decision
below follows from that one fact. If you are ever tempted to write "the server
should just record the discussion," stop: it structurally cannot.

### (b) Provenance — four kinds of claim, never interchangeable

```
  operator_entered   the human typed it            <- strong
  machine_observed   the SERVER saw it happen      <- strong
  model_reported     ChatGPT asserted it in an argument
  model_published    ChatGPT volunteered a memo    <- weakest
```

**Nothing carrying a model provenance may satisfy a gate or spend a credit.**
Model prose is testimony; server observation is the recording. When you add a
field, decide its provenance first and enforce it at the boundary.

### (c) Receipt asymmetry

A receipt is co-authored on purpose:

```
  the MODEL supplies:   exec_id, reason              (prose  — why it did it)
  the SERVER supplies:  command, execution_fingerprint (fact — what actually ran)
```

Never let the model supply the server's half. That asymmetry *is* the integrity
property of a receipt.

### (d) The Turn Ledger — and what it is *not*

`publish_turn` writes a memo to `turns.jsonl` so a chat can be abandoned and the
thread picked up in a fresh one with `resume_task`. It is **not** compaction:

```
  compaction (Claude Code / Codex)   publish_turn (here)
  --------------------------------   ---------------------------
  fires automatically at the limit   only when asked
  the harness does it (owns loop)    the MODEL must do it — see (a)
  the SAME session continues         the operator opens a NEW chat
  raw transcript kept on disk        no raw transcript ever existed
  solves: model context is full      solves: the CHAT UI is dying
```

Nothing auto-fires. A chat closed without publishing loses its reasoning — the
code is safe on disk, the decisions are not.

## 6. Permission modes and the ceiling

```python
MODE_ORDER = ("read_only", "plan", "build_ask",
              "auto_workspace", "bypass_sandboxed", "full")
```

`HARNESS_MAX_MODE` (default `auto_workspace`) answers exactly one question:
**"may the MODEL grant itself this?"** It is meaningless against the operator —
the local CLI and the localhost-only Workbench are the same authority that
`harness tasks set-mode` has always trusted. `check_ceiling(..., operator=True)`
waives the ceiling **and only the ceiling**.

Two traps that have already caused real bugs here:

1. **`operator_elevated` must be recorded** when an operator starts a task above
   the ceiling. Without that flag `effective_mode()` silently clamps the task
   back down on its first tool call and the operator's choice evaporates — worse
   than offering no button at all. Fixed in `0709e07`; pinned by
   `tests/test_mode_ceiling.py`.
2. **`bypass_sandboxed` requires Docker**, and that check applies to *everyone*,
   operator included. It is not a privilege question: with no container there is
   no sandbox, so offering the mode would be a lie. The server degrades it to
   `auto_workspace`.

The mode lists in `harness/cockpit/server.py`, `static/index.html` and
`static/render.mjs` are **drift-guarded by tests** (`tests/test_cockpit.py`). Add
a mode and all three surfaces plus `MODE_NOTE` must move together, or the suite
fails on purpose.

## 7. Architecture, and the rule that keeps it cheap to extend

```
harness/
  app.py          composition root: config -> HarnessServer -> MCP -> secured app
  __main__.py     the CLI
  config.py       12-factor config; persisted secret route
  context.py      HarnessServer (shared) + HarnessContext (per session)
  policy.py       Capability {READ, WRITE, EXECUTE} + the ONE mode table
  permissions.py  command classifier — ADVISORY HARDENING, NOT A BOUNDARY
  security.py     path confinement, secret-file denylist, command denylist
  middleware.py   pure-ASGI shell: secret route, Host/Origin, bearer, rate limit
  executor.py     Executor port: LocalExecutor (default) | DockerExecutor
  hooks.py        pre/post-tool hooks — THE extensibility seam
  scrub.py        credential redaction (a post-tool hook)
  evidence.py     server-side validation of acceptance criteria
  events.py       the journal
  server.py       FastMCP: thin typed wrappers, one capability each
  tools/          files search shell workspace git memory skills todos process ...
  tasks/          SQLite task store, state machine, contracts, turns, receipts
  cockpit/        the Workbench: Starlette API + vanilla HTML/CSS/ESM
```

**The rule:** tool logic is a **pure function over a `HarnessContext`**; each MCP
tool is **one thin wrapper declaring one capability**.

```
  adding a tool               = 1 pure function + 1 wrapper.   Nothing else.
  adding a permission mode    = edit policy.py.                Nothing else.
  adding cross-cutting policy = register a hook in hooks.py.
                                Do NOT edit the tool wrappers.
```

If your change requires touching many wrappers, you are working against the
architecture — reach for a hook instead.

## 8. Conventions

- **Commits:** conventional prefix plus a lowercase human sentence, e.g.
  `fix(cockpit): the operator could not reach modes the server already granted`.
  Bodies here are **prose, and long** — say what was wrong, what changed, and
  what is *still* not true. Match that register; these bodies are the project's
  real documentation.
- **Tests are the gate.** New behaviour arrives with a test that failed before
  the change. Drift between two surfaces gets a guard test, not a comment.
- **Comments explain *why*, not *what*.** The existing ones carry the reasoning
  ("advisory hardening, NOT a security boundary"). Preserve that.
- **Do not create a new manual.** Four already overlap (§9). Extend the current
  one, or the drift comes back.
- Python 3.13, stdlib-first. No new runtime dependency without a reason worth
  writing down in the commit body.

## 9. Which doc to trust, in order

Docs were written at different times and **some are stale**. This ranking exists
so a stale sentence never outranks a current one.

| Doc | Status | Authoritative for |
|---|---|---|
| **AGENTS.md** (this file) | current (2026-08-25) | Agent handoff: rules, concepts, conventions. |
| [README.md](README.md) | current | Human entry point, quickstart, connector setup. |
| [docs/USING-THE-HARNESS.md](docs/USING-THE-HARNESS.md) | current | **Everything operational.** Disk layout, modes, approvals, forking, the Turn Ledger, all 68 tools, refusal decoder, hard limits. |
| [docs/specs/four-controls-*.md](docs/specs) | current | The contract spec, the flight record, the signed acceptance — **and what was deliberately not done.** |
| [docs/specs/turn-ledger-flight-failures.md](docs/specs/turn-ledger-flight-failures.md) | current | The three defects real flights found that green tests missed. |
| [docs/STATE.md](docs/STATE.md) | stale numbers, **current reasoning** | Its "key decisions" and "honest limits" sections are genuinely valuable — do not delete. Its "57 tools / 276 tests" header is stale. |
| [docs/MANUAL.md](docs/MANUAL.md) | older deep-dive | Full operator CLI list, `~/.agents/skills` loading, gotchas. Its mode and startup chapters predate the Workbench dropdown and the `.bat` launchers. |
| [docs/CHECKLIST.md](docs/CHECKLIST.md) | historical | The build record through 2026-07-16. The ticks are real; the header counts are stale. |
| [docs/COMPARISON.md](docs/COMPARISON.md) | stale (2026-07-16) | Historical only. Its "GBP 0 on your own machine is unique" claim is **wrong** — Codex CLI also signs in with a ChatGPT subscription. |
| [docs/ROADMAP.md](docs/ROADMAP.md), [docs/WORK_SESSION.md](docs/WORK_SESSION.md) | archived | Superseded planning. Do **not** act on their "NEXT STEP". |

## 10. Known limits — settled, do not relitigate

- **The command classifier is advisory, not a security boundary.** A regex
  cannot know what `python -c` does. The real boundaries are the mode table and
  `HARNESS_SANDBOX=docker` with `network=none`. Known bypasses are *pinned* in
  `tests/test_quality_fixes.py` — documented, not forgotten.
- **Under `sandbox=docker`, internal git and ripgrep still run on the host**
  (hooks and config neutralized). `doctor` says so.
- **Windows process-tree kill is incomplete** — killing a PowerShell wrapper can
  leave a grandchild.
- **Roots need a restart.** A hot-reload watcher would be a self-service
  escalation surface for a model that has `run_command`. Deliberate.
- **No autonomous sub-agents.** There is no model here. Subtasks exist instead.
- **Green tests miss flight bugs.** Three times (the fork bug, F1/F2, F3) a green
  suite missed what one real run caught. Prefer a real flight for anything
  touching turns, evidence, or contracts.
- **Settled and closed:** no Pi, no TypeScript, no wholesale t3code fork, and the
  MagicDNS / SNI network diagnosis — probing `*.ts.net` from this machine is
  answered inside the tailnet and never touches the public Funnel ingress, which
  is why `scripts/check-funnel.ps1` resolves the public IPs via Google DNS and
  sets SNI by hand.

## 11. Starting a session — the 60-second version

```
 1. git log --oneline -5                 what happened last
 2. read this file                       the rules
 3. python -m harness doctor             is the environment sane
 4. python -m pytest tests -q            green BEFORE you touch it   (484)
 5. read docs/specs/four-controls-progress.md
                                         what is done, what was descoped
 6. make the smallest tested change that does the job
 7. python -m pytest tests -q            still green
 8. commit in the house style; push over SSH only
```

**The single most useful thing to know:** the operator is not a developer of this
codebase — they are its user, running it against real work every day. A
regression costs them live sessions. Prefer no change over a plausible change.
