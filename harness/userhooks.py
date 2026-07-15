"""Operator-configurable hooks (checklist Phase 7).

Lets the OPERATOR run their own script before/after tool calls — a linter gate,
a notifier, a custom policy — without editing harness code. This is the
security-sensitive one (GPT's correct MEDIUM/HIGH re-rating), so:

  * Config lives in <state_dir>/hooks.json — OUTSIDE every workspace root, so
    the model's path-gated tools can NEVER edit a hook it triggers.
  * Every hook runs with a bounded timeout, captured/capped output, and a
    restricted environment (no inherited secrets — same base env allowlist as
    run_command).
  * A `pre` hook may BLOCK the tool by exiting non-zero (fail-closed policy);
    a `post` hook can only observe/annotate, never change the result silently.
  * Every hook run is audited via the normal event/audit path (the caller logs).

hooks.json schema (list of):
  {
    "event": "pre" | "post",
    "tool": "write_file" | "*" | "run_command,edit_file",   # comma list or *
    "command": ["python", "scripts/gate.py"],               # argv, not a shell string
    "timeout": 10,
    "block_on_failure": true          # pre only: non-zero exit vetoes the tool
  }

The command receives the tool name, capability, and (best-effort) first arg via
env vars HARNESS_HOOK_TOOL / _CAP / _ARG and a JSON payload on stdin.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .hooks import HookVeto, ToolCall


@dataclass
class UserHook:
    event: str
    tools: tuple[str, ...]
    command: list[str]
    timeout: float
    block_on_failure: bool

    def matches(self, tool: str) -> bool:
        return "*" in self.tools or tool in self.tools


def load_user_hooks(state_dir: Path) -> list[UserHook]:
    f = Path(state_dir) / "hooks.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    hooks: list[UserHook] = []
    for h in data if isinstance(data, list) else []:
        cmd = h.get("command")
        if not isinstance(cmd, list) or not cmd:
            continue
        tools = tuple(t.strip() for t in str(h.get("tool", "*")).split(",") if t.strip()) or ("*",)
        hooks.append(UserHook(
            event=h.get("event", "post"),
            tools=tools,
            command=[str(c) for c in cmd],
            timeout=float(h.get("timeout", 10)),
            block_on_failure=bool(h.get("block_on_failure", False)),
        ))
    return hooks


def _restricted_env(config) -> dict:
    """Same base env as run_command: no inherited cloud creds/tokens."""
    from .executor import build_local_env

    try:
        return build_local_env(getattr(config, "env_allowlist", ()))
    except Exception:  # noqa: BLE001 - fall back to a minimal env
        import os

        keep = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE")
        return {k: os.environ[k] for k in keep if k in os.environ}


def _run_one(hook: UserHook, call: ToolCall, workspace, env) -> tuple[int, str]:
    args = call.args or ()
    arg0 = args[0] if (args and isinstance(args[0], str)) else ""
    payload = json.dumps({
        "tool": call.tool,
        "capability": call.capability.value if call.capability else None,
        "arg": arg0,
        "result": (call.result or "")[:4000],
    })
    run_env = dict(env)
    run_env["HARNESS_HOOK_TOOL"] = call.tool
    run_env["HARNESS_HOOK_CAP"] = call.capability.value if call.capability else ""
    run_env["HARNESS_HOOK_ARG"] = arg0[:500]
    try:
        p = subprocess.run(
            hook.command, cwd=str(workspace) if workspace else None,
            input=payload, text=True, capture_output=True,
            timeout=hook.timeout, env=run_env,
        )
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out[:2000]
    except subprocess.TimeoutExpired:
        return 124, f"[user hook timed out after {hook.timeout}s]"
    except Exception as exc:  # noqa: BLE001
        return 125, f"[user hook failed to run: {exc}]"


def make_user_pre_hook(config):
    """Pre-hook that runs matching operator `pre` hooks. A non-zero exit with
    block_on_failure vetoes the tool (fail-closed)."""
    def _pre(call: ToolCall) -> None:
        hooks = [h for h in load_user_hooks(config.state_dir)
                 if h.event == "pre" and h.matches(call.tool)]
        if not hooks:
            return
        env = _restricted_env(config)
        ws = getattr(call.context, "active_workspace", None)
        for h in hooks:
            code, out = _run_one(h, call, ws, env)
            if code != 0 and h.block_on_failure:
                raise HookVeto(f"Blocked by operator pre-hook (exit {code}): {out.strip()[:300]}")

    return _pre


def make_user_post_hook(config):
    """Post-hook that runs matching operator `post` hooks and appends any output
    they print (observability; cannot silently alter the tool result)."""
    def _post(call: ToolCall):
        hooks = [h for h in load_user_hooks(config.state_dir)
                 if h.event == "post" and h.matches(call.tool)]
        if not hooks:
            return None
        env = _restricted_env(config)
        ws = getattr(call.context, "active_workspace", None)
        notes = []
        for h in hooks:
            code, out = _run_one(h, call, ws, env)
            if out.strip():
                notes.append(f"[hook {' '.join(h.command[:2])} exit {code}] {out.strip()[:300]}")
        if notes:
            return (call.result or "") + "\n" + "\n".join(notes)
        return None

    return _post
