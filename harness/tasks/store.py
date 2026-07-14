"""Transactional SQLite store for tasks, projects, events, approvals, operations.

WAL mode + a process lock + schema-versioned migrations. Task bodies are stored
as a JSON blob (flexible) with `status` promoted to a column for querying. This
is the durable backbone the whole task layer sits on.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from pathlib import Path

from ..session import _now_iso
from .model import Task, TaskState

# Ordered migrations. To evolve the schema, append a new (version, [statements]).
_MIGRATIONS: list[tuple[int, list[str]]] = [
    (1, [
        "CREATE TABLE projects (id TEXT PRIMARY KEY, path TEXT UNIQUE, name TEXT, created TEXT)",
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, project_id TEXT, status TEXT, data TEXT, created TEXT, updated TEXT)",
        "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, time TEXT, type TEXT, data TEXT)",
        "CREATE TABLE approvals (id TEXT PRIMARY KEY, task_id TEXT, action TEXT, detail TEXT, status TEXT, created TEXT, decided TEXT)",
        "CREATE TABLE operations (op_id TEXT PRIMARY KEY, task_id TEXT, tool TEXT, created TEXT, result TEXT)",
        "CREATE INDEX idx_tasks_project ON tasks(project_id)",
        "CREATE INDEX idx_events_task ON events(task_id)",
    ]),
]


def _sid(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


class TaskStore:
    def __init__(self, db_path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    # ---- schema ------------------------------------------------------------

    def _migrate(self) -> None:
        with self._lock:
            self._db.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = self._db.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            current = row["v"] or 0
            for version, statements in _MIGRATIONS:
                if version > current:
                    for stmt in statements:
                        self._db.execute(stmt)
                    self._db.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ---- projects ----------------------------------------------------------

    def register_project(self, path: str, name: str = "") -> str:
        with self._lock:
            existing = self._db.execute("SELECT id FROM projects WHERE path=?", (str(path),)).fetchone()
            if existing:
                return existing["id"]
            pid = _sid("P")
            self._db.execute(
                "INSERT INTO projects (id, path, name, created) VALUES (?,?,?,?)",
                (pid, str(path), name or Path(path).name, _now_iso()),
            )
            self._db.commit()
            return pid

    def get_project(self, project_id: str) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            return dict(r) if r else None

    # ---- tasks -------------------------------------------------------------

    def create_task(self, project_id: str, workspace_path: str, **fields) -> Task:
        now = _now_iso()
        task = Task(
            id=_sid("T"), project_id=project_id, workspace_path=str(workspace_path),
            created=now, updated=now, **fields,
        )
        with self._lock:
            self._db.execute(
                "INSERT INTO tasks (id, project_id, status, data, created, updated) VALUES (?,?,?,?,?,?)",
                (task.id, project_id, task.status.value, task.model_dump_json(), now, now),
            )
            self._db.commit()
        self.add_event(task.id, "created", goal=task.goal)
        return task

    def get_task(self, task_id: str) -> Task | None:
        with self._lock:
            r = self._db.execute("SELECT data FROM tasks WHERE id=?", (task_id,)).fetchone()
        return Task.model_validate_json(r["data"]) if r else None

    def save_task(self, task: Task) -> None:
        task.updated = _now_iso()
        with self._lock:
            self._db.execute(
                "UPDATE tasks SET status=?, data=?, updated=? WHERE id=?",
                (task.status.value, task.model_dump_json(), task.updated, task.id),
            )
            self._db.commit()

    def list_tasks(self, project_id: str | None = None, status: str | None = None) -> list[Task]:
        q = "SELECT data FROM tasks"
        clauses, params = [], []
        if project_id:
            clauses.append("project_id=?"); params.append(project_id)
        if status:
            clauses.append("status=?"); params.append(status)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY created"
        with self._lock:
            rows = self._db.execute(q, params).fetchall()
        return [Task.model_validate_json(r["data"]) for r in rows]

    # ---- events ------------------------------------------------------------

    def add_event(self, task_id: str, type: str, **data) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO events (task_id, time, type, data) VALUES (?,?,?,?)",
                (task_id, _now_iso(), type, json.dumps(data, ensure_ascii=False)),
            )
            self._db.commit()

    def events(self, task_id: str, limit: int = 30) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT time, type, data FROM events WHERE task_id=? ORDER BY id DESC LIMIT ?",
                (task_id, limit),
            ).fetchall()
        out = []
        for r in reversed(rows):
            d = {"time": r["time"], "type": r["type"]}
            try:
                d.update(json.loads(r["data"]))
            except ValueError:
                pass
            out.append(d)
        return out

    # ---- approvals ---------------------------------------------------------

    def add_approval(self, task_id: str, action: str, detail: str) -> str:
        aid = _sid("A")
        with self._lock:
            self._db.execute(
                "INSERT INTO approvals (id, task_id, action, detail, status, created, decided) VALUES (?,?,?,?,?,?,?)",
                (aid, task_id, action, detail, "pending", _now_iso(), None),
            )
            self._db.commit()
        return aid

    def get_approval(self, approval_id: str) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            return dict(r) if r else None

    def decide_approval(self, approval_id: str, status: str) -> bool:
        with self._lock:
            cur = self._db.execute(
                "UPDATE approvals SET status=?, decided=? WHERE id=? AND status='pending'",
                (status, _now_iso(), approval_id),
            )
            self._db.commit()
            return cur.rowcount > 0

    def grantable_approval(self, task_id: str, action: str) -> dict | None:
        """An approved-but-unused approval matching this task+action (one-shot)."""
        with self._lock:
            r = self._db.execute(
                "SELECT * FROM approvals WHERE task_id=? AND action=? AND status='approved' "
                "ORDER BY created LIMIT 1",
                (task_id, action),
            ).fetchone()
            return dict(r) if r else None

    def consume_approval(self, approval_id: str) -> None:
        with self._lock:
            self._db.execute("UPDATE approvals SET status='used' WHERE id=?", (approval_id,))
            self._db.commit()

    def pending_approvals(self, task_id: str | None = None) -> list[dict]:
        with self._lock:
            if task_id:
                rows = self._db.execute(
                    "SELECT * FROM approvals WHERE status='pending' AND task_id=? ORDER BY created", (task_id,)
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT * FROM approvals WHERE status='pending' ORDER BY created"
                ).fetchall()
        return [dict(r) for r in rows]

    # ---- operations (idempotency) -----------------------------------------

    def get_operation(self, op_id: str) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM operations WHERE op_id=?", (op_id,)).fetchone()
            return dict(r) if r else None

    def record_operation(self, op_id: str, task_id: str, tool: str, result: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO operations (op_id, task_id, tool, created, result) VALUES (?,?,?,?,?)",
                (op_id, task_id, tool, _now_iso(), result),
            )
            self._db.commit()
