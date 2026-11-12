"""Shared evidence objects for Phase 9 analytics responses."""
from __future__ import annotations

from typing import Any


FIELD_SOURCES = {
    "frequency_seconds": ("game.interface.getEntity(line_id).frequency (1 / raw value)", "UI_CROSS_VERIFIED"),
    "throughput": ("game.interface.getEntity(line_id).rate", "UI_CROSS_VERIFIED"),
    "capacity_total": ("TRANSPORT_VEHICLE.config.capacities", "UI_CROSS_VERIFIED"),
    "stop_count": ("normalized LINE stops", "ENGINE_VERIFIED"),
    "vehicle_count": ("vehicle.line_id relationship", "DERIVED"),
}


def evidence(field: str, value: Any, status: str | None = None) -> dict[str, Any]:
    source, verification = FIELD_SOURCES.get(field, ("derived analytics", "DERIVED"))
    return {"field": field, "value": value, "source": source, "verification": status or verification}


def unavailable(metric: str, reason: str) -> dict[str, str]:
    return {"metric": metric, "status": "UNAVAILABLE", "reason": reason}
