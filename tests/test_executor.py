"""Execution backends: default selection, Docker argv construction, and a real
local run."""

from __future__ import annotations

import asyncio

from harness.config import Config
from harness.executor import DockerExecutor, LocalExecutor, build_executor, build_local_env


def run(coro):
    return asyncio.run(coro)


def _cfg(tmp_path, **kw):
    return Config(workspace_roots=[tmp_path], state_dir=tmp_path / "s",
                  secret_route="r", **kw)


def test_default_backend_is_local(tmp_path):
    ex = build_executor(_cfg(tmp_path))
    assert isinstance(ex, LocalExecutor)


def test_docker_backend_when_configured(tmp_path):
    ex = build_executor(_cfg(tmp_path, sandbox="docker", sandbox_image="alpine:3"))
    assert isinstance(ex, DockerExecutor)
    assert ex.image == "alpine:3"


def test_docker_argv_mounts_workspace_and_isolates_network():
    ex = DockerExecutor("python:3.12-slim", network="none")
    argv = ex.build_argv("pytest -q", "/home/me/proj")
    assert argv[:3] == ["docker", "run", "--rm"]
    assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
    assert "-v" in argv and argv[argv.index("-v") + 1] == "/home/me/proj:/work"
    assert argv[-3:] == ["/bin/sh", "-c", "pytest -q"]
    assert "-w" in argv and argv[argv.index("-w") + 1] == "/work"


def test_docker_argv_is_hardened():
    ex = DockerExecutor("img", pids=256, cpus="1", memory="512m", user="1000:1000", readonly=True)
    argv = ex.build_argv("ls", "/w")
    joined = " ".join(argv)
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--pids-limit 256" in joined
    assert "--cpus 1" in joined and "--memory 512m" in joined
    assert "--user 1000:1000" in joined
    assert "--read-only" in argv and "--tmpfs" in argv


def test_local_executor_runs_command(tmp_path):
    ex = LocalExecutor("")
    result = run(ex.run("echo harness_ok", tmp_path, timeout=30))
    assert result.returncode == 0
    assert "harness_ok" in result.combined


def test_spawn_argv_is_shared_seam():
    # Both run_command and start_process build their process the same way, so the
    # sandbox has no hole: spawn_argv is that one seam.
    local = LocalExecutor("")
    assert local.spawn_argv("ls", "/x")[-1] == "ls"
    docker = DockerExecutor("alpine:3")
    assert docker.spawn_argv("ls", "/x") == docker.build_argv("ls", "/x")
    assert docker.spawn_argv("ls", "/x")[:3] == ["docker", "run", "--rm"]


def test_local_env_preserves_windows_and_active_python_toolchain(monkeypatch):
    expected = {
        "APPDATA": r"C:\\Users\\me\\AppData\\Roaming",
        "LOCALAPPDATA": r"C:\\Users\\me\\AppData\\Local",
        "VIRTUAL_ENV": r"C:\\repo\\.venv",
        "CONDA_PREFIX": r"C:\\miniconda3\\envs\\project",
        "CONDA_DEFAULT_ENV": "project",
        "PYTHONUSERBASE": r"C:\\Users\\me\\Python",
    }
    for key, value in expected.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")

    env = build_local_env()

    assert {key: env.get(key) for key in expected} == expected
    assert "OPENAI_API_KEY" not in env
