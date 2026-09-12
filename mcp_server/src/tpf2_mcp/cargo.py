"""Dynamic cargo-type registry sourced from a TPF2 world snapshot."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CargoTypes = list[dict[str, Any]]


@dataclass(frozen=True)
class CargoRegistry:
    """Read-only, key-addressable cargo types without a hard-coded vanilla list."""

    items: CargoTypes
    by_key: dict[str, dict[str, Any]] = field(init=False)

    def __post_init__(self) -> None:
        normalized = [dict(item) for item in self.items if isinstance(item, dict) and isinstance(item.get("cargo_key"), str)]
        object.__setattr__(self, "items", normalized)
        object.__setattr__(self, "by_key", {item["cargo_key"]: item for item in normalized})

    @classmethod
    def from_snapshot(cls, state: dict[str, Any]) -> "CargoRegistry":
        values = state.get("cargo_types", [])
        return cls(values if isinstance(values, list) else [])

    def list(self) -> CargoTypes:
        return list(self.items)
