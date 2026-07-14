"""Hardened git invocation, routed through the session executor.

Every git call the harness makes goes through here, which does two things:

1. **Neutralizes the repo's own code.** Repository-controlled hooks are the real
   "git runs attacker code on the host" vector; we disable them
   (``core.hooksPath`` → devnull) and ignore system/global config so a crafted
   ``~/.gitconfig`` can't inject filters either.
2. **Restricts the environment.** Runs via ``executor.run_argv``, so git sees the
   same minimal env as any other harness tool — no host secrets.

(Containerizing git itself — for smudge/clean filters defined inside an untrusted
repo — needs host→container path rewriting and per-project images; that is the
P1 hardened-sandbox item. Hook disabling closes the primary vector now.)
"""

from __future__ import annotations

import os
from pathlib import Path

from ..context import HarnessContext
from ..executor import LocalExecutor
from ..proc import ProcessResult

_HARDEN_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
}


def _executor(hc: HarnessContext):
    return getattr(hc, "executor", None) or LocalExecutor(
        getattr(hc.config, "shell", ""), getattr(hc.config, "env_allowlist", ())
    )


async def git(
    hc: HarnessContext,
    base: Path,
    *args: str,
    env: dict | None = None,
    timeout: int = 60,
    hardened: bool | str = True,
) -> ProcessResult:
    """Run git through the session executor, at one of three hardening levels:

    * ``True`` (default) — repo hooks neutralized AND system/global config
      ignored. For the harness's own plumbing (checkpoints/worktrees/inspection)
      against possibly-untrusted repos.
    * ``"no_hooks"`` — the user's global config applies (so identity/signing
      work) but REPO HOOKS STAY OFF. The default for git_commit: a cloned repo's
      pre-commit hook must not execute code on the host just because the model
      committed. Opt back into hooks with HARNESS_COMMIT_HOOKS=true.
    * ``False`` — everything honored, including repo hooks. Operator opt-in only.
    """
    if hardened is True:
        merged = dict(_HARDEN_ENV)
        if env:
            merged.update(env)
        argv = ["git", "-c", f"core.hooksPath={os.devnull}", "-C", str(base), *args]
    elif hardened == "no_hooks":
        merged = {"GIT_TERMINAL_PROMPT": "0"}
        if env:
            merged.update(env)
        argv = ["git", "-c", f"core.hooksPath={os.devnull}", "-C", str(base), *args]
    else:
        merged = dict(env) if env else None
        argv = ["git", "-C", str(base), *args]
    return await _executor(hc).run_argv(argv, cwd=str(base), timeout=timeout, env=merged)
