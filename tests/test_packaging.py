"""Packaging guard: every real subpackage under harness/ must ship in the wheel.

The audit found `harness.tasks` missing from pyproject's static package list —
the installed wheel raised ModuleNotFoundError while repo-root test runs hid it.
This pins auto-discovery so a future subpackage can't be silently dropped.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _discovered_packages() -> list[str]:
    """Every directory under harness/ that is a real package (has __init__.py)."""
    pkgs = ["harness"]
    root = REPO / "harness"
    for init in root.rglob("__init__.py"):
        rel = init.parent.relative_to(REPO)
        name = ".".join(rel.parts)
        if name != "harness":
            pkgs.append(name)
    return sorted(pkgs)


def _include_globs() -> list[str]:
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(
        r"\[tool\.setuptools\.packages\.find\]\s*.*?include\s*=\s*\[([^\]]*)\]",
        text,
        re.S,
    )
    assert m, (
        "pyproject.toml must use [tool.setuptools.packages.find] with an "
        "include list — a static packages list is how harness.tasks got dropped."
    )
    return re.findall(r'"([^"]+)"', m.group(1))


def test_every_subpackage_matches_include_globs():
    globs = _include_globs()
    missing = [
        pkg for pkg in _discovered_packages()
        if not any(fnmatch.fnmatch(pkg, g) for g in globs)
    ]
    assert not missing, f"Packages not covered by pyproject include globs: {missing}"


def test_known_packages_present_on_disk():
    pkgs = _discovered_packages()
    for expected in ("harness", "harness.tools", "harness.tasks"):
        assert expected in pkgs


def test_cockpit_static_manifest_is_modular_and_complete():
    static = REPO / "harness" / "cockpit" / "static"
    required = {
        "index.html", "cockpit.css", "api.mjs", "state.mjs",
        "layout.mjs", "render.mjs", "app.mjs",
    }
    assets = {path.name for path in static.iterdir() if path.is_file()}
    assert required <= assets
    assert "cockpit.js" not in assets

    package_globs = ["static/*"]
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert all(any(fnmatch.fnmatch(f"static/{name}", glob) for glob in package_globs)
               for name in required)
    assert '"harness.cockpit" = ["static/*"]' in pyproject
