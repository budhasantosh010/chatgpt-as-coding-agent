from __future__ import annotations

import pytest

from harness.config import Config
from harness.context import HarnessContext


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    return ws


@pytest.fixture
def config(tmp_path):
    return Config(
        workspace_roots=[tmp_path],
        state_dir=tmp_path / "state",
        secret_route="test-secret-route",
        mode="full",
    )


@pytest.fixture
def hc(config, workspace):
    ctx = HarnessContext(config)
    ctx.set_workspace(str(workspace))
    return ctx
