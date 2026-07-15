"""Stable error codes for tool failures.

The primary tool output stays human-readable prose (the consumer is ChatGPT,
which reads prose better than JSON), but every error carries a stable
machine-checkable code — `Error: [CODE] message` — wired into the server's
error path. (A ResultEnvelope model used to live here unused; dead code is
dishonest docs, so it was removed.)
"""

from __future__ import annotations


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
