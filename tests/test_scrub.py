"""Secret-content scrubbing: known credential formats are redacted; ordinary
source code is left intact."""

from __future__ import annotations

from harness.scrub import scrub_text


def test_empty_is_noop():
    assert scrub_text("") == ("", 0)


def test_redacts_aws_key():
    out, n = scrub_text("cred AKIAIOSFODNN7EXAMPLE end")
    assert n == 1
    assert "AKIA" not in out
    assert "[REDACTED:aws-access-key-id]" in out


def test_redacts_github_token():
    token = "ghp_" + "a" * 36
    out, n = scrub_text(f"export GH_TOKEN={token}")
    assert n == 1 and token not in out


def test_redacts_openai_and_anthropic():
    text = "OPENAI=sk-" + "A" * 40 + " ANTH=sk-ant-" + "B" * 40
    out, n = scrub_text(text)
    assert n == 2
    assert "sk-AAAA" not in out and "sk-ant-BBBB" not in out


def test_redacts_private_key_block():
    block = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA1234567890\nabcdef....\n"
        "-----END RSA PRIVATE KEY-----"
    )
    out, n = scrub_text(f"key file:\n{block}\ntrailing")
    assert n == 1
    assert "PRIVATE KEY" not in out
    assert "trailing" in out and "key file:" in out


def test_redacts_jwt():
    jwt = "eyJhbGciOiJIUzI1NiIsInR5" + "." + "eyJzdWIiOiIxMjM0NTY3" + "." + "SflKxwRJSMeKKF2QT4fw"
    out, n = scrub_text(jwt)
    assert n == 1 and "[REDACTED:jwt]" in out


def test_counts_multiple():
    text = "AKIAIOSFODNN7EXAMPLE and AKIAIOSFODNN7EXAMPLE"
    _out, n = scrub_text(text)
    assert n == 2


def test_leaves_normal_code_alone():
    code = "def add(a, b):\n    return a + b  # sk is not a key, short\n"
    out, n = scrub_text(code)
    assert n == 0 and out == code
