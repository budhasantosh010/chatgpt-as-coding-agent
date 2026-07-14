# Project state & handoff

Single source of truth for what this is, how it's built, what's done, and what's
next. Read this first when resuming work.

## What it is

A local **MCP coding server** driven by **normal ChatGPT** (not Codex, not an API
key). ChatGPT is the reasoning loop; this server is the hands (read/write/edit/
search/shell + git + memory + skills + processes + worktrees). Reachable from
ChatGPT through a Tailscale Funnel + secret-route URL. Purpose: code with ChatGPT
like Claude Code / Codex, using ordinary ChatGPT usage instead of draining Codex.

No model-provider API is ever called from this server.

## Architecture (ports-and-adapters)

```
harness/
  app.py          composition root: config -> HarnessServer -> MCP -> secured app
  __main__.py     CLI: serve / doctor / url
  config.py       12-factor config; persisted secret route; adds worktrees root
  context.py      HarnessServer (shared config + SessionStore) + HarnessContext (per session)
  policy.py       Capability {READ,WRITE,EXECUTE} + PermissionPolicy (the one mode table)
  security.py     path confinement / secret-file denylist / command denylist
  session.py      per-workspace event journal (resume)
  proc.py         one async subprocess impl (env-aware, non-blocking)
  processes.py    ProcessManager for long-running background processes
  middleware.py   pure-ASGI security shell (secret route, Host/Origin, bearer, rate limit)
  server.py       FastMCP: per-session ctx + thin typed tool wrappers + capability gate
  tools/          files search shell workspace git memory skills todos process worktree
```

**The rule that makes it scale:** tool logic is pure functions over a
HarnessContext; each MCP tool is one thin wrapper declaring a capability. Adding
a tool = one function + one wrapper. Adding a permission mode = edit policy.py
only. Nothing else changes.

## Status: 29 tools, 66 tests, verified end-to-end

**Done — Tier 0 (foundations):** per-session isolation (HarnessServer +
SessionStore; concurrent ChatGPT conversations no longer corrupt each other).

**Done — Tier 1 (parity with Claude Code / Codex):**
- memory: remember / recall / forget (per-workspace, auto-surfaced on open)
- skills: list_skills / load_skill (workspace + ~/.agents/skills)
- todos: write_todos / list_todos (survive turn resets; shown in session_status)
- background processes: start / read / write / stop / list_processes
- atomic multi-file patch: apply_edits (snapshot + rollback)
- worktree-per-task: create / list / remove_worktree
- ergonomics: glob noise-filter (skips node_modules), auto-detected project commands
- git safety: git_diff, create/list/restore_checkpoint (private ref, no branch pollution)

**Roadmap — Tier 2/3 (not built):**
- container/OS sandbox for run_command (the real answer to prompt-injection; denylist is only a backstop)
- secret-content scrubbing (block secrets inside normal files, not just secret filenames)
- second transport (stdio) for non-ChatGPT clients
- hooks / lifecycle events (pre/post tool)

## Key decisions (don't relitigate)

- **No Pi, no TypeScript.** One pure-Python process. Rejected forking Pi (Node
  inside Python) as needless coupling/waste.
- **Transport gotcha (fixed):** the MCP SDK's built-in Host check is exact-match
  and rejects `*.ts.net` funnel hosts (Spectre hit this). We pass
  `transport_security(enable_dns_rebinding_protection=False)` and let our own
  SecurityMiddleware (with a `.ts.net` wildcard) gate Host/Origin. Also
  `json_response=True` + `stateless_http=True` to match the proven Spectre config.
- **Secret route** is the primary auth (256-bit path); optional bearer on top.
- Security is enforced in code, not by trusting the model. It is a denylist
  backstop, NOT a sandbox — untrusted use needs the Tier-2 container.

## Run & test

```
python -m pip install .            # or: pip install -r requirements.txt
python -m harness doctor           # validate config + environment
python -m harness serve            # start server on 127.0.0.1:8848
python -m pytest tests -q          # 66 tests (needs pip install .[dev])
```

See README.md for the full ChatGPT-connector + Tailscale setup.
