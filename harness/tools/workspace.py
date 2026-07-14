"""Workspace orientation: open_workspace and session_status.

open_workspace is the entry point for a coding session — it sets the active
workspace and returns the same orientation Claude Code gets on startup (git
state, structure, project type, and any AGENTS.md / CLAUDE.md rules).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..context import HarnessContext
from . import gitcmd, memory, todos

_PROJECT_MARKERS: list[tuple[str, str]] = [
    ("package.json", "node"),
    ("pnpm-lock.yaml", "node/pnpm"),
    ("pyproject.toml", "python"),
    ("requirements.txt", "python"),
    ("Cargo.toml", "rust"),
    ("go.mod", "go"),
    ("pom.xml", "java/maven"),
    ("build.gradle", "java/gradle"),
    ("Gemfile", "ruby"),
    ("composer.json", "php"),
    ("CMakeLists.txt", "cmake"),
]

_INSTRUCTION_FILES = ["AGENTS.md", "CLAUDE.md", ".cursorrules"]
_MAX_INSTRUCTION_CHARS = 6000


def _suggested_commands(ws: Path) -> list[str]:
    """Detect how to test/build/run this project so the agent doesn't guess."""
    import json

    out: list[str] = []
    pkg = ws / "package.json"
    if pkg.exists():
        try:
            scripts = (json.loads(pkg.read_text(encoding="utf-8", errors="replace")) or {}).get("scripts", {})
        except (ValueError, OSError):
            scripts = {}
        for name in ("test", "build", "lint", "typecheck", "dev", "start"):
            if name in scripts:
                out.append(f"npm run {name}    # {scripts[name]}")
    if (ws / "pyproject.toml").exists() or (ws / "setup.py").exists() or (ws / "requirements.txt").exists():
        out.append("pytest              # if tests/ present")
        if (ws / "ruff.toml").exists() or (ws / ".ruff.toml").exists():
            out.append("ruff check .")
    if (ws / "Cargo.toml").exists():
        out += ["cargo test", "cargo build"]
    if (ws / "go.mod").exists():
        out += ["go test ./...", "go build ./..."]
    if (ws / "Makefile").exists():
        out.append("make                # see Makefile targets")
    return out


async def _git(hc: HarnessContext, workspace: Path, *args: str) -> str | None:
    if shutil.which("git") is None:
        return None
    result = await gitcmd.git(hc, workspace, *args, timeout=15)
    if result.timed_out or result.returncode != 0:
        return None
    return result.stdout.strip()


async def open_workspace(hc: HarnessContext, path: str) -> str:
    ws = hc.set_workspace(path)
    hc.log("open_workspace", path=str(ws))

    lines: list[str] = [f"# Workspace opened: {ws}", ""]

    switched_from = getattr(hc, "_switched_from", None)
    if switched_from is not None:
        lines += [
            f"> ⚠️ This session already had `{switched_from}` open; now switched to "
            f"this one. If you're running more than one ChatGPT conversation against "
            f"this harness, they currently share state — use one at a time until "
            f"per-task isolation lands.",
            "",
        ]

    is_git = await _git(hc, ws, "rev-parse", "--is-inside-work-tree")
    if is_git == "true":
        branch = await _git(hc, ws, "rev-parse", "--abbrev-ref", "HEAD") or "?"
        status = await _git(hc, ws, "status", "--short")
        log = await _git(hc, ws, "log", "-5", "--oneline")
        lines.append(f"**Git branch:** {branch}")
        if status:
            lines += ["**Uncommitted changes:**", "```", status, "```"]
        else:
            lines.append("**Working tree:** clean")
        if log:
            lines += ["**Recent commits:**", "```", log, "```"]
    else:
        lines.append("**Git:** not a git repository")
    lines.append("")

    detected = [label for marker, label in _PROJECT_MARKERS if (ws / marker).exists()]
    if detected:
        lines.append(f"**Detected project type:** {', '.join(sorted(set(detected)))}")

    commands = _suggested_commands(ws)
    if commands:
        lines += ["**Suggested commands:**", "```", *commands, "```"]

    entries = sorted(ws.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    struct = [f"  {e.name}/" if e.is_dir() else f"  {e.name}" for e in entries[:60]]
    lines += ["**Top level:**", "```", *struct]
    if len(entries) > 60:
        lines.append(f"  ... and {len(entries) - 60} more")
    lines += ["```", ""]

    for name in _INSTRUCTION_FILES:
        f = ws / name
        if f.exists() and f.is_file():
            content = f.read_text(encoding="utf-8", errors="replace")
            if len(content) > _MAX_INSTRUCTION_CHARS:
                content = content[:_MAX_INSTRUCTION_CHARS] + "\n[... truncated]"
            lines += [f"## Project rules from {name}", content, ""]

    remembered = await memory.load_memories(hc)
    if remembered:
        lines.append("## Remembered facts (from previous sessions)")
        lines += [f"- [{it['id']}] {it['text']}" for it in remembered]
        lines.append("")

    return "\n".join(lines)


async def session_status(hc: HarnessContext) -> str:
    ws = hc.active_workspace
    if ws is None:
        return "No active workspace. Call open_workspace(path) to start."

    lines = [f"# Session status for {ws}", ""]

    status = await _git(hc, ws, "status", "--short")
    if status is not None:
        lines += ["**Current git changes:**", "```", status or "(clean)", "```"]
        diffstat = await _git(hc, ws, "diff", "--stat")
        if diffstat:
            lines += ["```", diffstat, "```"]
        lines.append("")

    current_todos = todos.load_todos(hc)
    if current_todos:
        lines.append(todos.format_todos(current_todos))
        lines.append("")

    if hc.session is not None:
        events = hc.session.recent(30)
        lines.append(f"**Recent actions ({len(events)}):**")
        if events:
            lines.append("```")
            for ev in events:
                detail = {k: v for k, v in ev.items() if k not in ("time", "event")}
                lines.append(f"{ev.get('time', '')}  {ev.get('event', '')}  {detail}")
            lines.append("```")
        else:
            lines.append("(no actions logged yet)")

    return "\n".join(lines)
