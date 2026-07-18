"""Server-owned observations used by evidence validation and audit trails."""

from __future__ import annotations

import hashlib
import re
import secrets
import time
import os
from pathlib import Path

from .hooks import ToolCall
from .session import _now_iso


_WRITE_FIRST_PATH = {"write_file", "edit_file", "notebook_edit"}


def _sha_bytes(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(hc, path: Path) -> str:
    workspace = Path(hc.require_workspace())
    try:
        return path.relative_to(workspace).as_posix()
    except ValueError:
        return path.as_posix()


def _write_paths(call: ToolCall) -> list[Path]:
    hc = call.context
    args = call.args or ()
    raw: list[str] = []
    if call.tool in _WRITE_FIRST_PATH and args and isinstance(args[0], str):
        raw = [args[0]]
    elif call.tool == "apply_edits" and args and isinstance(args[0], list):
        raw = [
            str(edit.get("path")) for edit in args[0]
            if isinstance(edit, dict) and edit.get("path")
        ]
    elif call.tool == "apply_patch" and args and isinstance(args[0], str):
        for line in args[0].splitlines():
            if line.startswith("+++ "):
                value = line[4:].strip()
                if value and value != "/dev/null":
                    raw.append(value[2:] if value.startswith(("a/", "b/")) else value)
    paths: list[Path] = []
    seen: set[str] = set()
    for value in raw:
        real = hc.resolve_write(value)
        key = str(real).casefold()
        if key not in seen:
            seen.add(key)
            paths.append(real)
    return paths


async def _git(hc, *args):
    from .tools import gitcmd

    return await gitcmd.git(hc, hc.require_workspace(), *args)


async def _is_tracked(hc, relative: str) -> bool:
    probe = await _git(hc, "ls-files", "--error-unmatch", "--", relative)
    return probe.returncode == 0


async def tree_hash(hc) -> str:
    """Hash the task's executable workspace state, including untracked content."""
    workspace = Path(hc.require_workspace())
    head = await _git(hc, "rev-parse", "HEAD")
    digest = hashlib.sha256()
    if head.returncode == 0:
        status = await _git(hc, "status", "--porcelain=v1", "-z", "--untracked-files=all")
        diff = await _git(hc, "diff", "HEAD")
        digest.update(b"git\0")
        digest.update(head.stdout.strip().encode("utf-8", "replace"))
        digest.update(b"\0status\0")
        digest.update(status.stdout.encode("utf-8", "replace"))
        digest.update(b"\0diff\0")
        digest.update(diff.stdout.encode("utf-8", "replace"))
        entries = status.stdout.split("\0")
        for entry in entries:
            if not entry.startswith("?? "):
                continue
            relative = entry[3:]
            real = workspace / Path(relative)
            digest.update(b"\0untracked\0")
            digest.update(relative.replace("\\", "/").encode("utf-8", "replace"))
            try:
                stat = real.stat()
            except OSError:
                digest.update(b"\0missing")
                continue
            if stat.st_size > 5 * 1024 * 1024:
                digest.update(f"\0{stat.st_size}\0{stat.st_mtime_ns}".encode())
            else:
                digest.update(b"\0" + _sha_bytes(real).encode())
        return digest.hexdigest()

    digest.update(b"non-git\0")
    excluded_dirs = {".git", ".harness", ".venv", "venv", "node_modules", "__pycache__"}
    files: list[Path] = []
    for root, dirs, names in os.walk(workspace, followlinks=False):
        dirs[:] = sorted((name for name in dirs if name not in excluded_dirs), key=str.casefold)
        files.extend(Path(root) / name for name in sorted(names, key=str.casefold))
        if len(files) > 100_000:
            raise ValueError("[STATE_TOO_LARGE] non-git workspace exceeds 100000 files")
    for real in sorted(files, key=lambda item: item.relative_to(workspace).as_posix().casefold()):
        relative = _relative(hc, real)
        digest.update(relative.encode("utf-8", "replace") + b"\0")
        try:
            stat = real.lstat()
        except OSError:
            digest.update(b"missing\0")
            continue
        digest.update(f"{stat.st_size}\0{stat.st_mtime_ns}\0".encode())
        if real.is_symlink():
            digest.update(os.readlink(real).encode("utf-8", "replace"))
        elif stat.st_size > 64 * 1024 * 1024:
            digest.update(b"large-file-metadata")
        else:
            digest.update(_sha_bytes(real).encode())
    return digest.hexdigest()


def execution_fingerprint(command: str, cwd: str, state_hash: str) -> str:
    normalized = " ".join(str(command).strip().split())
    return hashlib.sha256(
        f"{normalized}\0{cwd}\0{state_hash}".encode("utf-8", "replace")
    ).hexdigest()


def make_observation_pre_hook(store):
    async def _before(call: ToolCall) -> None:
        hc = call.context
        if store is None or not getattr(hc, "task_id", None):
            return
        if call.tool in _WRITE_FIRST_PATH | {"apply_edits", "apply_patch"}:
            snapshots = []
            for path in _write_paths(call):
                relative = _relative(hc, path)
                snapshots.append({
                    "path": path,
                    "relative": relative,
                    "before_sha256": _sha_bytes(path),
                    "tracked": await _is_tracked(hc, relative),
                })
            call.meta["observation_writes"] = snapshots
        if call.tool in ("run_command", "start_process"):
            args = call.args or ()
            cwd_arg = args[1] if len(args) > 1 else None
            work = hc.resolve_read(cwd_arg) if cwd_arg else hc.require_workspace()
            if not work.is_dir():
                work = work.parent
            call.meta["observation_exec"] = {
                "command": str(args[0]),
                "cwd": str(work),
                "tree_hash": await tree_hash(hc),
                "started": time.monotonic(),
                "started_at": _now_iso(),
            }

    return _before


def make_observation_post_hook(store):
    async def _after(call: ToolCall):
        hc = call.context
        task_id = getattr(hc, "task_id", None)
        result = call.result or ""
        if store is None or not task_id or result.startswith("Error:") or "APPROVAL REQUIRED" in result:
            return None

        if call.tool == "read_file" and call.args and isinstance(call.args[0], str):
            real = hc.resolve_read(call.args[0])
            store.add_event(
                task_id, "obs_read", path=_relative(hc, real),
                content_sha256=_sha_bytes(real),
            )

        for snapshot in call.meta.get("observation_writes", []):
            store.add_event(
                task_id,
                "obs_write",
                write_id=f"ev-{secrets.token_hex(4)}",
                path=snapshot["relative"],
                before_sha256=snapshot["before_sha256"],
                after_sha256=_sha_bytes(snapshot["path"]),
                tracked=snapshot["tracked"],
            )

        execution = call.meta.get("observation_exec")
        if call.tool == "run_command" and execution:
            match = re.search(r"exit code:\s*(-?\d+)", result)
            exec_id = f"px-{secrets.token_hex(4)}"
            fingerprint = execution_fingerprint(
                execution["command"], execution["cwd"], execution["tree_hash"]
            )
            store.add_event(
                task_id,
                "obs_exec",
                exec_id=exec_id,
                command=execution["command"],
                cwd=execution["cwd"],
                tree_hash=execution["tree_hash"],
                fingerprint=fingerprint,
                exit_code=int(match.group(1)) if match else None,
                started_at=execution["started_at"],
                duration_s=max(0.0, time.monotonic() - execution["started"]),
                runner=getattr(getattr(hc, "executor", None), "name", "local"),
            )
            return result + f"\n[execution id: {exec_id}]"

        if call.tool == "start_process" and execution:
            match = re.search(r"Started\s+(\S+)\s+in", result)
            if match and hc.processes is not None:
                managed = hc.processes.get(match.group(1), owner=hc.key)
                if managed is not None:
                    managed._observation = execution

        if call.tool in ("read_process", "stop_process") and call.args and hc.processes is not None:
            managed = hc.processes.get(str(call.args[0]), owner=hc.key)
            observation = getattr(managed, "_observation", None) if managed else None
            if managed and observation and managed.returncode is not None and not getattr(managed, "_observation_recorded", False):
                managed._observation_recorded = True
                fingerprint = execution_fingerprint(
                    managed.command, managed.cwd, observation["tree_hash"]
                )
                store.add_event(
                    task_id, "obs_exec", exec_id=managed.id, command=managed.command,
                    cwd=managed.cwd, tree_hash=observation["tree_hash"],
                    fingerprint=fingerprint, exit_code=managed.returncode,
                    started_at=observation["started_at"],
                    duration_s=max(0.0, time.monotonic() - observation["started"]),
                    runner=getattr(getattr(hc, "executor", None), "name", "local"),
                )
        return None

    return _after
