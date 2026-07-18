"""Per-workspace session log.

A tiny append-only event log keyed by workspace path. This is the antidote to
"ChatGPT owns the loop": when a turn stops and a new one starts, ChatGPT can
call session_status() and see what was already done instead of relying on the
chat transcript.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class Session:
    def __init__(self, state_dir: Path, workspace: Path):
        self.workspace = workspace
        key = hashlib.sha256(str(workspace).encode("utf-8")).hexdigest()[:16]
        self.dir = state_dir / "sessions" / key
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.dir / "events.jsonl"
        self.meta_path = self.dir / "meta.json"
        if not self.meta_path.exists():
            self.meta_path.write_text(
                json.dumps({"workspace": str(workspace), "created": _now_iso()}, indent=2),
                encoding="utf-8",
            )

    def log(self, event_type: str, **data) -> None:
        record = {"time": _now_iso(), "event": event_type, **data}
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def recent(self, n: int = 25) -> list[dict]:
        if not self.events_path.exists():
            return []
        lines = self.events_path.read_text(encoding="utf-8", errors="replace").splitlines()
        out: list[dict] = []
        for line in lines[-n:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
