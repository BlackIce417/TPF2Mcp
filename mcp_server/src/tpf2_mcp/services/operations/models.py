from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class GameOperation:
    operation_id: str
    operation_type: str
    snapshot_sequence: int | None
    target: dict[str, Any]
    parameters: dict[str, Any]
    expected_effect: dict[str, Any]
    expected_entity_state: dict[str, Any]

    def value(self) -> dict[str, Any]:
        return asdict(self)
