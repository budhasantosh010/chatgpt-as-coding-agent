from __future__ import annotations

import asyncio

from harness.tools import skills


def run(coro):
    return asyncio.run(coro)


def _make_skill(workspace, folder, name, description, body="Step 1. Do the thing."):
    d = workspace / ".harness" / "skills" / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )


def test_list_skills(hc, workspace):
    _make_skill(workspace, "debugging", "systematic-debugging", "Trace bugs to root cause")
    out = run(skills.list_skills(hc))
    assert "systematic-debugging" in out and "root cause" in out


def test_load_skill(hc, workspace):
    _make_skill(workspace, "review", "code-review", "Review a diff", body="Look for bugs first.")
    out = run(skills.load_skill(hc, "code-review"))
    assert "Look for bugs first." in out


def test_load_unknown_skill(hc, workspace):
    out = run(skills.load_skill(hc, "nonexistent"))
    assert "Unknown skill" in out


def test_plain_md_skill_uses_filename(hc, workspace):
    d = workspace / ".harness" / "skills"
    d.mkdir(parents=True, exist_ok=True)
    (d / "quickfix.md").write_text("No frontmatter here.", encoding="utf-8")
    out = run(skills.list_skills(hc))
    assert "quickfix" in out
