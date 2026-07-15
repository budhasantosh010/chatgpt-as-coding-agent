# Roadmap — what gets built, in what order, and why (decided 2026-07-15)

This is the deep-dive plan the user asked for. It takes every gap from
[COMPARISON.md](COMPARISON.md) §13, gives each one an explicit verdict
(BUILD / LATER / SKIP — nothing skipped silently), and orders the builds.

Read [MANUAL.md](MANUAL.md) for how the system works today and
[COCKPIT_DESIGN.md](COCKPIT_DESIGN.md) for the GUI design (decided, not built).

---

## 0. The t3code question, settled permanently

Two similar-sounding words that are opposites in cost:

```
 "FORK t3code"  = take their CODE   ← the COMPLICATED option
 "MODEL t3code" = copy their LOOK   ← FREE

 t3code's screens are welded by "cables" to ITS engine (Codex/Claude
 provider sessions, token streams). Forking = cutting every weld and
 re-welding to our engine, inside a codebase we didn't write, in a
 stack (Node/npm/React) this project doesn't use.

 A LAYOUT is just where boxes go. Copying where boxes go adds ZERO
 complexity — the complexity lives in the cables, and our cables
 ALREADY EXIST (51 tools, tasks.db, audit.jsonl, approvals CLI).
```

**Decision (locked):** build our own cockpit page, use t3code/Codex purely as
visual inspiration. Never fork. If we ever want more polish, rebuild the
front-end on the identical API — the engine never changes.

---

## 1. Verdict on every gap from COMPARISON.md §13

| # | Gap | Verdict | Size | Why |
|---|-----|---------|------|-----|
| 1 | LSP / code intelligence | **BUILD (2nd)** | LARGE | Biggest brain-boost for ChatGPT. Today it finds code by text search (grep); LSP answers "where is this DEFINED / who CALLS it" exactly. Start with the user's real languages (JS/TS, Python). |
| 2 | User-configurable hooks | **BUILD (3rd)** | SMALL | HookManager seam already exists; expose "run this script pre/post tool" via config instead of a Python edit. |
| 3 | Plugins / marketplace | **SKIP** | — | Personal tool, one user. Product feature. Revisit only if the repo grows a community. |
| 4 | Session fork / branch | **BUILD (4th)** | SMALL | `fork_task`: copy a task + fresh worktree from the same base commit → try two approaches side by side. Cheap because tasks + worktrees exist. |
| 5 | Per-domain network allowlist | **LATER** | MEDIUM | Only matters for untrusted repos under Docker; needs a proxy container. Wait for actual need. |
| 6 | OS-native sandbox | **SKIP** | — | Codex uses macOS Seatbelt / Linux Landlock. **Windows has no good equivalent** — Docker IS our sandbox on this machine. Documented honestly, not a to-do. |
| 7 | Path-scoped rules | **BUILD (3rd)** | SMALL | Load a rules file only when touched files match its globs. Small addition to `open_workspace`. |
| 8 | Diff review command | **ABSORBED by Cockpit** | — | The cockpit's diff panel is the viewer; the *reviewing brain* is ChatGPT itself via `git_diff` (already works). No separate build. |
| 9 | Sandbox internal git/rg | **LATER** | MEDIUM | Hardening for untrusted repos; the limit is documented and hooks are already neutralized (`no_hooks`). |
| 10 | Session share link | **SKIP** | — | Personal tool; a share link is a privacy surface with no payoff for one user. |
| 11 | Auto-format after edit | **BUILD (3rd)** | SMALL | A post-WRITE hook that runs the project's formatter. Rides the same mechanism as gap 2. |
| 12 | Semantic / embedding index | **SKIP (revisit)** | LARGE | Needs an embedding model. A LOCAL free one keeps £0 (no API), but the install is heavy (torch etc.). Revisit only if grep + LSP ever feel insufficient. |

**Still impossible by design (🚫, unchanged, forever):** autonomous sub-agents,
agent teams, background agents, batch fan-out, LLM command classifier — every
one requires an AI *inside* the harness = API bills = the thing this project
exists to avoid.

---

## 2. The build order

```
 NOW ──▶ 1. COCKPIT slice 1   projects + sessions underneath + mode
         │                    dropdown + drag-drop folder/file
         │                    (per COCKPIT_DESIGN.md; :8849 localhost-only)
         ▼
         2. COCKPIT slice 2   live activity feed + approve/deny buttons
         │                    + visual diff panel  (kills gap 8 too)
         ▼
         3. LSP               go-to-definition / find-references /
         │                    hover types for JS/TS + Python first
         ▼
         4. QUALITY BATCH     user hooks + path-scoped rules +
         │                    auto-format   (gaps 2, 7, 11 — one sprint,
         ▼                     one shared mechanism)
         5. FORK TASK         (gap 4)

 LATER   per-domain network allowlist (5) · sandboxed git/rg (9)
 SKIP    plugins (3) · OS sandbox on Windows (6) · share link (10)
         · semantic index (12, revisit)
 NEVER   anything needing a model inside the harness (🚫 list)
```

**Why the Cockpit outranks LSP** even though LSP is COMPARISON.md's #1 gap:
the gap list ranks what makes *ChatGPT* smarter; the user's actual daily pain
(their own words) is *seeing and controlling* the system without terminal
commands. Fix the human's pain first, the robot's second. LSP goes immediately
after.

---

## 3. Status

- Cockpit: designed + decided (see COCKPIT_DESIGN.md), **not built — awaiting
  the user's explicit GO.**
- Everything else: sequenced above, untouched until the cockpit ships.
