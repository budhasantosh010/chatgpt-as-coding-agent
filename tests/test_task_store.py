"""Task model state machine + SQLite store (persistence, migrations, CRUD)."""

from __future__ import annotations

from harness.tasks.model import Task, TaskState, can_transition
from harness.tasks.store import TaskStore


# --- state machine ---------------------------------------------------------

def test_legal_transitions():
    assert can_transition(TaskState.NEW, TaskState.PLANNING)
    assert can_transition(TaskState.PLANNING, TaskState.IMPLEMENTING)
    assert can_transition(TaskState.IMPLEMENTING, TaskState.VALIDATING)
    assert can_transition(TaskState.VALIDATING, TaskState.REVIEW_READY)
    assert can_transition(TaskState.REVIEW_READY, TaskState.COMPLETED)


def test_illegal_transitions():
    assert not can_transition(TaskState.NEW, TaskState.COMPLETED)
    assert not can_transition(TaskState.PLANNING, TaskState.VALIDATING)
    # terminal states are sticky
    assert not can_transition(TaskState.COMPLETED, TaskState.IMPLEMENTING)
    assert not can_transition(TaskState.CANCELLED, TaskState.PLANNING)


def test_block_and_cancel_always_allowed():
    assert can_transition(TaskState.IMPLEMENTING, TaskState.BLOCKED)
    assert can_transition(TaskState.PLANNING, TaskState.CANCELLED)


# --- store -----------------------------------------------------------------

def _store(tmp_path):
    return TaskStore(tmp_path / "tasks.db")


def test_register_project_is_idempotent(tmp_path):
    s = _store(tmp_path)
    a = s.register_project("/repo/proj", "proj")
    b = s.register_project("/repo/proj")
    assert a == b


def test_create_get_save_task(tmp_path):
    s = _store(tmp_path)
    pid = s.register_project("/repo/proj")
    t = s.create_task(pid, "/repo/proj", goal="add feature X", permission_mode="auto_workspace")
    assert t.id.startswith("T-")
    loaded = s.get_task(t.id)
    assert loaded.goal == "add feature X"
    loaded.status = TaskState.PLANNING
    loaded.plan = ["step 1", "step 2"]
    s.save_task(loaded)
    again = s.get_task(t.id)
    assert again.status == TaskState.PLANNING
    assert again.plan == ["step 1", "step 2"]


def test_list_tasks_filters(tmp_path):
    s = _store(tmp_path)
    pid = s.register_project("/repo/proj")
    t1 = s.create_task(pid, "/repo/proj", goal="one")
    t2 = s.create_task(pid, "/repo/proj", goal="two")
    t2.status = TaskState.COMPLETED
    s.save_task(t2)
    assert len(s.list_tasks(project_id=pid)) == 2
    assert [t.id for t in s.list_tasks(status="completed")] == [t2.id]


def test_events_recorded(tmp_path):
    s = _store(tmp_path)
    pid = s.register_project("/repo/proj")
    t = s.create_task(pid, "/repo/proj", goal="g")
    s.add_event(t.id, "note", text="hello")
    evs = s.events(t.id)
    assert any(e["type"] == "created" for e in evs)
    assert any(e.get("text") == "hello" for e in evs)


def test_duplicate_pending_approval_is_coalesced_by_exact_request(tmp_path):
    s = _store(tmp_path)
    pid = s.register_project("/repo/proj")
    task = s.create_task(pid, "/repo/proj", goal="g")

    first = s.add_approval(task.id, "command_arbitrary", "run_command: Get-Date", "same-hash")
    duplicate = s.add_approval(task.id, "command_arbitrary", "run_command: Get-Date", "same-hash")
    distinct = s.add_approval(task.id, "command_arbitrary", "run_command: Get-Random", "other-hash")

    assert duplicate == first
    assert distinct != first
    assert [row["id"] for row in s.pending_approvals(task.id)] == [first, distinct]


def test_migrations_are_idempotent(tmp_path):
    db = tmp_path / "tasks.db"
    TaskStore(db).close()
    s2 = TaskStore(db)  # reopening must not re-run migrations or error
    row = s2._db.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    assert row["v"] == 7
    s2.close()


def test_migration_v2_preserves_v1_rows(tmp_path):
    """Upgrading a v1 database keeps existing approvals and operations."""
    from harness.tasks.store import _MIGRATIONS
    import sqlite3

    db = tmp_path / "tasks.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    for stmt in dict(_MIGRATIONS)[1]:
        con.execute(stmt)
    con.execute("INSERT INTO schema_version (version) VALUES (1)")
    con.execute(
        "INSERT INTO approvals (id, task_id, action, detail, status, created, decided) "
        "VALUES ('A-1','T-1','network','curl x','pending','2026-01-01',NULL)"
    )
    con.execute(
        "INSERT INTO operations (op_id, task_id, tool, created, result) "
        "VALUES ('op-1','T-1','run_command','2026-01-01','exit 0')"
    )
    con.commit()
    con.close()

    s = TaskStore(db)
    try:
        assert s.get_operation("op-1", "T-1", "run_command")["result"] == "exit 0"
        row = s._db.execute("SELECT request_hash FROM approvals WHERE id='A-1'").fetchone()
        assert row is not None  # column added, row preserved
    finally:
        s.close()


def test_idempotent_operations(tmp_path):
    s = _store(tmp_path)
    pid = s.register_project("/repo/proj")
    t = s.create_task(pid, "/repo/proj")
    s.record_operation("op-1", t.id, "run_command", "exit 0")
    s.record_operation("op-1", t.id, "run_command", "DIFFERENT")  # ignored
    assert s.get_operation("op-1", t.id, "run_command")["result"] == "exit 0"


def test_operation_records_exact_request_hash(tmp_path):
    s = TaskStore(tmp_path / "tasks.db")
    pid = s.register_project(str(tmp_path), "p")
    t = s.create_task(pid, "goal")
    s.record_operation("op-hash", t.id, "run_command", "ok", "sha256-value")
    assert s.get_operation("op-hash", t.id, "run_command")["request_hash"] == "sha256-value"


def test_project_and_task_pins_are_durable(tmp_path):
    db = tmp_path / "tasks.db"
    s = TaskStore(db)
    pid = s.register_project("/repo/proj", "Project")
    task = s.create_task(pid, "/repo/proj", goal="g")

    assert s.set_project_pinned(pid, True)
    assert s.set_task_pinned(task.id, True)
    s.close()

    reopened = TaskStore(db)
    try:
        assert reopened.get_project(pid)["pinned"] is True
        assert reopened.get_task(task.id).pinned is True
        assert reopened.list_projects()[0]["pinned"] is True
    finally:
        reopened.close()


def test_events_have_stable_task_scoped_ids(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    project_path = tmp_path / "project"
    project_id = store.register_project(project_path, "Project")
    task = store.create_task(project_id, str(project_path), goal="events")
    store.add_event(task.id, "note", text="first")
    store.add_event(task.id, "note", text="second")

    events = store.events(task.id, limit=20)

    assert all(event["task_id"] == task.id for event in events)
    assert all(event["event_id"].startswith("db:") for event in events)
    assert len({event["event_id"] for event in events}) == len(events)
