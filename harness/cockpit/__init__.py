"""The Cockpit: a localhost-only operator GUI over the harness primitives.

It is NOT the brain (ChatGPT is) and NOT the hands' public endpoint (that's the
MCP server on :8848, behind the funnel). It is the OPERATOR CONSOLE: projects,
sessions (tasks), mode selection, live activity, approvals, diffs — a window
over primitives that already exist.

Two hard rules baked in (see docs/ROADMAP.md §3):
  * bind 127.0.0.1 only, never funneled — the model must never reach it;
  * every mutation carries a CSRF token in a custom header + Origin check, so a
    random webpage in your browser can't drive it.
"""
