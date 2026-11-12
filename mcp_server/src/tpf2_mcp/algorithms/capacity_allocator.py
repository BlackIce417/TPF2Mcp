"""Capacity-first allocation for parallel services sharing one OD market."""
from __future__ import annotations

from typing import Any


def allocate_to_available_capacity(demand: int, services: list[dict[str, Any]]) -> dict[str, Any]:
    """Fill the service with most usable residual capacity first.

    Capacity is consumed as assignments are made. Equal splitting is never a
    goal; a full service receives no assignment while another has room.
    """
    remaining = max(0, int(demand))
    allocations = []
    ranked = sorted(services, key=lambda item: (-max(0, int(item.get("residual_capacity") or 0)),
                                                float(item.get("departure_in_seconds") or 0),
                                                int(item["line_id"])))
    for service in ranked:
        residual = max(0, int(service.get("residual_capacity") or 0))
        assigned = min(remaining, residual)
        remaining -= assigned
        allocations.append({**service, "assigned": assigned,
                            "residual_after_assignment": residual - assigned})
    return {
        "requested": max(0, int(demand)),
        "assigned": max(0, int(demand)) - remaining,
        "unassigned": remaining,
        "allocations": allocations,
        "policy": "MAX_AVAILABLE_CAPACITY_FIRST_THEN_NEXT_DEPARTURE",
        "equal_split": False,
    }
