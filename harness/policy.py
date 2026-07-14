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


# Operating modes and how each decides a coarse capability. The fine-grained
# action classes (network/remote/deploy asking separately) refine this in
# permissions.py; this table is the base gate every tool passes through.
#   full            — everything (single-operator trust)
#   read_only       — inspection only
#   plan            — read/inspect only (Codex "plan")
#   build_ask       — reads auto; every mutation needs approval
#   auto_workspace  — workspace edits + commands auto; refined asks live in permissions.py
#   bypass_sandboxed— skip approval, rely on the container sandbox for safety
_MODE_TABLE: dict[str, dict[Capability, Decision]] = {
    "full": {c: Decision.ALLOW for c in Capability},
    "bypass_sandboxed": {c: Decision.ALLOW for c in Capability},
    "auto_workspace": {c: Decision.ALLOW for c in Capability},
    "read_only": {Capability.READ: Decision.ALLOW, Capability.WRITE: Decision.DENY, Capability.EXECUTE: Decision.DENY},
    "plan": {Capability.READ: Decision.ALLOW, Capability.WRITE: Decision.DENY, Capability.EXECUTE: Decision.DENY},
    "build_ask": {Capability.READ: Decision.ALLOW, Capability.WRITE: Decision.ASK, Capability.EXECUTE: Decision.ASK},
}

VALID_MODES = tuple(_MODE_TABLE)


class PermissionPolicy:
    """Maps (capability, mode) -> Decision. This is the base permission model;
    permissions.py adds action-class refinement + the approval channel."""

    def __init__(self, mode: str):
        self.mode = mode

    def decide(self, capability: Capability) -> Decision:
        table = _MODE_TABLE.get(self.mode)
        if table is None:
            return Decision.DENY  # unknown mode: fail closed
        return table.get(capability, Decision.DENY)

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
