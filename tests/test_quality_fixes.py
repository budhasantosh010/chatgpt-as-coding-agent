"""Q-series audit fixes: auto-checkpoint scope, stale guards on notebook/patch,
classifier tightening + the arbitrary-commands knob, and docker diagnostics."""

from __future__ import annotations

import asyncio

import pytest

from harness.config import Config
from harness.context import HarnessServer
from harness.permissions import Action, classify_command, decide
from harness.policy import Capability, Decision
from harness.server import _call
from harness.tasks import tools as tasktools
from harness.tools import files, git, notebook


def run(c):
    return asyncio.run(c)


@pytest.fixture
def taskctx(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state",
                 secret_route="x")
    srv = HarnessServer(cfg)
    tid = run(tasktools.start_task(srv, str(ws), goal="g",
                                   permission_mode="auto_workspace",
                                   isolation="workspace")).split()[2]
    hc = srv.context_for(tid, "conn")
    yield srv, tid, hc, ws
    srv.tasks.close()


# ---- Q2: classifier tightening + knob -----------------------------------------

def test_git_dash_c_push_classified_remote():
    assert classify_command("git -C . push origin main") is Action.GIT_REMOTE_WRITE
    assert classify_command("git --no-pager push") is Action.GIT_REMOTE_WRITE


def test_powershell_download_classified_network():
    assert classify_command("Invoke-WebRequest https://x/y -OutFile z") is Action.NETWORK
    assert classify_command("iwr https://x") is Action.NETWORK
    assert classify_command("certutil -urlcache -f http://x a.exe") is Action.NETWORK


def test_python_urlopen_classified_network():
    assert classify_command('python -c "import urllib.request; urllib.request.urlopen(1)"') is Action.NETWORK


def test_arbitrary_commands_knob():
    # Default: unrecognized commands auto-run in auto_workspace.
    assert decide("auto_workspace", Action.COMMAND_ARBITRARY, "allow") is Decision.ALLOW
    # ask: fail closed on anything the classifier didn't recognize.
    assert decide("auto_workspace", Action.COMMAND_ARBITRARY, "ask") is Decision.ASK
    # A recognized-safe file write is unaffected by the knob.
    assert decide("auto_workspace", Action.FILE_WRITE, "ask") is Decision.ALLOW


def test_known_bypasses_are_pinned():
    """HONESTY pin: a regex classifier cannot catch everything. These currently
    fall through to COMMAND_ARBITRARY — documented, not silently 'safe'. When a
    pattern is added, flip the expected value here deliberately."""
    still_arbitrary = [
        'bash -c "echo $(printf pu)$(printf sh)"',   # obfuscated
        'env python3 - <<EOF\nimport socket\nEOF',    # heredoc stdin
    ]
    for cmd in still_arbitrary:
        assert classify_command(cmd) is Action.COMMAND_ARBITRARY


# ---- Q3: auto-checkpoint fires on EXECUTE too ---------------------------------

def test_autocheckpoint_fires_for_execute(taskctx):
    srv, tid, hc, ws = taskctx
    from harness.tools import shell

    run(git._git(hc, ws, "init"))
    (ws / "a.txt").write_text("v1\n", encoding="utf-8")
    run(git._git(hc, ws, "add", "-A"))
    run(git._git(hc, ws, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init"))

    run(_call(hc, Capability.EXECUTE, shell.run_command, "echo mutate", None, 30))
    after = run(_call(hc, Capability.READ, git.list_checkpoints))
    assert "auto (pre-edit)" in after


def test_autocheckpoint_failure_is_recorded_not_silent(tmp_path):
    from harness.hooks import ToolCall, make_autocheckpoint_hook

    hook = make_autocheckpoint_hook(min_interval=0.0)

    class FakeHC:
        active_workspace = tmp_path  # not a git repo → checkpoint fails
        def log(self, *a, **k):
            pass

    call = ToolCall(tool="write_file", capability=Capability.WRITE,
                    session_key="s", context=FakeHC())
    run(hook(call))
    assert "autocheckpoint_failed" in call.meta


# ---- Q4: stale guards on notebook_edit + apply_patch --------------------------

def _make_nb(path):
    import json
    path.write_text(json.dumps({
        "cells": [{"cell_type": "code", "source": ["x = 1\n"], "metadata": {},
                   "outputs": [], "execution_count": None}],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
    }), encoding="utf-8")


def test_notebook_read_surfaces_sha_and_edit_rejects_stale(taskctx):
    srv, tid, hc, ws = taskctx
    nb = ws / "n.ipynb"
    _make_nb(nb)
    out = run(notebook.notebook_read(hc, "n.ipynb"))
    assert "sha256:" in out
    # A wrong sha is rejected.
    with pytest.raises(ValueError, match="Stale"):
        run(notebook.notebook_edit(hc, "n.ipynb", 0, "x = 2\n", "replace", "code",
                                   expected_sha="deadbeef0000"))
    # The correct sha succeeds.
    sha = out.split("sha256:")[1].split("]")[0]
    ok = run(notebook.notebook_edit(hc, "n.ipynb", 0, "x = 2\n", "replace", "code",
                                    expected_sha=sha))
    assert "replaced" in ok


def test_apply_patch_rejects_stale_expected_sha(taskctx):
    srv, tid, hc, ws = taskctx
    (ws / "f.txt").write_text("line1\n", encoding="utf-8")
    patch = (
        "--- a/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n-line1\n+line2\n"
    )
    with pytest.raises(ValueError, match="Stale"):
        run(files.apply_patch(hc, patch, expected_shas={"f.txt": "deadbeef0000"}))
