"""Proposal-first controller for individually verified TPF2 operations."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import uuid
from typing import Any, Callable

from ..journal import JsonlJournal
from .capabilities import capability
from .handlers import get as handler_for
from .models import GameOperation

SnapshotProvider = Callable[[bool], Any]


class OperationController:
    def __init__(self, snapshot_provider: SnapshotProvider, command_executor: Callable[[dict[str, Any]], dict[str, Any]] | None = None, allow_unverified_test: bool = False, journal_path: Any = None):
        self._snapshot_provider = snapshot_provider
        self._command_executor = command_executor
        self._allow_unverified_test = allow_unverified_test
        self._persistent_journal = JsonlJournal(journal_path)
        self._journal = self._persistent_journal.latest("operation_id")
        self._order = sorted(self._journal, key=lambda key: self._journal[key].get("created_at", ""))

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _line(index: Any, line_id: int) -> dict[str, Any] | None:
        return index.line_by_id.get(line_id)

    @staticmethod
    def _simulation_running(index: Any) -> tuple[bool, dict[str, Any]]:
        simulation = index.state.get("simulation")
        simulation = simulation if isinstance(simulation, dict) else {}
        multiplier = simulation.get("speed_multiplier")
        running = simulation.get("paused") is not True and isinstance(multiplier, (int, float)) and not isinstance(multiplier, bool) and multiplier > 0
        return running, simulation

    def propose(self, operation_type: str, target: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        index = self._snapshot_provider(False)
        handler = handler_for(operation_type)
        if handler is not None:
            error = handler.validate_parameters(target, parameters)
            if error:
                return {"status": "INVALID_PARAMETERS", "reason": error}
            if operation_type == "BUY_VEHICLE":
                source = index.vehicle_by_id.get(parameters["source_vehicle_id"])
                if source is None:
                    return {"status": "ENTITY_NOT_FOUND", "reason": f"source vehicle {parameters['source_vehicle_id']} not found"}
                operation_target = {"entity_type": "DEPOT", "entity_id": target["depot_id"], "depot_id": target["depot_id"], "source_vehicle_id": parameters["source_vehicle_id"]}
                expected_state = {"vehicle_ids": sorted(index.vehicle_by_id)}
            elif operation_type == "CREATE_LINE_FROM_SOURCE_ROUTE":
                source = self._line(index, target["source_line_id"])
                if source is None:
                    return {"status": "ENTITY_NOT_FOUND", "reason": f"source line {target['source_line_id']} not found"}
                if len(source.get("stops", [])) < 2:
                    return {"status": "INVALID_SOURCE_ROUTE", "reason": "source line needs at least two stops"}
                operation_target = {"entity_type": "LINE", "entity_id": target["source_line_id"], "source_line_id": target["source_line_id"]}
                expected_state = {"line_ids": sorted(index.line_by_id)}
            elif operation_type == "CREATE_LINE":
                effect = handler.expected_effect(index, target, parameters)
                if effect.get("resolution_error") is not None:
                    return {"status": "ROUTE_NOT_RESOLVED", "reason": effect["resolution_error"]}
                operation_target = {"entity_type": "LINE"}
                expected_state = {"line_ids": sorted(index.line_by_id)}
            elif operation_type == "SET_LINE_STOPS":
                line = self._line(index, target["line_id"])
                if line is None: return {"status": "ENTITY_NOT_FOUND", "reason": f"line {target['line_id']} not found"}
                effect = handler.expected_effect(index, target, parameters)
                if effect.get("resolution_error") is not None: return {"status": "ROUTE_NOT_RESOLVED", "reason": effect["resolution_error"]}
                operation_target = {"entity_type": "LINE", "entity_id": target["line_id"], "line_id": target["line_id"]}
                expected_state = {"route": [item.get("station_id") for item in line.get("stops", [])]}
            elif operation_type == "SET_LINE_STOP_POLICY":
                line = self._line(index, target["line_id"])
                stop_index = parameters["stop_index"]
                if line is None: return {"status": "ENTITY_NOT_FOUND", "reason": f"line {target['line_id']} not found"}
                if stop_index >= len(line.get("stops", [])): return {"status": "ENTITY_NOT_FOUND", "reason": f"stop {stop_index} not found"}
                operation_target = {"entity_type": "LINE", "entity_id": target["line_id"], "line_id": target["line_id"]}
                expected_state = {"policy": deepcopy(line["stops"][stop_index].get("policy"))}
            elif operation_type in {"HOLD_VEHICLE_AT_TERMINAL", "RELEASE_VEHICLE_FROM_HOLD"}:
                if operation_type == "HOLD_VEHICLE_AT_TERMINAL":
                    running, simulation = self._simulation_running(index)
                    if not running:
                        return {"status": "SIMULATION_NOT_RUNNING", "reason": "Holding a vehicle requires confirmed running simulation.", "simulation": simulation}
                vehicle = index.vehicle_by_id.get(target["vehicle_id"])
                if vehicle is None:
                    return {"status": "ENTITY_NOT_FOUND", "reason": f"vehicle {target['vehicle_id']} not found"}
                if operation_type == "HOLD_VEHICLE_AT_TERMINAL" and vehicle.get("raw_state") != 2:
                    return {"status": "VEHICLE_NOT_AT_TERMINAL", "reason": "Holding requires raw transport-vehicle state 2 at proposal time.", "raw_state": vehicle.get("raw_state")}
                operation_target = {"entity_type": "VEHICLE", "entity_id": target["vehicle_id"], "vehicle_id": target["vehicle_id"]}
                expected_state = {"line_id": vehicle.get("line_id"), "raw_state": vehicle.get("raw_state"), "departure_control": deepcopy(vehicle.get("departure_control")), "raw_autoDeparture": vehicle.get("raw_autoDeparture")}
            elif operation_type == "SELL_VEHICLE":
                vehicle = index.vehicle_by_id.get(target["vehicle_id"])
                if vehicle is None:
                    return {"status": "ENTITY_NOT_FOUND", "reason": f"vehicle {target['vehicle_id']} not found"}
                operation_target = {"entity_type": "VEHICLE", "entity_id": target["vehicle_id"], "vehicle_id": target["vehicle_id"]}
                expected_state = {"line_id": vehicle.get("line_id"), "name": vehicle.get("name")}
            else:
                vehicle = index.vehicle_by_id.get(target["vehicle_id"])
                line = self._line(index, target["line_id"])
                if vehicle is None or line is None:
                    missing = "vehicle" if vehicle is None else "line"
                    return {"status": "ENTITY_NOT_FOUND", "reason": f"{missing} not found"}
                operation_target = {"entity_type": "VEHICLE", "entity_id": target["vehicle_id"], **target}
                expected_state = {"line_id": vehicle.get("line_id")}
            operation = GameOperation(
                operation_id=f"op-{uuid.uuid4()}", operation_type=operation_type,
                snapshot_sequence=index.state.get("sequence"), target=operation_target,
                parameters=deepcopy(parameters), expected_effect=handler.expected_effect(index, target, parameters),
                expected_entity_state=expected_state,
            )
            return self._store_proposal(operation)
        if operation_type != "RENAME_LINE":
            return {"status": "OPERATION_NOT_SUPPORTED", "operation_type": operation_type,
                    "reason": "Only reversible rename proposals are modelled in Phase 11; no operation is executable before API verification."}
        line_id, name = target.get("line_id"), parameters.get("name")
        if not isinstance(line_id, int) or not isinstance(name, str) or not name.strip() or len(name) > 128:
            return {"status": "INVALID_PARAMETERS", "reason": "RENAME_LINE requires integer target.line_id and non-empty parameters.name up to 128 characters."}
        line = self._line(index, line_id)
        if line is None:
            return {"status": "ENTITY_NOT_FOUND", "reason": f"line {line_id} not found"}
        operation = GameOperation(
            operation_id=f"op-{uuid.uuid4()}", operation_type=operation_type,
            snapshot_sequence=index.state.get("sequence"),
            target={"entity_type": "LINE", "entity_id": line_id, "line_id": line_id},
            parameters={"name": name.strip()}, expected_effect={"name": {"before": line.get("name"), "after": name.strip()}},
            expected_entity_state={"name": line.get("name")},
        )
        return self._store_proposal(operation)

    def _store_proposal(self, operation: GameOperation) -> dict[str, Any]:
        record = {"operation_id": operation.operation_id, "status": "PROPOSED", "created_at": self._timestamp(),
                  "operation": operation.value(), "validation": None, "command_result": None, "verification": None}
        self._journal[operation.operation_id] = record
        self._order.append(operation.operation_id)
        self._persist(record)
        return self._public(record, requires_execution=True)

    def _persist(self, record: dict[str, Any]) -> None:
        self._persistent_journal.append(deepcopy(record))

    def validate(self, operation_id: str, force_refresh: bool = False) -> dict[str, Any]:
        record = self._journal.get(operation_id)
        if record is None: return {"status": "OPERATION_NOT_FOUND", "operation_id": operation_id}
        operation = record["operation"]
        index = self._snapshot_provider(force_refresh)
        checks: list[dict[str, Any]] = []
        handler = handler_for(operation["operation_type"])
        if handler is not None:
            current_sequence = index.state.get("sequence")
            checks.append({"check": "SNAPSHOT_CURRENT", "status": "PASS" if current_sequence == operation["snapshot_sequence"] else "FAIL", "expected": operation["snapshot_sequence"], "actual": current_sequence})
            if operation["operation_type"] == "BUY_VEHICLE":
                source_id = operation["parameters"]["source_vehicle_id"]
                exists = index.vehicle_by_id.get(source_id) is not None
                checks.append({"check": "SOURCE_VEHICLE_EXISTS", "status": "PASS" if exists else "FAIL", "entity_id": source_id})
                unchanged = sorted(index.vehicle_by_id) == operation["expected_entity_state"]["vehicle_ids"]
                checks.append({"check": "FLEET_STATE_UNCHANGED", "status": "PASS" if unchanged else "FAIL"})
            elif operation["operation_type"] == "CREATE_LINE_FROM_SOURCE_ROUTE":
                source_id = operation["target"]["source_line_id"]
                source = self._line(index, source_id)
                checks.append({"check": "SOURCE_LINE_EXISTS", "status": "PASS" if source else "FAIL", "entity_id": source_id})
                unchanged = sorted(index.line_by_id) == operation["expected_entity_state"]["line_ids"]
                checks.append({"check": "LINE_SET_UNCHANGED", "status": "PASS" if unchanged else "FAIL"})
            elif operation["operation_type"] == "CREATE_LINE":
                unchanged = sorted(index.line_by_id) == operation["expected_entity_state"]["line_ids"]
                checks.append({"check": "LINE_SET_UNCHANGED", "status": "PASS" if unchanged else "FAIL"})
            elif operation["operation_type"] == "SET_LINE_STOPS":
                line = self._line(index, operation["target"]["line_id"])
                observed = [item.get("station_id") for item in line.get("stops", [])] if line else None
                checks.append({"check": "LINE_ROUTE_UNCHANGED", "status": "PASS" if observed == operation["expected_entity_state"]["route"] else "FAIL"})
            elif operation["operation_type"] == "SET_LINE_STOP_POLICY":
                line = self._line(index, operation["target"]["line_id"])
                stop_index = operation["parameters"]["stop_index"]
                stop = line.get("stops", [])[stop_index] if line and stop_index < len(line.get("stops", [])) else None
                observed = stop.get("policy") if stop else None
                checks.append({"check": "STOP_POLICY_UNCHANGED", "status": "PASS" if stop and observed == operation["expected_entity_state"]["policy"] else "FAIL", "expected": operation["expected_entity_state"]["policy"], "actual": observed})
            elif operation["operation_type"] in {"HOLD_VEHICLE_AT_TERMINAL", "RELEASE_VEHICLE_FROM_HOLD"}:
                vehicle = index.vehicle_by_id.get(operation["target"]["vehicle_id"])
                exists = vehicle is not None
                checks.append({"check": "VEHICLE_EXISTS", "status": "PASS" if exists else "FAIL"})
                unchanged = bool(vehicle) and vehicle.get("line_id") == operation["expected_entity_state"]["line_id"] and vehicle.get("raw_state") == operation["expected_entity_state"]["raw_state"] and vehicle.get("departure_control") == operation["expected_entity_state"]["departure_control"] and vehicle.get("raw_autoDeparture") == operation["expected_entity_state"]["raw_autoDeparture"]
                checks.append({"check": "DEPARTURE_CONTROL_UNCHANGED", "status": "PASS" if unchanged else "FAIL", "expected": operation["expected_entity_state"], "actual": {"line_id": vehicle.get("line_id"), "raw_state": vehicle.get("raw_state"), "departure_control": vehicle.get("departure_control"), "raw_autoDeparture": vehicle.get("raw_autoDeparture")} if vehicle else None})
                if operation["operation_type"] == "HOLD_VEHICLE_AT_TERMINAL":
                    running, simulation = self._simulation_running(index)
                    checks.append({"check": "SIMULATION_RUNNING", "status": "PASS" if running else "FAIL", "actual": simulation})
            elif operation["operation_type"] == "SELL_VEHICLE":
                vehicle = index.vehicle_by_id.get(operation["target"]["vehicle_id"])
                exists = vehicle is not None
                checks.append({"check": "VEHICLE_EXISTS", "status": "PASS" if exists else "FAIL"})
                unchanged = bool(vehicle) and vehicle.get("line_id") == operation["expected_entity_state"]["line_id"] and vehicle.get("name") == operation["expected_entity_state"]["name"]
                checks.append({"check": "ENTITY_STATE_UNCHANGED", "status": "PASS" if unchanged else "FAIL", "expected": operation["expected_entity_state"], "actual": {"line_id": vehicle.get("line_id"), "name": vehicle.get("name")} if vehicle else None})
            else:
                vehicle = index.vehicle_by_id.get(operation["target"]["vehicle_id"])
                line = self._line(index, operation["target"]["line_id"])
                exists = vehicle is not None and line is not None
                checks.append({"check": "ENTITIES_EXIST", "status": "PASS" if exists else "FAIL"})
                unchanged = bool(vehicle) and vehicle.get("line_id") == operation["expected_entity_state"]["line_id"]
                checks.append({"check": "ENTITY_STATE_UNCHANGED", "status": "PASS" if unchanged else "FAIL", "expected": operation["expected_entity_state"]["line_id"], "actual": vehicle.get("line_id") if vehicle else None})
            cap = capability(operation["operation_type"])
            capability_ok = bool(cap and cap["engine_verified"]) or self._allow_unverified_test
            checks.append({"check": "CAPABILITY_VERIFIED", "status": "PASS" if capability_ok else "FAIL", "source_status": cap["source_status"] if cap else "UNKNOWN"})
            valid = all(item["status"] == "PASS" for item in checks)
            scoped_state_ok = all(item["status"] == "PASS" for item in checks if item["check"] != "CAPABILITY_VERIFIED")
            if valid: status = "VALIDATED"
            elif current_sequence != operation["snapshot_sequence"]: status = "STALE_PROPOSAL"
            elif any(item["check"] == "SIMULATION_RUNNING" and item["status"] == "FAIL" for item in checks): status = "SIMULATION_NOT_RUNNING"
            elif not scoped_state_ok: status = "ENTITY_STATE_CHANGED"
            else: status = "OPERATION_NOT_VERIFIED"
            validation = {"valid": valid, "status": status, "checks": checks, "validated_at": self._timestamp()}
            record["validation"] = validation; record["status"] = "VALIDATED" if valid else "REJECTED"
            self._persist(record)
            return self._public(record)
        line = self._line(index, operation["target"]["line_id"])
        checks.append({"check": "ENTITY_EXISTS", "status": "PASS" if line else "FAIL"})
        current_sequence = index.state.get("sequence")
        checks.append({"check": "SNAPSHOT_CURRENT", "status": "PASS" if current_sequence == operation["snapshot_sequence"] else "FAIL", "expected": operation["snapshot_sequence"], "actual": current_sequence})
        checks.append({"check": "ENTITY_STATE_UNCHANGED", "status": "PASS" if line and line.get("name") == operation["expected_entity_state"]["name"] else "FAIL", "expected": operation["expected_entity_state"]["name"], "actual": line.get("name") if line else None})
        cap = capability(operation["operation_type"])
        capability_ok = bool(cap and cap["verified"]) or self._allow_unverified_test
        checks.append({"check": "CAPABILITY_VERIFIED", "status": "PASS" if capability_ok else "FAIL", "source_status": "DEDICATED_SAVE_TEST_AUTHORIZED" if self._allow_unverified_test else cap["source_status"] if cap else "UNKNOWN"})
        valid = all(item["status"] == "PASS" for item in checks)
        if not line: status = "ENTITY_NOT_FOUND"
        elif current_sequence != operation["snapshot_sequence"]: status = "STALE_PROPOSAL"
        elif line.get("name") != operation["expected_entity_state"]["name"]: status = "ENTITY_STATE_CHANGED"
        elif not capability_ok: status = "OPERATION_NOT_VERIFIED"
        else: status = "VALIDATED"
        validation = {"valid": valid, "status": status, "checks": checks, "validated_at": self._timestamp()}
        record["validation"] = validation
        record["status"] = "VALIDATED" if valid else "REJECTED"
        self._persist(record)
        return self._public(record)

    def execute(self, operation_id: str, dry_run: bool = True) -> dict[str, Any]:
        record = self._journal.get(operation_id)
        if record is None: return {"status": "OPERATION_NOT_FOUND", "operation_id": operation_id}
        validation_view = self.validate(operation_id, force_refresh=False)
        validation = record["validation"]
        if not validation or not validation["valid"]:
            return self._public(record, execution_status=validation["status"] if validation else "VALIDATION_FAILED", command_sent=False)
        if not dry_run and self._command_executor is not None and (self._allow_unverified_test or bool(capability(record["operation"]["operation_type"]) and capability(record["operation"]["operation_type"])["verified"])):
            command_parameters = deepcopy(record["operation"]["parameters"])
            if record["operation"]["operation_type"] == "CREATE_LINE":
                resolved = record["operation"]["expected_effect"]["resolved_stops"]
                command_parameters.update({
                    "station_ids": [item["station_id"] for item in resolved],
                    "station_indices": [item["station_index"] for item in resolved],
                    "terminal_ids": [item["terminal"] for item in resolved],
                })
            if record["operation"]["operation_type"] == "SET_LINE_STOPS":
                resolved = record["operation"]["expected_effect"]["resolved_stops"]
                command_parameters.update({"station_ids": [item["station_id"] for item in resolved], "station_indices": [item["station_index"] for item in resolved], "terminal_ids": [item["terminal"] for item in resolved]})
            command = {"protocol_version": 1, "operation_id": operation_id, "operation_type": record["operation"]["operation_type"], "target": deepcopy(record["operation"]["target"]), "parameters": command_parameters}
            try:
                result = self._command_executor(command)
            except Exception as exc:
                record["command_result"] = {"accepted": False, "engine_command_sent": False, "status": "COMMAND_REJECTED", "reason": str(exc), "at": self._timestamp()}
                record["status"] = "FAILED"
                self._persist(record)
                return self._public(record, execution_status="COMMAND_REJECTED", command_sent=False)
            record["command_result"] = {**result, "status": result.get("code", "EXECUTED"), "at": self._timestamp()}
            record["status"] = "EXECUTED" if result.get("accepted") else "FAILED"
            self._persist(record)
            return self._public(record, execution_status=record["command_result"]["status"], command_sent=bool(result.get("engine_command_sent")), command=command)
        # No executor or an unverified capability is fail-closed, even when a
        # caller asks for a live execution.
        status = "DRY_RUN_VALIDATED" if dry_run else "OPERATION_NOT_VERIFIED"
        record["command_result"] = {"accepted": False, "engine_command_sent": False, "status": status,
                                    "reason": "No enabled verified executor is available; no command was sent to TPF2.", "at": self._timestamp()}
        record["status"] = "VALIDATED"
        self._persist(record)
        return self._public(record, execution_status=status, command_sent=False)

    def verify(self, operation_id: str) -> dict[str, Any]:
        record = self._journal.get(operation_id)
        if record is None: return {"status": "OPERATION_NOT_FOUND", "operation_id": operation_id}
        operation = record["operation"]
        handler = handler_for(operation["operation_type"])
        if handler is not None:
            index = self._snapshot_provider(True)
            result = handler.verify_postcondition(index, operation)
            record["verification"] = {**result, "before_snapshot_sequence": operation["snapshot_sequence"], "after_snapshot_sequence": index.state.get("sequence"), "verified_at": self._timestamp()}
            record["status"] = record["verification"]["status"]
            self._persist(record)
            return self._public(record)
        before = operation["expected_entity_state"]
        index = self._snapshot_provider(True)
        line = self._line(index, operation["target"]["line_id"])
        observed = line.get("name") if line else None
        expected = operation["parameters"]["name"]
        verified = observed == expected
        record["verification"] = {"status": "POSTCONDITION_VERIFIED" if verified else "POSTCONDITION_NOT_MET", "before_snapshot_sequence": operation["snapshot_sequence"], "after_snapshot_sequence": index.state.get("sequence"), "observed_change": {"name": {"before": before.get("name"), "after": observed}}, "verified_at": self._timestamp()}
        record["status"] = record["verification"]["status"]
        self._persist(record)
        return self._public(record)

    def rollback(self, operation_id: str) -> dict[str, Any]:
        record = self._journal.get(operation_id)
        if record is None: return {"status": "OPERATION_NOT_FOUND", "operation_id": operation_id}
        operation = record["operation"]
        if operation["operation_type"] != "RENAME_LINE":
            return {"status": "ROLLBACK_NOT_SUPPORTED", "operation_id": operation_id}
        return self.propose("RENAME_LINE", {"line_id": operation["target"]["line_id"]}, {"name": operation["expected_entity_state"]["name"]})

    def get(self, operation_id: str) -> dict[str, Any]:
        record = self._journal.get(operation_id)
        return self._public(record) if record else {"status": "OPERATION_NOT_FOUND", "operation_id": operation_id}

    def recent(self, limit: int = 20) -> dict[str, Any]:
        return {"operations": [self._public(self._journal[key]) for key in reversed(self._order[-limit:])], "limit": limit}

    @staticmethod
    def _public(record: dict[str, Any], **extra: Any) -> dict[str, Any]:
        value = deepcopy(record)
        value.update(extra)
        return value
