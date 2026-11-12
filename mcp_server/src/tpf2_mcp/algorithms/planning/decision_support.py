"""Deterministic topology what-if planning. Never writes to the game bridge."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class TopologyEdge:
    edge_id: str
    source: int
    target: int
    line_id: int | None
    virtual: bool = False


class DecisionSupport:
    def __init__(self, intelligence: Any):
        self.intelligence = intelligence
        self.snapshot_sequence = intelligence.snapshot_sequence
        self.stations = intelligence.stations_by_id
        self.line_metrics = intelligence.line_metrics
        self.edges = self._baseline_edges()
        self._scenario_cache: dict[str, dict[str, Any]] = {}

    def _baseline_edges(self) -> list[TopologyEdge]:
        result, seen = [], set()
        for line_id, line in self.intelligence.lines_by_id.items():
            stops = [stop.get("station_id") for stop in line.get("stops", []) if isinstance(stop, dict) and stop.get("station_id") in self.stations]
            for index, (source, target) in enumerate(zip(stops, stops[1:])):
                if source == target: continue
                key = (line_id, min(source, target), max(source, target), index)
                if key not in seen:
                    seen.add(key); result.append(TopologyEdge(f"line:{line_id}:{index}", source, target, line_id))
        return result

    @staticmethod
    def _adjacency(stations: set[int], edges: list[TopologyEdge]) -> dict[int, list[TopologyEdge]]:
        adjacency = {station: [] for station in stations}
        for edge in edges:
            if edge.source in adjacency and edge.target in adjacency:
                adjacency[edge.source].append(edge); adjacency[edge.target].append(edge)
        return adjacency

    @staticmethod
    def _other(edge: TopologyEdge, station: int) -> int:
        return edge.target if edge.source == station else edge.source

    def _components(self, stations: set[int], edges: list[TopologyEdge]) -> list[list[int]]:
        adjacency, unseen, components = self._adjacency(stations, edges), set(stations), []
        while unseen:
            root = min(unseen); unseen.remove(root); queue, component = deque([root]), []
            while queue:
                current = queue.popleft(); component.append(current)
                for edge in adjacency[current]:
                    neighbor = self._other(edge, current)
                    if neighbor in unseen: unseen.remove(neighbor); queue.append(neighbor)
            components.append(sorted(component))
        return sorted(components, key=lambda item: (-len(item), item))

    def _topology_summary(self, stations: set[int], edges: list[TopologyEdge]) -> dict[str, Any]:
        components = self._components(stations, edges)
        return {"connected_component_count": len(components), "station_count": len(stations), "edge_count": len(edges), "isolated_station_count": sum(1 for component in components if len(component) == 1), "largest_component_station_count": len(components[0]) if components else 0, "components": [{"component_id": index, "station_count": len(component), "station_ids": component} for index, component in enumerate(components)]}

    def detect_problems(self) -> dict[str, Any]:
        problems = []
        for recommendation in self.intelligence.recommendations(100)["recommendations"]:
            if recommendation["type"] == "CHECK_LONG_HEADWAY_LINE":
                line_id = recommendation["line_id"]
                problems.append({"problem_id": f"line:{line_id}:long_headway", "type": "LONG_HEADWAY_OUTLIER", "target": {"entity_type": "LINE", "entity_id": line_id}, "severity": "INFO", "confidence": "HIGH", "source_status": "HEURISTIC", "evidence": recommendation["reason"], "limitations": recommendation["limitations"]})
            elif recommendation["type"] == "REVIEW_ISOLATED_NETWORK_CLUSTER":
                stations = recommendation["station_ids"]
                problems.append({"problem_id": "component:" + "-".join(map(str, stations)) + ":isolated", "type": "ISOLATED_COMPONENT", "target": {"entity_type": "STATION_GROUP_CLUSTER", "entity_ids": stations}, "severity": "INFO", "confidence": "HIGH", "source_status": "HEURISTIC", "evidence": recommendation["reason"], "limitations": recommendation["limitations"]})
        return {"snapshot_sequence": self.snapshot_sequence, "problems": problems}

    def _component_for(self, station_id: int, edges: list[TopologyEdge] | None = None) -> int | None:
        summary = self._topology_summary(set(self.stations), edges or self.edges)
        return next((item["component_id"] for item in summary["components"] if station_id in item["station_ids"]), None)

    def problem_impact(self, problem_id: str) -> dict[str, Any] | None:
        if not problem_id.startswith("line:"): return None
        parts = problem_id.split(":")
        try: line_id = int(parts[1])
        except (IndexError, ValueError): return None
        metric = self.line_metrics.get(line_id)
        if metric is None: return None
        stations = [stop.get("station_id") for stop in metric["line"].get("stops", []) if stop.get("station_id") in self.stations]
        unique_stations = sorted(set(stations))
        transfer_lines = sorted({line["entity_id"] for station_id in unique_stations for line in self.intelligence.lines_by_station[station_id] if line["entity_id"] != line_id})
        vehicles = [vehicle["entity_id"] for vehicle in self.intelligence.vehicles_by_line.get(line_id, [])]
        component = self._component_for(unique_stations[0]) if unique_stations else None
        return {"snapshot_sequence": self.snapshot_sequence, "problem_id": problem_id, "line_id": line_id, "affected_stations": unique_stations, "fleet": vehicles, "transfer_lines": transfer_lines, "connected_component_id": component, "relationship_meaning": "graph/topology dependency only; not passenger, cargo, or financial impact.", "unavailable": {"town_relation": "UNAVAILABLE", "industry_relation": "UNAVAILABLE", "demand_impact": "UNAVAILABLE", "financial_impact": "UNAVAILABLE"}}

    def route(self, source: int, target: int, edges: list[TopologyEdge] | None = None, max_routes: int = 1) -> dict[str, Any] | None:
        if source not in self.stations or target not in self.stations: return None
        active = edges or self.edges; adjacency = self._adjacency(set(self.stations), active)
        distance, parents = {source: 0}, {source: []}
        queue = deque([source])
        while queue:
            current = queue.popleft()
            for edge in adjacency[current]:
                neighbor = self._other(edge, current); next_distance = distance[current] + 1
                if neighbor not in distance:
                    distance[neighbor] = next_distance; parents[neighbor] = [(current, edge)]; queue.append(neighbor)
                elif distance[neighbor] == next_distance: parents[neighbor].append((current, edge))
        if target not in distance: return {"snapshot_sequence": self.snapshot_sequence, "route_type": "line_station_connectivity_not_physical_path", "routes": [], "reason": "STATIONS_NOT_CONNECTED"}
        routes = []
        def build(node: int, hops: list[tuple[int, TopologyEdge]]) -> None:
            if len(routes) >= max_routes: return
            if node == source:
                ordered = list(reversed(hops)); stations = [source] + [self._other(edge, prior) for prior, edge in ordered]
                lines = [edge.line_id for _, edge in ordered]
                routes.append({"station_path": stations, "line_path": lines, "hop_count": len(ordered), "transfer_count": max(0, len([line for index, line in enumerate(lines) if index == 0 or line != lines[index - 1]]) - 1)})
                return
            for prior, edge in sorted(parents[node], key=lambda item: (item[0], item[1].edge_id)):
                build(prior, hops + [(prior, edge)])
        build(target, [])
        return {"snapshot_sequence": self.snapshot_sequence, "route_type": "line_station_connectivity_not_physical_path", "interpretation": "Minimum-hop topology routes, not fastest, cheapest, or physical paths.", "routes": routes}

    def resilience(self, stations: set[int] | None = None, edges: list[TopologyEdge] | None = None) -> dict[str, Any]:
        active_stations, active_edges = stations or set(self.stations), edges or self.edges
        adjacency = self._adjacency(active_stations, active_edges)
        discovery, low, articulation, bridges, clock = {}, {}, set(), [], 0
        def visit(node: int, parent_edge: str | None = None) -> None:
            nonlocal clock
            clock += 1; discovery[node] = low[node] = clock; children = 0
            for edge in adjacency[node]:
                neighbor = self._other(edge, node)
                if edge.edge_id == parent_edge: continue
                if neighbor not in discovery:
                    children += 1; visit(neighbor, edge.edge_id); low[node] = min(low[node], low[neighbor])
                    if parent_edge is not None and low[neighbor] >= discovery[node]: articulation.add(node)
                    if low[neighbor] > discovery[node]: bridges.append(edge)
                else: low[node] = min(low[node], discovery[neighbor])
            if parent_edge is None and children > 1: articulation.add(node)
        for station in sorted(active_stations):
            if station not in discovery: visit(station)
        topology = self._topology_summary(active_stations, active_edges)
        return {"snapshot_sequence": self.snapshot_sequence, "source_status": "DERIVED", "articulation_stations": [{"station_id": station, "name": self.stations[station].get("name"), "meaning": "Removing this station from the topology graph increases graph disconnection."} for station in sorted(articulation)], "bridge_connections": [{"edge_id": edge.edge_id, "station_a": edge.source, "station_b": edge.target, "line_id": edge.line_id, "virtual": edge.virtual, "meaning": "Removing this topology edge increases graph disconnection."} for edge in sorted(bridges, key=lambda item: item.edge_id)], "articulation_station_count": len(articulation), "bridge_connection_count": len(bridges), "largest_component_ratio": topology["largest_component_station_count"] / topology["station_count"] if topology["station_count"] else 0, "limitations": ["Topology resilience only; not congestion, demand, travel time, or financial resilience."]}

    def _apply_mutations(self, mutations: list[dict[str, Any]]) -> tuple[set[int], list[TopologyEdge], dict[int, dict[str, Any]], list[dict[str, Any]]]:
        stations, edges, metrics, normalized = set(self.stations), list(self.edges), deepcopy(self.line_metrics), []
        for index, mutation in enumerate(mutations):
            if not isinstance(mutation, dict): raise ValueError("each mutation must be an object")
            kind = mutation.get("type")
            if kind == "CHANGE_VIRTUAL_VEHICLE_COUNT":
                line_id, delta = mutation.get("line_id"), mutation.get("delta")
                if line_id not in metrics or not isinstance(delta, int): raise ValueError("CHANGE_VIRTUAL_VEHICLE_COUNT requires known line_id and integer delta")
                next_count = metrics[line_id]["vehicle_count"] + delta
                if next_count < 0: raise ValueError("virtual vehicle_count cannot be negative")
                metrics[line_id]["vehicle_count"] = next_count
                normalized.append({"type": kind, "line_id": line_id, "delta": delta})
            elif kind == "CHANGE_VIRTUAL_FREQUENCY":
                line_id, value = mutation.get("line_id"), mutation.get("frequency_seconds")
                if line_id not in metrics or not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0: raise ValueError("CHANGE_VIRTUAL_FREQUENCY requires known line_id and positive frequency_seconds")
                metrics[line_id]["frequency_seconds"] = value; normalized.append({"type": kind, "line_id": line_id, "frequency_seconds": value})
            elif kind == "CONNECT_EXISTING_STATIONS":
                source, target = mutation.get("station_a"), mutation.get("station_b")
                if source not in stations or target not in stations or source == target: raise ValueError("CONNECT_EXISTING_STATIONS requires two distinct known station IDs")
                edge = TopologyEdge(f"virtual:{min(source,target)}:{max(source,target)}", source, target, None, True)
                if edge not in edges: edges.append(edge)
                normalized.append({"type": kind, "station_a": source, "station_b": target})
            elif kind == "DISCONNECT_LINE":
                line_id = mutation.get("line_id")
                if line_id not in metrics: raise ValueError("DISCONNECT_LINE requires known line_id")
                edges = [edge for edge in edges if edge.line_id != line_id]; normalized.append({"type": kind, "line_id": line_id})
            else: raise ValueError("unsupported virtual mutation: " + str(kind))
        return stations, edges, metrics, normalized

    def simulate(self, mutations: list[dict[str, Any]]) -> dict[str, Any]:
        stations, edges, metrics, normalized = self._apply_mutations(mutations)
        cache_key = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if cache_key in self._scenario_cache:
            return deepcopy(self._scenario_cache[cache_key])
        baseline, scenario = self._topology_summary(set(self.stations), self.edges), self._topology_summary(stations, edges)
        baseline_vehicles, scenario_vehicles = sum(item["vehicle_count"] for item in self.line_metrics.values()), sum(item["vehicle_count"] for item in metrics.values())
        result = {"snapshot_sequence": self.snapshot_sequence, "source_status": "HYPOTHETICAL", "mutations": normalized, "baseline": {"topology": baseline, "vehicle_count": baseline_vehicles}, "scenario": {"topology": scenario, "vehicle_count": scenario_vehicles}, "delta": {"connected_component_count": scenario["connected_component_count"] - baseline["connected_component_count"], "isolated_station_count": scenario["isolated_station_count"] - baseline["isolated_station_count"], "vehicle_count": scenario_vehicles - baseline_vehicles, "frequency_seconds": {"status": "UNAVAILABLE", "reason": "Vehicle-count mutations cannot deterministically derive timetable frequency."}}, "limitations": ["Scenario exists only in MCP memory and does not modify the game.", "Cost, demand, load, waiting, revenue, and profit are unavailable."]}
        self._scenario_cache[cache_key] = deepcopy(result)
        return result

    def simulate_connection(self, station_a: int, station_b: int) -> dict[str, Any]:
        return self.simulate([{"type": "CONNECT_EXISTING_STATIONS", "station_a": station_a, "station_b": station_b}])

    def simulate_line_failure(self, line_id: int) -> dict[str, Any]:
        return self.simulate([{"type": "DISCONNECT_LINE", "line_id": line_id}])

    def simulate_station_failure(self, station_id: int) -> dict[str, Any] | None:
        if station_id not in self.stations: return None
        stations = set(self.stations); stations.remove(station_id)
        edges = [edge for edge in self.edges if edge.source != station_id and edge.target != station_id]
        baseline, scenario = self._topology_summary(set(self.stations), self.edges), self._topology_summary(stations, edges)
        return {"snapshot_sequence": self.snapshot_sequence, "source_status": "HYPOTHETICAL", "mutation": {"type": "REMOVE_VIRTUAL_STATION", "station_id": station_id}, "baseline": {"topology": baseline}, "scenario": {"topology": scenario}, "delta": {"connected_component_count": scenario["connected_component_count"] - baseline["connected_component_count"], "isolated_station_count": scenario["isolated_station_count"] - baseline["isolated_station_count"], "station_count": -1}, "limitations": ["Virtual topology failure only; it does not modify the game or establish real-world failure consequences."]}

    def planning_options(self, limit: int = 20) -> dict[str, Any]:
        options = []
        for problem in self.detect_problems()["problems"]:
            if problem["type"] == "LONG_HEADWAY_OUTLIER":
                line_id = problem["target"]["entity_id"]
                options.extend([{"problem_id": problem["problem_id"], "type": "INSPECT_LINE", "line_id": line_id, "source_status": "HEURISTIC", "statement": "Inspect the verified headway and topology before any game change."}, {"problem_id": problem["problem_id"], "type": "SIMULATE_EXTRA_VEHICLE", "mutations": [{"type": "CHANGE_VIRTUAL_VEHICLE_COUNT", "line_id": line_id, "delta": 1}], "source_status": "HYPOTHETICAL", "statement": "A virtual fleet-count hypothesis; it does not predict frequency, demand, or profit."}])
            elif problem["type"] == "ISOLATED_COMPONENT":
                stations = problem["target"]["entity_ids"]
                options.append({"problem_id": problem["problem_id"], "type": "SIMULATE_COMPONENT_CONNECTION", "stations": stations, "source_status": "HYPOTHETICAL", "statement": "Choose one station here and one in another component to simulate a topology connection."})
        return {"snapshot_sequence": self.snapshot_sequence, "options": options[:limit], "limitations": ["Options are hypotheses, not game commands."]}

    def new_line_candidates(self, limit: int = 10) -> dict[str, Any]:
        """Rank topology gaps without claiming demand or physical reachability."""
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer from 1 to 100")
        components = self._components(set(self.stations), self.edges)
        component_by_station = {station_id: index for index, component in enumerate(components) for station_id in component}
        direct_pairs = {frozenset((edge.source, edge.target)) for edge in self.edges}

        def terminal_evidence(station_id: int) -> dict[str, Any]:
            observed = sorted({
                (stop.get("station_index"), stop.get("terminal_id"))
                for line in self.intelligence.lines_by_id.values()
                for stop in line.get("raw_stops", [])
                if stop.get("station_id") == station_id
                and isinstance(stop.get("station_index"), int)
                and isinstance(stop.get("terminal_id"), int)
            })
            if len(observed) == 1:
                return {"status": "RESOLVED", "station_index": observed[0][0], "terminal": observed[0][1], "source_status": "OBSERVED_EXISTING_LINE_STOP"}
            return {"status": "UNAVAILABLE" if not observed else "AMBIGUOUS_TERMINAL", "candidates": [{"station_index": item[0], "terminal": item[1]} for item in observed]}

        candidates = []
        served = sorted(station_id for station_id in self.stations if self.intelligence.station_metrics[station_id]["line_count"] > 0)
        for offset, station_a in enumerate(served):
            for station_b in served[offset + 1:]:
                if frozenset((station_a, station_b)) in direct_pairs:
                    continue
                metric_a, metric_b = self.intelligence.station_metrics[station_a], self.intelligence.station_metrics[station_b]
                evidence_a, evidence_b = terminal_evidence(station_a), terminal_evidence(station_b)
                cross_component = component_by_station[station_a] != component_by_station[station_b]
                terminals_resolved = evidence_a["status"] == evidence_b["status"] == "RESOLVED"
                readiness = "TERMINAL_INPUT_READY_PHYSICAL_PATH_UNKNOWN" if terminals_resolved else "NEEDS_TERMINAL_EVIDENCE"
                goal = {"name": f"Planned {station_a}-{station_b}", "start_station_id": station_a, "via_station_ids": [], "end_station_id": station_b}
                if terminals_resolved:
                    goal["terminal_selectors"] = {str(station_a): evidence_a["terminal"], str(station_b): evidence_b["terminal"]}
                candidates.append({
                    "station_ids": [station_a, station_b],
                    "station_names": [self.stations[station_a].get("name"), self.stations[station_b].get("name")],
                    "candidate_type": "CROSS_COMPONENT_CONNECTION" if cross_component else "TOPOLOGY_REDUNDANCY",
                    "score": {"cross_component": cross_component, "combined_line_count": metric_a["line_count"] + metric_b["line_count"], "combined_graph_degree": metric_a["graph_degree"] + metric_b["graph_degree"]},
                    "terminal_evidence": {str(station_a): evidence_a, str(station_b): evidence_b},
                    "execution_readiness": readiness,
                    "task_goal_candidate": {"goal_type": "CREATE_LINE_GOAL", "goal": goal},
                })
        candidates.sort(key=lambda item: (item["execution_readiness"] != "TERMINAL_INPUT_READY_PHYSICAL_PATH_UNKNOWN", -int(item["score"]["cross_component"]), -item["score"]["combined_line_count"], -item["score"]["combined_graph_degree"], item["station_ids"]))
        return {"snapshot_sequence": self.snapshot_sequence, "source_status": "DERIVED", "planning_basis": "station/line topology only", "candidates": candidates[:limit], "limitations": ["No demand, town-region, distance, cost, travel-time, or physical track/road reachability claim.", "Candidates are read-only proposals; execution still requires a separately planned and approved Task."]}

    def compare_scenarios(self, scenarios: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(scenarios, list) or not 2 <= len(scenarios) <= 10: raise ValueError("scenarios must contain 2 to 10 scenarios")
        results = []
        for scenario in scenarios:
            if not isinstance(scenario, dict) or not isinstance(scenario.get("name"), str) or not isinstance(scenario.get("mutations", []), list): raise ValueError("each scenario requires name and mutations")
            result = self.simulate(scenario.get("mutations", [])); results.append({"name": scenario["name"], "result": result})
        best_connectivity = min(results, key=lambda item: item["result"]["scenario"]["topology"]["connected_component_count"])["name"]
        best_isolation = min(results, key=lambda item: item["result"]["scenario"]["topology"]["isolated_station_count"])["name"]
        return {"snapshot_sequence": self.snapshot_sequence, "source_status": "HYPOTHETICAL", "baseline": self._topology_summary(set(self.stations), self.edges), "scenarios": results, "comparison": {"connectivity_gain": {"better": best_connectivity, "metric": "lower connected_component_count"}, "isolation_reduction": {"better": best_isolation, "metric": "lower isolated_station_count"}, "cost": {"status": "UNAVAILABLE"}, "demand_effect": {"status": "UNAVAILABLE"}, "profit_effect": {"status": "UNAVAILABLE"}}}

    def analyze_and_plan(self) -> dict[str, Any]:
        resilience = self.resilience()
        return {"snapshot_sequence": self.snapshot_sequence, "summary": {"line_count": len(self.intelligence.lines_by_id), "station_count": len(self.stations), "vehicle_count": len(self.intelligence.vehicles_by_id)}, "problems": self.detect_problems()["problems"][:10], "critical_dependencies": {"articulation_stations": resilience["articulation_stations"][:10], "bridge_connections": resilience["bridge_connections"][:10]}, "planning_options": self.planning_options(15)["options"], "new_line_candidates": self.new_line_candidates(10)["candidates"], "scenario_results": [], "limitations": {"load": "UNAVAILABLE", "waiting": "UNAVAILABLE", "finance": "UNAVAILABLE", "cost": "UNAVAILABLE", "demand": "UNAVAILABLE", "physical_route_reachability": "UNAVAILABLE", "scenario_execution": "Scenarios are in-memory hypotheses and never modify the game."}}
