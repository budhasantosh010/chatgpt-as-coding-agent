"""The load-bearing tests: the security boundary must never regress."""

from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

from harness.app import build_asgi_app
from harness.config import Config
from harness.security import SecurityError, assert_command_allowed, is_secret_path


def test_relative_traversal_escaping_root_is_blocked(hc):
    with pytest.raises(SecurityError):
        hc.resolve_read("../../../Windows/System32/drivers/etc/hosts")


def test_absolute_path_outside_roots_is_blocked(hc):
    # A Windows drive path is not absolute under posixpath, so pick a path the
    # host OS actually treats as absolute — otherwise Linux joins it into the
    # workspace and nothing raises.
    outside = "C:/Windows/System32/config/SAM" if os.name == "nt" else "/etc/passwd"
    with pytest.raises(SecurityError):
        hc.resolve_read(outside)


def test_path_inside_workspace_is_allowed(hc, workspace):
    (workspace / "hello.txt").write_text("hi", encoding="utf-8")
    resolved = hc.resolve_read("hello.txt")
    assert resolved.name == "hello.txt"


def test_secret_file_read_is_blocked(hc, workspace):
    (workspace / "id_rsa").write_text("PRIVATE", encoding="utf-8")
    with pytest.raises(SecurityError):
        hc.resolve_read("id_rsa")


def test_secret_file_write_is_blocked(hc):
    with pytest.raises(SecurityError):
        hc.resolve_write("secrets.pem")


@pytest.mark.parametrize("name", ["id_rsa", "server.pem", "app.key", ".git-credentials", ".npmrc"])
def test_secret_globs_match(name):
    from pathlib import Path

    assert is_secret_path(Path("/some/dir") / name, list(_default_globs()))


def _default_globs():
    from harness.config import DEFAULT_SECRET_GLOBS

    return DEFAULT_SECRET_GLOBS


@pytest.mark.parametrize(
    "cmd",
    ["rm -rf /", "rm -rf ~", "mkfs.ext4 /dev/sda", "shutdown now", "git push --force origin main"],
)
def test_destructive_commands_blocked(cmd):
    with pytest.raises(SecurityError):
        assert_command_allowed(cmd)


@pytest.mark.parametrize("cmd", ["npm test", "git status", "python -m pytest", "ls -la"])
def test_normal_commands_allowed(cmd):
    assert_command_allowed(cmd)  # does not raise


def test_public_health_response_is_minimal_even_for_untrusted_host(tmp_path):
    cfg = Config(workspace_roots=[tmp_path], state_dir=tmp_path / "state", secret_route="secret")
    app, server = build_asgi_app(cfg)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/health",
                headers={"Host": "evil.example", "Origin": "https://evil.example"},
            )
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    finally:
        server.tasks.close()
