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

from pathlib import Path

from .proc import ProcessResult, run_subprocess, shell_argv


class Executor:
    """Port: decide how a command string becomes a process.

    ``spawn_argv`` is the single seam every code path shares — foreground
    (run_command) and background (start_process) both go through it, so the
    sandbox has no silent holes. ``run`` is the foreground convenience that also
    waits for completion.
    """

    name = "executor"

    def spawn_argv(self, command: str, cwd: str | Path) -> list[str]:
        raise NotImplementedError

    async def run(
        self,
        command: str,
        cwd: str | Path,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> ProcessResult:
        return await run_subprocess(
            self.spawn_argv(command, cwd), cwd=str(cwd), timeout=timeout, env=self._env(env)
        )

    def _env(self, env):  # overridable: isolation backends drop host env
        return env


class LocalExecutor(Executor):
    """Run in the host shell (current, default behaviour)."""

    name = "local"

    def __init__(self, config_shell: str = ""):
        self.config_shell = config_shell

    def spawn_argv(self, command, cwd) -> list[str]:
        return shell_argv(self.config_shell, command)


class DockerExecutor(Executor):
    """Run each command in a fresh, auto-removed container.

    The workspace is bind-mounted at ``/work`` and made the working directory,
    so file edits persist on the host while the command itself is isolated.
    Applies to both run_command and start_process. Stopping a backgrounded
    container is best-effort (killing the ``docker run`` client).
    """

    name = "docker"

    def __init__(self, image: str, network: str = "none", container_shell: str = "/bin/sh"):
        self.image = image
        self.network = network
        self.container_shell = container_shell

    def spawn_argv(self, command, cwd) -> list[str]:
        return [
            "docker", "run", "--rm", "-i",
            "--network", self.network,
            "-v", f"{cwd}:/work",
            "-w", "/work",
            self.image,
            self.container_shell, "-c", command,
        ]

    # kept for readability/tests; spawn_argv is the canonical builder.
    build_argv = spawn_argv

    def _env(self, env):
        # Never forward host environment (which may hold tokens) across the
        # isolation boundary. Pass values explicitly in the command if needed.
        return None


def build_executor(config) -> Executor:
    """Select the execution backend from config. Unknown values fall back to
    local rather than failing, so a typo never bricks the server."""
    sandbox = getattr(config, "sandbox", "local")
    if sandbox == "docker":
        return DockerExecutor(
            image=getattr(config, "sandbox_image", "python:3.12-slim"),
            network=getattr(config, "sandbox_network", "none"),
        )
    return LocalExecutor(getattr(config, "shell", ""))
