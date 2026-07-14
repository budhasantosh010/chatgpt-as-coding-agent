"""Capability + permission policy — the single place that decides what a tool is
allowed to do in the current mode.

Adding a new operating mode (e.g. Codex-style ``plan`` / ``build`` / ``ask``)
means editing only ``PermissionPolicy.decide``. Tools declare a capability and
never encode mode logic themselves.
"""

from __future__ import annotations

from enum import Enum

from .security import SecurityError


class Capability(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    # NETWORK = "network"   # reserved for a future capability


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"  # reserved: needs an out-of-band approval channel to be usable


class PermissionPolicy:
    """Maps (capability, mode) -> Decision. This is the whole permission model."""

    def __init__(self, mode: str):
        self.mode = mode

    def decide(self, capability: Capability) -> Decision:
        if self.mode == "read_only":
            return Decision.ALLOW if capability is Capability.READ else Decision.DENY
        if self.mode == "full":
            return Decision.ALLOW
        # Unknown mode: fail closed.
        return Decision.DENY

    def require(self, capability: Capability) -> None:
        decision = self.decide(capability)
        if decision is Decision.ALLOW:
            return
        if decision is Decision.ASK:
            raise SecurityError(
                f"Operation needs '{capability.value}' which requires approval, and "
                "no approval channel is configured. Switch the server to 'full' mode "
                "locally to allow it."
            )
        raise SecurityError(
            f"Operation needs capability '{capability.value}', denied in "
            f"'{self.mode}' mode. This can only be changed locally by the operator."
        )
