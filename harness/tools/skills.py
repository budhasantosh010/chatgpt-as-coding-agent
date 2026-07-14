"""Skills: loadable capability docs the agent can discover and pull on demand.

A skill is a markdown file (``SKILL.md`` in a folder, or ``<name>.md``) with
optional frontmatter (``name``, ``description``). They're discovered from the
workspace and the user's global skill library, listed cheaply by name +
description, and loaded in full only when needed — so capability can be added
with zero code and without bloating context.
"""

from __future__ import annotations

from pathlib import Path

from ..context import HarnessContext

_MAX_SKILL_CHARS = 25000
_WORKSPACE_SKILL_DIRS = (".harness/skills", ".agents/skills", ".claude/skills")
_GLOBAL_SKILL_DIRS = ("skills",)  # under state_dir
_HOME_SKILL_DIRS = (".agents/skills", ".claude/skills")


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end]
            body = text[end + 4 :].lstrip("\n")
            for line in block.splitlines():
                if line and not line[0].isspace() and ":" in line:
                    key, _, val = line.partition(":")
                    meta[key.strip()] = val.strip()
    return meta, body


def _skill_dirs(hc: HarnessContext) -> list[Path]:
    dirs: list[Path] = []
    ws = hc.active_workspace
    if ws is not None:
        dirs += [ws / rel for rel in _WORKSPACE_SKILL_DIRS]
    dirs += [hc.config.state_dir / rel for rel in _GLOBAL_SKILL_DIRS]
    dirs += [Path.home() / rel for rel in _HOME_SKILL_DIRS]
    seen: list[Path] = []
    for d in dirs:
        if d.exists() and d.is_dir() and d not in seen:
            seen.append(d)
    return seen


def _discover(hc: HarnessContext) -> list[dict]:
    found: dict[str, dict] = {}
    for base in _skill_dirs(hc):
        candidates: list[Path] = []
        candidates += list(base.rglob("SKILL.md"))
        candidates += [p for p in base.glob("*.md") if p.name != "SKILL.md"]
        for path in candidates:
            try:
                head = path.read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                continue
            meta, _ = _parse_frontmatter(head)
            name = meta.get("name") or (
                path.parent.name if path.name == "SKILL.md" else path.stem
            )
            if name not in found:
                found[name] = {
                    "name": name,
                    "description": meta.get("description", ""),
                    "path": str(path),
                }
    return list(found.values())


async def list_skills(hc: HarnessContext) -> str:
    skills = _discover(hc)
    if not skills:
        return (
            "No skills found. Add markdown skills under .harness/skills/, "
            ".agents/skills/, or ~/.agents/skills/."
        )
    lines = ["# Available skills (load one with load_skill(name))"]
    for s in sorted(skills, key=lambda x: x["name"]):
        desc = f" — {s['description']}" if s["description"] else ""
        lines.append(f"- {s['name']}{desc}")
    return "\n".join(lines)


async def load_skill(hc: HarnessContext, name: str) -> str:
    skills = _discover(hc)
    match = next((s for s in skills if s["name"] == name), None)
    if match is None:
        available = ", ".join(s["name"] for s in skills) or "(none)"
        return f"Unknown skill {name!r}. Available: {available}"
    try:
        content = Path(match["path"]).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Error reading skill {name!r}: {exc}"
    truncated = ""
    if len(content) > _MAX_SKILL_CHARS:
        content = content[:_MAX_SKILL_CHARS]
        truncated = f"\n\n[skill truncated at {_MAX_SKILL_CHARS} chars]"
    hc.log("load_skill", name=name)
    return content + truncated
