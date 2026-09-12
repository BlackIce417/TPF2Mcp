"""Snapshot-bound network intelligence index and deterministic planning layer."""
from __future__ import annotations

import math
from statistics import median
from typing import Any

from .evidence import evidence, unavailable


class NetworkIntelligenceIndex:
    """Precomputes topology and metric views for exactly one SnapshotIndex sequence."""

    def __init__(self, snapshot: Any):
        self.snapshot = snapshot
        self.snapshot_sequence = snapshot.state.get("sequence")
        self.lines_by_id = snapshot.line_by_id
        self.stations_by_id = snapshot.station_by_id
        self.vehicles_by_id = snapshot.vehicle_by_id
        self.towns_by_id = snapshot.town_by_id
        self.industries_by_id = snapshot.industry_by_id
        self.vehicles_by_line = snapshot.vehicles_by_line
        self.lines_by_station = snapshot.lines_by_station
        self.station_graph = snapshot.graph()
        self.line_metrics = {line_id: self._line_metrics(line_id) for line_id in self.lines_by_id}
        self.station_metrics = {station_id: self._station_metrics(station_id) for station_id in self.stations_by_id}

    def _line_metrics(self, line_id: int) -> dict[str, Any]:
        scorecard = self.snapshot.line_scorecard(line_id)
        line, network = scorecard["line"], scorecard["network"]
        stations = [stop.get("station_id") for stop in line.get("stops", []) if isinstance(stop, dict) and stop.get("station_id") in self.stations_by_id]
        unique_count = len(set(stations))
        stop_count = network["stop_count"]
        fleet_capacity = network["fleet_capacity_total"]
        vehicles = network["vehicle_count"]
        throughput = network["throughput"]
        return {"line": line, "stop_count": stop_count, "unique_station_count": unique_count, "repeated_stop_count": max(0, len(stations) - unique_count), "vehicle_count": vehicles, "fleet_capacity_total": fleet_capacity, "average_vehicle_capacity": network["average_vehicle_capacity"], "frequency_seconds": network["frequency_seconds"], "throughput": throughput, "capacity_per_stop": fleet_capacity / stop_count if fleet_capacity is not None and stop_count else None, "vehicles_per_stop": vehicles / stop_count if stop_count else None, "throughput_per_vehicle": throughput / vehicles if throughput is not None and vehicles else None, "scorecard": scorecard}

    def _station_metrics(self, station_id: int) -> dict[str, Any]:
        connectivity = self.snapshot.station_connectivity(station_id)
        component = next((item for item in self.station_graph.connected_components() if station_id in item), [station_id])
        reachable = max(0, len(component) - 1)
        total_others = max(0, len(self.stations_by_id) - 1)
        return {"station": connectivity["station"], "line_count": connectivity["line_count"], "unique_line_count": connectivity["line_count"], "line_ids": connectivity["line_ids"], "graph_degree": connectivity["graph_degree"], "neighbor_station_count": len(connectivity["connected_station_groups"]), "directly_reachable_station_count": reachable, "transfer_centrality": reachable / total_others if total_others else 0.0}

    def _envelope(self, value: dict[str, Any]) -> dict[str, Any]:
        return {"snapshot_sequence": self.snapshot_sequence, **value}

    def line_profile(self, line_id: int) -> dict[str, Any] | None:
        metrics = self.line_metrics.get(line_id)
        if metrics is None:
            return None
        return self._envelope({"line": {key: metrics["line"].get(key) for key in ("entity_id", "name")}, "topology": {key: metrics[key] for key in ("stop_count", "unique_station_count", "repeated_stop_count")}, "fleet": {key: metrics[key] for key in ("vehicle_count", "fleet_capacity_total", "average_vehicle_capacity")}, "operations": {key: metrics[key] for key in ("frequency_seconds", "throughput")}, "derived": {key: metrics[key] for key in ("capacity_per_stop", "vehicles_per_stop", "throughput_per_vehicle")}, "availability": {"load": "UNAVAILABLE", "waiting": "UNAVAILABLE", "finance": "UNAVAILABLE"}, "source_status": {"topology": "DERIVED", "fleet": "DERIVED", "frequency_seconds": "UI_CROSS_VERIFIED" if metrics["frequency_seconds"] is not None else "UNAVAILABLE", "throughput": "UI_CROSS_VERIFIED" if metrics["throughput"] is not None else "UNAVAILABLE", "ratios": "DERIVED"}, "evidence": [evidence("stop_count", metrics["stop_count"]), evidence("vehicle_count", metrics["vehicle_count"]), evidence("frequency_seconds", metrics["frequency_seconds"]), evidence("throughput", metrics["throughput"])]})

    def classify_lines(self, low_fleet_threshold: int = 1, long_route_stop_threshold: int = 6, high_frequency_seconds: float = 180, high_capacity_threshold: float = 500) -> dict[str, Any]:
        results = []
        for line_id, item in self.line_metrics.items():
            classifications = []
            def add(code: str, rule: dict[str, Any]) -> None:
                classifications.append({"classification": code, "source_status": "HEURISTIC", "rule": rule, "evidence": {key: item.get(key) for key in rule}})
            if item["unique_station_count"] == 2: add("SIMPLE_SHUTTLE", {"unique_station_count": 2})
            if item["repeated_stop_count"] > 0: add("REPEATED_STOP_ROUTE", {"repeated_stop_count": "> 0"})
            if item["vehicle_count"] <= low_fleet_threshold and item["stop_count"] >= long_route_stop_threshold: add("LOW_FLEET_ROUTE", {"vehicle_count": f"<= {low_fleet_threshold}", "stop_count": f">= {long_route_stop_threshold}"})
            if item["frequency_seconds"] is not None and item["frequency_seconds"] <= high_frequency_seconds and item["stop_count"] <= long_route_stop_threshold: add("HIGH_FREQUENCY_SHORT_ROUTE", {"frequency_seconds": f"<= {high_frequency_seconds}", "stop_count": f"<= {long_route_stop_threshold}"})
            if item["frequency_seconds"] is not None and item["frequency_seconds"] > high_frequency_seconds and item["stop_count"] >= long_route_stop_threshold: add("LOW_FREQUENCY_LONG_ROUTE", {"frequency_seconds": f"> {high_frequency_seconds}", "stop_count": f">= {long_route_stop_threshold}"})
            if item["fleet_capacity_total"] is not None and item["fleet_capacity_total"] >= high_capacity_threshold: add("HIGH_CAPACITY_ROUTE", {"fleet_capacity_total": f">= {high_capacity_threshold}"})
            if item["stop_count"] and item["unique_station_count"] / item["stop_count"] < 0.75: add("TRANSFER_HEAVY_ROUTE", {"unique_station_count/stop_count": "< 0.75"})
            if classifications: results.append({"line_id": line_id, "line_name": item["line"].get("name"), "classifications": classifications})
        return self._envelope({"thresholds": {"low_fleet_threshold": low_fleet_threshold, "long_route_stop_threshold": long_route_stop_threshold, "high_frequency_seconds": high_frequency_seconds, "high_capacity_threshold": high_capacity_threshold}, "results": results})

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        if not values: raise ValueError("no values")
        if len(values) == 1: return values[0]
        position = (len(values) - 1) * percentile
        lower, upper = math.floor(position), math.ceil(position)
        return values[lower] + (values[upper] - values[lower]) * (position - lower)

    def line_outliers(self, metric: str, method: str = "iqr", percentile: float = 0.05) -> dict[str, Any]:
        allowed = {"frequency_seconds", "vehicle_count", "fleet_capacity_total", "stop_count", "throughput", "vehicles_per_stop", "capacity_per_stop"}
        if metric not in allowed: raise ValueError("metric must be one of " + ", ".join(sorted(allowed)))
        if method not in {"iqr", "percentile"}: raise ValueError("method must be iqr or percentile")
        rows = [{"line_id": line_id, "line_name": data["line"].get("name"), "value": data[metric]} for line_id, data in self.line_metrics.items() if isinstance(data[metric], (int, float))]
        values = sorted(float(row["value"]) for row in rows)
        if len(values) < 2: return self._envelope({"metric": metric, "method": method, "results": [], "reason": "INSUFFICIENT_VALUES"})
        if method == "iqr":
            q1, q3 = self._percentile(values, .25), self._percentile(values, .75)
            lower, upper = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
        else:
            if not 0 < percentile < .5: raise ValueError("percentile must be between 0 and 0.5")
            lower, upper = self._percentile(values, percentile), self._percentile(values, 1 - percentile)
        results = [{**row, "direction": "LOW" if row["value"] < lower else "HIGH", "source_status": "DERIVED", "evidence": {"metric": metric, "value": row["value"], "lower_bound": lower, "upper_bound": upper}} for row in rows if row["value"] < lower or row["value"] > upper]
        return self._envelope({"metric": metric, "method": method, "bounds": {"lower": lower, "upper": upper}, "results": results, "interpretation": "Statistical outliers, not operating-health conclusions."})

    def similar_lines(self, line_id: int, limit: int = 10) -> dict[str, Any] | None:
        reference = self.line_metrics.get(line_id)
        if reference is None: return None
        candidates = ["stop_count", "vehicle_count", "frequency_seconds", "throughput", "fleet_capacity_total"]
        features = [feature for feature in candidates if all(isinstance(item[feature], (int, float)) for item in self.line_metrics.values())]
        if not features: return self._envelope({"reference_line": line_id, "features": [], "results": [], "reason": "INSUFFICIENT_FEATURE_COVERAGE"})
        means = {feature: sum(item[feature] for item in self.line_metrics.values()) / len(self.line_metrics) for feature in features}
        scales = {feature: math.sqrt(sum((item[feature] - means[feature]) ** 2 for item in self.line_metrics.values()) / len(self.line_metrics)) or 1.0 for feature in features}
        rows = []
        for other_id, item in self.line_metrics.items():
            if other_id == line_id: continue
            distance = math.sqrt(sum(((reference[feature] - item[feature]) / scales[feature]) ** 2 for feature in features))
            rows.append({"line_id": other_id, "name": item["line"].get("name"), "structural_distance": distance, "source_status": "DERIVED", "evidence": {feature: item[feature] for feature in features}})
        rows.sort(key=lambda row: (row["structural_distance"], row["line_id"]))
        return self._envelope({"reference_line": {"line_id": line_id, "name": reference["line"].get("name")}, "features": features, "normalization": "z-score", "distance": "euclidean", "interpretation": "Structural similarity only; it does not imply similar demand or profitability.", "results": rows[:limit]})

    def station_profile(self, station_id: int) -> dict[str, Any] | None:
        value = self.station_metrics.get(station_id)
        if value is None: return None
        return self._envelope({"station": value["station"], "connectivity": {key: value[key] for key in ("line_count", "unique_line_count", "line_ids", "graph_degree", "neighbor_station_count", "directly_reachable_station_count", "transfer_centrality")}, "source_status": "DERIVED", "limitations": ["Topology hub does not imply passenger traffic, waiting volume, or profitability."]})

    def rank_station_hubs(self, metric: str = "line_count", limit: int = 20) -> dict[str, Any]:
        allowed = {"line_count", "graph_degree", "reachable_station_count"}
        if metric not in allowed: raise ValueError("metric must be one of " + ", ".join(sorted(allowed)))
        key = "directly_reachable_station_count" if metric == "reachable_station_count" else metric
        results = [{"station_id": station_id, "name": value["station"].get("name"), metric: value[key], "line_count": value["line_count"], "graph_degree": value["graph_degree"], "source_status": "DERIVED"} for station_id, value in self.station_metrics.items()]
        results.sort(key=lambda row: (-row[metric], row["station_id"]))
        return self._envelope({"ranking_type": "network_topology_hub_not_traffic_ranking", "metric": metric, "results": results[:limit]})

    def reachability(self) -> dict[str, Any]:
        components = self.station_graph.connected_components()
        return self._envelope({"graph_type": "line_station_connectivity_not_physical_path", "station_count": len(self.stations_by_id), "connected_component_count": len(components), "components": [{"component_id": index, "station_count": len(component), "station_ids": component} for index, component in enumerate(components)]})

    def isolated_clusters(self, max_station_count: int = 10) -> dict[str, Any]:
        reachability = self.reachability()
        clusters = [component for component in reachability["components"] if component["station_count"] <= max_station_count]
        return self._envelope({"graph_type": "line_station_connectivity_not_physical_path", "max_station_count": max_station_count, "clusters": clusters, "interpretation": "Clusters have no line/station graph connection to other components."})

    def recommendations(self, limit: int = 20) -> dict[str, Any]:
        recommendations = []
        long_headways = self.line_outliers("frequency_seconds", "percentile", .05)
        for item in long_headways.get("results", []):
            if item["direction"] != "HIGH": continue
            recommendations.append({"type": "CHECK_LONG_HEADWAY_LINE", "severity": "INFO", "line_id": item["line_id"], "reason": item["evidence"], "source_status": "HEURISTIC", "statement": "This line has one of the longest verified headways in the current network.", "limitations": ["vehicle load unavailable", "station waiting unavailable", "profitability unavailable"]})
        for cluster in self.isolated_clusters(3)["clusters"]:
            recommendations.append({"type": "REVIEW_ISOLATED_NETWORK_CLUSTER", "severity": "INFO", "station_ids": cluster["station_ids"], "reason": {"station_count": cluster["station_count"]}, "source_status": "HEURISTIC", "statement": "This station group cluster has no line/station connectivity edge to other network components.", "limitations": ["This is topology only, not physical-map isolation or demand evidence."]})
        recommendations.sort(key=lambda row: (row["type"], row.get("line_id", -1), row.get("station_ids", [])))
        return self._envelope({"recommendations": recommendations[:limit], "rule_based": True, "limitations": ["No vehicle load telemetry", "No station waiting telemetry", "No line finance telemetry"]})

    def analyze(self) -> dict[str, Any]:
        frequency_outliers = self.line_outliers("frequency_seconds", "iqr")
        fleet = self.snapshot.fleet_summary()
        compact_fleet = {key: fleet[key] for key in ("vehicle_count", "assigned_vehicle_count", "unassigned_vehicle_count", "broken_reference_vehicle_count", "capacity_total", "average_capacity", "capacity_distribution", "source_status")}
        return self._envelope({"summary": {"line_count": len(self.lines_by_id), "station_count": len(self.stations_by_id), "vehicle_count": len(self.vehicles_by_id)}, "network_structure": {"reachability": self.reachability()["connected_component_count"], "largest_component_station_count": max((component["station_count"] for component in self.reachability()["components"]), default=0)}, "line_outliers": {"frequency_seconds": frequency_outliers["results"][:10]}, "hub_analysis": self.rank_station_hubs("line_count", 10)["results"], "fleet_analysis": compact_fleet, "isolated_components": self.isolated_clusters(3)["clusters"], "recommendations": self.recommendations(10)["recommendations"], "limitations": {"load": "UNAVAILABLE", "waiting": "UNAVAILABLE", "finance": "UNAVAILABLE", "town_station_relation": "UNAVAILABLE", "industry_semantics": "UNAVAILABLE"}})
