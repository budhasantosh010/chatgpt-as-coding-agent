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


def test_index_sends_operator_surface_security_headers(client):
    c, cp, tmp = client
    r = c.get("/")
    assert r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_index_exposes_accessible_three_pane_workbench(client):
    c, cp, tmp = client

    r = c.get("/")

    assert 'id="primarySidebar"' in r.text
    assert 'id="leftResizeHandle"' in r.text
    assert 'id="sessionTabs"' in r.text
    assert 'id="rightResizeHandle"' in r.text
    assert 'id="inspector"' in r.text
    assert r.text.count('role="separator"') == 2
    assert 'type="module" src="/static/app.mjs' in r.text


def test_new_session_dialog_exposes_all_four_locked_controls(client):
    c, cp, tmp = client
    html = c.get("/").text

    for control in ("ntEffort", "ntUltra", "ntFramework", "ntLoops", "ntTaskType"):
        assert f'id="{control}"' in html
    assert 'id="ntEstimate"' in html
    assert 'id="ntUltraCustom"' in html
    assert 'id="ntLoopsCustom"' in html
    assert "Confirm &amp; lock" in html
    ultra = html.split('id="ntUltra"', 1)[1].split("</fieldset>", 1)[0]
    assert ">Auto<" not in ultra


def test_contract_option_lists_cannot_drift_between_uis(client):
    """The New Session dialog and the attach-contract panel must render the
    same option numbers, sourced from contract-options.mjs alone (this guard
    exists because the two UIs really did drift once: ULTRA lost '2' and
    LOOPS showed 1/3/5)."""
    import json
    import re

    c, cp, tmp = client
    html = c.get("/").text
    options = c.get("/static/contract-options.mjs").text
    render = c.get("/static/render.mjs").text

    def mjs_list(name):
        return json.loads(re.search(rf"export const {name} = (\[[^\]]+\])", options).group(1))

    def radio_values(name):
        return re.findall(rf'name="{name}" value="([^"]+)"', html)

    assert radio_values("ntEffort") == mjs_list("EFFORT_LEVELS")
    assert radio_values("ntUltra") == mjs_list("ULTRA_OPTIONS")
    assert radio_values("ntLoops") == mjs_list("LOOPS_OPTIONS")
    assert radio_values("ntTaskType") == mjs_list("TASK_TYPES")
    assert mjs_list("ULTRA_OPTIONS") == ["0", "2", "3", "5", "8", "custom"]
    assert mjs_list("LOOPS_OPTIONS") == ["0", "2", "5", "10", "custom"]

    # The attach panel renders from the shared module — never its own numbers —
    # and must show the estimate and the permanent-lock warning before confirm.
    assert "contract-options.mjs" in render
    assert 'id="attachEstimate"' in render
    assert "locks this contract permanently" in render
    # Any literal digit inside an <option value="..."> means a hardcoded
    # number crept back in (templates interpolate with ${...} instead).
    assert not re.search(r'<option value="\d', render)


def test_motion_layer_versioned_served_and_reduced_motion_safe(client):
    """Category A motion handoff hard requirements: one cache-bust version
    across every static asset (a mismatch silently serves stale modules),
    cinematics gated behind prefers-reduced-motion, rAF loops that die with
    their DOM, and the animation layer observing (never owning) form state."""
    import re

    c, cp, tmp = client
    html = c.get("/").text
    app = c.get("/static/app.mjs").text
    render = c.get("/static/render.mjs").text
    motion = c.get("/static/contract-motion.mjs").text
    css = c.get("/static/cockpit.css").text

    versions = set(re.findall(r"\?v=(\d+)", html + app + render + motion))
    assert len(versions) == 1, f"cache-bust versions diverged: {versions}"

    assert "contract-motion.mjs" in app
    assert "prefers-reduced-motion" in motion
    assert "isConnected" in motion
    assert "prefers-reduced-motion:no-preference" in css
    # the animation layer must never decide outcomes: success/fail hooks only
    assert "playLaunch" in motion and "fail()" in motion


def test_renderer_skips_dom_rebuild_when_markup_unchanged(client):
    """Every store emit (5s poll, SSE events, loadTaskData) triggers render.
    Unconditional innerHTML assignment razed the workspace DOM each time,
    destroying keyboard focus and swallowing clicks that straddled a rebuild —
    the contract pills felt dead during engine activity. The renderer must
    memoize the last-set markup per container and skip identical strings."""
    import re

    c, cp, tmp = client
    render = c.get("/static/render.mjs").text
    assert "__renderedHTML" in render, "renderer lost its markup memoization"
    assignments = re.findall(r"\.innerHTML\s*=", render)
    assert len(assignments) == 1, (
        f"expected exactly one guarded innerHTML assignment (inside setHTML), found {len(assignments)}"
    )


def test_contract_estimate_reads_server_profiles_and_concurrency(client):
    c, cp, tmp = client
    cp.config.effort_profiles = {
        "low": 3, "medium": 9, "high": 18, "xhigh": 36, "max": 60,
    }
    cp.config.model_concurrency = 3

    html = c.get("/").text
    app = c.get("/static/app.mjs").text

    assert '"medium": 9' in html
    assert '"modelConcurrency": 3' in html
    assert "window.COCKPIT.effortProfiles" in app
    assert "window.COCKPIT.modelConcurrency" in app


def test_mode_update_retries_a_real_cross_process_conflict(client, monkeypatch):
    c, cp, tmp = client
    project = tmp / "race-project"
    project.mkdir()
    pid = cp.store.register_project(str(project), "Race")
    task = cp.store.create_task(pid, str(project), goal="race")

    from harness.tasks.store import TaskStore

    other = TaskStore(cp.store.path)
    original_get = cp.store.get_task
    injected = False

    def get_with_one_race(task_id):
        nonlocal injected
        current = original_get(task_id)
        if task_id == task.id and not injected:
            injected = True
            assert other.set_task_chat_url(task.id, "https://chatgpt.com/c/parallel")
        return current

    monkeypatch.setattr(cp.store, "get_task", get_with_one_race)
    try:
        response = c.post(
            "/api/task/mode",
            json={"task_id": task.id, "mode": "plan"},
            headers=_hdr(cp),
        )
    finally:
        other.close()

    assert response.status_code == 200
    saved = original_get(task.id)
    assert saved.permission_mode == "plan"
    assert saved.chat_url == "https://chatgpt.com/c/parallel"


def test_operator_can_satisfy_only_operator_kind_criterion(client):
    c, cp, tmp = client
    project = tmp / "operator-criterion"
    project.mkdir()
    pid = cp.store.register_project(str(project), "Operator criterion")
    task = cp.store.create_task(
        pid, str(project), goal="visual check", acceptance_criteria=["UI looks right"]
    )

    from harness.tasks.contracts import RunContract

    linked = cp.store.confirm_run_contract(
        task.id,
        RunContract.confirmed(
            task_type="review", effort_level="off", credit_ceiling=0,
            candidate_count=0, machine_concurrency=1, model_concurrency=1,
            framework="none", max_loops=0,
        ),
    )
    current = cp.store.get_task(linked.id)
    current.criteria_v2[0]["verification_kind"] = "operator"
    cp.store.save_task(current)

    response = c.post(
        "/api/task/criterion/operator-satisfy",
        json={"task_id": linked.id, "criterion_id": "AC-1"},
        headers=_hdr(cp),
    )

    assert response.status_code == 200
    criterion = cp.store.get_task(linked.id).criteria_v2[0]
    assert criterion["status"] == "satisfied"
    assert criterion["evidence_refs"] == [
        {"kind": "operator", "confirmed_by": "operator"}
    ]


def test_layout_module_defines_bounded_persisted_panes(client):
    c, cp, tmp = client

    r = c.get("/static/layout.mjs")

    assert r.status_code == 200
    assert "LEFT_MIN = 220" in r.text
    assert "LEFT_MAX = 480" in r.text
    assert "RIGHT_MIN = 320" in r.text
    assert "RIGHT_MAX = 720" in r.text
    assert "localStorage" in r.text
    assert "setPointerCapture" in r.text


def test_modular_ui_preserves_checkpoint_restore_contract(client):
    c, cp, tmp = client

    render = c.get("/static/render.mjs")
    app = c.get("/static/app.mjs")

    assert render.status_code == 200
    assert app.status_code == 200
    assert 'data-action="restore-checkpoint"' in render.text
    assert 'postJSON("/api/restore"' in app.text


def test_shell_exposes_responsive_navigation_controls(client):
    c, cp, tmp = client

    index = c.get("/")
    layout = c.get("/static/layout.mjs")

    assert 'id="sidebarToggle"' in index.text
    assert 'id="sidebarClose"' in index.text
    assert 'id="navBackdrop"' in index.text
    assert 'aria-controls="primarySidebar"' in index.text
    assert 'nextPaneWidth' in layout.text
    assert "CENTER_MIN = 520" in layout.text
    assert "fitPaneWidths" in layout.text
    assert "root.clientWidth" in layout.text
    assert 'matchMedia("(max-width: 1099px)")' in layout.text
    assert 'event.key === "Escape"' in layout.text
    assert 'releasePointerCapture' in layout.text


def test_grid_items_keep_explicit_tracks_when_panes_are_hidden(client):
    c, cp, tmp = client

    css = c.get("/static/cockpit.css").text

    assert ".primary-sidebar { grid-column:1;" in css
    assert ".resize-handle-left { grid-column:2;" in css
    assert ".center-pane { grid-column:3;" in css
    assert ".resize-handle-right { grid-column:4;" in css
    assert ".inspector { grid-column:5;" in css
    assert "@media (max-width:759px)" in css
    assert ".center-pane { grid-column:1;" in css


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


def test_new_session_confirms_run_contract_and_root_scope(client):
    c, cp, tmp = client
    project = tmp / "contract-project"
    c.post("/api/project/create", json={"path": str(project)}, headers=_hdr(cp))

    response = c.post("/api/task/new", json={
        "project_path": str(project), "goal": "contracted", "mode": "auto_workspace",
        "effort_level": "high", "credit_ceiling": 16, "candidate_count": 3,
        "machine_concurrency": 4, "framework": "aocs_omega", "max_loops": 5,
        "task_type": "build",
    }, headers=_hdr(cp))

    assert response.status_code == 200
    assert "Run Contract:" in response.json()["message"]
    task = cp.store.get_task(response.json()["task_id"])
    contract = cp.store.get_run_contract(task.id)
    assert contract.effort_level == "high" and contract.candidate_count == 3
    assert contract.framework == "aocs_omega" and contract.max_loops == 5
    assert task.credit_scope_id


def test_contract_panels_and_operator_actions_are_wired(client):
    c, cp, tmp = client
    render = c.get("/static/render.mjs").text
    app = c.get("/static/app.mjs").text

    for panel in ("contractPanel", "gatesPanel", "auditPanel"):
        assert f"function {panel}" in render
    assert 'data-action="confirm-criterion"' in render
    assert 'data-action="confirm-loop"' in render
    assert "proposed_outcome" in render
    assert "target_weakness" in render
    assert "delta_summary" in render
    assert "attach-contract" in render and "Validated evidence" in render
    assert "attachContract" in app
    assert "/api/task/criterion/operator-satisfy" in app
    assert "/api/task/loop/operator-confirm" in app


def test_effort_status_endpoint_returns_contract_gates_receipts_and_loops(client):
    c, cp, tmp = client
    project = tmp / "status-project"
    project.mkdir()
    pid = cp.store.register_project(str(project), "Status")
    task = cp.store.create_task(pid, str(project), goal="status")
    from harness.tasks.contracts import RunContract
    cp.store.confirm_run_contract(task.id, RunContract.confirmed(
        task_type="review", effort_level="off", credit_ceiling=0,
        candidate_count=0, machine_concurrency=1, model_concurrency=1,
        framework="none", max_loops=2,
    ))

    response = c.get(f"/api/task/effort?task_id={task.id}", headers={"Origin": COCKPIT_ORIGIN})

    assert response.status_code == 200
    body = response.json()
    assert body["contract"]["max_loops"] == 2
    assert body["receipts"] == [] and body["criteria"] == [] and body["loops"] == []


def test_chat_created_task_can_attach_contract_once(client):
    c, cp, tmp = client
    project = tmp / "attach-contract"
    project.mkdir()
    pid = cp.store.register_project(str(project), "Attach")
    task = cp.store.create_task(pid, str(project), goal="legacy")
    payload = {"task_id": task.id, "task_type": "review", "effort_level": "low",
               "candidate_count": 0, "machine_concurrency": 2,
               "framework": "none", "max_loops": 0}

    first = c.post("/api/task/contract", json=payload, headers=_hdr(cp))
    second = c.post("/api/task/contract", json=payload, headers=_hdr(cp))

    assert first.status_code == 200
    assert second.status_code == 409


def test_operator_can_see_and_repair_tampered_contract(client):
    c, cp, tmp = client
    project = tmp / "repair-contract"
    project.mkdir()
    pid = cp.store.register_project(str(project), "Repair")
    task = cp.store.create_task(pid, str(project), goal="repair")
    payload = {"task_id": task.id, "task_type": "review", "effort_level": "low",
               "candidate_count": 0, "machine_concurrency": 2,
               "framework": "none", "max_loops": 0}
    assert c.post("/api/task/contract", json=payload, headers=_hdr(cp)).status_code == 200
    linked = cp.store.get_task(task.id)
    cp.store._db.execute(
        "UPDATE run_contracts SET contract_hash='tampered' WHERE contract_id=?",
        (linked.contract_id,),
    )
    cp.store._db.commit()

    state = c.get("/api/state", headers={"Origin": COCKPIT_ORIGIN}).json()
    shown = next(item for item in state["tasks"] if item["id"] == task.id)
    assert "CONTRACT_TAMPERED" in shown["contract_error"]
    repaired = c.post("/api/task/contract", json=payload, headers=_hdr(cp))

    assert repaired.status_code == 200
    assert cp.store.get_run_contract(task.id).contract_hash != "tampered"
    assert any(event["type"] == "run_contract_repaired" for event in cp.store.events(task.id))


def test_add_existing_nonempty_folder_registers_project(client):
    # Regression (found by the first real-user run): "Add project folder" on an
    # EXISTING folder approved it as a root but never registered a project, so
    # the sidebar stayed empty. Existing non-empty folders must register.
    c, cp, tmp = client
    proj = tmp / "existing"
    proj.mkdir()
    (proj / "main.py").write_text("print('hi')\n", encoding="utf-8")
    r = c.post("/api/project/create", json={"path": str(proj)}, headers=_hdr(cp))
    assert r.status_code == 200 and "Project registered" in r.json()["message"]
    st = c.get("/api/state", headers={"Origin": COCKPIT_ORIGIN}).json()
    assert any(p["name"] == "existing" for p in st["projects"])
    # and the frontend Add-project flow must call the registration endpoint
    app_js = c.get("/static/app.mjs").text
    add_fn = app_js.split("async function addProject", 1)[1].split("async function", 1)[0]
    assert "/api/project/create" in add_fn


def test_cockpit_inplace_session_needs_no_approval_even_when_default_is_isolated(client):
    # The cockpit is the operator: choosing to work in the project folder must
    # never trigger the shared-checkout approval gate, even if the server's
    # default_isolation is an isolated mode. Guards the operator=True bypass.
    c, cp, tmp = client
    cp.server.config.default_isolation = "worktree"
    proj = tmp / "inplace"
    c.post("/api/project/create", json={"path": str(proj)}, headers=_hdr(cp))
    r = c.post("/api/task/new",
               json={"project_path": str(proj), "goal": "work here",
                     "mode": "auto_workspace", "isolation": "workspace"},
               headers=_hdr(cp))
    assert r.status_code == 200
    body = r.json()
    assert not body.get("needs_approval"), body
    assert "APPROVAL REQUIRED" not in body.get("message", "")


def test_state_includes_command_telemetry_for_terminal_inspector(client):
    c, cp, tmp = client
    proj = tmp / "telemetry-project"
    proj.mkdir()
    tid = c.post(
        "/api/task/new",
        json={"project_path": str(proj), "goal": "show terminal telemetry"},
        headers=_hdr(cp),
    ).json()["task_id"]
    task = cp.store.get_task(tid)
    task.commands.append({"command": "pytest -q", "exit": 0})
    cp.store.save_task(task)

    state = c.get("/api/state", headers={"Origin": COCKPIT_ORIGIN}).json()

    payload = next(item for item in state["tasks"] if item["id"] == tid)
    assert payload["commands"] == [{"command": "pytest -q", "exit": 0}]


def test_fork_from_cockpit(client):
    c, cp, tmp = client
    proj = tmp / "p"
    c.post("/api/project/create", json={"path": str(proj)}, headers=_hdr(cp))
    tid = c.post("/api/task/new", json={"project_path": str(proj), "goal": "g"},
                 headers=_hdr(cp)).json()["task_id"]
    r = c.post("/api/task/fork", json={"task_id": tid}, headers=_hdr(cp))
    assert r.status_code == 200 and "Forked" in r.json()["message"]


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://evil.example/chat"])
def test_chat_url_rejects_non_chatgpt_destinations(client, url):
    c, cp, tmp = client
    proj = tmp / "p"
    c.post("/api/project/create", json={"path": str(proj)}, headers=_hdr(cp))
    tid = c.post("/api/task/new", json={"project_path": str(proj), "goal": "g"},
                 headers=_hdr(cp)).json()["task_id"]

    r = c.post("/api/task/chat_url", json={"task_id": tid, "chat_url": url}, headers=_hdr(cp))

    assert r.status_code == 400


def test_chat_url_accepts_https_chatgpt(client):
    c, cp, tmp = client
    proj = tmp / "p"
    c.post("/api/project/create", json={"path": str(proj)}, headers=_hdr(cp))
    tid = c.post("/api/task/new", json={"project_path": str(proj), "goal": "g"},
                 headers=_hdr(cp)).json()["task_id"]
    url = "https://chatgpt.com/codex/task/example"

    r = c.post("/api/task/chat_url", json={"task_id": tid, "chat_url": url}, headers=_hdr(cp))

    assert r.status_code == 200
    assert cp.store.get_task(tid).chat_url == url


def test_project_and_session_pins_round_trip_through_state(client):
    c, cp, tmp = client
    proj = tmp / "p"
    c.post("/api/project/create", json={"path": str(proj), "name": "Pinned project"},
           headers=_hdr(cp))
    state = c.get("/api/state", headers={"Origin": COCKPIT_ORIGIN}).json()
    pid = next(p["id"] for p in state["projects"] if p["name"] == "Pinned project")
    tid = c.post("/api/task/new", json={"project_path": str(proj), "goal": "pinned task"},
                 headers=_hdr(cp)).json()["task_id"]

    project_result = c.post("/api/project/pinned", json={"project_id": pid, "pinned": True},
                            headers=_hdr(cp))
    task_result = c.post("/api/task/pinned", json={"task_id": tid, "pinned": True},
                         headers=_hdr(cp))
    state = c.get("/api/state", headers={"Origin": COCKPIT_ORIGIN}).json()

    assert project_result.status_code == 200
    assert task_result.status_code == 200
    assert next(p for p in state["projects"] if p["id"] == pid)["pinned"] is True
    assert next(t for t in state["tasks"] if t["id"] == tid)["pinned"] is True


def test_task_events_endpoint_is_scoped_to_selected_task(client):
    c, cp, tmp = client
    proj = tmp / "p"
    c.post("/api/project/create", json={"path": str(proj)}, headers=_hdr(cp))
    first = c.post("/api/task/new", json={"project_path": str(proj), "goal": "first"},
                   headers=_hdr(cp)).json()["task_id"]
    second = c.post("/api/task/new", json={"project_path": str(proj), "goal": "second"},
                    headers=_hdr(cp)).json()["task_id"]
    cp.store.add_event(first, "note", text="only-first")
    cp.store.add_event(second, "note", text="only-second")

    response = c.get(f"/api/task/events?task_id={first}&limit=200",
                     headers={"Origin": COCKPIT_ORIGIN})

    assert response.status_code == 200
    payload = response.json()["events"]
    assert any(event.get("text") == "only-first" for event in payload)
    assert all(event.get("text") != "only-second" for event in payload)
    assert all(event["task_id"] == first for event in payload)
    assert all(event["event_id"].startswith("db:") for event in payload)


def test_frontend_domain_helpers_cover_navigation_and_inspector_contracts(client):
    c, cp, tmp = client

    render = c.get("/static/render.mjs").text
    state = c.get("/static/state.mjs").text

    assert "export function taskMatchesSearch" in render
    assert "export function sortProjectsByActivity" in render
    assert "task.id" in render
    assert "task?.commands || []" in render
    assert "entry.exit" in render
    assert "task.pinned_files" in render
    assert "task.changed_files" in render
    assert "event.event_id" in state
    assert ".slice(-400)" in state


def test_renderer_preserves_workspace_scroll_across_same_task_refresh(client):
    c, cp, tmp = client

    render = c.get("/static/render.mjs").text

    assert "previousSelectedTask === state.selectedTask" in render
    assert "previousWorkspaceScroll" in render
    assert "workspaceScroll.scrollTop = previousWorkspaceScroll" in render


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
