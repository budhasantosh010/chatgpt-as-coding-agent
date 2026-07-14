from __future__ import annotations

import pytest

from harness.policy import Capability, Decision, PermissionPolicy
from harness.security import SecurityError


def test_full_mode_allows_everything():
    p = PermissionPolicy("full")
    for cap in Capability:
        assert p.decide(cap) is Decision.ALLOW
        p.require(cap)  # no raise


def test_read_only_allows_read_denies_the_rest():
    p = PermissionPolicy("read_only")
    assert p.decide(Capability.READ) is Decision.ALLOW
    p.require(Capability.READ)
    for cap in (Capability.WRITE, Capability.EXECUTE):
        assert p.decide(cap) is Decision.DENY
        with pytest.raises(SecurityError):
            p.require(cap)


def test_unknown_mode_fails_closed():
    p = PermissionPolicy("banana")
    with pytest.raises(SecurityError):
        p.require(Capability.READ)
