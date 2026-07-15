"""CLI entrypoint: ``python -m harness [serve|doctor|url]``."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from .config import Config


def _cmd_serve(config: Config) -> int:
    import uvicorn

    from .app import build_asgi_app

    app, _server = build_asgi_app(config)
    print(f"chatgpt-code-harness serving on http://{config.host}:{config.port}")
    print(f"MCP endpoint (local): http://{config.host}:{config.port}{config.mcp_path}")
    print(f"mode: {config.mode} | workspace roots: {[str(r) for r in config.workspace_roots]}")
    print("Expose to ChatGPT with: tailscale funnel " + str(config.port))
    # access_log disabled so the secret route path never lands in logs.
    uvicorn.run(app, host=config.host, port=config.port, access_log=False, log_level="info")
    return 0


def _cmd_stdio(config: Config) -> int:
    """Serve the same tool surface over stdio for local MCP clients (Claude
    Desktop, IDE extensions, etc.). No network, so no security middleware — the
    OS process boundary is the trust boundary."""
    from .context import HarnessServer
    from .server import build_mcp

    server = HarnessServer(config)
    mcp = build_mcp(config, server)
    print(f"chatgpt-code-harness (stdio) | mode: {config.mode} | sandbox: {config.sandbox}", file=sys.stderr)
    mcp.run(transport="stdio")
    return 0


def _tailnet_dnsname() -> str | None:
    import json
    import subprocess

    if shutil.which("tailscale") is None:
        return None
    try:
        out = subprocess.run(
            ["tailscale", "status", "--json"], capture_output=True, text=True, timeout=10
        )
        if out.returncode != 0:
            return None
        data = json.loads(out.stdout)
        name = (data.get("Self", {}) or {}).get("DNSName", "").rstrip(".")
        return name or None
    except (OSError, ValueError):
        return None


def _cmd_url(config: Config) -> int:
    print("Local MCP URL (keep the secret route private):")
    print(f"  {config.local_url()}")
    print()
    dns = _tailnet_dnsname()
    if dns:
        print("Public MCP URL for the ChatGPT connector (once `tailscale funnel` runs):")
        print(f"  https://{dns}{config.mcp_path}")
    else:
        print("Public URL once `tailscale funnel` is running:")
        print(f"  https://<machine>.<tailnet>.ts.net{config.mcp_path}")
        print("  (start Tailscale to auto-fill the hostname here)")
    return 0


def _cmd_approvals(config: Config, action: str, approval_id: str | None) -> int:
    """Operator-only approval queue for build_ask / auto_workspace modes.
    ChatGPT can *request* an action; only this local CLI can grant it."""
    from .tasks.store import TaskStore

    store = TaskStore(config.state_dir / "tasks.db")
    if action == "list":
        pending = store.pending_approvals()
        if not pending:
            print("No pending approvals.")
            return 0
        print("Pending approvals:")
        for a in pending:
            print(f"  {a['id']}  task={a['task_id']}  [{a['action']}]  {a['detail']}")
        print("\nApprove with: python -m harness approvals approve <id>")
        return 0
    if not approval_id:
        print(f"Usage: python -m harness approvals {action} <approval_id>")
        return 2
    status = "approved" if action == "approve" else "denied"
    ok = store.decide_approval(approval_id, status)
    print(f"{status.capitalize()} {approval_id}." if ok else f"{approval_id}: not found or already decided.")
    return 0 if ok else 1


def _cmd_doctor(config: Config) -> int:
    print("== chatgpt-code-harness doctor ==\n")
    print("Config:")
    for key, value in config.redacted().items():
        print(f"  {key}: {value}")
    print()

    ok = True
    print("Checks:")
    for root in config.workspace_roots:
        exists = root.exists()
        ok = ok and exists
        print(f"  [{'ok' if exists else 'MISSING'}] workspace root: {root}")
    checked_tools = ["git", "rg", "tailscale"]
    if config.sandbox == "docker":
        checked_tools.append("docker")
    for tool in checked_tools:
        found = shutil.which(tool)
        note = found or "not found"
        if tool == "tailscale" and not found:
            note += " (needed only to expose to ChatGPT)"
        elif tool == "rg" and not found:
            note += " (grep falls back to pure Python)"
        elif tool == "docker" and not found:
            note += " (REQUIRED: HARNESS_SANDBOX=docker but docker is missing)"
        docker_missing = tool == "docker" and not found
        if docker_missing:
            ok = False
        print(f"  [{'ok' if found else ('MISSING' if docker_missing else 'warn')}] {tool}: {note}")
    print(f"  [ok] output scrubbing: {'on' if config.scrub_output else 'OFF'}")
    print(f"  [ok] execution backend: {config.sandbox}")
    if config.sandbox == "docker":
        print("       note: run_command / start_process / diagnostics run in the "
              "container;")
        print("       internal git & ripgrep still run on the host (hooks/config "
              "neutralized).")
    print(f"  [ok] no-task fallback mode: {config.no_task_mode}  |  max requestable mode: {config.max_mode}")
    print(f"  [ok] commit hooks: {'ON (repo hooks run on host)' if config.commit_hooks else 'off (repo hooks neutralized)'}")
    print(f"  [ok] unrecognized commands in auto_workspace: {config.arbitrary_commands}"
          + ("  (classifier is advisory, not a boundary)" if config.arbitrary_commands == "allow" else ""))
    print(f"  [ok] state dir: {config.state_dir}")
    print(f"  [{'ok' if config.bearer_token else 'warn'}] bearer token: "
          f"{'set' if config.bearer_token else 'not set (secret route is the gate)'}")
    print()
    print("Doctor finished." + ("" if ok else " Fix MISSING items above."))
    return 0 if ok else 1


def _cmd_watch(config: Config, lines: int) -> int:
    """Live activity feed — the 'CLI moving while ChatGPT works' view. Tails the
    audit log and prints each tool call as it happens: which task, what mode,
    which tool, on what. Ctrl+C to stop."""
    import json as _json
    import time

    path = config.state_dir / "audit.jsonl"
    icons = {"read": "READ ", "write": "WRITE", "execute": "EXEC "}

    def show(rec: dict) -> None:
        t = (rec.get("time") or "")[11:19]
        cap = icons.get(rec.get("capability") or "", "     ")
        task = rec.get("task_id") or "(no task)"
        mode = rec.get("mode") or "?"
        detail = rec.get("detail") or ""
        if len(detail) > 60:
            detail = detail[:57] + "..."
        # flush: this is a live feed, so it must never sit in a buffer.
        print(f"{t}  {cap}  [{mode:<14}] {rec.get('tool',''):<18} {detail}   ({task})",
              flush=True)

    print(f"Watching {path}\n  Ctrl+C to stop. Waiting for ChatGPT activity...\n", flush=True)
    print(f"{'TIME':<8}  {'WHAT':<5}  {'MODE':<16} {'TOOL':<18} TARGET   (TASK)", flush=True)
    print("-" * 100, flush=True)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    # Show recent history first, then stream new lines as they're appended.
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        history = fh.readlines()
        for line in history[-lines:]:
            try:
                show(_json.loads(line))
            except ValueError:
                pass
        fh.seek(0, 2)
        try:
            while True:
                line = fh.readline()
                if not line:
                    time.sleep(0.4)
                    continue
                try:
                    show(_json.loads(line))
                except ValueError:
                    pass
        except KeyboardInterrupt:
            print("\nStopped watching.")
    return 0


def _cmd_tasks(config: Config, action: str, task_id: str | None, mode: str | None) -> int:
    """Operator-only task administration. `set-mode` is the ONLY way to run a
    task above the HARNESS_MAX_MODE ceiling — ChatGPT cannot grant itself
    full/bypass_sandboxed."""
    from .policy import VALID_MODES, effective_mode, mode_rank
    from .tasks.store import TaskStore

    store = TaskStore(config.state_dir / "tasks.db")
    if action == "list":
        tasks = store.list_tasks()
        if not tasks:
            print("No tasks yet. ChatGPT creates them with start_task.")
            return 0
        print(f"{'TASK ID':<14} {'STATE':<12} {'MODE (effective)':<24} GOAL")
        print("-" * 96)
        for t in tasks:
            eff = effective_mode(t.permission_mode, operator_elevated=t.operator_elevated,
                                 ceiling=config.max_mode, sandbox=config.sandbox)
            shown = eff if eff == t.permission_mode else f"{eff} (asked {t.permission_mode})"
            star = "*" if t.operator_elevated else " "
            print(f"{t.id:<14} {t.status.value:<12} {star}{shown:<23} {(t.title or t.goal)[:40]}")
        print("\n* = operator-elevated above the ceiling."
              f"  Server ceiling: {config.max_mode}")
        return 0
    if action == "set-mode":
        if not task_id or not mode:
            print("Usage: python -m harness tasks set-mode <task_id> <mode>")
            return 2
        if mode not in VALID_MODES:
            print(f"mode must be one of {VALID_MODES}")
            return 2
        task = store.get_task(task_id)
        if task is None:
            print(f"Unknown task {task_id!r}.")
            return 1
        task.permission_mode = mode
        # Elevation flag only when the operator actually raised it above the
        # ceiling; otherwise the normal ceiling keeps applying.
        task.operator_elevated = mode_rank(mode) > mode_rank(config.max_mode)
        store.save_task(task)
        store.add_event(task_id, "operator_set_mode", mode=mode,
                        elevated=task.operator_elevated)
        note = " (operator-elevated above the ceiling)" if task.operator_elevated else ""
        print(f"Task {task_id} mode set to {mode}{note}.")
        return 0
    print("Usage: python -m harness tasks set-mode <task_id> <mode>")
    return 2


def _cmd_worktrees(config: Config, action: str) -> int:
    """Prune worktrees of terminal (completed/cancelled/failed) tasks. Worktrees
    are never auto-deleted — the diff is the operator's review artifact — so
    this is the explicit cleanup step."""
    import subprocess

    from .tasks.model import _TERMINAL
    from .tasks.store import TaskStore

    if action != "prune":
        print("Usage: python -m harness worktrees prune")
        return 2
    store = TaskStore(config.state_dir / "tasks.db")
    pruned = kept = 0
    for task in store.list_tasks():
        wt = task.worktree_path
        if not wt or task.status not in _TERMINAL:
            if wt:
                kept += 1
            continue
        if not Path(wt).exists():
            continue
        r = subprocess.run(
            ["git", "-C", task.workspace_path, "worktree", "remove", "--force", wt],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            pruned += 1
            print(f"  pruned {wt}  (task {task.id}, {task.status.value})")
        else:
            print(f"  FAILED {wt}: {(r.stderr or r.stdout).strip()[:120]}")
    print(f"Pruned {pruned} worktree(s); {kept} active task worktree(s) kept.")
    return 0


def _cmd_roots(config: Config, action: str, path: str | None) -> int:
    """Manage approved workspace roots (state_dir/roots.json). Operator-only —
    there is no MCP tool for this, and roots.json lives outside every workspace
    root, so the model cannot grant itself new folders. Restart to apply."""
    import json as _json

    roots_file = Config._roots_file(config.state_dir)
    current = Config.load_extra_roots(config.state_dir)

    if action == "list":
        env_roots = [str(r) for r in config.workspace_roots]
        print("Active workspace roots (env + roots.json + defaults):")
        for r in env_roots:
            print(f"  {r}")
        print(f"\nroots.json ({roots_file}):")
        for r in current:
            print(f"  {r}")
        if not current:
            print("  (none — add one with: python -m harness roots add <path>)")
        return 0

    if not path:
        print(f"Usage: python -m harness roots {action} <path>")
        return 2
    resolved = str(Path(path).expanduser())

    if action == "add":
        if not Path(resolved).is_dir():
            print(f"Not a directory (create it first): {resolved}")
            return 1
        real = os.path.realpath(resolved)
        if real in current:
            print(f"Already an approved root: {real}")
            return 0
        current.append(real)
        roots_file.write_text(_json.dumps(current, indent=2), encoding="utf-8")
        print(f"Added workspace root: {real}")
        print("Restart the server (run.ps1) to apply.")
        return 0

    if action == "remove":
        real = os.path.realpath(resolved)
        remaining = [r for r in current if r not in (resolved, real)]
        if len(remaining) == len(current):
            print(f"Not in roots.json: {resolved}")
            return 1
        roots_file.write_text(_json.dumps(remaining, indent=2), encoding="utf-8")
        print(f"Removed workspace root: {resolved}")
        print("Restart the server to apply.")
        return 0

    print("Usage: python -m harness roots [list|add|remove] <path>")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness", description="ChatGPT code harness MCP server")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the MCP server over HTTP (default; for ChatGPT)")
    sub.add_parser("stdio", help="run the MCP server over stdio (for local MCP clients)")
    sub.add_parser("doctor", help="validate config and environment")
    sub.add_parser("url", help="print the MCP endpoint URLs")
    ap = sub.add_parser("approvals", help="operator approval queue (list/approve/deny)")
    ap.add_argument("action", nargs="?", choices=["list", "approve", "deny"], default="list")
    ap.add_argument("approval_id", nargs="?", default=None)
    tp = sub.add_parser("tasks", help="see tasks + their modes (list), or elevate one (set-mode)")
    tp.add_argument("action", nargs="?", choices=["list", "set-mode"], default="list")
    tp.add_argument("task_id", nargs="?", default=None)
    tp.add_argument("mode", nargs="?", default=None)
    wa = sub.add_parser("watch", help="live feed of what ChatGPT is doing right now")
    wa.add_argument("--lines", type=int, default=15, help="how much history to show first")
    wp = sub.add_parser("worktrees", help="prune worktrees of finished tasks")
    wp.add_argument("action", nargs="?", choices=["prune"], default="prune")
    rp = sub.add_parser("roots", help="manage approved workspace roots (list/add/remove)")
    rp.add_argument("action", nargs="?", choices=["list", "add", "remove"], default="list")
    rp.add_argument("path", nargs="?", default=None)
    args = parser.parse_args(argv)

    config = Config.from_env()
    command = args.command or "serve"
    if command == "serve":
        return _cmd_serve(config)
    if command == "stdio":
        return _cmd_stdio(config)
    if command == "url":
        return _cmd_url(config)
    if command == "doctor":
        return _cmd_doctor(config)
    if command == "approvals":
        return _cmd_approvals(config, args.action, args.approval_id)
    if command == "tasks":
        return _cmd_tasks(config, args.action, args.task_id, args.mode)
    if command == "watch":
        return _cmd_watch(config, args.lines)
    if command == "worktrees":
        return _cmd_worktrees(config, args.action)
    if command == "roots":
        return _cmd_roots(config, args.action, args.path)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
