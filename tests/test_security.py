"""The load-bearing tests: the security boundary must never regress."""

from __future__ import annotations

import pytest

from harness.security import SecurityError, assert_command_allowed, is_secret_path


def test_relative_traversal_escaping_root_is_blocked(hc):
    with pytest.raises(SecurityError):
        hc.resolve_read("../../../Windows/System32/drivers/etc/hosts")


def test_absolute_path_outside_roots_is_blocked(hc):
    with pytest.raises(SecurityError):
        hc.resolve_read("C:/Windows/System32/config/SAM")


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
