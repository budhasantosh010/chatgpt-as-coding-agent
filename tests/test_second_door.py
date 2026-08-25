"""The second public door: ngrok alongside the Tailscale Funnel.

Two roads, one engine. Adding ngrok must not weaken or disturb the funnel, and
— the reason this file exists — must not be reachable by anyone else who happens
to own a subdomain on the same shared ngrok suffix.

The failure this guards hardest is the boring one: an operator names their
tunnel and silently loses access to their own machine, because
HARNESS_ALLOWED_HOSTS *replaces* the default list rather than extending it. A
403 from that is indistinguishable from a dead tunnel, so it is worth a test
rather than a paragraph in a manual.
"""

from __future__ import annotations

import json

from starlette.testclient import TestClient

from harness.app import build_asgi_app
from harness.config import Config

NGROK = "lyolytic-floria-indiscernible.ngrok-free.dev"


def _reaches_harness(tmp_path, host: str, **overrides) -> bool:
    """Did a request claiming this Host get past the Host gate?

    A fresh app per probe: the MCP session manager refuses a second lifespan on
    one instance, so a shared app silently limits every test to one request.
    """
    cfg = Config(
        workspace_roots=[tmp_path], state_dir=tmp_path / "state",
        secret_route="secret", **overrides,
    )
    app, server = build_asgi_app(cfg)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/secret/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "t", "version": "1"}}},
                headers={"Host": host, "Accept": "application/json, text/event-stream"},
            )
    finally:
        server.tasks.close()
    if response.status_code != 403:
        return True
    return json.loads(response.text).get("error") != "host not allowed"


def test_the_reserved_ngrok_domain_is_accepted_once_configured(tmp_path):
    assert _reaches_harness(tmp_path, NGROK, public_host=NGROK)


def test_an_ngrok_host_is_refused_when_no_second_door_is_configured(tmp_path):
    """Default deployments must not accept ngrok traffic just because the
    hostname looks like ngrok."""
    assert not _reaches_harness(tmp_path, NGROK)


def test_a_neighbours_subdomain_on_the_same_suffix_is_refused(tmp_path):
    """*.ngrok-free.dev is shared with every other ngrok tenant. Matching the
    suffix — the way *.ts.net is matched — would trust strangers, so the second
    door is exact-match only."""
    assert not _reaches_harness(tmp_path, "someone-elses-name.ngrok-free.dev",
                                public_host=NGROK)


def test_loopback_survives_an_allowed_hosts_override(tmp_path):
    """The footgun: HARNESS_ALLOWED_HOSTS replaces the defaults. An operator who
    lists only their tunnel there must not lose their own Workbench."""
    assert _reaches_harness(tmp_path, "127.0.0.1", allowed_hosts=[NGROK])
    assert _reaches_harness(tmp_path, "localhost", allowed_hosts=[NGROK])


def test_the_funnel_still_works_with_the_second_door_open(tmp_path):
    """Adding ngrok must not disturb Tailscale — the user's working path."""
    assert _reaches_harness(tmp_path, "desktop-abc.tail1234.ts.net", public_host=NGROK)


def test_public_url_is_the_connector_url_or_nothing(tmp_path):
    with_door = Config(state_dir=tmp_path, secret_route="secret", public_host=NGROK)
    assert with_door.public_url() == f"https://{NGROK}/secret/mcp"
    without = Config(state_dir=tmp_path, secret_route="secret")
    assert without.public_url() == ""


def test_a_pasted_url_is_reduced_to_a_bare_hostname(monkeypatch, tmp_path):
    """The Host header carries no scheme, path or (post-parse) port, so a
    pasted "https://x/" would never match and would 403 like a broken tunnel."""
    monkeypatch.setenv("HARNESS_PUBLIC_HOST", f"  HTTPS://{NGROK.upper()}:443/mcp  ")
    monkeypatch.setenv("HARNESS_STATE_DIR", str(tmp_path))
    assert Config.from_env(load_dotenv=False).public_host == NGROK
