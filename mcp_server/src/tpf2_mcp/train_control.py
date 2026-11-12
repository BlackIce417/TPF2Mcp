"""MCP-facing train telemetry and bounded speed-control service."""
from __future__ import annotations

import hashlib
import math
import threading
import time
from typing import Any, Callable

from .loader_telemetry import (
    TrainTelemetryFrame,
    read_train_footprints,
    read_train_frame,
    read_train_identities,
)
from .native_ipc import ControllerCommandClient, ControllerCommandError


class TrainControlError(RuntimeError):
    """A safe, user-facing train-control validation or runtime error."""


def _vec3(value: Any) -> dict[str, float | None]:
    return {"x": _finite(value.x), "y": _finite(value.y), "z": _finite(value.z)}


def _edge(value: Any) -> dict[str, Any] | None:
    if not value.valid or not value.edge_entity_id:
        return None
    return {
        "edge_id": int(value.edge_entity_id),
        "position01": float(value.position01),
        "direction": int(value.direction),
    }


def _finite(value: Any) -> float | None:
    number = float(value)
    return number if math.isfinite(number) else None


def _kmh(value: Any) -> float | None:
    number = _finite(value)
    return round(number * 3.6, 3) if number is not None else None


def _route_summary(footprint: dict | None) -> dict[str, Any] | None:
    route = (footprint or {}).get("route_window")
    if not isinstance(route, dict):
        return None
    edges, start, current = route.get("edge_ids"), route.get("start_index"), route.get("current_index")
    if not isinstance(edges, list) or not isinstance(start, int) or not isinstance(current, int):
        return None
    offset = current - start
    forward = edges[offset:offset + 32] if 0 <= offset < len(edges) else []
    return {
        "start_index": start, "current_index": current,
        "end_index": start + len(edges) - 1, "edge_count": len(edges),
        "current_edge_id": forward[0] if forward else None,
        "forward_edge_ids": forward,
        "forward_edges_truncated": len(edges) - max(offset, 0) > len(forward),
    }


class TrainControlService:
    """Combine Loader telemetry with the sole Controller command publisher."""

    def __init__(
        self,
        *,
        frame_reader: Callable[[], TrainTelemetryFrame] = read_train_frame,
        identity_reader: Callable[[], tuple] = read_train_identities,
        footprint_reader: Callable[[], dict] = read_train_footprints,
        command_client_factory: Callable[[], ControllerCommandClient] = ControllerCommandClient,
        clock: Callable[[], float] = time.time,
        topology_reader: Callable[[], dict] | None = None,
    ):
        self._frame_reader = frame_reader
        self._identity_reader = identity_reader
        self._footprint_reader = footprint_reader
        self._command_client_factory = command_client_factory
        self._clock = clock
        self._lock = threading.Lock()
        self._controls: dict[str, dict[str, Any]] = {}
        if topology_reader is None:
            from .world_mcp import LoaderWorldRepository
            topology_reader = LoaderWorldRepository().get_full_network_topology
        self._topology_reader = topology_reader
        self._occupancy_index = None

    @staticmethod
    def _rule_id(command_id: str) -> int:
        value = int.from_bytes(hashlib.sha256(command_id.encode("utf-8")).digest()[:8], "little")
        return value or 1

    def _read(self) -> tuple[TrainTelemetryFrame, dict[int, Any], dict[int, dict], dict]:
        try:
            frame = self._frame_reader()
            identities = {int(row.entity_id): row for row in self._identity_reader()}
        except (OSError, KeyError, ValueError, RuntimeError) as exc:
            raise TrainControlError(f"TRAIN_TELEMETRY_UNAVAILABLE: {exc}") from exc
        footprint_payload: dict = {}
        try:
            footprint_payload = self._footprint_reader()
        except (OSError, KeyError, ValueError, RuntimeError):
            pass
        footprints = {
            int(row["entity_id"]): row
            for row in footprint_payload.get("vehicles", [])
            if isinstance(row, dict) and isinstance(row.get("entity_id"), int)
        }
        return frame, identities, footprints, footprint_payload

    @staticmethod
    def _train_record(frame: TrainTelemetryFrame, train: Any, identity: Any, footprint: dict | None,
                      include_parts: bool) -> dict[str, Any]:
        record = {
            "display_name": identity.display_name if identity else None,
            "vehicle_id": int(train.entity_id),
            "line_id": int(train.line_entity_id) or (identity.line_id if identity else None),
            "state": int(train.state),
            "flags": int(train.flags),
            "length_m": _finite(train.total_length_m),
            "speed": {
                "current_kmh": _kmh(train.current_speed_mps),
                "current_mps": _finite(train.current_speed_mps),
                "technical_max_kmh": _kmh(train.technical_max_speed_mps),
                "track_limit_kmh": _kmh(train.track_speed_limit_mps),
                "commanded_limit_kmh": _kmh(train.commanded_speed_limit_mps),
                "effective_limit_kmh": _kmh(train.effective_speed_limit_mps),
                "acceleration_mps2": _finite(train.acceleration_mps2),
                "brake_deceleration_mps2": _finite(train.brake_deceleration_mps2),
            },
            "position": {
                "center": _vec3(train.center),
                "front": _vec3(train.front),
                "rear": _vec3(train.rear),
                "center_edge": _edge(train.center_edge),
                "front_edge": _edge(train.front_edge),
                "rear_edge": _edge(train.rear_edge),
                "path_edge_index": int(train.path_edge_index),
                "path_edge_count": int(train.path_edge_count),
            },
            "load": {
                "passengers": int(train.passenger_count),
                "passenger_capacity": int(train.passenger_capacity),
                "freight": int(train.freight_amount),
                "freight_capacity": int(train.freight_capacity),
            },
            "sample_sequence": int(train.sample_sequence),
            "sample_time_us": int(train.sample_time_us),
            "route_window": _route_summary(footprint),
        }
        if include_parts:
            parts = frame.parts[train.parts_offset:train.parts_offset + train.parts_count]
            record["parts"] = [{
                "part_index": int(part.part_index),
                "entity_id": int(part.entity_id),
                "model_id": int(part.model_id),
                "flags": int(part.flags),
                "length_m": _finite(part.model_length_m),
                "technical_max_speed_kmh": _kmh(part.technical_max_speed_mps),
                "passengers": int(part.passenger_count),
                "passenger_capacity": int(part.passenger_capacity),
                "freight": int(part.freight_amount),
                "freight_capacity": int(part.freight_capacity),
                "center": _vec3(part.center),
            } for part in parts]
        return record

    def snapshot(self, *, display_name: str | None = None, include_parts: bool = False) -> dict[str, Any]:
        topology, topology_error = None, None
        try:
            # Build static topology before sampling motion, so a cold graph
            # build cannot make the returned train frame several seconds old.
            topology = self._topology_reader()
        except (OSError, KeyError, ValueError, RuntimeError) as exc:
            topology_error = str(exc)
        frame, identities, footprints, footprint_payload = self._read()
        trains = [
            self._train_record(frame, train, identities.get(int(train.entity_id)),
                               footprints.get(int(train.entity_id)), include_parts)
            for train in frame.trains
        ]
        if display_name is not None:
            trains = [row for row in trains if row["display_name"] == display_name]
            if not trains:
                raise TrainControlError(f"TRAIN_NOT_FOUND: display_name={display_name!r}")
            if len(trains) > 1:
                raise TrainControlError(f"AMBIGUOUS_TRAIN_NAME: display_name={display_name!r}")
        generated_at = footprint_payload.get("generated_at")
        age = self._clock() - generated_at if isinstance(generated_at, (int, float)) else None
        observed_at = self._clock()
        topology_id, section_states, occupancy_complete = None, [], False
        try:
            if topology is None:
                raise RuntimeError(topology_error or 'TOPOLOGY_UNAVAILABLE')
            if not topology.get('session_id') or topology['session_id'] != footprint_payload.get('session_id'):
                raise RuntimeError('TOPOLOGY_SESSION_MISMATCH')
            topology_id = topology['topology_id']
            from .train_dispatch import OccupancyIndex
            if self._occupancy_index is None or self._occupancy_index.topology_id != topology_id:
                self._occupancy_index = OccupancyIndex(topology)
            section_states, occupancy_complete = self._occupancy_index.overlay(
                trains, sampled_at=observed_at, source_fresh=isinstance(age,(int,float)) and 0 <= age <= 3,
                fleet_complete=display_name is None)
        except (OSError, KeyError, ValueError, RuntimeError) as exc:
            topology_error = str(exc)
            topology_id = None
            from .train_dispatch import TrainDispatchState
            from dataclasses import asdict
            for train in trains:
                train['dispatch'] = asdict(TrainDispatchState(
                    train['vehicle_id'], train['display_name'], None, observed_at, train['sample_sequence'],
                    reasons=['TOPOLOGY_UNAVAILABLE']))
        return {
            "schema_version": 1,
            "sample_sequence": int(frame.header.sample_sequence),
            "sample_time_us": int(frame.header.sample_time_us),
            "session_id": footprint_payload.get('session_id'),
            "train_count": len(trains),
            "topology_id": topology_id,
            "observed_at": observed_at,
            "section_states": section_states,
            "occupancy_complete": occupancy_complete,
            "occupancy_scope": "FULL_FLEET" if display_name is None else "FILTERED_TRAIN",
            "telemetry": {
                "train_wrappers": "AVAILABLE",
                "route_windows": "AVAILABLE" if footprints else "UNAVAILABLE",
                "route_window_age_seconds": round(age, 3) if age is not None else None,
                "topology_error": topology_error,
            },
            "trains": trains,
        }

    def runtime_status(self) -> dict[str, Any]:
        """Report only the current Loader/Controller transport health."""
        try:
            frame, identities, footprints, footprint_payload = self._read()
            generated_at = footprint_payload.get("generated_at")
            route_age = self._clock() - generated_at if isinstance(generated_at, (int, float)) else None
            loader = {
                "connected": True,
                "train_sample_sequence": int(frame.header.sample_sequence),
                "train_count": len(frame.trains),
                "identity_count": len(identities),
                "route_window_count": len(footprints),
                "route_window_age_seconds": round(route_age, 3) if route_age is not None else None,
                "route_windows_fresh": isinstance(route_age, (int, float)) and 0 <= route_age <= 3,
            }
        except TrainControlError as exc:
            loader = {"connected": False, "reason": str(exc)}
        try:
            controller_available = bool(ControllerCommandClient.available())
            controller_epoch = ControllerCommandClient.epoch() if controller_available else None
        except (OSError, RuntimeError):
            controller_available, controller_epoch = False, None
        return {
            "schema_version": 1,
            "transport_generation": "loader-controller-v2",
            "loader": loader,
            "controller": {"connected": controller_available, "epoch": controller_epoch},
            "legacy_file_bridge": {"exposed": False, "status": "ISOLATED"},
        }

    def _target(self, display_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
        frame, identities, footprints, footprint_payload = self._read()
        matches = [train for train in frame.trains
                   if (identities.get(int(train.entity_id)) is not None
                       and identities[int(train.entity_id)].display_name == display_name)]
        if not matches:
            raise TrainControlError(f"TRAIN_NOT_FOUND: display_name={display_name!r}")
        if len(matches) > 1:
            raise TrainControlError(f"AMBIGUOUS_TRAIN_NAME: display_name={display_name!r}")
        raw_generated_at = footprint_payload.get("generated_at")
        age = self._clock() - raw_generated_at if isinstance(raw_generated_at, (int, float)) else None
        if not isinstance(age, (int, float)) or not 0 <= age <= 3:
            raise TrainControlError(f"ROUTE_WINDOW_STALE: age_seconds={age!r}")
        wrapper = matches[0]
        footprint = footprints.get(int(wrapper.entity_id))
        route = (footprint or {}).get("route_window")
        if not isinstance(route, dict):
            raise TrainControlError("ROUTE_WINDOW_UNAVAILABLE: cannot safely scope a speed rule")
        train = self._train_record(frame, wrapper, identities.get(int(wrapper.entity_id)), footprint, False)
        wrapper_index = train["position"].get("path_edge_index")
        if isinstance(wrapper_index, int) and wrapper_index != route.get("current_index"):
            raise TrainControlError("ROUTE_WINDOW_STALE: wrapper and route path indices disagree")
        return train, route

    @staticmethod
    def _route_scope(train: dict[str, Any], route: dict[str, Any], lookahead_edges: int) -> tuple[list[int], int, int]:
        edges = route.get("edge_ids")
        start = route.get("start_index")
        current = route.get("current_index")
        if not isinstance(edges, list) or not isinstance(start, int) or not isinstance(current, int):
            raise TrainControlError("ROUTE_WINDOW_INVALID: missing edge_ids/start_index/current_index")
        offset = current - start
        if not 0 <= offset < len(edges):
            raise TrainControlError("ROUTE_WINDOW_STALE: current path index is outside the route window")
        selected = edges[offset:offset + lookahead_edges]
        if not selected or any(not isinstance(edge, int) or edge <= 0 for edge in selected):
            raise TrainControlError("ROUTE_WINDOW_INVALID: no usable forward edges")
        unique = list(dict.fromkeys(selected))
        return unique, current, current + len(selected) - 1

    def set_speed_limit(self, *, command_id: str, display_name: str, speed_kmh: float,
                        lookahead_edges: int, expires_in_seconds: int, confirmation: str,
                        reason: dict[str, Any]) -> dict[str, Any]:
        if confirmation != f"APPLY_SPEED_LIMIT:{command_id}":
            raise TrainControlError(f"CONFIRMATION_REQUIRED: expected APPLY_SPEED_LIMIT:{command_id}")
        if not isinstance(speed_kmh, (int, float)) or isinstance(speed_kmh, bool) or not math.isfinite(speed_kmh) or not 0 <= speed_kmh <= 500:
            raise TrainControlError('INVALID_SPEED_LIMIT: speed_kmh must be from 0 to 500')
        if not isinstance(reason, dict):
            raise TrainControlError('INVALID_REASON: reason must be an object')
        kind = reason.get('kind')
        action = '停车' if speed_kmh == 0 else '减速'
        if kind == 'FRONT_TRAIN_TOO_CLOSE':
            distance = reason.get('distance_threshold_m')
            if not isinstance(distance, (int, float)) or isinstance(distance, bool) or not math.isfinite(distance) or distance <= 0:
                raise TrainControlError('INVALID_REASON: distance_threshold_m must be positive')
            reason = {'kind': kind, 'distance_threshold_m': distance}
            reason_text = f'与前车距离过近，小于{distance:g}米，{action}'
        elif kind == 'WAIT_ENTRY_SIGNAL':
            target = reason.get('waiting_for_train')
            if not isinstance(target, str) or not target.strip() or len(target) > 256:
                raise TrainControlError('INVALID_REASON: waiting_for_train must be a display_name')
            reason = {'kind': kind, 'waiting_for_train': target}
            reason_text = f'等待进站信号机开放，{action}待避{target}'
        else:
            raise TrainControlError('INVALID_REASON: choose FRONT_TRAIN_TOO_CLOSE or WAIT_ENTRY_SIGNAL')
        train, route = self._target(display_name)
        technical_max = train["speed"]["technical_max_kmh"]
        if speed_kmh > technical_max + 0.01:
            raise TrainControlError(f"INVALID_SPEED_LIMIT: {speed_kmh} exceeds technical maximum {technical_max} km/h")
        edges, path_start, path_end = self._route_scope(train, route, lookahead_edges)
        request = {
            "display_name": display_name,
            "vehicle_id": train["vehicle_id"],
            "speed_kmh": float(speed_kmh),
            "lookahead_edges": lookahead_edges,
            "expires_in_seconds": expires_in_seconds,
            "reason": reason,
            "reason_text": reason_text,
        }
        with self._lock:
            previous = self._controls.get(command_id)
            if previous is not None:
                comparable = {key: previous.get(key) for key in request}
                if comparable != request:
                    raise TrainControlError("COMMAND_ID_CONFLICT: command_id was already used with different parameters")
                if previous.get("expires_at", 0) <= int(self._clock()):
                    previous["status"] = "EXPIRED"
                    return {**previous, "result": "ALREADY_EXPIRED"}
                return {**previous, "result": "ALREADY_APPLIED"}
            rule_id = self._rule_id(command_id)
            expires_at = int(self._clock()) + expires_in_seconds
            payload = {
                "vehicle_id": train["vehicle_id"], "speed_mps": speed_kmh / 3.6,
                "hold": speed_kmh == 0,
                "edge_ids": edges, "path_index_start": path_start,
                "path_index_end": path_end, "expires_at": expires_at,
            }
            try:
                reply = self._command_client_factory().upsert_speed_rule(rule_id, payload)
            except (OSError, ValueError, RuntimeError, ControllerCommandError) as exc:
                raise TrainControlError(f"CONTROLLER_COMMAND_FAILED: {exc}") from exc
            record = {
                "schema_version": 1, "command_id": command_id, "rule_id": rule_id,
                **request, "speed_mps": round(speed_kmh / 3.6, 6),
                "path_index_start": path_start, "path_index_end": path_end,
                "edge_count": len(edges), "expires_at": expires_at,
                "status": "ACTIVE", "result": "APPLIED",
                "controller_generation": reply.get("controller_generation"),
            }
            self._controls[command_id] = record
            return dict(record)

    def cancel_speed_limit(self, *, command_id: str, confirmation: str) -> dict[str, Any]:
        if confirmation != f"CANCEL_SPEED_LIMIT:{command_id}":
            raise TrainControlError(f"CONFIRMATION_REQUIRED: expected CANCEL_SPEED_LIMIT:{command_id}")
        with self._lock:
            record = self._controls.get(command_id)
            if record is None or record.get("status") != "ACTIVE":
                return {"schema_version": 1, "command_id": command_id, "result": "ALREADY_INACTIVE",
                        "reason_text": "取消限速命令"}
            try:
                reply = self._command_client_factory().remove_speed_rule(record["rule_id"])
            except ControllerCommandError as exc:
                if "RULE_NOT_FOUND" not in str(exc):
                    raise TrainControlError(f"CONTROLLER_COMMAND_FAILED: {exc}") from exc
                reply = exc.reply
            except (OSError, ValueError, RuntimeError) as exc:
                raise TrainControlError(f"CONTROLLER_COMMAND_FAILED: {exc}") from exc
            record.update(status="CANCELLED", cancelled_at=int(self._clock()))
            return {
                "schema_version": 1, "command_id": command_id, "display_name": record["display_name"],
                "result": "CANCELLED", "controller_generation": reply.get("controller_generation"),
                "reason_text": "取消限速命令",
            }

    def active_controls(self) -> dict[str, Any]:
        now = int(self._clock())
        with self._lock:
            controls = []
            for record in self._controls.values():
                row = dict(record)
                if row.get("status") == "ACTIVE" and row.get("expires_at", 0) <= now:
                    row["status"] = "EXPIRED"
                    record["status"] = "EXPIRED"
                if row.get("status") == "ACTIVE":
                    controls.append(row)
        return {"schema_version": 1, "active_count": len(controls), "controls": controls}
