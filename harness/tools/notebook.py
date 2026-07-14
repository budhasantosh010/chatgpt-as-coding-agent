"""Jupyter notebook (.ipynb) reading + cell editing.

Notebooks are JSON; a plain read/edit would fight the format. These tools show
cells with indices and edit/insert/delete a single cell while keeping the file
valid. Path-gated like every file tool.
"""

from __future__ import annotations

import json

from ..context import HarnessContext


def _load(real) -> dict:
    try:
        nb = json.loads(real.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"Not a valid notebook (JSON): {exc}") from exc
    if "cells" not in nb:
        raise ValueError("Not a notebook: no 'cells'.")
    return nb


def _src(cell) -> str:
    s = cell.get("source", "")
    return "".join(s) if isinstance(s, list) else str(s)


async def notebook_read(hc: HarnessContext, path: str) -> str:
    real = hc.resolve_read(path)
    if not real.exists():
        raise FileNotFoundError(f"Notebook not found: {real}")
    nb = _load(real)
    lines = [f"# {real.name} — {len(nb['cells'])} cells"]
    for i, cell in enumerate(nb["cells"]):
        ctype = cell.get("cell_type", "?")
        body = _src(cell)
        preview = body if len(body) <= 800 else body[:800] + "\n[... truncated]"
        lines += [f"\n## [{i}] {ctype}", "```", preview, "```"]
    hc.log("notebook_read", path=str(real), cells=len(nb["cells"]))
    return "\n".join(lines)


async def notebook_edit(
    hc: HarnessContext,
    path: str,
    cell_index: int,
    source: str = "",
    mode: str = "replace",
    cell_type: str = "code",
) -> str:
    """mode: 'replace' (set cell source), 'insert' (new cell before index),
    'delete' (remove cell)."""
    real = hc.resolve_write(path)
    if not real.exists():
        raise FileNotFoundError(f"Notebook not found: {real}")
    nb = _load(real)
    cells = nb["cells"]

    if mode == "delete":
        if not (0 <= cell_index < len(cells)):
            raise ValueError(f"cell_index {cell_index} out of range (0..{len(cells) - 1}).")
        cells.pop(cell_index)
        action = f"deleted cell {cell_index}"
    elif mode == "insert":
        new_cell = {"cell_type": cell_type, "metadata": {}, "source": source.splitlines(keepends=True)}
        if cell_type == "code":
            new_cell["outputs"] = []
            new_cell["execution_count"] = None
        idx = max(0, min(cell_index, len(cells)))
        cells.insert(idx, new_cell)
        action = f"inserted {cell_type} cell at {idx}"
    elif mode == "replace":
        if not (0 <= cell_index < len(cells)):
            raise ValueError(f"cell_index {cell_index} out of range (0..{len(cells) - 1}).")
        cells[cell_index]["source"] = source.splitlines(keepends=True)
        if cells[cell_index].get("cell_type") == "code":
            cells[cell_index]["outputs"] = []
            cells[cell_index]["execution_count"] = None
        action = f"replaced cell {cell_index}"
    else:
        raise ValueError("mode must be 'replace', 'insert', or 'delete'.")

    real.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    hc.log("notebook_edit", path=str(real), mode=mode, index=cell_index)
    return f"Notebook {real.name}: {action}. Now {len(cells)} cells."
