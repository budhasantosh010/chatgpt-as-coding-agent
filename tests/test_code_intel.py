"""Phase 2 coding-quality tools: repo_map, apply_patch, diagnostics."""

from __future__ import annotations

import asyncio
import shutil

import pytest

from harness.config import Config
from harness.context import HarnessServer
from harness.security import SecurityError
from harness.tools import diagnostics, files, repomap


def run(c):
    return asyncio.run(c)


def _hc(tmp_path):
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "s", secret_route="r")
    server = HarnessServer(cfg)
    hc = server.session_for("s")
    ws = tmp_path / "proj"; ws.mkdir()
    hc.set_workspace(str(ws))
    return hc, ws


def test_repo_map_python_symbols(tmp_path):
    hc, ws = _hc(tmp_path)
    (ws / "mod.py").write_text(
        "def top():\n    pass\n\nclass Foo:\n    def bar(self):\n        pass\n"
        "    def baz(self):\n        pass\n",
        encoding="utf-8",
    )
    out = run(repomap.repo_map(hc))
    assert "mod.py" in out
    assert "top()" in out
    assert "class Foo(bar, baz)" in out


def test_repo_map_js_symbols(tmp_path):
    hc, ws = _hc(tmp_path)
    (ws / "a.js").write_text("export function hello(){}\nclass Widget {}\n", encoding="utf-8")
    out = run(repomap.repo_map(hc))
    assert "hello" in out and "Widget" in out


def test_apply_patch_edits_file(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    hc, ws = _hc(tmp_path)
    (ws / "f.txt").write_text("line1\nline2\n", encoding="utf-8")
    patch = (
        "--- a/f.txt\n"
        "+++ b/f.txt\n"
        "@@ -1,2 +1,2 @@\n"
        " line1\n"
        "-line2\n"
        "+line2-edited\n"
    )
    out = run(files.apply_patch(hc, patch))
    assert "Applied patch" in out
    assert (ws / "f.txt").read_text(encoding="utf-8") == "line1\nline2-edited\n"


def test_apply_patch_rejects_escape(tmp_path):
    hc, ws = _hc(tmp_path)
    patch = "--- a/x\n+++ b/../../etc/evil\n@@ -0,0 +1 @@\n+evil\n"
    with pytest.raises(SecurityError):
        run(files.apply_patch(hc, patch))


def test_diagnostics_no_tool_is_graceful(tmp_path):
    hc, ws = _hc(tmp_path)
    (ws / "note.txt").write_text("hi", encoding="utf-8")  # no project markers
    out = run(diagnostics.diagnostics(hc))
    assert "No diagnostics tool" in out or "diagnostics" in out
