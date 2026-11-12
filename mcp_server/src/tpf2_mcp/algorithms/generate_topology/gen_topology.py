"""Compress physical rail segments into a candidate directed topology.

Bidirectional arcs describe physical connectivity, NOT verified train routes.
No global mutable graph, file I/O, or game mutation is performed.
"""
from __future__ import annotations

from enum import Enum
from dataclasses import asdict, dataclass, field
import math
from typing import Any

from tpf2_mcp.algorithms.rail_topology import RailGraph

class NodeType(str, Enum):
    STATION = "station"
    SWITCH = "switch"        # 单个物理分岔候选，尚未验证道岔通行关系
    SIGNAL = "signal"
    ENDPOINT = "endpoint"    # 轨道端点，不是线路所或道岔
    ANCHOR = "anchor"        # 闭环保留点，不是线路所或道岔


@dataclass
class Node:
    id: int
    type: NodeType
    display_name: str
    position: dict[str, float] = field(default_factory=dict)
    game_node_id: int | None = None
    station_ids: list[int] = field(default_factory=list)
    signal_ids: list[int] = field(default_factory=list)
    boundary_kind: str = ""
    signal_bindings: list[dict[str, Any]] = field(default_factory=list)
    station_wrapper: dict[str, Any] | None = None

@dataclass
class Edge:
    id: int
    from_node_id: int
    to_node_id: int
    length_m: float
    reverse_edge_id: int = 0
    track_resource_id: int = 0
    track_segments: list[dict[str, Any]] = field(default_factory=list)
    direction: str = "UNVERIFIED"

@dataclass
class NetworkTopology:
    nodes: dict[int, Node] = field(default_factory=dict)
    edges: dict[int, Edge] = field(default_factory=dict)
    outgoing: dict[int, list[int]] = field(default_factory=dict)
    incoming: dict[int, list[int]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    dispatch_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready output, retaining independent IDs for parallel arcs."""
        return {
            "schema_version": 1,
            "dispatch_ready": self.dispatch_ready,
            "nodes": [asdict(node) for node in self.nodes.values()],
            "edges": [asdict(edge) for edge in self.edges.values()],
            "warnings": list(self.warnings),
        }


def generate_topology(
    raw_network: dict[str, Any] | None = None,
    raw_signals: dict[str, Any] | None = None,
    *, collapse_stations: bool = True,
) -> NetworkTopology:
    """Build a fresh graph from Loader payloads or explicitly supplied data.

    Station terminals remain separate ports; merging a whole station would
    invent connectivity between disconnected platforms. Junctions are physical
    switch candidates based on physical connectivity only.
    Signal objects require operational_signal_observed=True and edge_param.
    """
    if raw_network is None:
        from tpf2_mcp.transport.loader_telemetry import read_json_channel
        raw_network = read_json_channel("rail-network.json")
        if raw_signals is None:
            try:
                raw_signals = read_json_channel("operational-telemetry-signals.json")
            except (OSError, KeyError):
                raw_signals = None
    if raw_network.get("status", "OK") != "OK":
        raise ValueError("rail network collection is not OK")
    physical = RailGraph(raw_network)
    graph = NetworkTopology()
    graph.warnings.append("PHYSICAL_CONNECTIVITY_ONLY: directions and switch movements are unverified")
    if raw_network.get("errors"):
        graph.warnings.append("SOURCE_COLLECTION_ERRORS")
    stations: dict[int, list[dict]] = {}
    for station in raw_network.get("stations", []):
        for terminal in station.get("terminals", []):
            node_id = terminal.get("node_id")
            if node_id not in physical.nodes:
                graph.warnings.append(f"STATION_TERMINAL_NODE_MISSING:{station['entity_id']}:{node_id}")
                continue
            stations.setdefault(node_id, []).append(station)

    # Expanded undirected graph: split raw edges at signals, then compress
    # chains whose intermediate vertices are neither boundaries nor branches.
    positions = {nid: dict(row["position"]) for nid, row in physical.nodes.items()}
    adjacency: dict[int, list[int]] = {nid: [] for nid in positions}
    pieces: dict[int, tuple[int, int, float, dict]] = {}
    signals_at: dict[int, list[int]] = {}
    cuts: dict[int, list[dict]] = {}
    recovered_bindings: dict[int, dict] = {}
    if raw_signals is None:
        graph.warnings.append("SIGNAL_INVENTORY_UNAVAILABLE")
    else:
        from tpf2_mcp.algorithms.dispatch_runtime.geometry import RailGraph as ProjectionGraph
        from tpf2_mcp.algorithms.dispatch_runtime.boundaries import normalize_directional_signals
        projection_graph = ProjectionGraph(raw_network)
        recovered = {row['entity_id']: row for row in normalize_directional_signals(raw_signals, projection_graph)}
        recovered_bindings = recovered
        for signal in raw_signals.get("signal_edge_objects", []):
            if signal.get("operational_signal_observed") is not True:
                continue
            eid, parameter = signal.get("edge_entity_id"), signal.get("edge_param")
            if parameter is None and signal.get('object_entity_id') in recovered:
                candidate = recovered[signal['object_entity_id']]
                _, _, error_m = projection_graph.project(eid, signal['position'])
                if math.isfinite(error_m) and error_m <= 5.0:
                    parameter = candidate['edge_param']
                    signal = {**signal, 'edge_param': parameter, 'location_source': 'OWNING_EDGE_PROJECTION',
                              'projection_error_m': error_m}
                    graph.warnings.append('SIGNAL_POSITIONS_PROJECTED_ON_OWNING_EDGE: maximum accepted residual 5m')
                else:
                    graph.warnings.append(f"SIGNAL_PROJECTION_TOO_FAR:{signal['object_entity_id']}")
            if (eid not in physical.edges or isinstance(parameter, bool)
                    or not isinstance(parameter, (float, int)) or not math.isfinite(parameter)
                    or not 0 <= parameter <= 1):
                graph.warnings.append(f"SIGNAL_LOCATION_UNRESOLVED:{signal.get('object_entity_id')}")
                continue
            cuts.setdefault(eid, []).append(signal)
        if cuts:
            graph.warnings.append("SIGNAL_EDGE_PARAM_INTERPRETED_AS_CURVE_PARAMETER: requires engine validation")

    next_vertex = max(positions, default=0) + 1
    for eid, raw_edge in sorted(physical.edges.items()):
        # Use the existing physical graph's Hermite curve convention. More
        # samples improve arc length estimates; lengths remain approximations.
        samples = physical.samples(eid, steps=128)

        def point(t):
            scaled = t * 128
            index = min(int(scaled), 127)
            weight = scaled - index
            return tuple(a + (b-a)*weight for a, b in zip(samples[index], samples[index+1]))

        def arc_length(start, end):
            points = [point(start)]
            points.extend(samples[i] for i in range(1, 128) if start < i/128 < end)
            points.append(point(end))
            return sum(math.dist(a, b) for a, b in zip(points, points[1:]))

        vertices = {0.0: raw_edge["node0"], 1.0: raw_edge["node1"]}
        for signal in sorted(cuts.get(eid, []), key=lambda row: (row['edge_param'], row['object_entity_id'])):
            t = float(signal["edge_param"])
            if t not in vertices:
                vertices[t] = next_vertex
                positions[next_vertex] = dict(zip(("x", "y", "z"), point(t)))
                adjacency[next_vertex] = []
                next_vertex += 1
            signals_at.setdefault(vertices[t], []).append(signal["object_entity_id"])
        ordered = sorted(vertices.items())
        for (start, a), (end, b) in zip(ordered, ordered[1:]):
            pid = len(pieces) + 1
            segment = {"game_edge_id": eid, "begin_position01": start, "end_position01": end}
            pieces[pid] = (a, b, arc_length(start, end), segment)
            adjacency[a].append(pid)
            adjacency[b].append(pid)

    boundaries = {nid for nid, links in adjacency.items()
                  if len(links) != 2 or nid in stations or nid in signals_at}
    # A disconnected cycle has no degree != 2 vertex; retain one anchor so it
    # becomes a self-loop instead of disappearing.
    seen = set()
    for seed in sorted(adjacency):
        if seed in seen:
            continue
        pending, component = [seed], []
        while pending:
            nid = pending.pop()
            if nid in seen:
                continue
            seen.add(nid)
            component.append(nid)
            for pid in adjacency[nid]:
                a, b, _, _ = pieces[pid]
                pending.append(b if a == nid else a)
        if not boundaries.intersection(component):
            boundaries.add(min(component))

    for nid in sorted(boundaries):
        memberships = stations.get(nid, [])
        signal_ids = sorted(set(signals_at.get(nid, [])))
        degree = len(adjacency[nid])
        kind = (NodeType.STATION if memberships else NodeType.SIGNAL if signal_ids else
                NodeType.SWITCH if degree > 2 else NodeType.ENDPOINT if degree < 2 else NodeType.ANCHOR)
        label = "/".join(sorted({row.get('name', str(row['entity_id'])) for row in memberships}))
        if not label:
            label = (f"信号机{signal_ids[0]}" if signal_ids else
                     f"道岔候选{nid}" if degree > 2 else f"轨道端点{nid}" if degree < 2 else f"闭环锚点{nid}")
        graph.nodes[nid] = Node(
            nid, kind, label, positions[nid], nid if nid in physical.nodes else None,
            sorted({row['entity_id'] for row in memberships}), signal_ids,
            "station_terminal" if memberships else "signal" if signal_ids else
            "switch_candidate" if degree > 2 else "endpoint" if degree < 2 else "cycle_anchor",
        )
        graph.nodes[nid].signal_bindings = [recovered_bindings[sid] for sid in signal_ids if sid in recovered_bindings]
        graph.outgoing[nid], graph.incoming[nid] = [], []

    visited = set()
    for source in sorted(boundaries):
        for first in adjacency[source]:
            if first in visited:
                continue
            current, pid, length, segments = source, first, 0.0, []
            while True:
                visited.add(pid)
                a, b, distance, segment = pieces[pid]
                forward = current == a
                target = b if forward else a
                oriented = dict(segment)
                if not forward:
                    oriented['begin_position01'], oriented['end_position01'] = segment['end_position01'], segment['begin_position01']
                segments.append(oriented)
                length += distance
                if target in boundaries:
                    break
                current = target
                pid = next(link for link in adjacency[current] if link != pid)
            edge_id = len(graph.edges) + 1
            resource_id = (edge_id + 1) // 2
            reverse = [{**s, 'begin_position01': s['end_position01'], 'end_position01': s['begin_position01']}
                       for s in reversed(segments)]
            graph.edges[edge_id] = Edge(edge_id, source, target, length, edge_id+1, resource_id, segments)
            graph.edges[edge_id+1] = Edge(edge_id+1, target, source, length, edge_id, resource_id, reverse)
            graph.outgoing[source].append(edge_id)
            graph.incoming[target].append(edge_id)
            graph.outgoing[target].append(edge_id+1)
            graph.incoming[source].append(edge_id+1)
    if len(visited) != len(pieces):
        raise ValueError("topology compression did not cover every physical track segment")
    graph.warnings = sorted(set(graph.warnings))
    if collapse_stations:
        from tpf2_mcp.algorithms.generate_topology.station_topology_node import collapse_station_nodes
        return collapse_station_nodes(graph, raw_network)
    return graph
