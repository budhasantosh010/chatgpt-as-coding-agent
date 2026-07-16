"""Execution backends for run_command — the seam for sandboxing.

The default is :class:`LocalExecutor`: commands run in the host shell. That is
the correct, dependency-free choice for personal use on your own trusted machine
(and keeps "download it and it works anywhere" true).

:class:`DockerExecutor` runs each command in a throwaway container with only the
workspace mounted and networking off by default — real isolation for untrusted
repos or hands-off agent autonomy. It is opt-in via ``HARNESS_SANDBOX=docker``
so nothing about the default install depends on Docker being present.

This is a port with two adapters. A future backend (Firecracker, a remote
runner, gVisor) is a third class here and nothing else changes.
"""

from __future__ import annotations

import os
from pathlib import Path

from .proc import ProcessResult, run_subprocess, shell_argv

# The safe base set of environment variables a command may see. Everything
# needed to actually run tools (find executables, home dir, locale, temp) but
# NOT cloud creds / tokens. Extra names come from HARNESS_ENV_ALLOWLIST.
_BASE_ENV_KEYS = (
    "PATH", "PATHEXT", "HOME", "HOMEDRIVE", "HOMEPATH", "USERPROFILE",
    "SystemRoot", "SystemDrive", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR",
    "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ", "SHELL", "USER", "USERNAME",
    "LOGNAME", "PYTHONIOENCODING", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
    # Windows user-site discovery and active interpreter environments. These
    # are locations/selectors, not credentials; dropping them can leave a
    # `pytest.exe` launcher on PATH while hiding the package it belongs to.
    "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
    "VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "PYTHONUSERBASE",
)


def build_local_env(allowlist=(), extra: dict | None = None) -> dict:
    """A minimal, complete environment: the safe base keys present on the host,
    plus any operator-allowlisted names, plus explicit per-command additions."""
    keys = set(_BASE_ENV_KEYS) | set(allowlist or ())
    env = {k: os.environ[k] for k in keys if k in os.environ}
    if extra:
        env.update(extra)
    return env


class Executor:
    """Port: decide how a command string becomes a process.

    ``spawn_argv`` is the single seam every code path shares — foreground
    (run_command) and background (start_process) both go through it, so the
    sandbox has no silent holes. ``run`` is the foreground convenience that also
    waits for completion. ``build_env`` decides what the command may see.
    """

    name = "executor"
    inherit_env = True

    def spawn_argv(self, command: str, cwd: str | Path) -> list[str]:
        raise NotImplementedError

    def build_env(self, extra: dict | None = None):
        return extra  # None => inherit host env (base Executor is permissive)

    def build_tool_env(self, extra: dict | None = None) -> dict:
        """Environment for harness-internal tools (git, ripgrep) run via
        ``run_argv``. Always minimal + complete, regardless of backend, so our
        own tooling can never leak host secrets either."""
        return build_local_env(getattr(self, "env_allowlist", ()), extra)

    async def run(
        self,
        command: str,
        cwd: str | Path,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> ProcessResult:
        return await run_subprocess(
            self.spawn_argv(command, cwd), cwd=str(cwd), timeout=timeout,
            env=self.build_env(env), inherit_env=self.inherit_env,
        )

    async def run_argv(
        self,
        argv: list[str],
        cwd: str | Path | None = None,
        timeout: int = 60,
        env: dict[str, str] | None = None,
    ) -> ProcessResult:
        """Run a raw argv (a harness-internal tool like git/rg) in a restricted
        environment. This is the single seam those tools use — nothing shells out
        directly, so env restriction is enforced everywhere."""
        return await run_subprocess(
            list(argv), cwd=str(cwd) if cwd is not None else None,
            timeout=timeout, env=self.build_tool_env(env), inherit_env=False,
        )


class LocalExecutor(Executor):
    """Run in the host shell with a restricted environment (default backend)."""

    name = "local"
    inherit_env = False  # the env we hand it is the COMPLETE environment

    def __init__(self, config_shell: str = "", env_allowlist=()):
        self.config_shell = config_shell
        self.env_allowlist = tuple(env_allowlist)

    def spawn_argv(self, command, cwd) -> list[str]:
        return shell_argv(self.config_shell, command)

    def build_env(self, extra: dict | None = None) -> dict:
        return build_local_env(self.env_allowlist, extra)


class DockerExecutor(Executor):
    """Run each command in a fresh, auto-removed container.

    The workspace is bind-mounted at ``/work`` and made the working directory,
    so file edits persist on the host while the command itself is isolated.
    Applies to run_command, start_process, and diagnostics (via ``run`` /
    ``spawn_argv``). Stopping a backgrounded container is best-effort (killing
    the ``docker run`` client).

    SCOPE (honest): ``run_argv`` is NOT overridden, so harness-internal git and
    ripgrep still execute on the host — with repo hooks and system/global config
    neutralized (see gitcmd.py), which closes the primary code-execution vector.
    Fully containerizing git needs host→container path rewriting for worktree
    gitdir pointers + per-project images; that remains deliberately deferred.
    """

    name = "docker"

    def __init__(self, image: str, network: str = "none", container_shell: str = "/bin/sh",
                 cpus: str = "2", memory: str = "2g", pids: int = 512,
                 user: str = "", readonly: bool = False):
        self.image = image
        self.network = network
        self.container_shell = container_shell
        self.cpus = cpus
        self.memory = memory
        self.pids = pids
        self.user = user
        self.readonly = readonly

    def spawn_argv(self, command, cwd) -> list[str]:
        argv = [
            "docker", "run", "--rm", "-i",
            "--network", self.network,
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", str(self.pids),
            "--cpus", str(self.cpus),
            "--memory", str(self.memory),
        ]
        if self.user:
            argv += ["--user", self.user]
        if self.readonly:
            argv += ["--read-only", "--tmpfs", "/tmp"]
        argv += [
            "-v", f"{cwd}:/work",
            "-w", "/work",
            self.image,
            self.container_shell, "-c", command,
        ]
        return argv

    # kept for readability/tests; spawn_argv is the canonical builder.
    build_argv = spawn_argv

    def build_env(self, extra: dict | None = None):
        # Never forward host environment (which may hold tokens) across the
        # isolation boundary. The container gets its image's env only.
        return None


def build_executor(config) -> Executor:
    """Select the execution backend from config. Unknown values fall back to
    local rather than failing, so a typo never bricks the server."""
    sandbox = getattr(config, "sandbox", "local")
    if sandbox == "docker":
        return DockerExecutor(
            image=getattr(config, "sandbox_image", "python:3.12-slim"),
            network=getattr(config, "sandbox_network", "none"),
            cpus=getattr(config, "sandbox_cpus", "2"),
            memory=getattr(config, "sandbox_memory", "2g"),
            pids=getattr(config, "sandbox_pids", 512),
            user=getattr(config, "sandbox_user", ""),
            readonly=getattr(config, "sandbox_readonly", False),
        )
    return LocalExecutor(getattr(config, "shell", ""), getattr(config, "env_allowlist", ()))
