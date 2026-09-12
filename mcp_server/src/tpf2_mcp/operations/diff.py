from __future__ import annotations

from typing import Any


def entity_diff(entity_type: str, entity_id: int, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Small, explicit entity diff; other world changes are correlation only."""
    changes = {key: {"before": before.get(key), "after": after.get(key)} for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)}
    return {"entity": {"type": entity_type, "id": entity_id}, "changes": changes,
            "unexpected_snapshot_changes": [], "limitation": "Other snapshot changes are correlated, not attributed to this operation."}
