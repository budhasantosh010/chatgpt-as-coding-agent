"""Did the connector ever re-read our tool list?

Access logging is deliberately off (the secret route must never reach a log),
which left one question unanswerable: when ChatGPT shows a stale set of tools,
is it re-fetching and filtering, or serving a cached menu that nothing on this
machine can reach? connector.jsonl records the JSON-RPC method of each request
so that question has an answer instead of a theory.
"""

from __future__ import annotations

import json

from starlette.testclient import TestClient

from harness.app import build_asgi_app
from harness.config import Config


def _client(tmp_path, **overrides):
    cfg = Config(
        workspace_roots=[tmp_path], state_dir=tmp_path / "state",
        secret_route="secret", allowed_hosts=["testserver"], **overrides,
    )
    return cfg, build_asgi_app(cfg)


def _rows(cfg):
    path = cfg.state_dir / "connector.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_tools_list_request_is_recorded_with_its_agent(tmp_path):
    cfg, (app, server) = _client(tmp_path)
    try:
        with TestClient(app) as client:
            client.post(
                "/secret/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                headers={"Accept": "application/json, text/event-stream",
                         "User-Agent": "OpenAI-Probe/1.0"},
            )
        rows = [row for row in _rows(cfg) if row["method"] == "tools/list"]
        assert rows, "a tools/list fetch left no trace"
        # The agent is how an OpenAI fetch is told apart from our own probes.
        assert rows[0]["agent"] == "OpenAI-Probe/1.0"
    finally:
        server.tasks.close()


def test_logging_does_not_consume_the_request_body(tmp_path):
    """The middleware reads the body to find the method, so the real handler
    must still receive it intact — a diagnostic that eats requests is worse
    than no diagnostic."""
    cfg, (app, server) = _client(tmp_path)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/secret/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "probe", "version": "1"}}},
                headers={"Accept": "application/json, text/event-stream"},
            )
        assert response.status_code == 200
        assert response.json()["result"]["serverInfo"]["name"]
    finally:
        server.tasks.close()


def test_rejected_requests_are_not_logged(tmp_path):
    """Anything the security gate turns away never reaches the logger, so a
    scanner cannot grow the file (or learn that the route exists)."""
    cfg, (app, server) = _client(tmp_path)
    try:
        with TestClient(app) as client:
            client.post("/wrong-route/mcp", json={"jsonrpc": "2.0", "method": "tools/list"})
        assert _rows(cfg) == []
    finally:
        server.tasks.close()


def test_logging_can_be_switched_off(tmp_path):
    cfg, (app, server) = _client(tmp_path, connector_log=False)
    try:
        with TestClient(app) as client:
            client.post(
                "/secret/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                headers={"Accept": "application/json, text/event-stream"},
            )
        assert _rows(cfg) == []
    finally:
        server.tasks.close()
