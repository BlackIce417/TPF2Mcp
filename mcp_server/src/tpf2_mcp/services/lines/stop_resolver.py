from __future__ import annotations
from typing import Any


class LineStopResolver:
    """Evidence-only resolver; it never invents a terminal choice."""
    def __init__(self, index: Any): self.index = index

    def resolve_station_stop(self, station_id: int, transport_mode: str | None = None, terminal_selector: int | None = None) -> dict[str, Any]:
        if station_id not in self.index.station_by_id:
            return {"station_id": station_id, "resolution_status": "STATION_NOT_FOUND"}
        observed = {(stop.get("station_index"), stop.get("terminal_id")) for line in self.index.line_by_id.values() for stop in line.get("raw_stops", []) if stop.get("station_id") == station_id and isinstance(stop.get("station_index"), int) and isinstance(stop.get("terminal_id"), int)}
        candidates = sorted(observed)
        if terminal_selector is not None:
            observed_selector = next((item for item in candidates if item[1] == terminal_selector), None)
            return {"station_id": station_id, "station_group_id": station_id, "station_index": observed_selector[0] if observed_selector else None, "terminal": terminal_selector, "resolution_status": "RESOLVED" if observed_selector else "NO_COMPATIBLE_TERMINAL", "source_status": "OBSERVED_EXPLICIT_TERMINAL" if observed_selector else "USER_EXPLICIT_NOT_ENGINE_VALIDATED"}
        if not candidates:
            return {"station_id": station_id, "resolution_status": "UNAVAILABLE", "reason": "No normalized raw-terminal evidence is present in this snapshot."}
        if len(candidates) != 1:
            return {"station_id": station_id, "resolution_status": "AMBIGUOUS_TERMINAL", "terminal_candidates": [{"station_index": item[0], "terminal": item[1]} for item in candidates]}
        return {"station_id": station_id, "station_group_id": station_id, "station_index": candidates[0][0], "terminal": candidates[0][1], "resolution_status": "RESOLVED", "source_status": "OBSERVED_EXISTING_LINE_STOP"}
