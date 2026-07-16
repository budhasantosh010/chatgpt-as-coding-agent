"""Cockpit HTTP app: JSON API + SSE feed + static UI, localhost-only.

Security model (docs/ROADMAP.md §3):
  * Bind 127.0.0.1 only (the supervisor enforces host); never funneled.
  * Every MUTATION (POST/PATCH/DELETE) requires:
      - a CSRF token in the custom header `X-Cockpit-Token` (a random webpage
        cannot set a custom header cross-origin without a CORS preflight, which
        we never grant), AND
      - an Origin/Referer that is the cockpit itself.
  * GET + the SSE feed are read-only and Origin-checked. EventSource can't send
    custom headers, so the feed relies on same-origin + read-only, never on the
    token (the SSE×CSRF collision, resolved).

The cockpit acts on the SAME primitives the operator CLI uses (TaskStore,
Config, git, allowlist) plus its own HarnessServer for actions that need the
executor (create task, fork). It never runs behind the model.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import (
    JSONResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from ..config import Config

STATIC = Path(__file__).parent / "static"


class Cockpit:
    """Holds cockpit-wide state: the CSRF token, the engine-facing ingest token,
    a HarnessServer for executor-backed actions, and the live EventBus."""

    def __init__(self, config: Config, supervisor=None):
        from ..context import HarnessServer

        self.config = config
        self.supervisor = supervisor
        self.csrf_token = secrets.token_urlsafe(24)
        self.ingest_token = config.event_token or secrets.token_urlsafe(24)
        self.server = HarnessServer(config)
        self.events = self.server.events  # operator actions publish here
        self.store = self.server.tasks

    def origin_ok(self, request) -> bool:
        host = f"127.0.0.1:{self.config.cockpit_port}"
        allowed = {f"http://{host}", f"http://localhost:{self.config.cockpit_port}"}
        origin = request.headers.get("origin")
        if origin is not None:
            return origin in allowed
        # No Origin (e.g. same-origin GET): fall back to Referer host check.
        ref = request.headers.get("referer", "")
        return any(ref.startswith(a) for a in allowed) or ref == ""

    def csrf_ok(self, request) -> bool:
        return (
            self.origin_ok(request)
            and request.headers.get("x-cockpit-token") == self.csrf_token
        )


def _err(msg: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=status)


def build_cockpit_app(cockpit: Cockpit) -> Starlette:
    cfg = cockpit.config

    # ---- helpers -----------------------------------------------------------

    def guard(request) -> JSONResponse | None:
        if not cockpit.csrf_ok(request):
            return _err("forbidden (bad origin or CSRF token)", 403)
        return None

    def task_dict(t) -> dict:
        from ..policy import effective_mode

        eff = effective_mode(t.permission_mode, operator_elevated=t.operator_elevated,
                              ceiling=cfg.max_mode, sandbox=cfg.sandbox)
        return {
            "id": t.id, "project_id": t.project_id, "title": t.title, "goal": t.goal,
            "status": t.status.value, "mode": t.permission_mode, "effective_mode": eff,
            "operator_elevated": t.operator_elevated,
            "worktree_path": t.worktree_path, "workspace_path": t.workspace_path,
            "changed_files": t.changed_files, "checkpoints": t.checkpoints,
            "test_results": t.test_results, "acceptance_criteria": t.acceptance_criteria,
            "pinned_files": t.pinned_files, "chat_url": t.chat_url,
            "parent_id": t.parent_id, "created": t.created, "updated": t.updated,
        }

    # ---- static + bootstrap ------------------------------------------------

    async def index(request):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        # Inject the CSRF token + cockpit port so same-origin JS can use them.
        boot = (f'<script>window.COCKPIT={{token:"{cockpit.csrf_token}",'
                f'port:{cfg.cockpit_port}}};</script>')
        html = html.replace("<!--BOOT-->", boot)
        return Response(html, media_type="text/html")

    # ---- read endpoints (GET, origin-checked) ------------------------------

    async def api_state(request):
        if not cockpit.origin_ok(request):
            return _err("forbidden", 403)
        projects = []
        seen = set()
        for t in cockpit.store.list_tasks():
            if t.project_id not in seen:
                seen.add(t.project_id)
        for p in _all_projects(cockpit):
            projects.append(p)
        return JSONResponse({
            "projects": projects,
            "tasks": [task_dict(t) for t in cockpit.store.list_tasks()],
            "roots": [str(r) for r in cfg.workspace_roots],
            "engine": cockpit.supervisor.engine_status() if cockpit.supervisor else "n/a",
            "max_mode": cfg.max_mode,
            "modes": ["read_only", "plan", "build_ask", "auto_workspace"],
        })

    async def api_approvals(request):
        if not cockpit.origin_ok(request):
            return _err("forbidden", 403)
        return JSONResponse({"approvals": cockpit.store.pending_approvals()})

    async def api_files(request):
        if not cockpit.origin_ok(request):
            return _err("forbidden", 403)
        path = request.query_params.get("path", "")
        try:
            base = _confined(cockpit, path)
        except ValueError as exc:
            return _err(str(exc))
        entries = []
        for child in sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if child.name == ".git":
                continue
            entries.append({"name": child.name, "dir": child.is_dir(),
                            "path": str(child)})
        return JSONResponse({"path": str(base), "entries": entries})

    async def api_diff(request):
        if not cockpit.origin_ok(request):
            return _err("forbidden", 403)
        tid = request.query_params.get("task_id", "")
        t = cockpit.store.get_task(tid)
        if t is None:
            return _err("unknown task", 404)
        from ..tools import git as gittool

        hc = _hc_for(cockpit, t)
        try:
            diff = await gittool.git_diff(hc, None)
        except Exception as exc:  # noqa: BLE001
            diff = f"(diff unavailable: {exc})"
        return JSONResponse({"task_id": tid, "diff": diff})

    async def sse(request):
        # Read-only live feed. Origin-checked; no token (EventSource can't set
        # custom headers). Replays from Last-Event-ID, then polls the bus.
        if not cockpit.origin_ok(request):
            return _err("forbidden", 403)
        last = int(request.headers.get("last-event-id")
                   or request.query_params.get("since") or 0)

        async def stream():
            nonlocal last
            yield b": connected\n\n"
            while True:
                # Emit pending events FIRST (flush before checking disconnect),
                # so a client that reads-then-closes still gets its data.
                for e in cockpit.events.since(last):
                    last = e["event_id"]
                    yield (f"id: {last}\nevent: {e['type']}\n"
                           f"data: {json.dumps(e)}\n\n").encode("utf-8")
                if await request.is_disconnected():
                    break
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---- ingest (engine -> cockpit event push) -----------------------------

    async def ingest(request):
        # The engine child POSTs its tool-call events here with the shared token.
        if request.headers.get("x-harness-event-token") != cockpit.ingest_token:
            return _err("forbidden", 403)
        try:
            event = json.loads(await request.body())
        except ValueError:
            return _err("bad json")
        d = event.get("data", {})
        # Re-publish into the cockpit bus so the SSE feed is one unified stream.
        cockpit.events.publish(event.get("type", "tool_call"),
                               task_id=event.get("task_id"), **d)
        return JSONResponse({"ok": True})

    # ---- mutations (POST, CSRF-guarded) ------------------------------------

    async def api_new_task(request):
        if (g := guard(request)):
            return g
        body = await _json(request)
        project = body.get("project_path", "")
        goal = body.get("goal", "").strip()
        mode = body.get("mode", "auto_workspace")
        if not goal:
            return _err("a goal is required")
        from ..tasks import tools as tt

        try:
            out = await tt.start_task(cockpit.server, project, goal, mode)
        except Exception as exc:  # noqa: BLE001
            return _err(str(exc))
        if "APPROVAL REQUIRED" in out:
            return JSONResponse({"needs_approval": True, "message": out})
        tid = out.split()[2]
        return JSONResponse({"task_id": tid, "message": out})

    async def api_create_project(request):
        if (g := guard(request)):
            return g
        body = await _json(request)
        from ..tasks import tools as tt

        try:
            out = await tt.create_project(cockpit.server, body.get("path", ""),
                                          body.get("name", ""))
        except Exception as exc:  # noqa: BLE001
            return _err(str(exc))
        return JSONResponse({"message": out})

    async def api_set_mode(request):
        if (g := guard(request)):
            return g
        body = await _json(request)
        tid, mode = body.get("task_id"), body.get("mode")
        from ..policy import VALID_MODES, mode_rank

        if mode not in VALID_MODES:
            return _err("invalid mode")
        t = cockpit.store.get_task(tid)
        if t is None:
            return _err("unknown task", 404)
        t.permission_mode = mode
        # Cockpit is operator-only, so choosing full/bypass here is legitimate
        # elevation (checklist 2.3) — mark it so the ceiling lets it through.
        t.operator_elevated = mode_rank(mode) > mode_rank(cfg.max_mode)
        cockpit.store.save_task(t)
        cockpit.store.add_event(tid, "cockpit_set_mode", mode=mode)
        return JSONResponse({"ok": True, "task": task_dict(t)})

    async def api_fork(request):
        if (g := guard(request)):
            return g
        body = await _json(request)
        from ..tasks import tools as tt

        try:
            out = await tt.fork_task(cockpit.server, body.get("task_id"), body.get("goal", ""))
        except Exception as exc:  # noqa: BLE001
            return _err(str(exc))
        return JSONResponse({"message": out})

    async def api_approval_decide(request):
        if (g := guard(request)):
            return g
        body = await _json(request)
        aid, decision = body.get("id"), body.get("decision")
        if decision not in ("approve", "deny"):
            return _err("decision must be approve/deny")
        approval = cockpit.store.get_approval(aid)
        ok = cockpit.store.decide_approval(aid, "approved" if decision == "approve" else "denied")
        if ok and body.get("remember") and decision == "approve" and approval \
                and approval["action"] == "command_arbitrary":
            from .. import allowlist

            t = cockpit.store.get_task(approval["task_id"])
            detail = approval.get("detail") or ""
            cmd = detail.split(": ", 1)[1] if ": " in detail else detail
            if t and cmd:
                allowlist.allow(cfg.state_dir, t.workspace_path, cmd)
        return JSONResponse({"ok": ok})

    async def api_restore(request):
        if (g := guard(request)):
            return g
        body = await _json(request)
        t = cockpit.store.get_task(body.get("task_id"))
        if t is None:
            return _err("unknown task", 404)
        from ..tools import git as gittool

        hc = _hc_for(cockpit, t)
        try:
            out = await gittool.restore_checkpoint(hc, body.get("checkpoint_id", ""))
        except Exception as exc:  # noqa: BLE001
            return _err(str(exc))
        return JSONResponse({"message": out})

    async def api_pin_file(request):
        if (g := guard(request)):
            return g
        body = await _json(request)
        t = cockpit.store.get_task(body.get("task_id"))
        if t is None:
            return _err("unknown task", 404)
        p = body.get("path", "")
        if p and p not in t.pinned_files:
            t.pinned_files.append(p)
            cockpit.store.save_task(t)
        return JSONResponse({"ok": True, "task": task_dict(t)})

    async def api_upload(request):
        # Drag a FILE into a session (checklist 3.7): copy bytes into the task's
        # working folder. Confined to the task's workspace; name is basenamed.
        if (g := guard(request)):
            return g
        import base64

        body = await _json(request)
        t = cockpit.store.get_task(body.get("task_id"))
        if t is None:
            return _err("unknown task", 404)
        name = Path(body.get("name", "")).name
        if not name:
            return _err("no filename")
        try:
            data = base64.b64decode(body.get("b64", ""))
        except Exception:  # noqa: BLE001
            return _err("bad file data")
        dest_dir = Path(t.worktree_path or t.workspace_path)
        dest = dest_dir / name
        try:
            _confined(cockpit, str(dest))  # must land inside a root
        except ValueError as exc:
            return _err(str(exc))
        dest.write_bytes(data)
        if str(dest) not in t.pinned_files:
            t.pinned_files.append(str(dest))
            cockpit.store.save_task(t)
        return JSONResponse({"ok": True, "path": str(dest)})

    async def api_set_chat_url(request):
        if (g := guard(request)):
            return g
        body = await _json(request)
        t = cockpit.store.get_task(body.get("task_id"))
        if t is None:
            return _err("unknown task", 404)
        t.chat_url = body.get("chat_url", "").strip()
        cockpit.store.save_task(t)
        return JSONResponse({"ok": True})

    async def api_pick_folder(request):
        # Native OS folder dialog (checklist 1.4) — browsers can't reveal a
        # folder's absolute path, so the supervisor opens the real dialog.
        if (g := guard(request)):
            return g
        if cockpit.supervisor is None:
            return _err("folder picker needs the supervisor (harness up)", 501)
        path = await asyncio.get_event_loop().run_in_executor(
            None, cockpit.supervisor.pick_folder)
        return JSONResponse({"path": path or ""})

    async def api_add_root(request):
        if (g := guard(request)):
            return g
        body = await _json(request)
        path = body.get("path", "")
        if not Path(path).is_dir():
            return _err("not a directory")
        import os

        real = os.path.realpath(path)
        current = Config.load_extra_roots(cfg.state_dir)
        if real not in current:
            current.append(real)
            Config._roots_file(cfg.state_dir).write_text(
                json.dumps(current, indent=2), encoding="utf-8")
        return JSONResponse({"ok": True, "needs_restart": True, "root": real})

    async def api_restart_engine(request):
        if (g := guard(request)):
            return g
        if cockpit.supervisor is None:
            return _err("no supervisor to restart the engine", 501)
        info = cockpit.supervisor.engine_busy()
        if info and not (await _json(request)).get("force"):
            return JSONResponse({"needs_confirm": True, "busy": info})
        cockpit.supervisor.restart_engine()
        return JSONResponse({"ok": True})

    routes = [
        Route("/", index),
        Route("/api/state", api_state),
        Route("/api/approvals", api_approvals),
        Route("/api/files", api_files),
        Route("/api/diff", api_diff),
        Route("/events", sse),
        Route("/_ingest", ingest, methods=["POST"]),
        Route("/api/task/new", api_new_task, methods=["POST"]),
        Route("/api/project/create", api_create_project, methods=["POST"]),
        Route("/api/task/mode", api_set_mode, methods=["POST"]),
        Route("/api/task/fork", api_fork, methods=["POST"]),
        Route("/api/task/pin", api_pin_file, methods=["POST"]),
        Route("/api/task/upload", api_upload, methods=["POST"]),
        Route("/api/task/chat_url", api_set_chat_url, methods=["POST"]),
        Route("/api/approval/decide", api_approval_decide, methods=["POST"]),
        Route("/api/restore", api_restore, methods=["POST"]),
        Route("/api/pick_folder", api_pick_folder, methods=["POST"]),
        Route("/api/root/add", api_add_root, methods=["POST"]),
        Route("/api/engine/restart", api_restart_engine, methods=["POST"]),
    ]
    app = Starlette(routes=routes)
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
    return app


# ---- module helpers --------------------------------------------------------


def _all_projects(cockpit) -> list[dict]:
    rows = []
    with cockpit.store._lock:
        cur = cockpit.store._db.execute("SELECT id, path, name FROM projects ORDER BY created")
        for r in cur.fetchall():
            rows.append({"id": r["id"], "path": r["path"], "name": r["name"]})
    return rows


def _confined(cockpit, path: str) -> Path:
    import os

    from ..security import is_within

    if not path:
        roots = cockpit.config.workspace_roots
        return roots[0] if roots else Path.home()
    cand = Path(os.path.realpath(path))
    if not any(is_within(cand, r) for r in cockpit.config.workspace_roots):
        raise ValueError("path is outside approved roots")
    if not cand.is_dir():
        cand = cand.parent
    return cand


def _hc_for(cockpit, task):
    """A context bound to a task's workspace for read/restore actions."""
    hc = cockpit.server.context_for(task.id, "cockpit")
    return hc


async def _json(request) -> dict:
    try:
        return json.loads(await request.body() or b"{}")
    except ValueError:
        return {}
