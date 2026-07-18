"""Server-side evidence validation shared by completion, effort, and loops.

The validator proves structural ownership and freshness facts the server can
actually know. It deliberately does not claim that evidence is semantically
relevant; that remains visible for operator audit.
"""

from __future__ import annotations

import re
import json
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone


_SHELL_META = re.compile(r"[;&|`$<>{}\n]")
_VERIFICATION_COMMANDS = tuple(
    re.compile(pattern, re.I) for pattern in (
        r"(?:python[0-9.]*\s+-m\s+)?pytest(?:\s.*)?",
        r"python[0-9.]*\s+-m\s+(?:unittest|mypy|ruff|flake8|tox|compileall)(?:\s.*)?",
        r"(?:tox|mypy|ruff|flake8|pylint)(?:\s.*)?",
        r"(?:npm|pnpm|yarn)\s+(?:test|run\s+(?:test|build|lint|typecheck|check|verify|ci)(?::[\w.-]+)?)(?:\s.*)?",
        r"(?:jest|vitest|tsc|eslint)(?:\s.*)?",
        r"cargo\s+(?:test|build|check|clippy)(?:\s.*)?",
        r"go\s+(?:test|build|vet)(?:\s.*)?",
        r"dotnet\s+(?:test|build)(?:\s.*)?",
        r"make\s+(?:test|build|check|lint|typecheck|verify|ci)(?:\s.*)?",
    )
)


def normalize_command(command: str) -> str:
    return " ".join(str(command).strip().split())


def classify_verification_command(command: str) -> bool:
    """True only for test/build/lint/typecheck/diagnostic commands.

    This intentionally does not reuse permissions.classify_command(), whose
    safe tier also contains observation commands such as echo and directory
    listings that cannot prove correctness.
    """
    normalized = normalize_command(command)
    return bool(
        normalized
        and not _SHELL_META.search(normalized)
        and any(pattern.fullmatch(normalized) for pattern in _VERIFICATION_COMMANDS)
    )


@dataclass(frozen=True)
class EvidenceValidation:
    tier: str
    refs: list[dict]
    kinds: frozenset[str]
    ignored: list[dict]


class VerificationApprovalRequired(ValueError):
    """A custom proof command needs its own operator evidence approval."""


_TRIVIAL_OBSERVATION = re.compile(
    r"(?:echo|ls|dir|pwd|whoami|Get-ChildItem|Get-Location)(?:\s.*)?|"
    r"git\s+(?:status|log)(?:\s.*)?",
    re.I,
)


def _path_key(value: str) -> str:
    return str(value).replace("\\", "/").casefold()


def _instant(value: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fresh(event: dict, opened_at: str, *, started: bool = False) -> bool:
    if not opened_at:
        return True
    value = (event.get("started_at") or event.get("time")) if started else event.get("time")
    try:
        return _instant(value) >= _instant(opened_at)
    except (TypeError, ValueError):
        return False


def _event_order(event: dict) -> tuple[datetime, int]:
    try:
        when = _instant(event.get("time", ""))
    except (TypeError, ValueError):
        when = datetime.min.replace(tzinfo=timezone.utc)
    raw_id = str(event.get("event_id", "0")).split(":")[-1]
    return when, int(raw_id) if raw_id.isdigit() else 0


def _canonical_ref(kind: str, ref: dict, **extra) -> dict:
    fields = {
        "source": ("file", "lines", "fact"),
        "execution": ("exec_id", "reason"),
        "diff": ("write_ids",),
        "decision": ("what", "why"),
    }[kind]
    clean = {"kind": kind}
    for field in fields:
        if field in ref and ref[field] not in (None, "", []):
            clean[field] = ref[field]
    clean.update(extra)
    return clean


def _family_events(store, task) -> list[dict]:
    task_ids = {task.id}
    if task.credit_scope_id:
        task_ids.update(
            candidate.id for candidate in store.list_tasks()
            if candidate.credit_scope_id == task.credit_scope_id
        )
    events: list[dict] = []
    for task_id in task_ids:
        events.extend(store.events(task_id, limit=10000))
    return sorted(events, key=_event_order)


def validate_evidence(
    store,
    task,
    evidence,
    *,
    opened_at: str = "",
    verification_plan: list[str] | tuple[str, ...] | None = None,
    cycle_id: str = "",
    question: str = "",
    allow_custom_verification: bool = False,
) -> EvidenceValidation:
    """Validate evidence refs against server-owned observations.

    ``verification_plan`` is mandatory for credit-cycle V1 verification. It is
    optional for criterion gates, which may cite any recognized verification
    observed for the task after its contract was confirmed.
    """
    refs = evidence if isinstance(evidence, list) else [evidence]
    events = _family_events(store, task)
    valid: list[dict] = []
    ignored: list[dict] = []
    kinds: set[str] = set()
    planned = (
        {normalize_command(command) for command in verification_plan}
        if verification_plan is not None else None
    )

    for raw in refs:
        if not isinstance(raw, dict):
            ignored.append({"value": raw, "reason": "reference must be an object"})
            continue
        ref = dict(raw)
        kind = ref.get("kind")
        if kind == "source":
            file = str(ref.get("file", "")).strip()
            if not file or not str(ref.get("lines", "")).strip() or not str(ref.get("fact", "")).strip():
                ignored.append({**ref, "reason": "source needs file, lines, and fact"})
                continue
            reads = [
                event for event in events
                if event.get("type") == "obs_read"
                and _path_key(event.get("path", "")) == _path_key(file)
            ]
            if not reads:
                ignored.append({**ref, "reason": "file was not read through the harness"})
                continue
            enriched = _canonical_ref(
                "source", ref, content_sha256=reads[-1].get("content_sha256", "")
            )
            valid.append(enriched)
            kinds.add("source")
            continue

        if kind == "execution":
            exec_id = str(ref.get("exec_id", "")).strip()
            matches = [
                event for event in events
                if event.get("type") == "obs_exec" and event.get("exec_id") == exec_id
                and event.get("exit_code") == 0
                and _fresh(event, opened_at, started=True)
            ]
            if not matches:
                ignored.append({**ref, "reason": "execution is missing, stale, or not owned"})
                continue
            command = normalize_command(matches[-1].get("command", ""))
            if planned is not None and command not in planned:
                ignored.append({**ref, "reason": "command was not pre-registered"})
                continue
            matched = matches[-1]
            if any(
                event.get("type") == "obs_write"
                and _event_order(event) > _event_order(matched)
                for event in events
            ):
                ignored.append({**ref, "reason": "workspace changed after execution"})
                continue
            enriched = _canonical_ref(
                "execution", ref, command=command,
                execution_fingerprint=matches[-1].get("fingerprint", ""),
            )
            if not classify_verification_command(command):
                reason = str(ref.get("reason", "")).strip()
                if (not allow_custom_verification or not reason
                        or _TRIVIAL_OBSERVATION.fullmatch(command)):
                    ignored.append({**ref, "reason": "command is not recognized verification"})
                    continue
                detail = json.dumps({
                    "task_id": task.id, "cycle_id": cycle_id,
                    "question": question, "command": command, "reason": reason,
                }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                request_hash = hashlib.sha256(detail.encode()).hexdigest()
                approval = store.grantable_approval(
                    task.id, "verification_evidence", request_hash
                )
                if approval is None:
                    approval_id = store.add_approval(
                        task.id, "verification_evidence", detail, request_hash
                    )
                    raise VerificationApprovalRequired(
                        f"[VERIFICATION_APPROVAL_REQUIRED] approve {approval_id} and retry"
                    )
                enriched["verification_approval_id"] = approval["id"]
            valid.append(enriched)
            kinds.add("machine")
            continue

        if kind == "diff":
            write_ids = ref.get("write_ids")
            if not isinstance(write_ids, list) or not write_ids:
                ignored.append({**ref, "reason": "diff needs write_ids"})
                continue
            writes = []
            for write_id in write_ids:
                match = next((
                    event for event in events
                    if event.get("type") == "obs_write"
                    and write_id in (event.get("write_id"), event.get("event_id"))
                    and _fresh(event, opened_at)
                ), None)
                if match is None:
                    writes = []
                    break
                writes.append(match)
            if not writes or not any(
                event.get("before_sha256") != event.get("after_sha256") for event in writes
            ):
                ignored.append({**ref, "reason": "writes are missing, stale, or unchanged"})
                continue
            canonical = dict(ref)
            canonical["write_ids"] = sorted({str(item) for item in write_ids})
            valid.append(_canonical_ref("diff", canonical))
            kinds.add("machine")
            continue

        if kind == "decision":
            if str(ref.get("what", "")).strip() and str(ref.get("why", "")).strip():
                valid.append(_canonical_ref("decision", ref))
                kinds.add("decision")
            else:
                ignored.append({**ref, "reason": "decision needs what and why"})
            continue

        ignored.append({**ref, "reason": "unknown evidence kind"})

    unique: dict[str, dict] = {}
    for ref in valid:
        identity = json.dumps(ref, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        unique.setdefault(identity, ref)
    valid = list(unique.values())
    if not valid:
        raise ValueError("[EVIDENCE_INVALID] no server-valid evidence references")
    tier = "machine" if "machine" in kinds else "source" if "source" in kinds else "decision"
    return EvidenceValidation(tier, valid, frozenset(kinds), ignored)
