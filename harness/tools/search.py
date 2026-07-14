"""Search tools: glob (filename patterns) and grep (content search via ripgrep)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import anyio

from ..context import HarnessContext
from ..proc import run_subprocess

# Heavy/noise directories that pollute results and waste context. Skipped by
# glob so ChatGPT never descends into node_modules & friends. (grep already
# skips these via ripgrep's .gitignore handling.)
_NOISE_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".next", ".nuxt", "target", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".gradle", ".idea", ".vscode", "vendor",
    ".terraform", "coverage", ".turbo",
})


def _is_noise(path: Path, base: Path) -> bool:
    try:
        rel_parts = path.relative_to(base).parts
    except ValueError:
        rel_parts = path.parts
    return any(part in _NOISE_DIRS for part in rel_parts)


async def glob_files(hc: HarnessContext, pattern: str, path: str | None = None, limit: int = 200) -> str:
    base_str = path if path is not None else str(hc.require_workspace())
    base = hc.resolve_read(base_str)
    if not base.is_dir():
        raise NotADirectoryError(f"{base} is not a directory.")

    def _collect() -> list[Path]:
        matches = [p for p in base.glob(pattern) if p.is_file() and not _is_noise(p, base)]
        matches.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        return matches

    matches = await anyio.to_thread.run_sync(_collect)
    shown = matches[:limit]
    if not shown:
        return f"No files match {pattern!r} under {base}."
    rows = "\n".join(str(p) for p in shown)
    more = f"\n... and {len(matches) - limit} more" if len(matches) > limit else ""
    return f"{len(matches)} match(es) for {pattern!r}:\n{rows}{more}"


async def grep(
    hc: HarnessContext,
    pattern: str,
    path: str | None = None,
    glob: str | None = None,
    ignore_case: bool = False,
    context: int = 0,
    output_mode: str = "content",
    limit: int = 200,
) -> str:
    base_str = path if path is not None else str(hc.require_workspace())
    base = hc.resolve_read(base_str)

    rg = shutil.which("rg")
    if rg is None:
        return await anyio.to_thread.run_sync(_grep_python, base, pattern, ignore_case, limit)

    args = [rg, "--line-number", "--no-heading", "--color", "never"]
    if ignore_case:
        args.append("--ignore-case")
    if glob:
        args += ["--glob", glob]
    if output_mode == "files_with_matches":
        args.append("--files-with-matches")
    elif output_mode == "count":
        args.append("--count")
    elif context and context > 0:
        args += ["--context", str(context)]
    args += ["--", pattern, str(base)]

    result = await run_subprocess(args, timeout=30)
    if result.timed_out:
        return "grep timed out after 30s. Narrow the pattern or path."
    if result.returncode not in (0, 1):  # 1 == no matches, which is fine
        return f"grep error: {result.stderr.strip() or 'unknown'}"
    out = result.stdout
    if not out.strip():
        return f"No matches for {pattern!r} under {base}."

    lines = out.splitlines()
    body = "\n".join(lines[:limit])
    more = f"\n... and {len(lines) - limit} more lines" if len(lines) > limit else ""
    return body + more


def _grep_python(base: Path, pattern: str, ignore_case: bool, limit: int) -> str:
    flags = re.IGNORECASE if ignore_case else 0
    try:
        rx = re.compile(pattern, flags)
    except re.error as exc:
        return f"Invalid regex: {exc}"
    hits: list[str] = []
    for file in base.rglob("*"):
        if not file.is_file():
            continue
        try:
            with file.open("r", encoding="utf-8", errors="ignore") as fh:
                for i, line in enumerate(fh, 1):
                    if rx.search(line):
                        hits.append(f"{file}:{i}:{line.rstrip()}")
                        if len(hits) >= limit:
                            return "\n".join(hits) + "\n... (limit reached)"
        except OSError:
            continue
    return "\n".join(hits) if hits else f"No matches for {pattern!r} under {base}."
