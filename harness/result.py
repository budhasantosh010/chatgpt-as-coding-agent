"""Structured result envelope + stable error codes.

The primary tool output stays human-readable prose (the consumer is ChatGPT,
which reads prose better than JSON). This envelope is the machine-readable form
for structured consumers (a future UI, the task layer, tests) and gives errors
stable codes so success/failure is unambiguous.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResultEnvelope(BaseModel):
    ok: bool
    task_id: str | None = None
    operation_id: str | None = None
    data: str = ""
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None


def error_code_for(message: str) -> str:
    """Map a normalized error string to a stable, machine-checkable code."""
    m = message.lower()
    if "stale write" in m:
        return "STALE_FILE"
    if "approval required" in m:
        return "APPROVAL_REQUIRED"
    if "denied in" in m or "secret" in m or "outside the approved" in m:
        return "PERMISSION_DENIED"
    if "not found" in m or "unknown" in m:
        return "NOT_FOUND"
    if "timed out" in m or "timeout" in m:
        return "TIMEOUT"
    return "ERROR"
