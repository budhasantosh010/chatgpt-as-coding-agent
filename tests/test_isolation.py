"""The session-isolation gap, pinned as a test.

Over the real stateless HTTP transport the MCP SDK issues no session id, so
_session_key() returns 'default' for every conversation and they share one
workspace. This asserts the isolation we WANT; it fails today and is marked
xfail(strict), so when Phase 1's explicit task_id makes it pass, strict xfail
flips to a failure and reminds us to delete the marker.
"""

from __future__ import annotations

import pytest

from harness.config import Config
from harness.context import HarnessServer
from harness.server import _session_key


@pytest.mark.xfail(reason="shared-default isolation; fixed by task_id in Phase 1", strict=True)
def test_two_transport_conversations_are_isolated(tmp_path):
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "s", secret_route="r")
    server = HarnessServer(cfg)
    ws_a = tmp_path / "A"; ws_a.mkdir()
    ws_b = tmp_path / "B"; ws_b.mkdir()

    # Two ChatGPT conversations; the stateless transport gives both no session
    # header, so _session_key(None) == 'default' for each.
    convo1 = server.session_for(_session_key(None))
    convo1.set_workspace(str(ws_a))
    convo2 = server.session_for(_session_key(None))
    convo2.set_workspace(str(ws_b))

    # If the two conversations were isolated, convo1 would still see A.
    assert convo1.active_workspace == ws_a
