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


def test_migrations_are_idempotent(tmp_path):
    db = tmp_path / "tasks.db"
    TaskStore(db).close()
    s2 = TaskStore(db)  # reopening must not re-run migrations or error
    row = s2._db.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    assert row["v"] == 1


def test_idempotent_operations(tmp_path):
    s = _store(tmp_path)
    pid = s.register_project("/repo/proj")
    t = s.create_task(pid, "/repo/proj")
    s.record_operation("op-1", t.id, "run_command", "exit 0")
    s.record_operation("op-1", t.id, "run_command", "DIFFERENT")  # ignored
    assert s.get_operation("op-1")["result"] == "exit 0"
