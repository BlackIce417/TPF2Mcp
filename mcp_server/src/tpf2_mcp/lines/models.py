from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class LineRouteRequest:
    start_station_id: int
    end_station_id: int
    via_station_ids: tuple[int, ...] = ()
    transport_mode: str | None = None

    def normalized_stop_sequence(self) -> list[int]:
        return [self.start_station_id, *self.via_station_ids, self.end_station_id]
