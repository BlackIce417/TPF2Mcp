"""Schema-v2 world-snapshot indexing and read-only network analysis."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from statistics import median
import time
from typing import Any

from .cargo import CargoRegistry
from .graph import TransportGraph

Collection = list[dict[str, Any]]


def _items(state: dict[str, Any], key: str) -> Collection:
    value = state.get(key, [])
    return value if isinstance(value, list) else []


@dataclass
class SnapshotIndex:
    """O(1) entity lookup and relationship indexes for one schema-v2 snapshot."""

    state: dict[str, Any]
    town_by_id: dict[int, dict[str, Any]] = field(init=False)
    industry_by_id: dict[int, dict[str, Any]] = field(init=False)
    station_by_id: dict[int, dict[str, Any]] = field(init=False)
    line_by_id: dict[int, dict[str, Any]] = field(init=False)
    vehicle_by_id: dict[int, dict[str, Any]] = field(init=False)
    cargo_registry: CargoRegistry = field(init=False)
    vehicles_by_line: dict[int, list[dict[str, Any]]] = field(init=False)
    lines_by_station: dict[int, list[dict[str, Any]]] = field(init=False)
    broken_vehicle_references: list[dict[str, Any]] = field(init=False)
    unresolved_stop_references: list[dict[str, Any]] = field(init=False)
    built_at: float = field(default_factory=time.monotonic, init=False)

    def __post_init__(self) -> None:
        self.town_by_id = self._by_id("towns")
        self.industry_by_id = self._by_id("industries")
        self.station_by_id = self._by_id("stations")
        self.line_by_id = self._by_id("lines")
        self.vehicle_by_id = self._by_id("vehicles")
        self.cargo_registry = CargoRegistry.from_snapshot(self.state)
        self.vehicles_by_line = {line_id: [] for line_id in self.line_by_id}
        self.lines_by_station = {station_id: [] for station_id in self.station_by_id}
        self.broken_vehicle_references = []
        self.unresolved_stop_references = []
        for vehicle in self.vehicle_by_id.values():
            line_id = vehicle.get("line_id")
            if line_id is None:
                continue
            if line_id in self.vehicles_by_line:
                self.vehicles_by_line[line_id].append(vehicle)
            else:
                self.broken_vehicle_references.append(vehicle)
        for line in self.line_by_id.values():
            for stop in _items(line, "stops"):
                station_id = stop.get("station_id")
                if station_id in self.lines_by_station:
                    self.lines_by_station[station_id].append(line)
                else:
                    self.unresolved_stop_references.append({"line_id": line.get("entity_id"), "stop": stop})

    def _by_id(self, collection: str) -> dict[int, dict[str, Any]]:
        return {item["entity_id"]: item for item in _items(self.state, collection) if isinstance(item.get("entity_id"), int)}

    def collection(self, name: str) -> Collection:
        return _items(self.state, name)

    def cargo_types(self) -> Collection:
        return self.cargo_registry.list()

    def entity(self, collection: str, entity_id: int) -> dict[str, Any] | None:
        return {"towns": self.town_by_id, "industries": self.industry_by_id, "stations": self.station_by_id,
                "lines": self.line_by_id, "vehicles": self.vehicle_by_id}[collection].get(entity_id)

    @staticmethod
    def mode(entity: dict[str, Any]) -> str:
        # No public field was observed in live LINE/TRANSPORT_VEHICLE components.
        # Keep the absence explicit rather than inferring from a display name.
        return entity.get("transport_mode") if entity.get("transport_mode") in {"ROAD", "TRAM", "BUS", "TRUCK", "RAIL", "WATER", "AIR"} else "UNKNOWN"

    def line_summary(self, line_id: int) -> dict[str, Any] | None:
        line = self.line_by_id.get(line_id)
        if line is None:
            return None
        stations = [self.station_by_id[stop["station_id"]] for stop in _items(line, "stops") if stop.get("station_id") in self.station_by_id]
        vehicles = self.vehicles_by_line.get(line_id, [])
        return {"line": self._line(line), "stations": [self._station(s) for s in stations], "vehicles": [self._vehicle(v) for v in vehicles],
                "summary": {"stop_count": len(_items(line, "stops")), "vehicle_count": len(vehicles), "transport_mode": self.mode(line)}}

    def network_summary(self) -> dict[str, Any]:
        lines = list(self.line_by_id.values())
        vehicles = list(self.vehicle_by_id.values())
        line_modes: dict[str, int] = {}
        vehicle_modes: dict[str, int] = {}
        for line in lines: line_modes[self.mode(line)] = line_modes.get(self.mode(line), 0) + 1
        for vehicle in vehicles: vehicle_modes[self.mode(vehicle)] = vehicle_modes.get(self.mode(vehicle), 0) + 1
        return {"line_count": len(lines), "station_count": len(self.station_by_id), "vehicle_count": len(vehicles),
                "lines_by_mode": line_modes, "vehicles_by_mode": vehicle_modes,
                "unassigned_vehicle_count": len([v for v in vehicles if v.get("line_id") is None]),
                "broken_vehicle_reference_count": len(self.broken_vehicle_references),
                "lines_without_vehicles": [line_id for line_id, items in self.vehicles_by_line.items() if not items],
                "stations_without_lines": [station_id for station_id, items in self.lines_by_station.items() if not items],
                "stop_references": {"total": sum(len(_items(line, "stops")) for line in lines), "resolved": sum(len(_items(line, "stops")) for line in lines) - len(self.unresolved_stop_references), "unresolved": len(self.unresolved_stop_references)}}

    def lines_without_vehicles(self) -> Collection:
        return [self._line(line) for line_id, line in self.line_by_id.items() if not self.vehicles_by_line[line_id]]

    def unassigned_vehicles(self) -> dict[str, Collection]:
        return {"unassigned": [self._vehicle(v) for v in self.vehicle_by_id.values() if v.get("line_id") is None],
                "broken_reference": [self._vehicle(v) for v in self.broken_vehicle_references]}

    def suspicious_lines(self, vehicle_threshold: int = 20) -> Collection:
        result = []
        for line_id, line in self.line_by_id.items():
            stops, vehicles = len(_items(line, "stops")), len(self.vehicles_by_line[line_id])
            reasons = ([] if stops > 1 else ["STOP_COUNT_LE_1"]) + ([] if vehicles else ["NO_VEHICLES"]) + (["VEHICLE_COUNT_ABOVE_THRESHOLD"] if vehicles > vehicle_threshold else [])
            if reasons: result.append({"line": self._line(line), "reasons": reasons, "vehicle_count": vehicles})
        return result

    def world_snapshot(self) -> dict[str, Any]:
        result = deepcopy(self.state)
        result["stations"] = [self._station(item) for item in self.station_by_id.values()]
        result["lines"] = [self._line(item) for item in self.line_by_id.values()]
        result["vehicles"] = [self._vehicle(item) for item in self.vehicle_by_id.values()]
        return result

    def overview(self) -> dict[str, Any]:
        timestamp = self.state.get("timestamp")
        source_age = round(max(0.0, time.time() - timestamp) * 1000) if isinstance(timestamp, (int, float)) and timestamp > 0 else None
        return {"schema_version": self.state.get("schema_version"), "snapshot_sequence": self.state.get("sequence"), "index_age_ms": round((time.monotonic() - self.built_at) * 1000), "source_snapshot_age_ms": source_age, "source_timestamp_precision": "seconds" if source_age is not None else "unavailable", "game": self.state.get("game", {}), "company": self.state.get("company", {}), "metadata": self.state.get("metadata", {}),
                "counts": {key: len(_items(self.state, key)) for key in ("towns", "industries", "stations", "lines", "vehicles", "cargo_types")}}

    def capabilities(self) -> dict[str, dict[str, str]]:
        return {"vehicle_capacity": {"status": "UI_CROSS_VERIFIED", "source": "TRANSPORT_VEHICLE.config.capacities"}, "vehicle_load": {"status": "UNAVAILABLE", "reason": "No verified runtime current-load field in the normalized world snapshot."}, "vehicle_occupancy": {"status": "UNAVAILABLE", "reason": "Requires verified per-vehicle current load."}, "station_waiting": {"status": "UNAVAILABLE", "reason": "No verified station-wide waiting source in the normalized world snapshot."}, "line_assigned_demand": {"status": "ENGINE_COMPONENT_CLASSIFIED", "source": "get_line_demand Bridge probe over SIM_PERSON/SIM_CARGO and SIM_*_AT_TERMINAL", "reason": "Live bounded per-line onboard/waiting totals; cargo type is reported when the component exposes it."}, "line_frequency": {"status": "UI_CROSS_VERIFIED", "source": "game.interface.getEntity(line_id).frequency (1 / raw value)"}, "line_throughput": {"status": "UI_CROSS_VERIFIED", "source": "game.interface.getEntity(line_id).rate"}, "line_finance": {"status": "UNAVAILABLE", "reason": "No verified line finance source."}, "company_balance": {"status": "ENGINE_AVAILABLE", "source": "ACCOUNT.balance", "reason": "Raw engine field only; it did not match infinite-money UI bank balance."}, "company_cash_semantic": {"status": "UNRESOLVED", "reason": "Three paused UI samples showed $∞ while ACCOUNT.balance was 0."}, "network_intelligence": {"status": "DERIVED", "reason": "Deterministic analysis over one normalized snapshot."}, "line_similarity": {"status": "DERIVED", "reason": "Z-score normalized structural-feature distance."}}

    @staticmethod
    def _number(value: Any, minimum: float = 0) -> float | int | None:
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= minimum else None

    def line_scorecard(self, line_id: int) -> dict[str, Any] | None:
        summary = self.line_summary(line_id)
        if summary is None:
            return None
        vehicles = self.vehicles_by_line.get(line_id, [])
        capacities = [self._number(vehicle.get("capacity_total")) for vehicle in vehicles]
        known_capacities = [capacity for capacity in capacities if capacity is not None]
        frequency = self._number(summary["line"].get("frequency_seconds"), 0.000001)
        throughput = self._number(summary["line"].get("throughput"))
        capacity_complete = len(known_capacities) == len(vehicles)
        fleet_capacity = sum(known_capacities) if capacity_complete else None
        average_capacity = (fleet_capacity / len(vehicles)) if fleet_capacity is not None and vehicles else None
        departures = 3600 / frequency if frequency is not None else None
        return {"line": summary["line"], "network": {"stop_count": summary["summary"]["stop_count"], "vehicle_count": len(vehicles), "frequency_seconds": frequency, "throughput": throughput, "fleet_capacity_total": fleet_capacity, "average_vehicle_capacity": average_capacity, "capacity_coverage": {"vehicles_with_capacity": len(known_capacities), "vehicle_count": len(vehicles)}}, "derived": {"departures_per_hour": departures, "formulas": {"departures_per_hour": "3600 / frequency_seconds", "fleet_capacity_total": "sum(assigned vehicle.capacity_total)", "average_vehicle_capacity": "fleet_capacity_total / vehicle_count"}}, "availability": {"frequency": frequency is not None, "throughput": throughput is not None, "fleet_capacity_total": fleet_capacity is not None, "average_vehicle_capacity": average_capacity is not None, "departures_per_hour": departures is not None}, "source_status": {"frequency": "UI_CROSS_VERIFIED" if frequency is not None else "UNAVAILABLE", "throughput": "UI_CROSS_VERIFIED" if throughput is not None else "UNAVAILABLE", "fleet_capacity_total": "DERIVED" if fleet_capacity is not None else "UNAVAILABLE", "average_vehicle_capacity": "DERIVED" if average_capacity is not None else "UNAVAILABLE", "departures_per_hour": "DERIVED" if departures is not None else "UNAVAILABLE"}}

    @staticmethod
    def _diagnostic(code: str, severity: str, line: dict[str, Any], evidence: dict[str, Any], interpretation: str) -> dict[str, Any]:
        return {"code": code, "severity": severity, "entity_type": "line", "entity_id": line["entity_id"], "evidence": evidence, "interpretation": interpretation}

    def diagnose_line_structure(self, line_id: int, long_headway_seconds: float = 600, short_headway_seconds: float = 120, high_vehicle_count: int = 10) -> dict[str, Any] | None:
        scorecard = self.line_scorecard(line_id)
        if scorecard is None:
            return None
        line, network, diagnostics = scorecard["line"], scorecard["network"], []
        if network["stop_count"] == 0: diagnostics.append(self._diagnostic("NO_STOPS", "warning", line, {"stop_count": 0}, "The line has no resolved station-group stops."))
        elif network["stop_count"] == 1: diagnostics.append(self._diagnostic("SINGLE_STOP", "warning", line, {"stop_count": 1}, "The line has one resolved station-group stop."))
        if network["vehicle_count"] == 0: diagnostics.append(self._diagnostic("NO_VEHICLES", "warning", line, {"vehicle_count": 0}, "The line has no assigned vehicles."))
        frequency = network["frequency_seconds"]
        if frequency is not None and frequency > long_headway_seconds: diagnostics.append(self._diagnostic("LONG_HEADWAY", "warning", line, {"frequency_seconds": frequency, "threshold_seconds": long_headway_seconds}, "The line has a long verified service interval."))
        if frequency is not None and frequency < short_headway_seconds: diagnostics.append(self._diagnostic("SHORT_HEADWAY", "info", line, {"frequency_seconds": frequency, "threshold_seconds": short_headway_seconds}, "The line has a short verified service interval."))
        if network["vehicle_count"] > high_vehicle_count: diagnostics.append(self._diagnostic("HIGH_VEHICLE_COUNT", "info", line, {"vehicle_count": network["vehicle_count"], "threshold": high_vehicle_count}, "The line has a high assigned-vehicle count."))
        return {"scorecard": scorecard, "thresholds": {"long_headway_seconds": long_headway_seconds, "short_headway_seconds": short_headway_seconds, "high_vehicle_count": high_vehicle_count}, "diagnostics": diagnostics}

    def diagnose_transport_network(self, long_headway_seconds: float = 600, short_headway_seconds: float = 120, high_vehicle_count: int = 10) -> dict[str, Any]:
        by_code: dict[str, list[dict[str, Any]]] = {code: [] for code in ("NO_STOPS", "SINGLE_STOP", "NO_VEHICLES", "LONG_HEADWAY", "SHORT_HEADWAY", "HIGH_VEHICLE_COUNT")}
        for line_id in self.line_by_id:
            result = self.diagnose_line_structure(line_id, long_headway_seconds, short_headway_seconds, high_vehicle_count)
            for diagnostic in result["diagnostics"] if result else []:
                by_code[diagnostic["code"]].append(diagnostic)
        return {"thresholds": {"long_headway_seconds": long_headway_seconds, "short_headway_seconds": short_headway_seconds, "high_vehicle_count": high_vehicle_count}, "stations_without_lines": [{"entity_type": "station_group", "entity_id": station["entity_id"], "code": "STATION_WITHOUT_LINES", "severity": "warning", "evidence": {"line_count": 0}, "interpretation": "The station group has no resolved line stops."} for station in self.stations_without_lines()], "lines_without_vehicles": by_code["NO_VEHICLES"], "unassigned_vehicles": [{"entity_type": "vehicle", "entity_id": vehicle["entity_id"], "code": "UNASSIGNED_VEHICLE", "severity": "info", "evidence": {"line_id": None}, "interpretation": "The vehicle has no assigned line."} for vehicle in self.unassigned_vehicles()["unassigned"]], "broken_references": [{"entity_type": "vehicle", "entity_id": vehicle["entity_id"], "code": "BROKEN_LINE_REFERENCE", "severity": "warning", "evidence": {"line_id": vehicle.get("line_id")}, "interpretation": "The vehicle references a line absent from this snapshot."} for vehicle in self.unassigned_vehicles()["broken_reference"]], "single_stop_lines": by_code["SINGLE_STOP"], "no_stop_lines": by_code["NO_STOPS"], "long_headway_lines": by_code["LONG_HEADWAY"], "short_headway_lines": by_code["SHORT_HEADWAY"], "high_vehicle_count_lines": by_code["HIGH_VEHICLE_COUNT"]}

    def compare_lines(self, line_ids: list[int]) -> dict[str, Any]:
        results, missing = [], []
        for line_id in line_ids:
            scorecard = self.line_scorecard(line_id)
            if scorecard is None:
                missing.append(line_id)
            else:
                network = scorecard["network"]
                results.append({"line_id": line_id, "name": scorecard["line"].get("name"), **{key: network[key] for key in ("stop_count", "vehicle_count", "frequency_seconds", "throughput", "fleet_capacity_total", "average_vehicle_capacity")}})
        return {"columns": ["line_id", "name", "stop_count", "vehicle_count", "frequency_seconds", "throughput", "fleet_capacity_total", "average_vehicle_capacity"], "lines": results, "missing_line_ids": missing}

    def rank_lines(self, metric: str, order: str = "desc", limit: int = 20) -> dict[str, Any]:
        allowed = {"frequency_seconds", "throughput", "vehicle_count", "fleet_capacity_total"}
        if metric not in allowed:
            raise ValueError("metric must be one of " + ", ".join(sorted(allowed)))
        rows = []
        for line_id in self.line_by_id:
            scorecard = self.line_scorecard(line_id)
            value = scorecard["network"].get(metric) if scorecard else None
            if value is not None:
                rows.append({"line_id": line_id, "name": scorecard["line"].get("name"), metric: value})
        rows.sort(key=lambda row: row[metric], reverse=order == "desc")
        return {"metric": metric, "order": order, "limit": limit, "source_status": "DERIVED" if metric == "fleet_capacity_total" else "UI_CROSS_VERIFIED" if metric in {"frequency_seconds", "throughput"} else "DERIVED", "results": rows[:limit]}

    def graph(self) -> TransportGraph:
        return TransportGraph(self.station_by_id, list(self.line_by_id.values()))

    def station_connectivity(self, station_id: int) -> dict[str, Any] | None:
        station = self.station_by_id.get(station_id)
        if station is None:
            return None
        lines = self.lines_by_station.get(station_id, [])
        connected = set()
        for line in lines:
            connected.update(stop.get("station_id") for stop in _items(line, "stops") if stop.get("station_id") in self.station_by_id and stop.get("station_id") != station_id)
        return {"station": self._station(station), "line_count": len(lines), "line_ids": [line["entity_id"] for line in lines], "connected_station_groups": [self._station(self.station_by_id[item]) for item in sorted(connected)], "graph_degree": self.graph().degree(station_id), "source_status": "DERIVED"}

    def rank_transfer_stations(self, limit: int = 20) -> dict[str, Any]:
        rows = [{"station_id": station_id, "name": station.get("name"), "line_count": len(self.lines_by_station[station_id]), "line_ids": [line["entity_id"] for line in self.lines_by_station[station_id]], "graph_degree": self.graph().degree(station_id)} for station_id, station in self.station_by_id.items()]
        rows.sort(key=lambda row: (-row["line_count"], -row["graph_degree"], row["station_id"]))
        return {"ranking_type": "connectivity_ranking_not_traffic_ranking", "metric": "line_count", "results": rows[:limit]}

    def find_station_route(self, source_station_id: int, target_station_id: int) -> dict[str, Any] | None:
        route = self.graph().route(source_station_id, target_station_id)
        if route is None:
            return None
        route["station_names"] = [self.station_by_id[station_id].get("name") for station_id in route["station_ids"]]
        return route

    def fleet_summary(self) -> dict[str, Any]:
        vehicles = list(self.vehicle_by_id.values())
        capacities = [self._number(vehicle.get("capacity_total")) for vehicle in vehicles]
        known = [value for value in capacities if value is not None]
        by_line = {line_id: [vehicle["entity_id"] for vehicle in items] for line_id, items in self.vehicles_by_line.items()}
        return {"vehicle_count": len(vehicles), "assigned_vehicle_count": len(vehicles) - len(self.unassigned_vehicles()["unassigned"]) - len(self.broken_vehicle_references), "unassigned_vehicle_count": len(self.unassigned_vehicles()["unassigned"]), "broken_reference_vehicle_count": len(self.broken_vehicle_references), "capacity_total": sum(known) if len(known) == len(vehicles) else None, "average_capacity": (sum(known) / len(known)) if known else None, "capacity_distribution": {"count": len(known), "min": min(known) if known else None, "max": max(known) if known else None, "mean": sum(known) / len(known) if known else None, "median": median(known) if known else None}, "vehicles_by_line": by_line, "source_status": {"capacity": "UI_CROSS_VERIFIED" if len(known) == len(vehicles) else "UNAVAILABLE", "distribution": "DERIVED" if known else "UNAVAILABLE"}}

    def fleet_profile(self) -> dict[str, Any]:
        vehicles = list(self.vehicle_by_id.values())
        by_depot: dict[str, int] = {}
        by_state: dict[str, int] = {}
        for vehicle in vehicles:
            depot, state = vehicle.get("raw_depot"), vehicle.get("raw_state")
            by_depot[str(depot)] = by_depot.get(str(depot), 0) + 1
            by_state[str(state)] = by_state.get(str(state), 0) + 1
        return {"snapshot_sequence": self.state.get("sequence"), "total_vehicles": len(vehicles), "vehicles_by_line": {str(key): len(value) for key, value in self.vehicles_by_line.items()}, "unassigned_vehicle_ids": [item["entity_id"] for item in vehicles if item.get("line_id") is None], "vehicles_by_raw_depot": by_depot, "vehicles_by_raw_state": by_state, "capacity": self.fleet_summary()["capacity_distribution"], "source_status": {"line_assignment": "ENGINE_VERIFIED", "depot": "ENGINE_AVAILABLE_RAW", "state": "ENGINE_AVAILABLE_RAW", "capacity": "UI_CROSS_VERIFIED"}}

    def line_fleet_profile(self, line_id: int) -> dict[str, Any] | None:
        line = self.line_by_id.get(line_id)
        if line is None: return None
        vehicles = self.vehicles_by_line.get(line_id, [])
        capacities = [item.get("capacity_total") for item in vehicles if isinstance(item.get("capacity_total"), (int, float))]
        return {"line_id": line_id, "line_name": line.get("name"), "vehicle_ids": [item["entity_id"] for item in vehicles], "vehicle_count": len(vehicles), "capacity_total": sum(capacities) if len(capacities) == len(vehicles) else None, "frequency_seconds": line.get("frequency_seconds"), "throughput": line.get("throughput"), "source_status": {"vehicle_ids": "ENGINE_VERIFIED", "capacity_total": "DERIVED" if len(capacities) == len(vehicles) else "UNAVAILABLE", "frequency_seconds": "UI_CROSS_VERIFIED" if line.get("frequency_seconds") is not None else "UNAVAILABLE"}}

    def rank_vehicles_by_capacity(self, order: str = "desc", limit: int = 20) -> dict[str, Any]:
        rows = [{"vehicle_id": vehicle["entity_id"], "name": vehicle.get("name"), "line_id": vehicle.get("line_id"), "capacity_total": capacity} for vehicle in self.vehicle_by_id.values() if (capacity := self._number(vehicle.get("capacity_total"))) is not None]
        rows.sort(key=lambda row: row["capacity_total"], reverse=order == "desc")
        return {"metric": "capacity_total", "order": order, "limit": limit, "source_status": "UI_CROSS_VERIFIED", "results": rows[:limit]}

    def vehicle_operating_state(self, vehicle_id: int) -> dict[str, Any] | None:
        vehicle = self.vehicle_by_id.get(vehicle_id)
        if vehicle is None: return None
        capacity = vehicle.get("capacity_total")
        capacity_ok = isinstance(capacity, (int, float)) and not isinstance(capacity, bool) and capacity >= 0
        return {"vehicle": self._vehicle(vehicle), "operations": {"capacity": capacity if capacity_ok else None, "load": None, "load_total": None, "occupancy_ratio": None, "cargo": [], "raw_state": vehicle.get("raw_state")},
                "availability": {"capacity": capacity_ok, "load": False, "cargo": False, "occupancy_ratio": False, "raw_state": "raw_state" in vehicle},
                "source_status": {"capacity": "UI_CROSS_VERIFIED" if capacity_ok else "UNAVAILABLE", "load": "UNAVAILABLE", "cargo": "UNAVAILABLE", "occupancy_ratio": "UNAVAILABLE"},
                "unavailable_reasons": {"load": "No verified current-load field; getInfo cargoInfos contains configuration capacity/offset only.", "cargo": "No verified current-load field; per-cargo contents are unavailable.", "occupancy_ratio": "Requires verified load_total and capacity_total."}}

    def station_operating_state(self, station_id: int) -> dict[str, Any] | None:
        station = self.station_by_id.get(station_id)
        if station is None: return None
        return {"station": self._station(station), "operations": {"waiting_total": None, "waiting": []}, "availability": {"waiting": False}, "source_status": {"waiting": "UNAVAILABLE"}, "unavailable_reasons": {"waiting": "Station transport samples are a quality ratio input, not a verified waiting metric."}}

    def line_operating_summary(self, line_id: int) -> dict[str, Any] | None:
        summary = self.line_summary(line_id)
        if summary is None: return None
        frequency = summary["line"].get("frequency_seconds")
        throughput = summary["line"].get("throughput")
        frequency_ok = isinstance(frequency, (int, float)) and not isinstance(frequency, bool) and frequency > 0
        throughput_ok = isinstance(throughput, (int, float)) and not isinstance(throughput, bool) and throughput >= 0
        summary["operations"] = {"vehicle_count": summary["summary"]["vehicle_count"], "capacity": None, "load": None, "occupancy_ratio": None, "frequency_seconds": frequency if frequency_ok else None, "throughput": throughput if throughput_ok else None}
        summary["finance"] = {"revenue": None, "cost": None, "profit": None}
        summary["availability"] = {"capacity": False, "load": False, "occupancy_ratio": False, "frequency": frequency_ok, "throughput": throughput_ok, "revenue": False, "cost": False, "profit": False}
        summary["source_status"] = {"capacity": "UNAVAILABLE", "load": "UNAVAILABLE", "occupancy_ratio": "UNAVAILABLE", "frequency": "UI_CROSS_VERIFIED" if frequency_ok else "UNAVAILABLE", "throughput": "UI_CROSS_VERIFIED" if throughput_ok else "UNAVAILABLE", "revenue": "UNAVAILABLE", "cost": "UNAVAILABLE", "profit": "UNAVAILABLE"}
        summary["unavailable_reasons"] = {"capacity": "Line capacity requires verified vehicle current-load data.", "load": "No verified vehicle current-load source.", "occupancy_ratio": "Requires verified load and capacity.", "revenue": "No verified line-finance source.", "cost": "No verified line-finance source.", "profit": "No verified line-finance source."}
        return summary

    def low_load_vehicles(self, threshold: float) -> dict[str, Any]:
        return {"availability": {"capacity": False, "load": False, "occupancy_ratio": False}, "threshold": threshold, "results": []}

    def high_waiting_stations(self, threshold: int) -> dict[str, Any]:
        return {"availability": {"waiting": False}, "threshold": threshold, "results": []}

    def stations_without_lines(self) -> Collection:
        return [self._station(station) for station_id, station in self.station_by_id.items() if not self.lines_by_station[station_id]]

    def _line(self, line: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(line); vehicles = self.vehicles_by_line.get(line["entity_id"], [])
        result["transport_mode"] = self.mode(line); result["vehicle_ids"] = [v["entity_id"] for v in vehicles]; result["vehicle_count"] = len(vehicles)
        return result

    def _station(self, station: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(station); lines = self.lines_by_station.get(station["entity_id"], [])
        result["line_ids"] = [line["entity_id"] for line in lines]; result["line_count"] = len(lines)
        return result

    def _vehicle(self, vehicle: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(vehicle); result["transport_mode"] = self.mode(vehicle); return result
