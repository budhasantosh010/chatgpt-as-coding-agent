"""Code-intelligence tools over the LSP client (checklist Phase 5).

lsp_definition / lsp_references / lsp_hover / lsp_symbols. Each resolves the path
inside the workspace roots (same gate as read_file), asks the language server,
and formats the answer as compact text ChatGPT can act on. If no server is
installed for the language, returns an actionable install hint (never an error).
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..context import HarnessContext
from ..lsp import install_hint, lang_for


def _rel(hc: HarnessContext, uri_or_path: str) -> str:
    """A workspace-relative path for display, from an LSP file:// uri."""
    if uri_or_path.startswith("file:"):
        p = Path(unquote(urlparse(uri_or_path).path))
        if os.name == "nt" and p.as_posix().startswith("/") and len(p.as_posix()) > 2 and p.as_posix()[2] == ":":
            p = Path(p.as_posix()[1:])
    else:
        p = Path(uri_or_path)
    ws = hc.active_workspace
    try:
        return str(p.relative_to(ws)) if ws else str(p)
    except ValueError:
        return str(p)


def _loc_line(hc: HarnessContext, loc: dict) -> str:
    uri = loc.get("uri") or loc.get("targetUri", "")
    rng = loc.get("range") or loc.get("targetSelectionRange") or {}
    start = rng.get("start", {})
    line = start.get("line", 0) + 1
    return f"{_rel(hc, uri)}:{line}"


async def _server(hc: HarnessContext, path: str):
    real = hc.resolve_read(path)
    language = lang_for(str(real))
    if language is None:
        return None, real, f"No language support for {Path(real).suffix} files."
    mgr = getattr(hc, "lsp", None)
    if mgr is None:
        return None, real, "LSP is not available in this context."
    root = hc.active_workspace or real.parent
    srv = mgr.get(Path(root), language)
    if srv is None:
        return None, real, (
            f"No {language} language server installed. Install one to enable "
            f"code intelligence:\n    {install_hint(language)}"
        )
    return srv, real, None


async def lsp_definition(hc: HarnessContext, path: str, line: int, character: int = 0) -> str:
    srv, real, err = await _server(hc, path)
    if err:
        return err
    resp = srv.definition(real, line, character)
    if not resp or resp.get("result") in (None, []):
        return f"No definition found at {path}:{line}:{character}."
    result = resp["result"]
    locs = result if isinstance(result, list) else [result]
    lines = [f"Definition(s) for symbol at {path}:{line}:{character}:"]
    lines += [f"  → {_loc_line(hc, l)}" for l in locs]
    return "\n".join(lines)


async def lsp_references(hc: HarnessContext, path: str, line: int, character: int = 0) -> str:
    srv, real, err = await _server(hc, path)
    if err:
        return err
    resp = srv.references(real, line, character)
    if not resp or not resp.get("result"):
        return f"No references found at {path}:{line}:{character}."
    locs = resp["result"]
    lines = [f"{len(locs)} reference(s) to symbol at {path}:{line}:{character}:"]
    lines += [f"  {_loc_line(hc, l)}" for l in locs[:200]]
    if len(locs) > 200:
        lines.append(f"  … and {len(locs) - 200} more")
    return "\n".join(lines)


async def lsp_hover(hc: HarnessContext, path: str, line: int, character: int = 0) -> str:
    srv, real, err = await _server(hc, path)
    if err:
        return err
    resp = srv.hover(real, line, character)
    if not resp or not resp.get("result"):
        return f"No hover info at {path}:{line}:{character}."
    contents = resp["result"].get("contents")
    text = _hover_text(contents)
    return text or f"No hover info at {path}:{line}:{character}."


def _hover_text(contents) -> str:
    if contents is None:
        return ""
    if isinstance(contents, str):
        return contents
    if isinstance(contents, dict):
        return contents.get("value", "")
    if isinstance(contents, list):
        return "\n".join(_hover_text(c) for c in contents if c)
    return str(contents)


_SYMBOL_KINDS = {
    1: "file", 2: "module", 3: "namespace", 4: "package", 5: "class",
    6: "method", 7: "property", 8: "field", 9: "constructor", 10: "enum",
    11: "interface", 12: "function", 13: "variable", 14: "constant",
    23: "struct", 26: "typeParameter",
}


async def lsp_symbols(hc: HarnessContext, path: str) -> str:
    srv, real, err = await _server(hc, path)
    if err:
        return err
    resp = srv.symbols(real)
    if not resp or not resp.get("result"):
        return f"No symbols found in {path}."
    out: list[str] = [f"Symbols in {path}:"]

    def walk(items, depth=0):
        for s in items:
            kind = _SYMBOL_KINDS.get(s.get("kind"), "?")
            rng = s.get("selectionRange") or s.get("range") or {}
            ln = rng.get("start", {}).get("line", 0) + 1
            out.append(f"  {'  ' * depth}{kind} {s.get('name', '')}  :{ln}")
            if s.get("children"):
                walk(s["children"], depth + 1)

    walk(resp["result"])
    return "\n".join(out)
