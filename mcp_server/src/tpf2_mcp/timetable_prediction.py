"""Bind observed vehicles to timetable trips and project conservative ETAs."""
from __future__ import annotations

import math
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


@dataclass
class TripBinding:
    phase_index: int
    cycle_index: int
    last_stop_index: int
    observed_arrival_game_time: float
    scheduled_arrival_game_time: float
    delay_seconds: float


class TimetablePredictor:
    """Persistent per-world bindings inferred from reliable station observations."""

    def __init__(self, on_time_tolerance_seconds: float = 30.0, state_path: Path | None = None):
        self.on_time_tolerance_seconds = on_time_tolerance_seconds
        self.state_path = Path(state_path) if state_path is not None else None
        self._save_id: str | None = None
        self._bindings: dict[tuple[int, int], TripBinding] = {}

    def _load(self, save_id: str | None) -> None:
        self._save_id = save_id
        self._bindings.clear()
        if self.state_path is None:
            return
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return
        if value.get("save_id") != save_id:
            return
        for item in value.get("bindings", []):
            try:
                key = (int(item["line_id"]), int(item["vehicle_id"]))
                self._bindings[key] = TripBinding(**{name: item[name] for name in TripBinding.__dataclass_fields__})
            except (KeyError, TypeError, ValueError):
                continue

    def _save(self) -> None:
        if self.state_path is None:
            return
        bindings = []
        for (line_id, vehicle_id), binding in sorted(self._bindings.items()):
            bindings.append({"line_id": line_id, "vehicle_id": vehicle_id,
                             **{name: getattr(binding, name) for name in TripBinding.__dataclass_fields__}})
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps({"schema_version": 1, "save_id": self._save_id,
                                         "bindings": bindings}, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.state_path)

    def reset(self, save_id: str | None = None) -> None:
        self._save_id = save_id
        self._bindings.clear()

    @staticmethod
    def _scheduled(line: dict[str, Any], phase_index: int, cycle_index: int, stop_index: int) -> float:
        return (float(line["epoch_game_time_ms"]) / 1000 + cycle_index * float(line["cycle_seconds"])
                + float(line["phase_offsets_seconds"][phase_index])
                + float(line["stops"][stop_index]["arrival_offset_seconds"]))

    def _nearest_binding(self, line: dict[str, Any], stop_index: int, now: float) -> TripBinding | None:
        if not line.get("phase_offsets_seconds") or not line.get("stops") or not line.get("cycle_seconds"):
            return None
        best: tuple[float, int, int, float] | None = None
        for phase_index, phase in enumerate(line["phase_offsets_seconds"]):
            origin = (float(line["epoch_game_time_ms"]) / 1000 + float(phase)
                      + float(line["stops"][stop_index]["arrival_offset_seconds"]))
            approximate = round((now - origin) / float(line["cycle_seconds"]))
            for cycle_index in (approximate - 1, approximate, approximate + 1):
                scheduled = origin + cycle_index * float(line["cycle_seconds"])
                candidate = (abs(now - scheduled), phase_index, cycle_index, scheduled)
                if best is None or candidate < best:
                    best = candidate
        if best is None:
            return None
        _, phase_index, cycle_index, scheduled = best
        return TripBinding(phase_index, cycle_index, stop_index, now, scheduled, now - scheduled)

    @staticmethod
    def _arrival_cycle(line: dict[str, Any], binding: TripBinding, stop_index: int, now: float) -> int:
        # Once bound, never select a later cycle merely because the train is very
        # late.  That would erase a delay greater than half a cycle.  A cycle only
        # advances when the observed stop sequence wraps to the start.
        return binding.cycle_index + (1 if stop_index <= binding.last_stop_index else 0)

    def predictions(self, save_id: str | None, line: dict[str, Any], frame: dict[str, Any],
        vehicles: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        if save_id != self._save_id:
            self._load(save_id)
        line_id = line.get("line_id")
        game_ms = _number((frame.get("simulation") or {}).get("clock", {}).get("game_time"))
        if not isinstance(line_id, int) or game_ms is None:
            return {int(v["entity_id"]): self._unknown("GAME_CLOCK_UNAVAILABLE") for v in vehicles if isinstance(v.get("entity_id"), int)}
        now = game_ms / 1000
        result: dict[int, dict[str, Any]] = {}
        for vehicle in vehicles:
            vehicle_id, stop_index = vehicle.get("entity_id"), vehicle.get("stop_index")
            if not isinstance(vehicle_id, int) or not isinstance(stop_index, int) or not 0 <= stop_index < len(line.get("stops", [])):
                if isinstance(vehicle_id, int):
                    result[vehicle_id] = self._unknown("STOP_INDEX_UNAVAILABLE")
                continue
            key = (line_id, vehicle_id)
            binding = self._bindings.get(key)
            in_station = vehicle.get("raw_state") == 2 and not vehicle.get("position_stale")
            if in_station and binding is None:
                binding = self._nearest_binding(line, stop_index, now)
                if binding:
                    self._bindings[key] = binding
                    self._save()
            elif in_station and binding and stop_index != binding.last_stop_index:
                cycle = self._arrival_cycle(line, binding, stop_index, now)
                scheduled = self._scheduled(line, binding.phase_index, cycle, stop_index)
                binding = TripBinding(binding.phase_index, cycle, stop_index, now, scheduled, now - scheduled)
                self._bindings[key] = binding
                self._save()
            if binding is None:
                result[vehicle_id] = self._unknown("AWAITING_FIRST_STATION_OBSERVATION")
                continue
            if in_station:
                scheduled, eta = binding.scheduled_arrival_game_time, binding.observed_arrival_game_time
                target_stop = stop_index
                prediction_source = "OBSERVED_AT_STATION"
            else:
                target_stop = stop_index
                cycle = binding.cycle_index + (1 if target_stop <= binding.last_stop_index else 0)
                scheduled = self._scheduled(line, binding.phase_index, cycle, target_stop)
                eta = scheduled + binding.delay_seconds
                prediction_source = "LAST_OBSERVED_DELAY_PROPAGATED"
                if eta <= now:
                    result[vehicle_id] = self._payload(binding, line, target_stop, scheduled, None,
                                                       "LATE_UNDETERMINED", None, "SCHEDULE_OVERRUN")
                    continue
            delay = eta - scheduled
            state = "LATE" if delay > self.on_time_tolerance_seconds else "ON_TIME"
            result[vehicle_id] = self._payload(binding, line, target_stop, scheduled, eta, state, delay, prediction_source)
        return result

    def _payload(self, binding: TripBinding, line: dict[str, Any], stop_index: int, scheduled: float,
                 eta: float | None, state: str, delay: float | None, source: str) -> dict[str, Any]:
        stop = line["stops"][stop_index]
        return {
            "binding_state": "INFERRED_FIXED_PERSISTED" if self.state_path is not None else "INFERRED_FIXED",
            "binding_source": "FIRST_STATION_OBSERVATION_NEAREST_PLAN_SLOT_PERSISTED" if self.state_path is not None else "FIRST_STATION_OBSERVATION_NEAREST_PLAN_SLOT",
            "phase_index": binding.phase_index,
            "cycle_index": binding.cycle_index,
            "target_stop_index": stop_index,
            "target_station_group_id": stop.get("station_group_id"),
            "target_station_name": stop.get("station_name"),
            "scheduled_arrival_game_time": round(scheduled, 3),
            "estimated_arrival_game_time": round(eta, 3) if eta is not None else None,
            "delay_seconds": round(delay, 1) if delay is not None else None,
            "punctuality": state,
            "prediction_source": source,
        }

    @staticmethod
    def _unknown(reason: str) -> dict[str, Any]:
        return {"binding_state": "UNBOUND", "punctuality": "LATE_UNDETERMINED",
                "prediction_source": reason, "scheduled_arrival_game_time": None,
                "estimated_arrival_game_time": None, "delay_seconds": None}


def project_prediction_to_wall(prediction: dict[str, Any], frame: dict[str, Any]) -> dict[str, Any]:
    """Attach local-clock Unix seconds only while a fresh running clock is usable."""
    value = dict(prediction)
    simulation = frame.get("simulation") or {}
    game_ms = _number((simulation.get("clock") or {}).get("game_time"))
    sampled_at, rate = _number(frame.get("sampled_at")), _number(simulation.get("speed_multiplier"))
    running = simulation.get("status") in {"RUNNING", "RUNNING_INFERRED"}
    for source, target in (("scheduled_arrival_game_time", "scheduled_arrival_at"),
                           ("estimated_arrival_game_time", "estimated_arrival_at")):
        game_target = _number(value.get(source))
        value[target] = (round(sampled_at + (game_target - game_ms / 1000) / rate, 3)
                         if running and sampled_at is not None and game_ms is not None and rate is not None and rate > 0 and game_target is not None
                         else None)
    return value
