"""Redact secrets from tool output before it leaves the machine.

The harness's whole purpose is to send your code to ChatGPT, so a live key or
token sitting inside a file, a diff, or command output would be exfiltrated by
an ordinary read. Secret *files* are already blocked outright (``security.py``);
this catches secrets embedded in otherwise-legitimate files and logs, and is
wired as a post-tool hook so it covers read_file, grep, git_diff, run_command —
every path that returns text to the model.

It is deliberately pattern-based and high-signal: only well-known credential
formats are matched, to avoid mangling real source code. It reduces accidental
leakage; it is not a guarantee. Disable with HARNESS_SCRUB_OUTPUT=false.
"""

from __future__ import annotations

import re

# (name, pattern): each is a distinctive, low-false-positive credential format.
_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b")),
    ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("google-oauth-token", re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}")),
    ("slack-token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("slack-webhook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+")),
    ("stripe-key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("twilio-key", re.compile(r"\bSK[0-9a-fA-F]{32}\b")),
    ("sendgrid-key", re.compile(r"\bSG\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    (
        "private-key-block",
        re.compile(
            r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
)


def scrub_text(text: str) -> tuple[str, int]:
    """Return (redacted_text, num_redactions). Each secret becomes
    ``[REDACTED:<type>]``. Safe on empty/None-ish input."""
    if not text:
        return text, 0
    total = 0
    for name, pattern in _PATTERNS:
        text, count = pattern.subn(f"[REDACTED:{name}]", text)
        total += count
    return text, total
