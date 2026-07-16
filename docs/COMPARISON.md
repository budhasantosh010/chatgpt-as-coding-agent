# Side-by-side: our harness vs Codex, Claude Code, OpenCode, Cursor, Pi

Researched July 2026 against live docs (not memory). Sources at the bottom.
**Last reconciled to our actual code: 2026-07-16** — LSP, user hooks, fork,
path-scoped rules, auto-format, and the Workbench GUI are now BUILT (they were
gaps in the first cut of this doc). See §13 for the closed-vs-remaining ledger.

**Legend**
```
 ✅ = has it, fully
 🟡 = has part of it / a weaker version
 ❌ = does not have it
 🚫 = IMPOSSIBLE FOR US BY DESIGN — needs an AI model inside the harness,
      and we deliberately have none (that's the whole point: no API bills)
 ➖ = not applicable / ChatGPT itself already provides it
```

---

## 0. THE ONE DIFFERENCE THAT EXPLAINS EVERYTHING ELSE

Read this before any table, or every row will mislead you.

```
   THE OTHER FIVE:  one program that bundles EVERYTHING
   ┌────────────────────────────────────────────┐
   │  MODEL (the AI)                            │  ← they call an API. You pay per token,
   │  + AGENT LOOP (think→act→observe→repeat)   │    or burn your subscription quota.
   │  + UI (the TUI/IDE you type into)          │
   │  + TOOLS (read/write/bash…)                │
   └────────────────────────────────────────────┘

   OURS: we build ONLY the bottom layer. ChatGPT brings the rest.
   ┌────────────────────────────────────────────┐
   │  MODEL      ─┐                             │
   │  AGENT LOOP  ├─ ChatGPT.com provides these │  ← your NORMAL ChatGPT
   │  UI          ┘   (already paid for)        │    subscription. No API key.
   ├────────────────────────────────────────────┤
   │  TOOLS  ← THIS IS OUR ENTIRE PROJECT       │  ← an MCP server on your laptop
   └────────────────────────────────────────────┘
```

**So:** we are not a competitor to these five. We are the *hands half* of a
harness, and ChatGPT is the *brain half* you already own. That's why some rows
below say ➖ (ChatGPT already does it) and some say 🚫 (needs a brain we don't have).

```
 WHO OWNS WHAT
 ─────────────────────────────────────────────────────────────────────
 Codex        OpenAI models only     · CLI + IDE + cloud + GitHub bot
 Claude Code  Anthropic models only  · CLI + IDE + web + desktop + Actions
 OpenCode     75+ providers          · TUI + desktop + web + IDE
 Cursor       own + others           · a whole IDE (VS Code fork)
 Pi           many providers         · minimal TUI + SDK/RPC
 OURS         NO MODEL AT ALL        · MCP server; ChatGPT is the UI
```

---

## 1. Core file tools

| Feature | Codex | Claude Code | OpenCode | Cursor | Pi | **OURS** |
|---|---|---|---|---|---|---|
| Read file | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ `read_file` |
| Write file | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ `write_file` |
| Edit (exact string) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ `edit_file` |
| Multi-file atomic batch | ✅ | 🟡 | 🟡 | ✅ | ❌ | ✅ `apply_edits` (auto-rollback) |
| Unified-diff patch | ✅ `apply_patch` | 🟡 | ✅ | 🟡 | ❌ | ✅ `apply_patch` |
| List directory | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ `list_dir` |
| **Stale-write guard** (reject if file changed since read) | ❌ | 🟡 | ❌ | ❌ | ❌ | ✅ **`expected_sha`** ← we're ahead |
| Notebook (.ipynb) editing | 🟡 | ✅ | ❌ | 🟡 | ❌ | ✅ `notebook_read/edit` |
| Read images | ✅ | ✅ | ✅ | ✅ | 🟡 | ✅ `read_image` |

## 2. Search & navigation

| Feature | Codex | Claude Code | OpenCode | Cursor | Pi | **OURS** |
|---|---|---|---|---|---|---|
| Glob / file find | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ `glob` (skips node_modules) |
| Grep / regex search | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ `grep` (ripgrep) |
| Symbol map of repo | 🟡 | ✅ (LSP) | ✅ (LSP) | ✅ | ❌ | 🟡 `repo_map` (ast+regex) |
| **LSP: go-to-def, references, types** | 🟡 | ✅ | ✅ **40+ langs** | ✅ | ❌ | ✅ `lsp_definition/references/hover/symbols` (py/ts/js/rust/go; server auto-detected) |
| **Semantic index (embeddings)** | ❌ | ❌ | ❌ | ✅ **the big one** | ❌ | ❌ **GAP** |
| Live type errors after edit | 🟡 | ✅ | ✅ | ✅ | ❌ | 🟡 `diagnostics_check` (runs your linter) |

## 3. Running code

| Feature | Codex | Claude Code | OpenCode | Cursor | Pi | **OURS** |
|---|---|---|---|---|---|---|
| Run shell command | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ `run_command` |
| Background/long-running processes | ✅ `/ps` `/stop` | ✅ | ✅ | ✅ | ❌ *(uses tmux on purpose)* | ✅ `start/read/write/stop/list_process` |
| Restricted env (no secret leak) | ✅ | ✅ | 🟡 | 🟡 | ❌ | ✅ env allowlist |
| Output caps | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

## 4. Memory & project rules

| Feature | Codex | Claude Code | OpenCode | Cursor | Pi | **OURS** |
|---|---|---|---|---|---|---|
| Project rules file | ✅ AGENTS.md | ✅ CLAUDE.md | ✅ AGENTS.md | ✅ `.cursor/rules` | ✅ AGENTS.md/CLAUDE.md | ✅ reads AGENTS.md/CLAUDE.md on `open_workspace` |
| **Path-scoped rules** (load only for matching files) | 🟡 | ✅ `.claude/rules` + `paths:` | 🟡 | ✅ globs | ❌ | ✅ `.harness/rules` + globs, surfaced on matching WRITE |
| Agent-written memories | ✅ `/memories` | 🟡 | 🟡 | ✅ Memories | 🟡 | ✅ **3 tiers**: global/project/task |
| Memory survives restart | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ (`memory/*.json`) |
| Worktrees share project memory | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ **(git common-dir keyed)** ← ahead |
| Custom system prompt | ✅ | 🟡 | ✅ | ✅ `SYSTEM.md` | ✅ | 🟡 fixed MCP instructions |

## 5. Sessions & persistence

| Feature | Codex | Claude Code | OpenCode | Cursor | Pi | **OURS** |
|---|---|---|---|---|---|---|
| Sessions saved to disk | ✅ | ✅ | ✅ | ✅ | ✅ JSONL tree | ✅ **SQLite `tasks.db`** |
| Resume a past session | ✅ `resume --last` | ✅ `--continue` | ✅ | ✅ | ✅ `/resume` | ✅ `resume_task` |
| **Fork / branch a session** | ✅ `fork` | 🟡 rewind | 🟡 | ❌ | ✅ **`/tree` `/fork` `/clone`** | ✅ `fork_task` (own worktree, lineage recorded) |
| Archive / delete sessions | ✅ | 🟡 | ✅ | ✅ | ✅ | 🟡 `cancel_task` |
| **Share session by link** | 🟡 cloud | 🟡 | ✅ `/share` | ✅ | ✅ `/share` | ❌ **GAP** |
| Conversation compaction | ✅ `/compact` | ✅ | ✅ | ✅ | ✅ auto | ➖ *ChatGPT's job* |
| Per-folder activity journal | ❌ | 🟡 | ❌ | ❌ | ❌ | ✅ `sessions/<hash>/events.jsonl` |

## 6. Planning & task structure

| Feature | Codex | Claude Code | OpenCode | Cursor | Pi | **OURS** |
|---|---|---|---|---|---|---|
| Plan mode | ✅ `/plan` | ✅ | ✅ Plan/Build | ✅ | ❌ *(on purpose)* | ✅ `permission_mode=plan` |
| Todo list | ✅ | ✅ TodoWrite | ✅ | ✅ | ❌ *(on purpose)* | ✅ `write_todos/list_todos` |
| Persistent goal | ✅ `/goal` | 🟡 | 🟡 | 🟡 | ❌ | ✅ `set_task_goal` |
| **Acceptance criteria** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ **`set_acceptance_criteria`** ← unique |
| **Formal task state machine** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ **new→…→review_ready→completed** ← unique |
| **Completion needs evidence** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ **`finish_task` demands test results** ← unique |
| Task telemetry (files/commands/tests auto-recorded) | 🟡 | 🟡 | ❌ | 🟡 | ❌ | ✅ auto-populated |
| Sub-tasks (checklist children) | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ `create_subtask` |

## 7. Permissions & safety ← **our strongest area**

| Feature | Codex | Claude Code | OpenCode | Cursor | Pi | **OURS** |
|---|---|---|---|---|---|---|
| Approval modes | ✅ 3 (untrusted/on-request/never) | ✅ | ✅ | ✅ 3 run modes | ❌ *(build your own)* | ✅ **6 modes** |
| Ask-before-risky-action | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ `⏸ APPROVAL REQUIRED` |
| **Approval bound to the EXACT command** | ✅ *(per-command IDs)* | 🟡 | 🟡 | 🟡 | ❌ | ✅ **sha256(task+tool+args)** |
| **Approval decided OUT-OF-BAND (not in the chat)** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ **operator CLI only** ← unique |
| Folder confinement | ✅ workspace-write | ✅ | ✅ | ✅ | 🟡 trust.json | ✅ **roots (always on, every mode)** |
| **Model CANNOT escalate its own power** | 🟡 | 🟡 | 🟡 | 🟡 | ❌ | ✅ **hard ceiling `HARNESS_MAX_MODE`** ← ahead |
| Secret-file blocking (.env, keys) | 🟡 | 🟡 | ❌ | 🟡 | ❌ | ✅ denylist |
| **Secret scrubbing from ALL output** | ❌ | ❌ | ❌ | 🟡 hooks | ❌ | ✅ **on by default** ← ahead |
| Declarative command policy | ✅ `execpolicy` | ✅ allowlist | ✅ | ✅ `permissions.json` | ❌ | 🟡 regex classifier + `ARBITRARY_COMMANDS=ask` |
| Audit log of every action | 🟡 | 🟡 | ❌ | ✅ enterprise | ❌ | ✅ `audit.jsonl` |
| Terminal tasks frozen after done | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ unique |

## 8. Sandboxing

| Feature | Codex | Claude Code | OpenCode | Cursor | Pi | **OURS** |
|---|---|---|---|---|---|---|
| OS-native sandbox | ✅ **Seatbelt/Landlock/Windows** | ✅ | 🟡 | ✅ | ❌ | ❌ **GAP** |
| Container sandbox | ✅ cloud | 🟡 | 🟡 | ✅ | ❌ | ✅ Docker (hardened: cap-drop, no-new-priv, pids/cpu/mem) |
| Network off inside sandbox | ✅ | ✅ | 🟡 | ✅ | ❌ | ✅ `network=none` |
| **Per-domain network allowlist** | 🟡 | 🟡 | ❌ | ✅ **`sandbox.json`** | ❌ | ❌ **GAP** |
| Sandbox covers internal git/rg | ✅ | ✅ | — | ✅ | — | ❌ **GAP (documented)** |

## 9. Isolation & git

| Feature | Codex | Claude Code | OpenCode | Cursor | Pi | **OURS** |
|---|---|---|---|---|---|---|
| Git worktree per task | ✅ | ✅ | 🟡 | ✅ | 🟡 ext | ✅ **automatic in `start_task`** |
| Two tasks can't touch same files | ✅ | ✅ | 🟡 | ✅ | ❌ | ✅ proven by test |
| Checkpoint / undo edits | 🟡 | ✅ rewind | ✅ `/undo` `/redo` | ✅ | 🟡 ext | ✅ `create/list/restore_checkpoint` |
| **Auto-checkpoint before edits** | ❌ | ✅ | ❌ | 🟡 | ❌ | ✅ (debounced, pre-WRITE **and** pre-EXEC) |
| Commit | ✅ | ✅ | ✅ | ✅ | ✅ (bash) | ✅ `git_commit` |
| **Repo hooks blocked from running on host** | 🟡 | 🟡 | ❌ | 🟡 | ❌ | ✅ **`no_hooks` default** ← ahead |
| Open a PR | ✅ | ✅ | ✅ | ✅ | 🟡 | ✅ `open_pr` (approval-gated) |
| Code review of a diff | ✅ `codex review` | ✅ `/code-review` | 🟡 | ✅ BugBot | ❌ | 🟡 visual diff in the Workbench; the *AI* review is ChatGPT via `git_diff` |

## 10. Extensibility

| Feature | Codex | Claude Code | OpenCode | Cursor | Pi | **OURS** |
|---|---|---|---|---|---|---|
| **MCP client** (use other servers) | ✅ | ✅ | ✅ | ✅ | ❌ *(on purpose)* | ✅ `mcp_call` **+ permission-gated** ← ahead |
| **Is itself an MCP server** | ✅ `mcp-server` | 🟡 | ✅ | ❌ | ❌ | ✅ **that's the whole product** |
| Skills (markdown capability docs) | ✅ `/skills` | ✅ | ✅ | 🟡 | ✅ | ✅ `list_skills/load_skill` |
| Reads `~/.agents/skills` | 🟡 | 🟡 | ✅ | ❌ | ✅ | ✅ **yes, automatically** |
| **User-configurable hooks** | ✅ | ✅ **script/HTTP/prompt/subagent** | ✅ | ✅ 4 events | ✅ TS ext | ✅ `<state_dir>/hooks.json` (operator-only, sandboxed env, pre can veto) |
| Plugins / marketplace | ✅ | ✅ | ✅ | ✅ | ✅ npm/git | ❌ **GAP** |
| Prompt templates / slash cmds | ✅ | ✅ | ✅ | ✅ | ✅ | 🟡 skills only |
| SDK / programmatic embed | ✅ app-server | ✅ Agent SDK | ✅ server+SDK | 🟡 | ✅ SDK/RPC | 🟡 stdio MCP |
| Auto-format after edit | 🟡 | 🟡 | ✅ | ✅ | ❌ | ✅ opt-in (`HARNESS_AUTO_FORMAT`; ruff/black/prettier/rustfmt/gofmt) |

## 11. Sub-agents & parallelism 🚫

| Feature | Codex | Claude Code | OpenCode | Cursor | Pi | **OURS** |
|---|---|---|---|---|---|---|
| Autonomous LLM sub-agents | ✅ (`explorer`/`worker`, TOML, max_threads 6) | ✅ (own context, background) | ✅ | ✅ async subagents | ❌ *(on purpose)* | 🚫 **impossible** |
| Agent teams (peers talk) | 🟡 | ✅ experimental | ❌ | 🟡 | ❌ | 🚫 |
| Background agents | ✅ cloud | ✅ | ✅ | ✅ | ❌ | 🚫 |
| Batch fan-out (CSV) | ✅ | 🟡 | ❌ | ❌ | ❌ | 🚫 |

> **Why 🚫 and not ❌:** spawning an AI sub-agent means *the harness itself must
> call an AI*. That needs an API key and costs money per token — the exact thing
> this project exists to avoid. We have **no model inside**. This is a permanent,
> deliberate trade, not a missing feature. Our answer is `create_subtask`: one
> ChatGPT working a checklist of child jobs, resumable, sharing the worktree.
> **Pi makes the same choice** and tells you to use tmux instead.

## 12. Model, UI & surfaces ➖

| Feature | Codex | Claude Code | OpenCode | Cursor | Pi | **OURS** |
|---|---|---|---|---|---|---|
| Pick/switch model | ✅ | ✅ | ✅ 75+ | ✅ | ✅ | ➖ ChatGPT's picker |
| Reasoning-effort control | ✅ | ✅ | 🟡 | 🟡 | ✅ | ➖ |
| Web search | ✅ `--search` | ✅ | 🟡 | ✅ | 🟡 | ➖ ChatGPT has it |
| TUI / GUI | ✅ | ✅ | ✅ | ✅ IDE | ✅ | ✅ **Workbench** (`harness up`): 3-pane operator GUI — tree+pins+search, session tabs, inspector (Activity/Changes/Terminal/Files/Approvals). Chat itself stays in ChatGPT ➖ |
| Token/cost meter | ✅ `/usage` | ✅ `/context` | ✅ | ✅ | ✅ | ➖ (subscription — no per-token cost) |
| Vim mode / keymaps | ✅ | 🟡 | ✅ | ✅ | ✅ | ➖ |
| IDE extension | ✅ VS Code+JetBrains | ✅ | ✅ | ✅ *(is one)* | ❌ | 🟡 via stdio MCP |
| GitHub bot / cloud tasks | ✅ | ✅ Actions | 🟡 | ✅ | ❌ | ❌ out of scope |
| **Live activity feed for the operator** | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 | ✅ **`harness watch`** |
| **Remote access over internet** | 🟡 remote-control | 🟡 | 🟡 | 🟡 | ❌ | ✅ **Tailscale Funnel + secret route** |
| Cost | 💰 sub/API | 💰 sub/API | 💰 your API keys | 💰 sub | 💰 your API keys | ✅ **your existing ChatGPT sub. £0 extra** |

---

## 13. THE HONEST SCORECARD — updated 2026-07-16

Of the 12 gaps in the original 2026-07-15 scorecard, **7 are now CLOSED** (built
and tested) and 5 remain. History preserved below so the progress is auditable.

```
 CLOSED SINCE 2026-07-15  (was gap → what we built)
 ────────────────────────────────────────────────────────────────
 ✔ 1. LSP / code intelligence   lsp_definition/references/hover/symbols;
                                auto-detects pyright/pylsp/tsserver/
                                rust-analyzer/gopls; verified cross-file.
 ✔ 2. User-configurable hooks   <state_dir>/hooks.json — operator-only
                                (outside every root), timeout, output cap,
                                restricted env; pre-hooks can veto.
 ✔ 4. Session fork / branch     fork_task: own worktree from the same
                                base, goal/criteria copied, lineage kept.
 ✔ 7. Path-scoped rules         .harness/rules/*.md with globs:, surfaced
                                exactly when a WRITE touches a match.
 ✔ 8. Diff review               visual diff in the Workbench inspector;
                                the AI half is ChatGPT via git_diff.
 ✔11. Auto-format after edit    opt-in post-WRITE hook (ruff/black/
                                prettier/rustfmt/gofmt).
 ✔ —  Operator GUI (unlisted    the WORKBENCH (`harness up`): 3-pane GUI,
      in the original 12!)      session tabs, pins, Ctrl-K search, live
                                activity, approvals, terminal telemetry.

 STILL MISSING (could build, would add real value)
 ────────────────────────────────────────────────────────
   3. Plugins / marketplace      no bundle+share format. Personal tool → SKIP
                                 unless a community forms.
   5. Per-domain net allowlist   Cursor's sandbox.json beats our all-or-nothing
                                 network=none. Only matters under Docker → LATER.
   6. OS-native sandbox          Codex uses macOS Seatbelt / Linux Landlock (no
                                 Docker). Windows has no clean equivalent, so
                                 Docker stays our answer → LATER / RESEARCH.
   9. Sandbox internal git/rg    they still run on the host under Docker;
                                 hooks/config already neutralized → LATER.
  10. Session share link         a privacy surface for a single-user tool → SKIP.
  12. Semantic/embedding index   Cursor's superpower. Needs an embedding model; a
                                 LOCAL free one is heavy → REVISIT only if
                                 grep + LSP ever feel insufficient.

 IMPOSSIBLE BY DESIGN (🚫 — we have no AI inside the harness)
 ────────────────────────────────────────────────────────
   autonomous sub-agents · agent teams · background agents ·
   LLM command classifier · batch fan-out
   → each needs the harness to CALL a model = API bills = the very thing this
     project exists to avoid. Pi made the identical choice. Our answer is
     create_subtask: one ChatGPT working a checklist, sharing the worktree.

 NOT NEEDED (➖ — ChatGPT already provides it)
 ────────────────────────────────────────────────────────
   model switching · reasoning effort · web search · compaction ·
   the chat transcript itself · token meter · vim mode
```

## 14. Where we BEAT all five

```
 ✅ Free-est: uses the ChatGPT subscription you already pay for. No API key
    anywhere in the codebase. Nobody else can say that.
 ✅ Approvals are decided OUTSIDE the model's reach — a CLI on your keyboard.
    Every other tool approves inside the same UI the agent drives.
 ✅ Hard privilege ceiling: the model literally cannot request `full`.
 ✅ Approval bound to an exact args-hash, per task, one-shot.
 ✅ Stale-write guard (expected_sha) — nobody else has this.
 ✅ Secret scrubbing on every output path, by default.
 ✅ Formal task state machine + acceptance criteria + evidence-gated completion.
 ✅ Idempotency keys (operation_id) so a retry can't double-apply.
 ✅ Worktrees share project memory via git common-dir.
 ✅ Repo pre-commit hooks can't execute on your host by default.
 ✅ Idempotency keys REJECT a reused key with different args (return
    IDEMPOTENCY_CONFLICT) instead of silently replaying the wrong result.
 ✅ Operator GUI where the approve buttons are physically unreachable by the
    model (separate localhost port, never funneled, CSRF-guarded).
 ✅ Works from ANY device with ChatGPT — phone included — via the Funnel.
```

## 15. One-line verdict

```
 Codex       = the most complete OpenAI-native harness (cloud, GitHub, subagents,
               OS sandbox). Locked to OpenAI. Costs quota.
 Claude Code = the most extensible (skills+hooks+subagents+teams+plugins+LSP).
               Locked to Anthropic. Costs quota.
 OpenCode    = the best open-source all-rounder; 75+ providers, real LSP.
               You bring API keys = you pay per token.
 Cursor      = the best *IDE* experience; semantic index is unmatched.
               Not a terminal harness; subscription.
 Pi          = the minimalist's harness. Deliberately no MCP, no subagents,
               no plan mode — "build it yourself as an extension."
 OURS        = the only one where the brain is your normal ChatGPT and the hands
               are a locked-down MCP server you own. Weakest at code
               intelligence. Strongest at permissions, isolation, and auditability.
               Nothing else lets you code from your phone, on your PC's files,
               on a subscription you already pay for.
```

---

## Sources

- Codex: [CLI reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli) · [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) · [Sandboxing](https://developers.openai.com/codex/concepts/sandboxing) · [Approvals & security](https://developers.openai.com/codex/agent-approvals-security) · [Cloud](https://developers.openai.com/codex/cloud) · [GitHub](https://developers.openai.com/codex/integrations/github)
- Claude Code: [Extend Claude Code](https://code.claude.com/docs/en/features-overview)
- OpenCode: [opencode.ai](https://opencode.ai/) · [docs](https://opencode.ai/docs/)
- Cursor: [Run modes](https://cursor.com/docs/agent/security/run-modes) · [Terminal](https://cursor.com/docs/agent/tools/terminal) · [LLM safety & controls](https://cursor.com/docs/enterprise/llm-safety-and-controls) · [Changelog 2.5](https://cursor.com/changelog/2-5)
- Pi: [pi.dev](https://pi.dev/) · [coding-agent README](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/README.md)
