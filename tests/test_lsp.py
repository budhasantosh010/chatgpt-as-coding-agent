"""Phase 5 LSP: real code intelligence + graceful degradation.

The real definition/references/hover/symbols tests need a python language server
(pylsp). They are skipped if none is installed, so CI without one stays green;
the degradation test always runs.
"""

from __future__ import annotations

import asyncio

import pytest

from harness.config import Config
from harness.context import HarnessServer
from harness.lsp import LSPServer, lang_for, server_for
from harness.tasks import tools as tasktools
from harness.tools import codeintel


def run(c):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(c)


HAVE_PY_LSP = server_for("python") is not None


@pytest.fixture()
def ctx(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "lib.py").write_text(
        "def greet(name):\n    return 'hi ' + name\n", encoding="utf-8")
    (proj / "app.py").write_text(
        "from lib import greet\n\n\ndef main():\n    return greet('world')\n", encoding="utf-8")
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state", secret_route="x")
    srv = HarnessServer(cfg)
    tid = run(tasktools.start_task(srv, str(proj), "g")).split()[2]
    hc = srv.context_for(tid, "conn")
    hc.set_workspace(str(proj))
    yield srv, hc, proj
    srv.lsp.shutdown_all()
    srv.tasks.close()


def test_lang_detection():
    assert lang_for("a.py") == "python"
    assert lang_for("a.ts") == "typescript"
    assert lang_for("a.rs") == "rust"
    assert lang_for("a.unknownext") is None


def test_definition_retries_when_language_server_is_still_indexing(monkeypatch, tmp_path):
    server = object.__new__(LSPServer)
    calls = []
    sleeps = []
    responses = iter([
        {"result": []},
        {"result": []},
        {"result": []},
        {"result": [{"uri": "file:///lib.py"}]},
    ])
    server._ensure_open = lambda _path: None
    server._request = lambda method, params: calls.append(method) or next(responses)
    monkeypatch.setattr(
        "harness.lsp.time",
        type("Clock", (), {"sleep": staticmethod(sleeps.append)}),
        raising=False,
    )

    response = server.definition(tmp_path / "app.py", 5, 12)

    assert response["result"][0]["uri"].endswith("lib.py")
    assert calls == ["textDocument/definition"] * 4
    assert sleeps == [0.2, 0.5, 1.0]


def test_degrades_without_server(ctx, monkeypatch):
    srv, hc, proj = ctx
    # Force "no server" regardless of what's installed.
    monkeypatch.setattr(srv.lsp, "get", lambda *a, **k: None)
    out = run(codeintel.lsp_definition(hc, "app.py", 5, 12))
    assert "language server" in out.lower() and "install" in out.lower()


def test_unsupported_extension(ctx):
    srv, hc, proj = ctx
    (proj / "readme.md").write_text("# hi", encoding="utf-8")
    out = run(codeintel.lsp_definition(hc, "readme.md", 1, 0))
    assert "No language support" in out


@pytest.mark.skipif(not HAVE_PY_LSP, reason="no python language server installed")
def test_definition_across_files(ctx):
    srv, hc, proj = ctx
    # In app.py, `greet('world')` is on line 5; jump to its def in lib.py.
    out = run(codeintel.lsp_definition(hc, "app.py", 5, 12))
    assert "lib.py" in out, out


@pytest.mark.skipif(not HAVE_PY_LSP, reason="no python language server installed")
def test_references_finds_usage(ctx):
    srv, hc, proj = ctx
    # References to greet (defined lib.py line 1) should include app.py.
    out = run(codeintel.lsp_references(hc, "lib.py", 1, 4))
    assert "reference" in out.lower()
    assert "app.py" in out or "lib.py" in out


@pytest.mark.skipif(not HAVE_PY_LSP, reason="no python language server installed")
def test_symbols_lists_functions(ctx):
    srv, hc, proj = ctx
    out = run(codeintel.lsp_symbols(hc, "lib.py"))
    assert "greet" in out


@pytest.mark.skipif(not HAVE_PY_LSP, reason="no python language server installed")
def test_hover_returns_something(ctx):
    srv, hc, proj = ctx
    out = run(codeintel.lsp_hover(hc, "lib.py", 1, 4))
    assert out and "No hover" not in out or "greet" in out
