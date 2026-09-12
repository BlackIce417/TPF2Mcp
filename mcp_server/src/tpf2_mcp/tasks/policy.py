from __future__ import annotations

from typing import Any


POLICIES = {"MANUAL", "AUTO_SAFE", "PLAN_ONLY"}


def can_auto_execute(policy: str, operation_capability: dict[str, Any] | None) -> bool:
    return policy == "AUTO_SAFE" and bool(operation_capability and operation_capability.get("verified") and not operation_capability.get("destructive") and operation_capability.get("supports_rollback") and operation_capability.get("risk_class") == "LOW")
