"""Cockpit HTTP API: CSRF, projects/sessions, mode, approvals, diff, SSE, uploads.

Uses Starlette's TestClient (real ASGI request path) against a Cockpit backed by
a temp state dir. No engine child is spawned (supervisor=None).
"""

from __future__ import annotations

import base64

import pytest
from starlette.testclient import TestClient

from harness.config import Config
from harness.cockpit.server import Cockpit, build_cockpit_app

COCKPIT_ORIGIN = "http://127.0.0.1:8849"


@pytest.fixture()
def client(tmp_path):
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state",
                 secret_route="x", cockpit_port=8849)
    cp = Cockpit(cfg)
    app = build_cockpit_app(cp)
    with TestClient(app) as c:
        yield c, cp, tmp_path
    cp.server.tasks.close()


def _hdr(cp, origin=COCKPIT_ORIGIN):
    return {"X-Cockpit-Token": cp.csrf_token, "Origin": origin}


# ---- CSRF / origin ----------------------------------------------------------

def test_mutation_without_token_is_forbidden(client):
    c, cp, tmp = client
    r = c.post("/api/task/new", json={"goal": "x"}, headers={"Origin": COCKPIT_ORIGIN})
    assert r.status_code == 403


def test_mutation_with_foreign_origin_is_forbidden(client):
    c, cp, tmp = client
    r = c.post("/api/task/new", json={"goal": "x"},
               headers={"X-Cockpit-Token": cp.csrf_token, "Origin": "https://evil.com"})
    assert r.status_code == 403


def test_index_serves_and_injects_token(client):
    c, cp, tmp = client
    r = c.get("/")
    assert r.status_code == 200
    assert cp.csrf_token in r.text  # injected for same-origin JS


# ---- projects + sessions ----------------------------------------------------

def test_create_project_then_new_session_then_setmode(client):
    c, cp, tmp = client
    proj = tmp / "myproj"
    r = c.post("/api/project/create", json={"path": str(proj), "name": "My Proj"},
               headers=_hdr(cp))
    assert r.status_code == 200 and "Project created" in r.json()["message"]

    # state reflects the new project
    st = c.get("/api/state", headers={"Origin": COCKPIT_ORIGIN}).json()
    assert any(p["name"] == "My Proj" for p in st["projects"])

    # new session (task) under it
    r = c.post("/api/task/new",
               json={"project_path": str(proj), "goal": "build it", "mode": "auto_workspace"},
               headers=_hdr(cp))
    assert r.status_code == 200
    tid = r.json()["task_id"]

    # change its mode
    r = c.post("/api/task/mode", json={"task_id": tid, "mode": "plan"}, headers=_hdr(cp))
    assert r.status_code == 200 and r.json()["task"]["mode"] == "plan"


def test_fork_from_cockpit(client):
    c, cp, tmp = client
    proj = tmp / "p"
    c.post("/api/project/create", json={"path": str(proj)}, headers=_hdr(cp))
    tid = c.post("/api/task/new", json={"project_path": str(proj), "goal": "g"},
                 headers=_hdr(cp)).json()["task_id"]
    r = c.post("/api/task/fork", json={"task_id": tid}, headers=_hdr(cp))
    assert r.status_code == 200 and "Forked" in r.json()["message"]


# ---- approvals --------------------------------------------------------------

def test_approvals_flow(client):
    c, cp, tmp = client
    proj = tmp / "p"
    c.post("/api/project/create", json={"path": str(proj)}, headers=_hdr(cp))
    tid = c.post("/api/task/new", json={"project_path": str(proj), "goal": "g"},
                 headers=_hdr(cp)).json()["task_id"]
    # Manufacture a pending approval via the store (as the gate would).
    aid = cp.store.add_approval(tid, "command_arbitrary", "run_command: weird-tool", "h1")
    lst = c.get("/api/approvals", headers={"Origin": COCKPIT_ORIGIN}).json()
    assert any(a["id"] == aid for a in lst["approvals"])
    r = c.post("/api/approval/decide", json={"id": aid, "decision": "approve"}, headers=_hdr(cp))
    assert r.status_code == 200 and r.json()["ok"]
    assert cp.store.get_approval(aid)["status"] == "approved"


def test_approve_remember_persists_command(client):
    c, cp, tmp = client
    from harness import allowlist

    proj = tmp / "p"; proj.mkdir()
    tid = c.post("/api/task/new", json={"project_path": str(proj), "goal": "g"},
                 headers=_hdr(cp)).json()["task_id"]
    aid = cp.store.add_approval(tid, "command_arbitrary", "run_command: mytool --x", "h2")
    c.post("/api/approval/decide",
           json={"id": aid, "decision": "approve", "remember": True}, headers=_hdr(cp))
    assert allowlist.is_allowed(cp.config.state_dir, [proj], "mytool --x")


# ---- file upload (drag-drop) ------------------------------------------------

def test_upload_file_into_session(client):
    c, cp, tmp = client
    proj = tmp / "p"; proj.mkdir()
    tid = c.post("/api/task/new", json={"project_path": str(proj), "goal": "g"},
                 headers=_hdr(cp)).json()["task_id"]
    b64 = base64.b64encode(b"hello world").decode()
    r = c.post("/api/task/upload", json={"task_id": tid, "name": "notes.txt", "b64": b64},
               headers=_hdr(cp))
    assert r.status_code == 200
    dest = proj / "notes.txt"
    assert dest.exists() and dest.read_bytes() == b"hello world"


def test_upload_path_traversal_blocked(client):
    c, cp, tmp = client
    proj = tmp / "p"; proj.mkdir()
    tid = c.post("/api/task/new", json={"project_path": str(proj), "goal": "g"},
                 headers=_hdr(cp)).json()["task_id"]
    b64 = base64.b64encode(b"x").decode()
    # name is basenamed, so a traversal name lands flat in the folder, never escapes
    r = c.post("/api/task/upload",
               json={"task_id": tid, "name": "../../escape.txt", "b64": b64}, headers=_hdr(cp))
    assert r.status_code == 200
    assert not (tmp.parent / "escape.txt").exists()
    assert (proj / "escape.txt").exists()


# ---- SSE feed ---------------------------------------------------------------

def _drive_sse(app, cp, origin=COCKPIT_ORIGIN, max_chunks=3):
    """Drive the /events ASGI route directly: send the request, collect a few
    body chunks, then send http.disconnect so the generator exits cleanly.
    Avoids TestClient's infinite-stream teardown hang."""
    import anyio

    async def run():
        scope = {
            "type": "http", "method": "GET", "path": "/events",
            "headers": [(b"origin", origin.encode())],
            "query_string": b"",
        }
        sent = []
        disconnected = {"v": False}

        async def receive():
            if not disconnected["v"]:
                disconnected["v"] = True
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.disconnect"}

        async def send(msg):
            sent.append(msg)

        async def caller():
            with anyio.move_on_after(3):
                await app(scope, receive, send)

        await caller()
        return sent

    return anyio.run(run)


def test_sse_streams_events(client):
    c, cp, tmp = client
    app = build_cockpit_app(cp)
    cp.events.publish("tool_call", task_id="T-1", tool="read_file", detail="a.py")
    sent = _drive_sse(app, cp)
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 200
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert b"read_file" in body


def test_sse_foreign_origin_forbidden(client):
    c, cp, tmp = client
    r = c.get("/events", headers={"Origin": "https://evil.com"})
    assert r.status_code == 403


# ---- ingest (engine -> cockpit push) ----------------------------------------

def test_ingest_requires_token_and_republishes(client):
    c, cp, tmp = client
    bad = c.post("/_ingest", json={"type": "tool_call", "data": {"tool": "x"}})
    assert bad.status_code == 403
    before = len(cp.events.since(0))
    ok = c.post("/_ingest", json={"type": "tool_call", "task_id": "T-9", "data": {"tool": "grep"}},
                headers={"X-Harness-Event-Token": cp.ingest_token})
    assert ok.status_code == 200
    assert len(cp.events.since(0)) == before + 1
