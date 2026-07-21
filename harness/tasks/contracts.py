"""Typed, hash-verified Run Contract for the four independent controls."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, model_validator


_TASK_TYPES = {"build", "review", "plan", "research"}
_EFFORT_LEVELS = {"off", "low", "medium", "high", "xhigh", "max"}
_FRAMEWORKS = {"none", "aocs_omega"}

# Operator ceilings for the two countable controls, mirroring the Workbench's
# custom-entry caps (contract-options.mjs ULTRA_CUSTOM_MAX / LOOPS_CUSTOM_MAX).
# Enforced when a NEW contract is confirmed, not in the model validator, so
# contracts already on disk stay loadable. A "bounded refinement" control that
# accepts 999999 is not a bound, and every creation path (Workbench and the MCP
# tools ChatGPT drives) funnels through confirmed().
MAX_CANDIDATE_COUNT = 64
MAX_LOOPS = 100


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def contract_hash(data: dict[str, Any]) -> str:
    payload = {k: v for k, v in data.items() if k != "contract_hash"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RunContract(BaseModel):
    contract_version: int = 1
    task_type: str
    effort_level: str
    credit_ceiling: int
    ultra_enabled: bool
    candidate_count: int
    machine_concurrency: int
    model_concurrency: int
    framework: str
    max_loops: int
    early_stop: bool = True
    operator_confirmed: bool = True
    confirmed_at: str
    contract_hash: str

    @model_validator(mode="after")
    def validate_contract(self) -> "RunContract":
        if self.contract_version != 1:
            raise ValueError("unsupported contract_version")
        if self.task_type not in _TASK_TYPES:
            raise ValueError(f"invalid task_type {self.task_type!r}")
        if self.effort_level not in _EFFORT_LEVELS:
            raise ValueError(f"invalid effort_level {self.effort_level!r}")
        if self.framework not in _FRAMEWORKS:
            raise ValueError(f"invalid framework {self.framework!r}")
        if self.effort_level == "off" and self.credit_ceiling != 0:
            raise ValueError("EFFORT Off requires credit_ceiling=0")
        if self.effort_level != "off" and self.credit_ceiling <= 0:
            raise ValueError("enabled EFFORT requires a positive credit_ceiling")
        if self.candidate_count < 0:
            raise ValueError("candidate_count must be >= 0")
        if self.ultra_enabled != (self.candidate_count > 0):
            raise ValueError("ultra_enabled must match candidate_count > 0")
        if self.machine_concurrency < 1 or self.model_concurrency < 1:
            raise ValueError("concurrency values must be >= 1")
        if self.max_loops < 0:
            raise ValueError("max_loops must be >= 0")
        if not self.early_stop or not self.operator_confirmed:
            raise ValueError("v1 contracts require early_stop and operator confirmation")
        expected = contract_hash(self.model_dump(mode="json"))
        if self.contract_hash != expected:
            raise ValueError("[CONTRACT_TAMPERED] Run Contract hash does not match its contents")
        return self

    @classmethod
    def confirmed(
        cls,
        *,
        task_type: str,
        effort_level: str,
        credit_ceiling: int,
        candidate_count: int,
        machine_concurrency: int,
        model_concurrency: int,
        framework: str,
        max_loops: int,
    ) -> "RunContract":
        if candidate_count > MAX_CANDIDATE_COUNT:
            raise ValueError(f"candidate_count must be <= {MAX_CANDIDATE_COUNT}")
        if max_loops > MAX_LOOPS:
            raise ValueError(f"max_loops must be <= {MAX_LOOPS}")
        data = {
            "contract_version": 1,
            "task_type": task_type,
            "effort_level": effort_level,
            "credit_ceiling": credit_ceiling,
            "ultra_enabled": candidate_count > 0,
            "candidate_count": candidate_count,
            "machine_concurrency": machine_concurrency,
            "model_concurrency": model_concurrency,
            "framework": framework,
            "max_loops": max_loops,
            "early_stop": True,
            "operator_confirmed": True,
            "confirmed_at": _now_iso(),
        }
        data["contract_hash"] = contract_hash(data)
        return cls.model_validate(data)
