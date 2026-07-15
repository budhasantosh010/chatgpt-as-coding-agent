"""Path-scoped project rules (checklist 6.1).

A whole-repo AGENTS.md/CLAUDE.md is loaded once by open_workspace. Path-scoped
rules are the finer tool: a rule file that applies ONLY to files matching its
globs (e.g. "in migrations/**, never edit an applied migration"). We surface the
right rule at the right moment — when a WRITE touches a matching path — instead
of dumping every rule up front.

Rule files live in <ws>/.harness/rules/*.md and <ws>/.cursor/rules/*.mdc, with
optional YAML-ish frontmatter:

    ---
    globs: src/**/*.ts, migrations/**
    ---
    Body of the rule ChatGPT should follow for those files.

No YAML dependency: we parse the tiny `key: value` frontmatter by hand.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

_RULE_DIRS = (".harness/rules", ".cursor/rules", ".agents/rules")
_RULE_EXTS = (".md", ".mdc", ".txt")


@dataclass
class Rule:
    name: str
    globs: list[str]
    body: str


def _parse(path: Path) -> Rule | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    globs: list[str] = []
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            front = text[3:end]
            body = text[end + 4:].lstrip("\n")
            for line in front.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    if k.strip().lower() in ("globs", "paths", "glob", "path"):
                        globs += [g.strip() for g in v.replace(",", "\n").split("\n") if g.strip()]
    return Rule(name=path.stem, globs=globs, body=body.strip())


def load_rules(workspace: Path) -> list[Rule]:
    rules: list[Rule] = []
    for d in _RULE_DIRS:
        rd = workspace / d
        if not rd.is_dir():
            continue
        for f in sorted(rd.iterdir()):
            if f.is_file() and f.suffix.lower() in _RULE_EXTS:
                r = _parse(f)
                if r is not None:
                    rules.append(r)
    return rules


def _matches(rule: Rule, rel_path: str) -> bool:
    if not rule.globs:
        return False  # unscoped rules belong in AGENTS.md, not here
    rp = rel_path.replace("\\", "/")
    base = rp.rsplit("/", 1)[-1]
    for g in rule.globs:
        g = g.replace("\\", "/")
        # fnmatch has no real `**`; build the sensible variants by hand.
        variants = {g}
        if g.startswith("**/"):
            variants.add(g[3:])                 # **/*.py also matches root app.py
        if g.endswith("/**"):
            variants.add(g[:-3])
            variants.add(g[:-3] + "/*")
        if any(fnmatch.fnmatch(rp, v) or fnmatch.fnmatch(base, v) for v in variants):
            return True
        # directory-prefix globs: "migrations/**" matches "migrations/…/x"
        if g.endswith("/**") and rp.startswith(g[:-2].rstrip("/") + "/"):
            return True
    return False


def rules_for(workspace: Path, rel_path: str) -> list[Rule]:
    return [r for r in load_rules(workspace) if _matches(r, rel_path)]


def summary(workspace: Path) -> str:
    """One-line-per-rule listing for open_workspace orientation."""
    rules = load_rules(workspace)
    if not rules:
        return ""
    lines = ["Path-scoped rules (apply when you touch matching files):"]
    for r in rules:
        scope = ", ".join(r.globs) if r.globs else "(no globs — move to AGENTS.md)"
        lines.append(f"  - {r.name}: {scope}")
    return "\n".join(lines)
