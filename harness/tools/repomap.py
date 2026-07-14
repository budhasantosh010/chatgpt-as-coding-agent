"""Repo map: a compact symbol index (top-level functions/classes per file) so the
model can locate code fast without reading every file. Python is parsed with the
stdlib ``ast``; other languages use high-signal regexes. Noise dirs are skipped.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ..context import HarnessContext
from .search import _is_noise

# language -> regex capturing symbol names (first non-None group)
_REGEX_LANGS: dict[str, re.Pattern] = {
    ".js": re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)|^\s*(?:export\s+)?class\s+(\w+)", re.M),
    ".ts": re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)|^\s*(?:export\s+)?class\s+(\w+)|^\s*(?:export\s+)?interface\s+(\w+)", re.M),
    ".go": re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)|^\s*type\s+(\w+)\s", re.M),
    ".rs": re.compile(r"^\s*(?:pub\s+)?fn\s+(\w+)|^\s*(?:pub\s+)?struct\s+(\w+)|^\s*(?:pub\s+)?trait\s+(\w+)", re.M),
    ".java": re.compile(r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:class|interface)\s+(\w+)", re.M),
    ".rb": re.compile(r"^\s*def\s+(\w+)|^\s*class\s+(\w+)", re.M),
}
_REGEX_LANGS[".jsx"] = _REGEX_LANGS[".js"]
_REGEX_LANGS[".tsx"] = _REGEX_LANGS[".ts"]


def _py_symbols(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(f"{node.name}()")
        elif isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            out.append(f"class {node.name}({', '.join(methods[:12])})" if methods else f"class {node.name}")
    return out


def _regex_symbols(text: str, pattern: re.Pattern) -> list[str]:
    names: list[str] = []
    for m in pattern.finditer(text):
        name = next((g for g in m.groups() if g), None)
        if name:
            names.append(name)
    return names


async def repo_map(hc: HarnessContext, path: str | None = None, max_files: int = 200) -> str:
    base = hc.resolve_read(path) if path else hc.require_workspace()
    if not base.is_dir():
        base = base.parent

    exts = {".py"} | set(_REGEX_LANGS)
    files = [
        p for p in sorted(base.rglob("*"))
        if p.is_file() and p.suffix in exts and not _is_noise(p, base)
    ]
    shown = files[:max_files]
    lines: list[str] = [f"# Repo map ({len(files)} source files, showing {len(shown)})"]
    for f in shown:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        syms = _py_symbols(text) if f.suffix == ".py" else _regex_symbols(text, _REGEX_LANGS[f.suffix])
        rel = f.relative_to(base)
        if syms:
            lines.append(f"{rel}: " + ", ".join(syms[:20]) + (" …" if len(syms) > 20 else ""))
        else:
            lines.append(f"{rel}")
    if len(files) > max_files:
        lines.append(f"... and {len(files) - max_files} more files")
    return "\n".join(lines)
