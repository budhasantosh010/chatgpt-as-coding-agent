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


def test_long_skill_pages_completely(hc, workspace):
    # A skill longer than the per-call cap (e.g. a full operating doctrine like
    # AOCS at ~55k chars) must be readable IN FULL via offset paging — a
    # silently-truncated constitution loses its later sections.
    body = ("A" * 24000) + "MIDDLE" + ("B" * 24000) + "THE-VERY-END"
    _make_skill(workspace, "doctrine", "big-doctrine", "huge skill", body=body)

    part1 = run(skills.load_skill(hc, "big-doctrine"))
    assert "skill continues" in part1 and "offset=" in part1

    offset = int(part1.rsplit("offset=", 1)[1].split(")")[0])
    part2 = run(skills.load_skill(hc, "big-doctrine", offset=offset))

    combined = part1.split("\n\n[skill continues", 1)[0] + part2
    if "skill continues" in part2:  # a third page, if any
        offset2 = int(part2.rsplit("offset=", 1)[1].split(")")[0])
        combined = combined.split("\n\n[skill continues", 1)[0] + run(
            skills.load_skill(hc, "big-doctrine", offset=offset2))
    assert "MIDDLE" in combined and "THE-VERY-END" in combined

    past = run(skills.load_skill(hc, "big-doctrine", offset=10_000_000))
    assert "past" in past and "load_skill" in past
