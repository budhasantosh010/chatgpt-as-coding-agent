"""Sidebar row actions, for projects as well as sessions.

Projects only ever had Pin. Rename, Archive and Delete existed for sessions and
nowhere else, so tidying the sidebar meant tidying half of it. These tests fix
the shape of the other half, and pin down the two decisions that make it safe:

  * project "Delete" unregisters, it does not erase. Tasks, receipts and credit
    ledgers survive and re-adding the same PATH brings the project back.
  * a session may only move to another project while it has done no work. Its
    diffs, executions and receipts all live in one folder; refiling it after the
    fact would make the sidebar describe a place the work never happened.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from harness.cockpit.server import Cockpit, build_cockpit_app
from harness.config import Config
from harness.tasks.model import TaskState

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


def _hdr(cp):
    return {"X-Cockpit-Token": cp.csrf_token, "Origin": COCKPIT_ORIGIN}


def _project(cp, tmp_path, name="Alpha"):
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    return cp.store.register_project(str(folder), name), folder


def _task(cp, project_id, folder, goal="fix it"):
    return cp.store.create_task(project_id, str(folder), goal=goal)


# ---- projects: rename, archive, remove ---------------------------------------

def test_project_can_be_renamed(client):
    c, cp, tmp = client
    pid, _ = _project(cp, tmp)
    r = c.post("/api/project/rename", json={"project_id": pid, "name": "Renamed"},
               headers=_hdr(cp))
    assert r.status_code == 200
    assert cp.store.get_project(pid)["name"] == "Renamed"


def test_renaming_a_project_leaves_the_folder_alone(client):
    """The label is sidebar state. The directory is the operator's real code,
    with worktrees and pinned paths pointing into it."""
    c, cp, tmp = client
    pid, folder = _project(cp, tmp)
    c.post("/api/project/rename", json={"project_id": pid, "name": "Something Else"},
           headers=_hdr(cp))
    assert folder.exists()
    assert cp.store.get_project(pid)["path"] == str(folder)


def test_empty_project_name_is_refused(client):
    c, cp, tmp = client
    pid, _ = _project(cp, tmp)
    r = c.post("/api/project/rename", json={"project_id": pid, "name": "   "},
               headers=_hdr(cp))
    assert r.status_code == 400
    assert cp.store.get_project(pid)["name"] == "Alpha"


def test_project_archive_round_trips(client):
    c, cp, tmp = client
    pid, _ = _project(cp, tmp)
    c.post("/api/project/archived", json={"project_id": pid, "archived": True},
           headers=_hdr(cp))
    assert cp.store.get_project(pid)["archived"] is True
    c.post("/api/project/archived", json={"project_id": pid, "archived": False},
           headers=_hdr(cp))
    assert cp.store.get_project(pid)["archived"] is False


def test_removing_a_project_keeps_its_sessions_and_folder(client):
    """The whole point of the Delete decision: nothing is destroyed."""
    c, cp, tmp = client
    pid, folder = _project(cp, tmp)
    task = _task(cp, pid, folder)

    r = c.post("/api/project/remove", json={"project_id": pid}, headers=_hdr(cp))

    assert r.status_code == 200
    assert folder.exists(), "removing a project must never touch the disk"
    assert cp.store.get_task(task.id) is not None, "its sessions must survive"
    assert pid not in [p["id"] for p in cp.store.list_projects()]


def test_re_adding_the_same_folder_restores_a_removed_project(client):
    """The documented way back. Same row, same id, same sessions."""
    c, cp, tmp = client
    pid, folder = _project(cp, tmp)
    task = _task(cp, pid, folder)
    c.post("/api/project/remove", json={"project_id": pid}, headers=_hdr(cp))

    again = cp.store.register_project(str(folder), "Alpha")

    assert again == pid
    assert pid in [p["id"] for p in cp.store.list_projects()]
    assert cp.store.get_task(task.id).project_id == pid


def test_removing_a_project_with_a_running_session_is_refused(client):
    c, cp, tmp = client
    pid, folder = _project(cp, tmp)
    task = _task(cp, pid, folder)
    cp.store.mutate_task(
        task.id, lambda t: setattr(t, "status", TaskState.IMPLEMENTING)
    )

    r = c.post("/api/project/remove", json={"project_id": pid}, headers=_hdr(cp))

    assert r.status_code == 409
    assert pid in [p["id"] for p in cp.store.list_projects()]


# ---- sessions: rename, unread, move -----------------------------------------

def test_session_rename_sets_the_title_and_leaves_the_goal(client):
    """The goal is contract input that receipts refer back to; a sidebar menu
    does not get to edit it."""
    c, cp, tmp = client
    pid, folder = _project(cp, tmp)
    task = _task(cp, pid, folder, goal="original goal")

    r = c.post("/api/task/rename", json={"task_id": task.id, "title": "Nicer name"},
               headers=_hdr(cp))

    assert r.status_code == 200
    reloaded = cp.store.get_task(task.id)
    assert reloaded.title == "Nicer name"
    assert reloaded.goal == "original goal"


def test_unread_round_trips_and_reaches_the_state_payload(client):
    c, cp, tmp = client
    pid, folder = _project(cp, tmp)
    task = _task(cp, pid, folder)

    c.post("/api/task/unread", json={"task_id": task.id, "unread": True},
           headers=_hdr(cp))

    payload = c.get("/api/state").json()
    row = [t for t in payload["tasks"] if t["id"] == task.id][0]
    assert row["unread"] is True


def test_a_fresh_session_moves_and_takes_its_workspace_with_it(client):
    c, cp, tmp = client
    source, source_dir = _project(cp, tmp, "Alpha")
    target, target_dir = _project(cp, tmp, "Beta")
    task = _task(cp, source, source_dir)

    r = c.post("/api/task/move", json={"task_id": task.id, "project_id": target},
               headers=_hdr(cp))

    assert r.status_code == 200
    moved = cp.store.get_task(task.id)
    assert moved.project_id == target
    # Rebinding the workspace is the point: a session filed under Beta whose
    # files live in Alpha would mislead every time the operator looked at it.
    assert moved.workspace_path == str(target_dir)


def test_a_session_that_has_worked_refuses_to_move(client):
    c, cp, tmp = client
    source, source_dir = _project(cp, tmp, "Alpha")
    target, _ = _project(cp, tmp, "Beta")
    task = _task(cp, source, source_dir)
    cp.store.mutate_task(task.id, lambda t: setattr(t, "changed_files", ["calc.py"]))

    r = c.post("/api/task/move", json={"task_id": task.id, "project_id": target},
               headers=_hdr(cp))

    assert r.status_code == 409
    assert "fork" in r.json()["error"].lower()
    assert cp.store.get_task(task.id).project_id == source


def test_a_recorded_execution_also_blocks_a_move(client):
    """Work is not only edited files: a run of the test suite happened in a
    specific folder too, and the receipt that cites it says so."""
    c, cp, tmp = client
    source, source_dir = _project(cp, tmp, "Alpha")
    target, _ = _project(cp, tmp, "Beta")
    task = _task(cp, source, source_dir)
    cp.store.add_event(task.id, "obs_exec", command="pytest -q", exec_id="px-1")

    r = c.post("/api/task/move", json={"task_id": task.id, "project_id": target},
               headers=_hdr(cp))

    assert r.status_code == 409
    assert cp.store.get_task(task.id).project_id == source


def test_moving_to_a_missing_project_is_a_404_not_a_409(client):
    c, cp, tmp = client
    source, source_dir = _project(cp, tmp)
    task = _task(cp, source, source_dir)

    r = c.post("/api/task/move", json={"task_id": task.id, "project_id": "P-nope"},
               headers=_hdr(cp))

    assert r.status_code == 404


def test_row_actions_still_require_the_csrf_token(client):
    """Every new mutation joins the same guard as the old ones."""
    c, cp, tmp = client
    pid, folder = _project(cp, tmp)
    task = _task(cp, pid, folder)
    for path, body in (
        ("/api/project/rename", {"project_id": pid, "name": "x"}),
        ("/api/project/archived", {"project_id": pid, "archived": True}),
        ("/api/project/remove", {"project_id": pid}),
        ("/api/task/rename", {"task_id": task.id, "title": "x"}),
        ("/api/task/unread", {"task_id": task.id, "unread": True}),
        ("/api/task/move", {"task_id": task.id, "project_id": pid}),
    ):
        r = c.post(path, json=body, headers={"Origin": COCKPIT_ORIGIN})
        assert r.status_code == 403, f"{path} accepted a request with no token"
