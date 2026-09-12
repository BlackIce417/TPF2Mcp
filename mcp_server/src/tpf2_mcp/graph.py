"""Read-only station/line connectivity graph; this is not a physical route graph."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GraphEdge:
    line_id: int
    line_name: str | None
    source: int
    target: int
    frequency_seconds: float | int | None
    throughput: float | int | None


class TransportGraph:
    """Undirected station-group graph derived from consecutive line stops."""

    route_type = "line_station_connectivity_not_physical_path"

    def __init__(self, stations: dict[int, dict[str, Any]], lines: list[dict[str, Any]]):
        self.stations = stations
        self.adjacency: dict[int, list[GraphEdge]] = {station_id: [] for station_id in stations}
        self.line_edges: dict[int, list[GraphEdge]] = {}
        for line in lines:
            line_id = line.get("entity_id")
            if not isinstance(line_id, int):
                continue
            stops = [stop.get("station_id") for stop in line.get("stops", []) if isinstance(stop, dict) and stop.get("station_id") in stations]
            edges: list[GraphEdge] = []
            for source, target in zip(stops, stops[1:]):
                if source == target:
                    continue
                edge = GraphEdge(line_id, line.get("name"), source, target, line.get("frequency_seconds"), line.get("throughput"))
                edges.append(edge)
                self.adjacency[source].append(edge)
                self.adjacency[target].append(edge)
            self.line_edges[line_id] = edges

    @staticmethod
    def _other(edge: GraphEdge, station_id: int) -> int:
        return edge.target if edge.source == station_id else edge.source

    def degree(self, station_id: int) -> int:
        return len({self._other(edge, station_id) for edge in self.adjacency.get(station_id, [])})

    def connected_components(self) -> list[list[int]]:
        unseen, components = set(self.stations), []
        while unseen:
            start = next(iter(unseen))
            queue, component = deque([start]), []
            unseen.remove(start)
            while queue:
                current = queue.popleft()
                component.append(current)
                for edge in self.adjacency[current]:
                    other = self._other(edge, current)
                    if other in unseen:
                        unseen.remove(other)
                        queue.append(other)
            components.append(sorted(component))
        return sorted(components, key=lambda component: (len(component), component), reverse=True)

    def route(self, source_station_id: int, target_station_id: int) -> dict[str, Any] | None:
        if source_station_id not in self.stations or target_station_id not in self.stations:
            return None
        if source_station_id == target_station_id:
            return {"route_type": self.route_type, "station_ids": [source_station_id], "legs": [], "transfer_count": 0}
        queue = deque([source_station_id])
        previous: dict[int, tuple[int, GraphEdge] | None] = {source_station_id: None}
        while queue and target_station_id not in previous:
            current = queue.popleft()
            for edge in self.adjacency[current]:
                other = self._other(edge, current)
                if other not in previous:
                    previous[other] = (current, edge)
                    queue.append(other)
        if target_station_id not in previous:
            return {"route_type": self.route_type, "station_ids": [], "legs": [], "transfer_count": None, "reason": "STATIONS_NOT_CONNECTED"}
        hops: list[tuple[int, int, GraphEdge]] = []
        current = target_station_id
        while previous[current] is not None:
            prior, edge = previous[current]  # type: ignore[misc]
            hops.append((prior, current, edge))
            current = prior
        hops.reverse()
        legs: list[dict[str, Any]] = []
        for source, target, edge in hops:
            if legs and legs[-1]["line_id"] == edge.line_id and legs[-1]["to_station_id"] == source:
                legs[-1]["to_station_id"] = target
                legs[-1]["station_ids"].append(target)
            else:
                legs.append({"line_id": edge.line_id, "line_name": edge.line_name, "from_station_id": source, "to_station_id": target, "station_ids": [source, target], "frequency_seconds": edge.frequency_seconds, "throughput": edge.throughput})
        return {"route_type": self.route_type, "station_ids": [source_station_id] + [target for _, target, _ in hops], "legs": legs, "transfer_count": max(0, len(legs) - 1)}
