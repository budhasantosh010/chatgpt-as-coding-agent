"""Diagnostics: detect and run the project's checker, so the model stops editing
blind. This is the pragmatic 80% of an LSP — after a change, run the real
typecheck/lint and surface errors — without an LSP client's machinery.

The checker is auto-detected from project markers; the first available tool wins.
Runs through the session executor (restricted env / sandbox), like any command.
"""

from __future__ import annotations

import shutil

from ..context import HarnessContext
from ..executor import LocalExecutor

# (marker file, tool executable, argv-tail). First whose tool is on PATH wins.
_CHECKERS: list[tuple[str, str, list[str]]] = [
    ("pyproject.toml", "ruff", ["check", "."]),
    ("ruff.toml", "ruff", ["check", "."]),
    (".ruff.toml", "ruff", ["check", "."]),
    ("requirements.txt", "ruff", ["check", "."]),
    ("tsconfig.json", "tsc", ["--noEmit"]),
    ("package.json", "eslint", ["."]),
    ("Cargo.toml", "cargo", ["check", "--quiet"]),
    ("go.mod", "go", ["vet", "./..."]),
]


def _detect(ws) -> tuple[str, list[str]] | None:
    for marker, tool, tail in _CHECKERS:
        if (ws / marker).exists() and shutil.which(tool):
            return tool, tail
    # python fallback: pyflakes if present
    if shutil.which("pyflakes") and any(ws.glob("*.py")):
        return "pyflakes", ["."]
    return None


async def diagnostics(hc: HarnessContext, path: str | None = None) -> str:
    ws = hc.require_workspace()
    detected = _detect(ws)
    if detected is None:
        return (
            "No diagnostics tool detected/installed for this project. Install one "
            "(ruff, tsc, eslint, cargo, go) or run your check via run_command."
        )
    tool, tail = detected
    argv = [tool, *tail]
    if path:
        # replace the '.' target with the specific path where applicable
        argv = [tool] + [(str(hc.resolve_read(path)) if a == "." else a) for a in tail]

    executor = getattr(hc, "executor", None) or LocalExecutor(
        hc.config.shell, getattr(hc.config, "env_allowlist", ())
    )
    # Under the Docker sandbox, run the checker INSIDE the container (run() →
    # spawn_argv), not on the host via run_argv — a project checker (e.g. cargo
    # check) can execute repo-controlled build scripts. Locally, run_argv keeps
    # the restricted-env argv path.
    if getattr(executor, "name", "local") == "docker":
        import shlex
        result = await executor.run(shlex.join(argv), cwd=str(ws), timeout=120)
    else:
        result = await executor.run_argv(argv, cwd=str(ws), timeout=120)
    out = result.combined.strip()
    max_chars = hc.config.max_output_chars
    if len(out) > max_chars:
        out = out[:max_chars] + f"\n[truncated at {max_chars} chars]"
    hc.log("diagnostics", tool=tool, exit_code=result.returncode)
    header = f"# diagnostics ({' '.join(argv)}) — exit {result.returncode}"
    if result.returncode == 0 and not out:
        return header + "\nNo problems found. ✅"
    return f"{header}\n```\n{out or '(no output)'}\n```"
