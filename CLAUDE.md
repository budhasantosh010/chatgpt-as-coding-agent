# CLAUDE.md

**Read [AGENTS.md](AGENTS.md) — all of it — before your first edit.**

That file is the single handoff for every coding agent on this repository
(Claude Code, Codex, Cursor, opencode, Gemini CLI, Copilot). This file exists
only because Claude Code looks for this filename; it deliberately holds no rules
of its own, so there is nothing here that can drift out of step with AGENTS.md.

Quick orientation, then go read it:

```
  what it is    a local MCP server that lets a normal ChatGPT subscription
                code on this machine. ChatGPT is the brain; this is the hands.

  never do      call a model-provider API  ·  touch the Tailscale Funnel
                use https/gh for git (SSH only)  ·  add npm/React
                let model prose satisfy a gate  ·  let the model self-elevate

  before edits  python -m harness doctor  &&  python -m pytest tests -q   (484)
```
