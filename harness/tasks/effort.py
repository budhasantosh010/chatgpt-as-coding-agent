"""Deterministic receipt identities and regenerable Markdown views."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _normalize(value: str) -> str:
    return " ".join(str(value).strip().casefold().split())


def receipt_fingerprint(question: str, conclusion: str, refs: list[dict]) -> str:
    identities = {
        json.dumps(ref, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for ref in refs
    }
    payload = "\0".join((_normalize(question), _normalize(conclusion), *sorted(identities)))
    return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()


def receipt_markdown(receipt: dict) -> str:
    evidence = json.dumps(receipt.get("evidence_refs", []), ensure_ascii=False, indent=2)
    return (
        f"# Effort receipt {receipt['cycle_id']}\n\n"
        f"- Tier: {receipt['tier']}\n"
        f"- Question: {receipt['question']}\n"
        f"- Conclusion: {receipt['conclusion']}\n"
        f"- Decision: {receipt['decision']}\n"
        f"- Validated: {receipt['validated_at']}\n\n"
        f"## Server-validated evidence\n\n```json\n{evidence}\n```\n"
    )


def write_receipt_view(state_dir: Path, task_id: str, receipt: dict) -> Path:
    path = Path(state_dir) / "tasks" / task_id / "effort" / f"{receipt['cycle_id']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(receipt_markdown(receipt), encoding="utf-8")
    return path
