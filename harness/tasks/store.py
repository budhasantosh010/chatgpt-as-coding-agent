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
from .contracts import RunContract, contract_hash
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
    # v2 (audit S3+S4): approvals bind to the EXACT request (hash over
    # task/tool/action/normalized args), and operations are keyed per
    # (task, tool, op_id) so a cached result can never leak across tasks/tools.
    (2, [
        "ALTER TABLE approvals ADD COLUMN request_hash TEXT",
        "CREATE TABLE operations_v2 (op_id TEXT, task_id TEXT, tool TEXT, created TEXT, result TEXT, "
        "PRIMARY KEY (task_id, tool, op_id))",
        "INSERT INTO operations_v2 (op_id, task_id, tool, created, result) "
        "SELECT op_id, task_id, tool, created, result FROM operations",
        "DROP TABLE operations",
        "ALTER TABLE operations_v2 RENAME TO operations",
    ]),
    # v3: only one live approval prompt may exist for an exact request. Older
    # databases can contain duplicates, so keep the earliest row before adding
    # the partial unique index. Empty legacy hashes remain intentionally free.
    (3, [
        "DELETE FROM approvals WHERE rowid NOT IN ("
        "SELECT MIN(rowid) FROM approvals "
        "WHERE status='pending' AND COALESCE(request_hash, '') <> '' "
        "GROUP BY task_id, action, request_hash"
        ") AND status='pending' AND COALESCE(request_hash, '') <> ''",
        "CREATE UNIQUE INDEX idx_approvals_pending_request "
        "ON approvals(task_id, action, request_hash) "
        "WHERE status='pending' AND request_hash <> ''",
    ]),
    # v4: project pinning is durable domain state. Task pinning lives in the
    # backward-compatible task JSON body via Pydantic's default field.
    (4, [
        "ALTER TABLE projects ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0",
    ]),
    # v5: an idempotency key is valid only for the exact original arguments.
    # Legacy rows have an empty hash and are treated as unverifiable instead of
    # risking a cached result from a different request.
    (5, [
        "ALTER TABLE operations ADD COLUMN request_hash TEXT NOT NULL DEFAULT ''",
    ]),
    # v6: concurrency-safe task rows plus the durable four-controls foundation.
    (6, [
        "ALTER TABLE tasks ADD COLUMN revision INTEGER NOT NULL DEFAULT 0",
        "CREATE TABLE run_contracts ("
        "contract_id TEXT PRIMARY KEY, root_task_id TEXT NOT NULL UNIQUE, "
        "contract_json TEXT NOT NULL, contract_hash TEXT NOT NULL, "
        "confirmed_at TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0)",
        "CREATE TABLE credit_scopes ("
        "scope_id TEXT PRIMARY KEY, contract_id TEXT NOT NULL, task_id TEXT NOT NULL, "
        "kind TEXT NOT NULL, ceiling INTEGER NOT NULL, created TEXT NOT NULL)",
        "CREATE TABLE credits ("
        "credit_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, task_id TEXT NOT NULL, "
        "fingerprint TEXT NOT NULL, tier TEXT NOT NULL, status TEXT NOT NULL, "
        "question TEXT NOT NULL, verification_plan TEXT DEFAULT '', "
        "receipt_json TEXT DEFAULT '', receipt_path TEXT DEFAULT '', "
        "opened TEXT NOT NULL, closed TEXT DEFAULT '')",
        "CREATE UNIQUE INDEX idx_credits_scope_fp ON credits(scope_id, fingerprint) "
        "WHERE status='spent'",
        "CREATE INDEX idx_credits_scope ON credits(scope_id)",
        "CREATE INDEX idx_credits_task ON credits(task_id)",
        "CREATE UNIQUE INDEX idx_credits_open_task ON credits(task_id) "
        "WHERE status='open'",
        "CREATE TABLE loop_passes ("
        "pass_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, pass_number INTEGER NOT NULL, "
        "verification_kind TEXT NOT NULL, input_state_hash TEXT NOT NULL, "
        "target_weakness TEXT NOT NULL, directive TEXT NOT NULL, repeat_key TEXT NOT NULL, "
        "status TEXT NOT NULL, verification_plan TEXT DEFAULT '', "
        "output_state_hash TEXT DEFAULT '', delta_summary TEXT DEFAULT '', "
        "opened TEXT NOT NULL, closed TEXT DEFAULT '')",
        "CREATE UNIQUE INDEX idx_loops_repeat ON loop_passes(task_id, repeat_key) "
        "WHERE status IN ('open','improved','no_gain','worse','pending_operator')",
        "CREATE INDEX idx_loops_task ON loop_passes(task_id)",
    ]),
    (7, [
        "ALTER TABLE loop_passes ADD COLUMN proposed_outcome TEXT NOT NULL DEFAULT ''",
    ]),
]


def _sid(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(12)}"


class TaskConflictError(ValueError):
    """A stale whole-task snapshot tried to overwrite a newer revision."""


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
            if not r:
                return None
            project = dict(r)
            project["pinned"] = bool(project.get("pinned"))
            return project

    def list_projects(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, path, name, created, pinned FROM projects ORDER BY created"
            ).fetchall()
        projects = [dict(row) for row in rows]
        for project in projects:
            project["pinned"] = bool(project["pinned"])
        return projects

    def set_project_pinned(self, project_id: str, pinned: bool) -> bool:
        with self._lock:
            cur = self._db.execute(
                "UPDATE projects SET pinned=? WHERE id=?", (int(bool(pinned)), project_id)
            )
            self._db.commit()
            return cur.rowcount > 0

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

    def create_task_with_contract(
        self, project_id: str, workspace_path: str, contract: RunContract, **fields
    ) -> Task:
        """Atomically create a root task, its immutable contract, and credit scope."""
        now = _now_iso()
        contract_id = _sid("rc")
        scope_id = _sid("cs") if contract.effort_level != "off" else ""
        task = Task(
            id=_sid("T"), project_id=project_id, workspace_path=str(workspace_path),
            created=now, updated=now, contract_id=contract_id,
            credit_scope_id=scope_id, **fields,
        )
        if not task.criteria_v2:
            task.criteria_v2 = [
                {
                    "id": f"AC-{index}", "text": text, "required": True,
                    "status": "open", "verification_kind": "machine",
                    "evidence_refs": [], "verified_at": "",
                }
                for index, text in enumerate(task.acceptance_criteria, 1)
            ]
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.execute(
                    "INSERT INTO tasks (id, project_id, status, data, created, updated) "
                    "VALUES (?,?,?,?,?,?)",
                    (task.id, project_id, task.status.value, task.model_dump_json(), now, now),
                )
                self._db.execute(
                    "INSERT INTO run_contracts "
                    "(contract_id, root_task_id, contract_json, contract_hash, confirmed_at, revision) "
                    "VALUES (?,?,?,?,?,0)",
                    (contract_id, task.id, contract.model_dump_json(),
                     contract.contract_hash, contract.confirmed_at),
                )
                if scope_id:
                    self._db.execute(
                        "INSERT INTO credit_scopes "
                        "(scope_id, contract_id, task_id, kind, ceiling, created) "
                        "VALUES (?,?,?,?,?,?)",
                        (scope_id, contract_id, task.id, "root",
                         contract.credit_ceiling, now),
                    )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        self.add_event(task.id, "created", goal=task.goal)
        self.add_event(task.id, "run_contract_confirmed", contract_id=contract_id)
        return task

    def create_candidate_task(self, source: Task, **fields) -> Task:
        """Atomically enforce the locked ULTRA limit and create one candidate."""
        contract = self.get_run_contract(source.id)
        if contract is None or not contract.ultra_enabled:
            raise ValueError("[NOT_ULTRA] this task's contract has no candidates")
        now = _now_iso()
        child = Task(
            id=_sid("T"), project_id=source.project_id,
            workspace_path=source.workspace_path, created=now, updated=now, **fields,
        )
        scope_id = _sid("cs") if contract.effort_level != "off" else ""
        child.credit_scope_id = scope_id
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                root = self._db.execute(
                    "SELECT root_task_id FROM run_contracts WHERE contract_id=?",
                    (source.contract_id,),
                ).fetchone()
                used = self._db.execute(
                    "SELECT COUNT(*) AS n FROM events WHERE task_id=? AND type='candidate_created'",
                    (root["root_task_id"],),
                ).fetchone()["n"]
                if used >= contract.candidate_count:
                    raise ValueError("[CANDIDATE_LIMIT] locked candidate count is exhausted")
                self._db.execute(
                    "INSERT INTO tasks (id, project_id, status, data, created, updated) "
                    "VALUES (?,?,?,?,?,?)",
                    (child.id, child.project_id, child.status.value,
                     child.model_dump_json(), now, now),
                )
                if scope_id:
                    self._db.execute(
                        "INSERT INTO credit_scopes "
                        "(scope_id, contract_id, task_id, kind, ceiling, created) "
                        "VALUES (?,?,?,?,?,?)",
                        (scope_id, source.contract_id, child.id, "candidate",
                         contract.credit_ceiling, now),
                    )
                self._db.execute(
                    "INSERT INTO events (task_id, time, type, data) VALUES (?,?,?,?)",
                    (root["root_task_id"], now, "candidate_created",
                     json.dumps({"child": child.id, "scope_id": scope_id})),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        self.add_event(child.id, "created", goal=child.goal)
        return child

    def candidate_usage(self, task_id: str) -> int:
        task = self.get_task(task_id)
        if task is None or not task.contract_id:
            return 0
        with self._lock:
            root = self._db.execute(
                "SELECT root_task_id FROM run_contracts WHERE contract_id=?",
                (task.contract_id,),
            ).fetchone()
            if root is None:
                raise ValueError("[CONTRACT_TAMPERED] linked Run Contract row is missing")
            row = self._db.execute(
                "SELECT COUNT(*) AS n FROM events WHERE task_id=? AND type='candidate_created'",
                (root["root_task_id"],),
            ).fetchone()
        return int(row["n"])

    def rollback_candidate_task(self, source_task_id: str, child_task_id: str) -> None:
        """Remove a candidate reservation that could not obtain isolation."""
        source = self.get_task(source_task_id)
        child = self.get_task(child_task_id)
        if source is None or child is None or child.parent_id != source_task_id:
            raise ValueError("[CANDIDATE_ROLLBACK] candidate reservation is invalid")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                root = self._db.execute(
                    "SELECT root_task_id FROM run_contracts WHERE contract_id=?",
                    (source.contract_id,),
                ).fetchone()
                rows = self._db.execute(
                    "SELECT id, data FROM events WHERE task_id=? AND type='candidate_created'",
                    (root["root_task_id"],),
                ).fetchall()
                event_ids = [
                    row["id"] for row in rows
                    if json.loads(row["data"] or "{}").get("child") == child_task_id
                ]
                for event_id in event_ids:
                    self._db.execute("DELETE FROM events WHERE id=?", (event_id,))
                if child.credit_scope_id:
                    self._db.execute("DELETE FROM credits WHERE scope_id=?", (child.credit_scope_id,))
                    self._db.execute("DELETE FROM credit_scopes WHERE scope_id=?", (child.credit_scope_id,))
                self._db.execute("DELETE FROM approvals WHERE task_id=?", (child_task_id,))
                self._db.execute("DELETE FROM operations WHERE task_id=?", (child_task_id,))
                self._db.execute("DELETE FROM loop_passes WHERE task_id=?", (child_task_id,))
                self._db.execute("DELETE FROM events WHERE task_id=?", (child_task_id,))
                self._db.execute("DELETE FROM tasks WHERE id=?", (child_task_id,))
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise

    def get_task(self, task_id: str) -> Task | None:
        with self._lock:
            r = self._db.execute(
                "SELECT data, revision FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
        if not r:
            return None
        task = Task.model_validate_json(r["data"])
        task.revision = int(r["revision"])
        return task

    def save_task(self, task: Task) -> None:
        """Save one exact snapshot, refusing to overwrite a newer revision."""
        expected = int(task.revision)
        next_revision = expected + 1
        task.updated = _now_iso()
        task.revision = next_revision
        with self._lock:
            cur = self._db.execute(
                "UPDATE tasks SET status=?, data=?, updated=?, revision=? "
                "WHERE id=? AND revision=?",
                (task.status.value, task.model_dump_json(), task.updated,
                 next_revision, task.id, expected),
            )
            if cur.rowcount != 1:
                self._db.rollback()
                task.revision = expected
                raise TaskConflictError(
                    f"[TASK_CONFLICT] task {task.id} changed since revision {expected}; "
                    "reload and retry"
                )
            self._db.commit()

    def mutate_task(self, task_id: str, mutate, *, retries: int = 1) -> Task | None:
        """Reload, change one logical field group, and CAS-save with one retry."""
        for attempt in range(retries + 1):
            task = self.get_task(task_id)
            if task is None:
                return None
            mutate(task)
            try:
                self.save_task(task)
                return task
            except TaskConflictError:
                if attempt >= retries:
                    raise
        return None

    def set_task_pinned(self, task_id: str, pinned: bool) -> bool:
        return self.mutate_task(
            task_id, lambda task: setattr(task, "pinned", bool(pinned))
        ) is not None

    def set_task_chat_url(self, task_id: str, chat_url: str) -> bool:
        return self.mutate_task(
            task_id, lambda task: setattr(task, "chat_url", str(chat_url))
        ) is not None

    def set_task_mode(self, task_id: str, mode: str, operator_elevated: bool) -> Task | None:
        def change(task: Task) -> None:
            task.permission_mode = mode
            task.operator_elevated = bool(operator_elevated)

        return self.mutate_task(task_id, change)

    def set_task_status(self, task_id: str, status: TaskState | str) -> Task | None:
        target = status if isinstance(status, TaskState) else TaskState(status)
        return self.mutate_task(
            task_id, lambda task: setattr(task, "status", target)
        )

    def pin_task_file(self, task_id: str, path: str) -> Task | None:
        def change(task: Task) -> None:
            if path not in task.pinned_files:
                task.pinned_files.append(path)

        return self.mutate_task(task_id, change)

    def list_tasks(self, project_id: str | None = None, status: str | None = None) -> list[Task]:
        q = "SELECT data, revision FROM tasks"
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
        tasks = []
        for row in rows:
            task = Task.model_validate_json(row["data"])
            task.revision = int(row["revision"])
            tasks.append(task)
        return tasks

    # ---- Run Contracts ----------------------------------------------------

    def confirm_run_contract(self, task_id: str, contract: RunContract) -> Task:
        """Atomically link one immutable contract and optional root credit scope."""
        contract_id = _sid("rc")
        scope_id = _sid("cs") if contract.effort_level != "off" else ""
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT data, revision FROM tasks WHERE id=?", (task_id,)
                ).fetchone()
                if row is None:
                    raise ValueError(f"unknown task {task_id!r}")
                task = Task.model_validate_json(row["data"])
                task.revision = int(row["revision"])
                if task.contract_id:
                    raise ValueError(f"task {task_id} already has a confirmed Run Contract")

                task.contract_id = contract_id
                task.credit_scope_id = scope_id
                if not task.criteria_v2:
                    task.criteria_v2 = [
                        {
                            "id": f"AC-{index}",
                            "text": text,
                            "required": True,
                            "status": "open",
                            "verification_kind": "machine",
                            "evidence_refs": [],
                            "verified_at": "",
                        }
                        for index, text in enumerate(task.acceptance_criteria, 1)
                    ]
                task.updated = _now_iso()
                task.revision += 1
                self._db.execute(
                    "INSERT INTO run_contracts "
                    "(contract_id, root_task_id, contract_json, contract_hash, confirmed_at, revision) "
                    "VALUES (?,?,?,?,?,0)",
                    (contract_id, task_id, contract.model_dump_json(),
                     contract.contract_hash, contract.confirmed_at),
                )
                if scope_id:
                    self._db.execute(
                        "INSERT INTO credit_scopes "
                        "(scope_id, contract_id, task_id, kind, ceiling, created) "
                        "VALUES (?,?,?,?,?,?)",
                        (scope_id, contract_id, task_id, "root",
                         contract.credit_ceiling, _now_iso()),
                    )
                cur = self._db.execute(
                    "UPDATE tasks SET data=?, updated=?, revision=? "
                    "WHERE id=? AND revision=?",
                    (task.model_dump_json(), task.updated, task.revision,
                     task_id, task.revision - 1),
                )
                if cur.rowcount != 1:
                    raise TaskConflictError(
                        f"[TASK_CONFLICT] task {task_id} changed during contract confirmation"
                    )
                self._db.commit()
                return task
            except Exception:
                self._db.rollback()
                raise

    def get_run_contract(self, task_id: str) -> RunContract | None:
        task = self.get_task(task_id)
        if task is None or not task.contract_id:
            return None
        with self._lock:
            row = self._db.execute(
                "SELECT contract_json, contract_hash FROM run_contracts WHERE contract_id=?",
                (task.contract_id,),
            ).fetchone()
        if row is None:
            raise ValueError("[CONTRACT_TAMPERED] linked Run Contract row is missing")
        contract = RunContract.model_validate_json(row["contract_json"])
        if contract.contract_hash != row["contract_hash"]:
            raise ValueError("[CONTRACT_TAMPERED] stored contract hash does not match")
        return contract

    def repair_run_contract(self, task_id: str, contract: RunContract) -> Task:
        task = self.get_task(task_id)
        if task is None or not task.contract_id:
            raise ValueError("[NO_CONTRACT] no linked contract can be repaired")
        if task.status in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
            raise ValueError("[TASK_TERMINAL] terminal contracts cannot be repaired")
        if bool(task.credit_scope_id) != (contract.effort_level != "off"):
            raise ValueError("[REPAIR_SCOPE_MISMATCH] effort scope topology cannot change")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                old = self._db.execute(
                    "SELECT contract_hash FROM run_contracts WHERE contract_id=?",
                    (task.contract_id,),
                ).fetchone()
                self._db.execute(
                    "INSERT INTO run_contracts VALUES (?,?,?,?,?,0) "
                    "ON CONFLICT(contract_id) DO UPDATE SET contract_json=excluded.contract_json, "
                    "contract_hash=excluded.contract_hash, confirmed_at=excluded.confirmed_at, "
                    "revision=run_contracts.revision+1",
                    (task.contract_id, task_id, contract.model_dump_json(),
                     contract.contract_hash, contract.confirmed_at),
                )
                if task.credit_scope_id:
                    changed = self._db.execute(
                        "UPDATE credit_scopes SET ceiling=? WHERE scope_id=? AND contract_id=?",
                        (contract.credit_ceiling, task.credit_scope_id, task.contract_id),
                    )
                    if changed.rowcount != 1:
                        raise ValueError("[REPAIR_SCOPE_MISMATCH] linked scope is missing")
                self._db.execute(
                    "INSERT INTO events (task_id,time,type,data) VALUES (?,?,?,?)",
                    (task_id, _now_iso(), "run_contract_repaired", json.dumps({
                        "old_hash": old["contract_hash"] if old else "missing",
                        "new_hash": contract.contract_hash,
                    }, sort_keys=True)),
                )
                self._db.commit()
                return task
            except Exception:
                self._db.rollback()
                raise

    def extend_credit_scope(self, task_id: str, amount: int, scope_id: str = "") -> RunContract:
        task = self.get_task(task_id)
        contract = self.get_run_contract(task_id)
        if task is None or contract is None:
            raise ValueError("[NO_CONTRACT] task has no confirmed Run Contract")
        if contract.effort_level == "off" or not task.credit_scope_id:
            raise ValueError("[EFFORT_OFF] an extension cannot enable EFFORT")
        target_scope = scope_id or task.credit_scope_id
        old_hash = contract.contract_hash
        data = contract.model_dump(mode="json")
        data["credit_ceiling"] += amount
        data["contract_hash"] = contract_hash(data)
        extended = RunContract.model_validate(data)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                changed = self._db.execute(
                    "UPDATE credit_scopes SET ceiling=ceiling+? "
                    "WHERE scope_id=? AND contract_id=?",
                    (amount, target_scope, task.contract_id),
                )
                if changed.rowcount != 1:
                    raise ValueError("[SCOPE_NOT_FOUND] scope is outside this contract")
                self._db.execute(
                    "UPDATE run_contracts SET contract_json=?, contract_hash=?, revision=revision+1 "
                    "WHERE contract_id=?",
                    (extended.model_dump_json(), extended.contract_hash, task.contract_id),
                )
                self._db.execute(
                    "INSERT INTO events (task_id, time, type, data) VALUES (?,?,?,?)",
                    (task_id, _now_iso(), "contract_extended", json.dumps({
                        "kind": "credits", "amount": amount, "scope_id": target_scope,
                        "old_hash": old_hash, "new_hash": extended.contract_hash,
                    }, sort_keys=True)),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return extended

    def extend_contract_limit(self, task_id: str, kind: str, amount: int) -> RunContract:
        task = self.get_task(task_id)
        contract = self.get_run_contract(task_id)
        if task is None or contract is None:
            raise ValueError("[NO_CONTRACT] task has no confirmed Run Contract")
        field = {"candidates": "candidate_count", "loops": "max_loops"}.get(kind)
        if field is None:
            raise ValueError("[EXTENSION_KIND] unsupported contract limit")
        if getattr(contract, field) == 0:
            raise ValueError(f"[CONTROL_OFF] an extension cannot enable {kind}")
        old_hash = contract.contract_hash
        data = contract.model_dump(mode="json")
        data[field] += amount
        if kind == "candidates":
            data["ultra_enabled"] = True
        data["contract_hash"] = contract_hash(data)
        extended = RunContract.model_validate(data)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.execute(
                    "UPDATE run_contracts SET contract_json=?, contract_hash=?, "
                    "revision=revision+1 WHERE contract_id=?",
                    (extended.model_dump_json(), extended.contract_hash, task.contract_id),
                )
                self._db.execute(
                    "INSERT INTO events (task_id, time, type, data) VALUES (?,?,?,?)",
                    (task_id, _now_iso(), "contract_extended", json.dumps({
                        "kind": kind, "amount": amount, "old_hash": old_hash,
                        "new_hash": extended.contract_hash,
                    }, sort_keys=True)),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return extended

    def apply_approved_extension(
        self, task_id: str, approval_id: str, action: str, request_hash: str,
        kind: str, amount: int, scope_id: str = "",
    ) -> dict:
        """Consume one exact approval and apply its extension in one transaction."""
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                approval = self._db.execute(
                    "SELECT * FROM approvals WHERE id=? AND task_id=? AND action=? "
                    "AND request_hash=?",
                    (approval_id, task_id, action, request_hash),
                ).fetchone()
                if approval is None or approval["status"] != "approved":
                    raise ValueError("[APPROVAL_USED] this extension approval is no longer usable")
                task_row = self._db.execute(
                    "SELECT data FROM tasks WHERE id=?", (task_id,)
                ).fetchone()
                if task_row is None:
                    raise ValueError(f"[TASK_NOT_FOUND] {task_id}")
                task = Task.model_validate_json(task_row["data"])
                if task.status in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
                    raise ValueError("[TASK_TERMINAL] terminal tasks cannot be extended")
                contract_row = self._db.execute(
                    "SELECT contract_json, contract_hash, revision FROM run_contracts "
                    "WHERE contract_id=?", (task.contract_id,),
                ).fetchone()
                if contract_row is None:
                    raise ValueError("[CONTRACT_TAMPERED] linked Run Contract row is missing")
                contract = RunContract.model_validate_json(contract_row["contract_json"])
                if contract.contract_hash != contract_row["contract_hash"]:
                    raise ValueError("[CONTRACT_TAMPERED] stored contract hash does not match")
                old_hash = contract.contract_hash
                new_hash = old_hash
                value = 0
                if kind == "credits":
                    target = scope_id or task.credit_scope_id
                    scope = self._db.execute(
                        "SELECT kind, ceiling FROM credit_scopes "
                        "WHERE scope_id=? AND contract_id=?", (target, task.contract_id),
                    ).fetchone()
                    if scope is None:
                        raise ValueError("[SCOPE_NOT_FOUND] scope is outside this contract")
                    value = int(scope["ceiling"]) + amount
                    self._db.execute(
                        "UPDATE credit_scopes SET ceiling=? WHERE scope_id=?", (value, target)
                    )
                    # The root pot defines the base inherited by candidates. A named
                    # candidate extension is deliberately local to that one pot.
                    if scope["kind"] == "root":
                        data = contract.model_dump(mode="json")
                        data["credit_ceiling"] = value
                        data["contract_hash"] = contract_hash(data)
                        contract = RunContract.model_validate(data)
                        new_hash = contract.contract_hash
                        self._db.execute(
                            "UPDATE run_contracts SET contract_json=?, contract_hash=?, "
                            "revision=revision+1 WHERE contract_id=? AND revision=?",
                            (contract.model_dump_json(), new_hash, task.contract_id,
                             contract_row["revision"]),
                        )
                else:
                    field = {"candidates": "candidate_count", "loops": "max_loops"}.get(kind)
                    if field is None:
                        raise ValueError("[EXTENSION_KIND] unsupported contract limit")
                    data = contract.model_dump(mode="json")
                    data[field] += amount
                    if kind == "candidates":
                        data["ultra_enabled"] = True
                    data["contract_hash"] = contract_hash(data)
                    contract = RunContract.model_validate(data)
                    value = int(getattr(contract, field))
                    new_hash = contract.contract_hash
                    changed = self._db.execute(
                        "UPDATE run_contracts SET contract_json=?, contract_hash=?, "
                        "revision=revision+1 WHERE contract_id=? AND revision=?",
                        (contract.model_dump_json(), new_hash, task.contract_id,
                         contract_row["revision"]),
                    )
                    if changed.rowcount != 1:
                        raise ValueError("[CONTRACT_CONFLICT] contract changed during extension")
                consumed = self._db.execute(
                    "UPDATE approvals SET status='used', decided=? "
                    "WHERE id=? AND status='approved'", (_now_iso(), approval_id),
                )
                if consumed.rowcount != 1:
                    raise ValueError("[APPROVAL_USED] this extension approval is no longer usable")
                self._db.execute(
                    "INSERT INTO events (task_id, time, type, data) VALUES (?,?,?,?)",
                    (task_id, _now_iso(), "contract_extended", json.dumps({
                        "kind": kind, "amount": amount, "scope_id": scope_id,
                        "old_hash": old_hash, "new_hash": new_hash,
                    }, sort_keys=True)),
                )
                self._db.commit()
                return {"kind": kind, "value": value, "contract": contract}
            except Exception:
                self._db.rollback()
                raise

    # ---- effort cycles ----------------------------------------------------

    def effort_status(self, scope_id: str) -> dict:
        with self._lock:
            scope = self._db.execute(
                "SELECT * FROM credit_scopes WHERE scope_id=?", (scope_id,)
            ).fetchone()
            if scope is None:
                raise ValueError("[EFFORT_OFF] this task has no credit scope")
            rows = self._db.execute(
                "SELECT tier, COUNT(*) AS n FROM credits "
                "WHERE scope_id=? AND status='spent' GROUP BY tier", (scope_id,),
            ).fetchall()
            tiers = {row["tier"]: int(row["n"]) for row in rows}
            opened = self._db.execute(
                "SELECT credit_id, task_id, question, opened FROM credits "
                "WHERE scope_id=? AND status='open' ORDER BY opened", (scope_id,),
            ).fetchall()
        return {
            **dict(scope), "spent": sum(tiers.values()), "tiers": tiers,
            "open_cycles": [dict(row) for row in opened],
        }

    def spent_receipts(self, scope_id: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT task_id, receipt_json FROM credits "
                "WHERE scope_id=? AND status='spent' ORDER BY closed", (scope_id,),
            ).fetchall()
        receipts = []
        for row in rows:
            receipt = json.loads(row["receipt_json"] or "{}")
            receipt["task_id"] = row["task_id"]
            receipts.append(receipt)
        return receipts

    def begin_cycle(
        self, task_id: str, question: str, purpose: str, verification_plan: str
    ) -> dict:
        task = self.get_task(task_id)
        if task is None:
            raise ValueError(f"[TASK_NOT_FOUND] {task_id}")
        if task.status in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
            raise ValueError("[TASK_TERMINAL] terminal tasks cannot open effort cycles")
        contract = self.get_run_contract(task_id)
        if contract is None or contract.effort_level == "off" or not task.credit_scope_id:
            raise ValueError("[EFFORT_OFF] this task's contract has no effort scope")
        if not str(question).strip():
            raise ValueError("[QUESTION_REQUIRED] cycle question cannot be empty")
        cycle_id, opened = _sid("cy"), _now_iso()
        metadata = json.dumps({"purpose": str(purpose).strip()}, ensure_ascii=False)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                if self._db.execute(
                    "SELECT 1 FROM credits WHERE task_id=? AND status='open'", (task_id,)
                ).fetchone():
                    raise ValueError("[CYCLE_OPEN] this task already has an open cycle")
                scope = self._db.execute(
                    "SELECT ceiling FROM credit_scopes WHERE scope_id=?",
                    (task.credit_scope_id,),
                ).fetchone()
                if scope is None:
                    raise ValueError("[EFFORT_OFF] credit scope is missing")
                spent = self._db.execute(
                    "SELECT COUNT(*) AS n FROM credits WHERE scope_id=? AND status='spent'",
                    (task.credit_scope_id,),
                ).fetchone()["n"]
                if spent >= scope["ceiling"]:
                    raise ValueError("[NO_CREDITS] the shared effort scope is exhausted")
                self._db.execute(
                    "INSERT INTO credits "
                    "(credit_id, scope_id, task_id, fingerprint, tier, status, question, "
                    "verification_plan, receipt_json, receipt_path, opened, closed) "
                    "VALUES (?,?,?,?,?,'open',?,?,?,?,?,?)",
                    (
                        cycle_id, task.credit_scope_id, task_id, "", "",
                        str(question).strip(), str(verification_plan).strip(), metadata,
                        "", opened, "",
                    ),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return {
            "cycle_id": cycle_id, "scope_id": task.credit_scope_id,
            "effort_level": contract.effort_level, "spent": int(spent),
            "ceiling": int(scope["ceiling"]), "opened": opened,
        }

    def get_cycle(self, task_id: str, cycle_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM credits WHERE credit_id=? AND task_id=?",
                (cycle_id, task_id),
            ).fetchone()
        return dict(row) if row else None

    def abandon_cycle(self, task_id: str, cycle_id: str, reason: str) -> bool:
        task = self.get_task(task_id)
        if task and task.status in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
            raise ValueError("[TASK_TERMINAL] terminal tasks cannot mutate effort cycles")
        with self._lock:
            cur = self._db.execute(
                "UPDATE credits SET status='abandoned', closed=?, receipt_json=? "
                "WHERE credit_id=? AND task_id=? AND status='open'",
                (
                    _now_iso(), json.dumps({"abandon_reason": str(reason).strip()}),
                    cycle_id, task_id,
                ),
            )
            self._db.commit()
        return cur.rowcount == 1

    def spend_cycle(
        self, task_id: str, cycle_id: str, *, tier: str, fingerprint: str,
        receipt: dict, decision_limit: int,
    ) -> dict:
        task = self.get_task(task_id)
        if task and task.status in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
            raise ValueError("[TASK_TERMINAL] terminal tasks cannot spend effort credits")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                cycle = self._db.execute(
                    "SELECT * FROM credits WHERE credit_id=? AND task_id=?",
                    (cycle_id, task_id),
                ).fetchone()
                if cycle is None or cycle["status"] != "open":
                    raise ValueError("[NO_OPEN_CYCLE] cycle is missing or no longer open")
                scope = self._db.execute(
                    "SELECT ceiling FROM credit_scopes WHERE scope_id=?",
                    (cycle["scope_id"],),
                ).fetchone()
                spent = self._db.execute(
                    "SELECT COUNT(*) AS n FROM credits WHERE scope_id=? AND status='spent'",
                    (cycle["scope_id"],),
                ).fetchone()["n"]
                if spent >= scope["ceiling"]:
                    raise ValueError("[NO_CREDITS] the shared effort scope is exhausted")
                duplicate = self._db.execute(
                    "SELECT credit_id FROM credits WHERE scope_id=? AND status='spent' "
                    "AND fingerprint=?", (cycle["scope_id"], fingerprint),
                ).fetchone()
                if duplicate:
                    raise ValueError(
                        f"[RECEIPT_REJECTED] duplicates earlier credit {duplicate['credit_id']}"
                    )
                new_exec_ids = {
                    ref.get("exec_id") for ref in receipt.get("evidence_refs", [])
                    if ref.get("kind") == "execution" and ref.get("exec_id")
                }
                new_exec_fps = {
                    ref.get("execution_fingerprint") for ref in receipt.get("evidence_refs", [])
                    if ref.get("kind") == "execution" and ref.get("execution_fingerprint")
                }
                prior_rows = self._db.execute(
                    "SELECT credit_id, receipt_json FROM credits "
                    "WHERE scope_id=? AND status='spent'", (cycle["scope_id"],),
                ).fetchall()
                for prior in prior_rows:
                    prior_receipt = json.loads(prior["receipt_json"] or "{}")
                    refs = prior_receipt.get("evidence_refs", [])
                    prior_ids = {ref.get("exec_id") for ref in refs if ref.get("exec_id")}
                    prior_fps = {
                        ref.get("execution_fingerprint") for ref in refs
                        if ref.get("execution_fingerprint")
                    }
                    if new_exec_ids.intersection(prior_ids) or new_exec_fps.intersection(prior_fps):
                        raise ValueError(
                            f"[RECEIPT_REJECTED] execution already backed {prior['credit_id']}"
                        )
                if tier == "decision":
                    decisions = self._db.execute(
                        "SELECT COUNT(*) AS n FROM credits WHERE scope_id=? "
                        "AND status='spent' AND tier='decision'", (cycle["scope_id"],),
                    ).fetchone()["n"]
                    if decisions >= decision_limit:
                        raise ValueError("[DECISION_CAP] decision-tier allowance is exhausted")
                path = f"effort/{cycle_id}.md"
                cur = self._db.execute(
                    "UPDATE credits SET fingerprint=?, tier=?, status='spent', "
                    "receipt_json=?, receipt_path=?, closed=? "
                    "WHERE credit_id=? AND task_id=? AND status='open'",
                    (
                        fingerprint, tier,
                        json.dumps(receipt, ensure_ascii=False, sort_keys=True),
                        path, _now_iso(), cycle_id, task_id,
                    ),
                )
                if cur.rowcount != 1:
                    raise ValueError("[NO_OPEN_CYCLE] cycle changed while spending")
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        status = self.effort_status(cycle["scope_id"])
        return {**status, "receipt_path": path}

    # ---- refinement loops -------------------------------------------------

    def begin_loop_pass(
        self, task_id: str, *, verification_kind: str, input_state_hash: str,
        target_weakness: str, directive: str, repeat_key: str,
        verification_plan: str,
    ) -> dict:
        task = self.get_task(task_id)
        if task and task.status in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
            raise ValueError("[TASK_TERMINAL] terminal tasks cannot open refinement passes")
        contract = self.get_run_contract(task_id)
        if contract is None or contract.max_loops == 0:
            raise ValueError("[LOOPS_OFF] this contract has no refinement passes")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                rows = self._db.execute(
                    "SELECT pass_id, pass_number, status, repeat_key FROM loop_passes "
                    "WHERE task_id=? ORDER BY pass_number", (task_id,),
                ).fetchall()
                duplicate = next((row for row in rows if row["repeat_key"] == repeat_key), None)
                if duplicate:
                    raise ValueError(
                        f"[LOOP_REPEAT] repeats earlier pass {duplicate['pass_id']}"
                    )
                if any(row["status"] == "pending_operator" for row in rows):
                    raise ValueError("[LOOP_PENDING_OPERATOR] confirm the pending pass first")
                if any(row["status"] == "open" for row in rows):
                    raise ValueError("[LOOP_OPEN] this task already has an open pass")
                closed = [row for row in rows if row["status"] != "abandoned"]
                if len(closed) >= contract.max_loops:
                    raise ValueError("[LOOP_LIMIT] locked refinement-pass limit is exhausted")
                if len(closed) >= 2 and all(
                    row["status"] == "no_gain" for row in closed[-2:]
                ):
                    raise ValueError("[LOOP_PLATEAU] two consecutive passes found no gain")
                pass_id, number = _sid("lp"), len(closed) + 1
                self._db.execute(
                    "INSERT INTO loop_passes "
                    "(pass_id, task_id, pass_number, verification_kind, input_state_hash, "
                    "target_weakness, directive, repeat_key, status, verification_plan, opened) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (pass_id, task_id, number, verification_kind, input_state_hash,
                     target_weakness, directive, repeat_key, "open", verification_plan,
                     _now_iso()),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return {"pass_id": pass_id, "pass_number": number, "max_loops": contract.max_loops}

    def get_loop_pass(self, task_id: str, pass_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM loop_passes WHERE task_id=? AND pass_id=?",
                (task_id, pass_id),
            ).fetchone()
        return dict(row) if row else None

    def loop_passes(self, task_id: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM loop_passes WHERE task_id=? ORDER BY pass_number",
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def complete_loop_pass(
        self, task_id: str, pass_id: str, *, status: str,
        output_state_hash: str, delta_summary: str, proposed_outcome: str = "",
    ) -> None:
        with self._lock:
            cur = self._db.execute(
                "UPDATE loop_passes SET status=?, output_state_hash=?, "
                "delta_summary=?, proposed_outcome=?, closed=? "
                "WHERE task_id=? AND pass_id=? AND status='open'",
                (status, output_state_hash, delta_summary, proposed_outcome,
                 _now_iso(), task_id, pass_id),
            )
            if cur.rowcount != 1:
                self._db.rollback()
                raise ValueError("[NO_OPEN_LOOP] pass is missing or no longer open")
            self._db.commit()

    def confirm_operator_loop(self, task_id: str, pass_id: str, outcome: str) -> None:
        with self._lock:
            cur = self._db.execute(
                "UPDATE loop_passes SET status=?, closed=? "
                "WHERE task_id=? AND pass_id=? AND status='pending_operator'",
                (outcome, _now_iso(), task_id, pass_id),
            )
            if cur.rowcount != 1:
                self._db.rollback()
                raise ValueError("[NO_PENDING_LOOP] no operator loop awaits confirmation")
            self._db.commit()

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
                "SELECT id, task_id, time, type, data FROM events "
                "WHERE task_id=? ORDER BY id DESC LIMIT ?",
                (task_id, limit),
            ).fetchall()
        out = []
        for r in reversed(rows):
            d = {
                "event_id": f"db:{r['id']}",
                "task_id": r["task_id"],
                "time": r["time"],
                "type": r["type"],
            }
            try:
                d.update(json.loads(r["data"]))
            except ValueError:
                pass
            out.append(d)
        return out

    # ---- approvals ---------------------------------------------------------

    def add_approval(self, task_id: str, action: str, detail: str, request_hash: str = "") -> str:
        with self._lock:
            if request_hash:
                existing = self._db.execute(
                    "SELECT id FROM approvals WHERE task_id=? AND action=? "
                    "AND request_hash=? AND status='pending' ORDER BY created LIMIT 1",
                    (task_id, action, request_hash),
                ).fetchone()
                if existing:
                    return existing["id"]
            aid = _sid("A")
            self._db.execute(
                "INSERT INTO approvals (id, task_id, action, detail, status, created, decided, request_hash) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (aid, task_id, action, detail, "pending", _now_iso(), None, request_hash),
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

    def grantable_approval(self, task_id: str, action: str, request_hash: str = "") -> dict | None:
        """An approved-but-unused approval matching this EXACT request (one-shot).
        Bound to the request hash, not just the action class — approving
        `pip install X` must not authorize `pip install Y`."""
        with self._lock:
            r = self._db.execute(
                "SELECT * FROM approvals WHERE task_id=? AND action=? AND request_hash=? "
                "AND status='approved' ORDER BY created LIMIT 1",
                (task_id, action, request_hash),
            ).fetchone()
            return dict(r) if r else None

    def matching_approval(self, task_id: str, action: str, request_hash: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM approvals WHERE task_id=? AND action=? AND request_hash=? "
                "ORDER BY created DESC LIMIT 1", (task_id, action, request_hash),
            ).fetchone()
        return dict(row) if row else None

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

    def get_operation(self, op_id: str, task_id: str, tool: str) -> dict | None:
        """Scoped to (task, tool): task B reusing task A's operation_id must
        re-execute, never receive A's cached result."""
        with self._lock:
            r = self._db.execute(
                "SELECT * FROM operations WHERE op_id=? AND task_id=? AND tool=?",
                (op_id, task_id, tool),
            ).fetchone()
            return dict(r) if r else None

    def record_operation(
        self,
        op_id: str,
        task_id: str,
        tool: str,
        result: str,
        request_hash: str = "",
    ) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO operations "
                "(op_id, task_id, tool, created, result, request_hash) VALUES (?,?,?,?,?,?)",
                (op_id, task_id, tool, _now_iso(), result, request_hash),
            )
            self._db.commit()
