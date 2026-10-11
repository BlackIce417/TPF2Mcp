"""Read-only topology study; draft territory ownership, never game commands."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import heapq
import json
import math
from pathlib import Path
import uuid

REGIONS = {"HK": ("汉口", None, "#40b9f2"), "WC": (
    "武昌", None, "#f4a641"), "WH": ("武汉", None, "#b69bff")}


class UnionFind:
    def __init__(self, count):
        self.parent = list(range(count))

    def find(self, item):
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def merge(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[b] = a

    def together(self, items):
        items = list(items)
        for item in items[1:]:
            self.merge(items[0], item)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def distance(a, b):
    return math.dist((a["x"], a["y"], a.get("z", 0)), (b["x"], b["y"], b.get("z", 0)))


def point(edge, nodes, t):
    a, b = nodes[edge["node0"]], nodes[edge["node1"]]
    delta = {k: b[k] - a[k] for k in ("x", "y", "z")}
    u, v = edge.get("tangent0") or delta, edge.get("tangent1") or delta
    return {k: (2*t**3-3*t*t+1)*a[k] + (t**3-2*t*t+t)*u[k]
            + (-2*t**3+3*t*t)*b[k] + (t**3-t*t)*v[k] for k in delta}


def shortest(graph, seeds, weights):
    costs, labels, queue = {}, {}, []
    for node, label in sorted(seeds):
        if node not in costs:
            costs[node], labels[node] = 0.0, label
            heapq.heappush(queue, (0.0, label, node))
    while queue:
        cost, label, node = heapq.heappop(queue)
        if (cost, label) != (costs[node], labels[node]):
            continue
        for other in graph[node]:
            candidate = cost + (weights[node] + weights[other])/2
            if (candidate, label) < (costs.get(other, math.inf), labels.get(other, "~")):
                costs[other], labels[other] = candidate, label
                heapq.heappush(queue, (candidate, label, other))
    return costs, labels


def freeze_coordinate_anchors(out, result, net):
    """Seed once from the survey; rerunning a signal survey never moves anchors.

    Signal/edge IDs below are historical evidence, not persistent identity.
    Directional signal calibration is intentionally not implemented here.
    """
    path = out / "boundary-anchors.json"
    if path.exists():
        existing = read(path)
        if existing.get("save_id") != result["save_id"]:
            raise ValueError(
                "Existing coordinate anchors belong to another save; use a separate study directory")
        return
    nodes = {n["entity_id"]: n["position"] for n in net["nodes"]}
    edges = {e["entity_id"]: e for e in net["edges"]}
    stations = {s["entity_id"]: s for s in net["stations"]}
    anchors = []
    for b in result["boundaries"]:
        edge, t = edges[b["edge_id"]], b["edge_param"]
        a, z = point(edge, nodes, max(0, t-.001)
                     ), point(edge, nodes, min(1, t+.001))
        length = distance(a, z)
        if length <= 0:
            raise ValueError("Cannot determine anchor orientation")
        anchors.append({
            "anchor_id": str(uuid.uuid4()), "label": b["boundary_id"], "revision": 1,
            "position": b["position"], "coordinate_frame": "GAME_WORLD_METERS",
            "positive_tangent": {k: (z[k]-a[k])/length for k in ("x", "y", "z")},
            "negative_region": b["regions"][0], "positive_region": b["regions"][1],
            "corridor_references": [{"name": stations[s]["name"], "position": stations[s]["center"],
                                    "station_id_hint": s} for s in b["nearest_stations"] if s is not None],
            "search_policy": {"xy_radius_m": 50, "max_vertical_offset_m": 5, "max_axis_angle_degrees": 25,
                              "max_signal_path_distance_m": 1500, "ambiguous_match": "DO_NOT_BIND",
                              "automatic_anchor_movement": False},
            "seed_evidence": {"topology_sha256": result["topology_sha256"], "edge_id": b["edge_id"],
                              "edge_param": t, "signal_ids": b["signal_ids"]},
            "calibration": {"status": "PENDING_DIRECTIONAL_CALIBRATION", "up_down_mapping": None,
                            "negative_to_positive": None, "positive_to_negative": None,
                            "control_ready": False}})
    document = {"schema_version": 1, "save_id": result["save_id"], "status": "DRAFT_COORDINATE_ANCHORS",
                "created_at": result["created_at"], "identity": "STABLE_UUID_AND_WORLD_COORDINATE",
                "anchors": anchors}
    # Exclusive creation protects against accidental replacement and concurrent studies.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mod-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    if not out.is_relative_to((repo / "diagnostics").resolve()):
        raise ValueError(
            "Study output must stay under repository diagnostics/")
    root = args.mod_root.resolve()
    data_path = root / "var/rail-map/rail-network-data.json"
    net = read(data_path)
    manifest = read(root / "var/rail-map/rail-network-manifest.json")
    heartbeat = read(root / "bridge/heartbeat.json")
    control = read(root / "bridge/rail-control-state.json")
    nodes = {n["entity_id"]: n["position"] for n in net["nodes"]}
    edges = {e["entity_id"]: e for e in net["edges"]}
    stations = {s["entity_id"]: s for s in net["stations"]}
    for region, (name, _, color) in list(REGIONS.items()):
        matches = [sid for sid, s in stations.items() if s["name"] in {
            name, name+"站"}]
        if len(matches) != 1:
            raise ValueError(
                f"Expected exactly one anchor for {name}, got {matches}; resolve the station identity first")
        REGIONS[region] = (name, matches[0], color)
    assert manifest["save_id"] == net["save_id"]
    # Signal state has no save ID: record this limitation and cross-check edge membership.
    assert all(s["edge_id"] in edges for s in control["signals"])
    assert all(e["node0"] in nodes and e["node1"]
               in nodes for e in edges.values())
    signal_by_edge = defaultdict(list)
    for sig in control["signals"]:
        if sig["source_status"] != "TRACK_OBJECT_CANDIDATE":
            signal_by_edge[sig["edge_id"]].append(sig)
    segments, edge_segments, incident, cuts = [
    ], defaultdict(list), defaultdict(list), []
    for eid, edge in sorted(edges.items()):
        groups = defaultdict(list)
        for sig in signal_by_edge[eid]:
            t = float(sig["edge_param"])
            assert 0 < t < 1
            groups[t].append(sig)
        ts = [0.0, *sorted(groups), 1.0]
        for start, end in zip(ts, ts[1:]):
            pts = [point(edge, nodes, start+(end-start)*i/12)
                   for i in range(13)]
            sid = len(segments)
            segments.append({"segment_id": sid, "edge_id": eid, "start": start, "end": end,
                             "length_m": sum(distance(a, b) for a, b in zip(pts, pts[1:])),
                             "center": point(edge, nodes, (start+end)/2)})
            edge_segments[eid].append(sid)
        incident[edge["node0"]].append(edge_segments[eid][0])
        incident[edge["node1"]].append(edge_segments[eid][-1])
        for index, t in enumerate(ts[1:-1]):
            cuts.append({"edge_id": eid, "edge_param": t, "signal_ids": [s["entity_id"] for s in groups[t]],
                         "position": point(edge, nodes, t), "a": edge_segments[eid][index], "b": edge_segments[eid][index+1]})
    uf = UnionFind(len(segments))
    for items in incident.values():
        uf.together(items)
    # Only existing signals can split ownership; all unsignalled junctions remain whole.
    edge_neighbors = defaultdict(set)
    for items in incident.values():
        eids = {segments[i]["edge_id"] for i in items}
        for eid in eids:
            edge_neighbors[eid].update(eids - {eid})
    cores, preview_generations = {}, set()
    for sid, station in stations.items():
        platforms = {eid for t in station.get("terminals", []) for eid in t.get(
            "platform_edge_ids", []) if eid in edges}
        if not platforms:
            raise ValueError(f"No platform edge evidence for station {sid}")
        preview = read(
            root / f"var/rail-map/station-previews/station-{sid}.json")
        assert preview["save_id"] == net["save_id"]
        preview_generations.add(preview.get("generated_at"))
        allowed = {e["entity_id"] for e in preview["edges"]} | platforms
        reached, queue = set(platforms), list(platforms)
        while queue:
            eid = queue.pop()
            for other in edge_neighbors[eid] & allowed - reached:
                reached.add(other)
                queue.append(other)
        cores[sid] = reached
        uf.together(i for eid in reached for i in edge_segments[eid])
    # Co-located same-name passenger/freight sites share a dispatcher, but keep entity IDs.
    station_list = list(stations.values())
    for index, a in enumerate(station_list):
        for b in station_list[index+1:]:
            if a["name"] == b["name"] and distance(a["center"], b["center"]) < 350:
                uf.merge(edge_segments[min(cores[a["entity_id"]])]
                         [0], edge_segments[min(cores[b["entity_id"]])][0])
    weights, members = defaultdict(float), defaultdict(list)
    for seg in segments:
        atom = uf.find(seg["segment_id"])
        seg["atom_id"] = atom
        weights[atom] += seg["length_m"]
        members[atom].append(seg["segment_id"])
    graph = {atom: set() for atom in members}
    for cut in cuts:
        a, b = uf.find(cut["a"]), uf.find(cut["b"])
        if a != b:
            graph[a].add(b)
            graph[b].add(a)
    station_atom = {sid: uf.find(
        edge_segments[min(core)][0]) for sid, core in cores.items()}
    seeds = [(station_atom[hub], region)
             for region, (_, hub, _) in REGIONS.items()]
    assert len({a for a, _ in seeds}
               ) == 3, "Hub protected areas merged; manual boundary study required"
    # Multi-track yards must not cost the sum of all parallel tracks. Use physical
    # footprint as a coarse corridor distance; this is zoning, not train routing.
    zoning_weights = {}
    for atom, ids in members.items():
        group = [segments[i] for i in ids]
        extent = math.sqrt(sum((max(s["center"][k] for s in group)-min(
            s["center"][k] for s in group))**2 for k in ("x", "y", "z")))
        zoning_weights[atom] = min(
            weights[atom], extent+max(s["length_m"] for s in group))
    costs, owner = shortest(graph, seeds, zoning_weights)
    unseeded = []
    remaining = set(graph)-set(owner)
    while remaining:
        first = min(remaining)
        component, queue = {first}, [first]
        while queue:
            for other in graph[queue.pop()]:
                if other not in component:
                    component.add(other)
                    queue.append(other)
        remaining -= component
        component_segments = [segments[i]
                              for atom in component for i in members[atom]]
        length = sum(s["length_m"] for s in component_segments)
        center = {k: sum(s["center"][k]*s["length_m"]
                         for s in component_segments)/length for k in ("x", "y", "z")}
        region = min(REGIONS, key=lambda r: distance(
            center, stations[REGIONS[r][1]]["center"]))
        for atom in component:
            owner[atom] = region
        unseeded.append({"atom_ids": sorted(component), "edge_ids": sorted({s["edge_id"] for s in component_segments}),
                         "length_m": length, "center": center, "region": region, "assignment": "PROVISIONAL_GEOGRAPHIC_FALLBACK",
                         "station_ids": [sid for sid, atom in station_atom.items() if atom in component]})
    nearest_station = {}
    for region in REGIONS:
        regional_graph = {atom: {n for n in neighbors if owner[n] == region}
                          for atom, neighbors in graph.items() if owner[atom] == region}
        _, labels = shortest(regional_graph, [(atom, str(
            sid)) for sid, atom in station_atom.items() if owner[atom] == region], zoning_weights)
        nearest_station.update(labels)
    for seg in segments:
        seg["region"] = owner[seg["atom_id"]]
    # Preserve the physical graph independently of administrative station unions.
    node_graph = defaultdict(list)
    for eid, edge in edges.items():
        length = sum(segments[i]["length_m"] for i in edge_segments[eid])
        node_graph[edge["node0"]].append((edge["node1"], eid, length))
        node_graph[edge["node1"]].append((edge["node0"], eid, length))
    components, remaining_nodes = [], set(node_graph)
    while remaining_nodes:
        seed = min(remaining_nodes)
        queue = [seed]
        component_nodes = {seed}
        component_edges = set()
        remaining_nodes.remove(seed)
        while queue:
            for other, eid, _ in node_graph[queue.pop()]:
                component_edges.add(eid)
                if other in remaining_nodes:
                    remaining_nodes.remove(other)
                    component_nodes.add(other)
                    queue.append(other)
        components.append({"node_count": len(component_nodes),
                          "edge_ids": sorted(component_edges)})
    junction_dist = {nid: 0.0 for nid,
                     links in node_graph.items() if len(links) >= 3}
    queue = [(0.0, nid) for nid in junction_dist]
    heapq.heapify(queue)
    while queue:
        cost, nid = heapq.heappop(queue)
        if cost != junction_dist[nid]:
            continue
        for other, _, length in node_graph[nid]:
            candidate = cost+length
            if candidate < junction_dist.get(other, math.inf):
                junction_dist[other] = candidate
                heapq.heappush(queue, (candidate, other))
    station_rows = [{"entity_id": sid, "name": s["name"], "region": owner[station_atom[sid]], "center": s["center"],
                     "protected_edge_count": len(cores[sid]), "atom_id": station_atom[sid],
                     "cargo": sorted({t.get("cargo") for t in s.get("terminals", []) if t.get("cargo") is not None})}
                    for sid, s in stations.items()]
    boundaries = []
    for cut in cuts:
        a, b = uf.find(cut["a"]), uf.find(cut["b"])
        if owner[a] == owner[b]:
            continue
        eid = cut["edge_id"]
        edge = edges[eid]
        left_length = sum(segments[i]["length_m"]
                          for i in edge_segments[eid] if segments[i]["end"] <= cut["edge_param"])
        right_length = sum(segments[i]["length_m"] for i in edge_segments[eid]
                           if segments[i]["start"] >= cut["edge_param"])
        turnout_distance = min(left_length+junction_dist.get(
            edge["node0"], math.inf), right_length+junction_dist.get(edge["node1"], math.inf))
        boundary = {k: v for k, v in cut.items() if k not in ("a", "b")}
        boundary.update(boundary_id=f"B{len(boundaries)+1:03}", regions=[owner[a], owner[b]],
                        nearest_stations=[
                            int(nearest_station[x]) if x in nearest_station else None for x in (a, b)],
                        nearest_node_distance_m=min(
                            distance(cut["position"], nodes[edge[k]]) for k in ("node0", "node1")),
                        line_ids=edge.get("line_ids", []), direction_verified=False,
                        nearest_turnout_graph_distance_m=round(
                            turnout_distance, 1) if math.isfinite(turnout_distance) else None,
                        readiness="DRAFT_SIGNAL_CUT_NEEDS_DIRECTION_AND_CLEARANCE_CHECK")
        boundaries.append(boundary)
    depots = []
    for depot in net.get("depots", []):
        eid = depot.get("nearest_edge_id")
        if eid not in edge_segments:
            raise ValueError(f"Unmapped depot {depot['entity_id']}")
        t = depot.get("nearest_edge_param", 0)
        seg = next(segments[i] for i in edge_segments[eid]
                   if segments[i]["start"] <= t <= segments[i]["end"])
        depots.append({"entity_id": depot["entity_id"], "name": depot["name"], "region": seg["region"],
                       "edge_id": eid, "connection_source": depot.get("track_connection_source")})
    signal_owners = []
    for sig in control["signals"]:
        ids = edge_segments[sig["edge_id"]]
        t = sig["edge_param"]
        seg = next(segments[i] for i in ids if segments[i]
                   ["start"] <= t < segments[i]["end"])
        signal_owners.append(
            {"signal_id": sig["entity_id"], "edge_id": sig["edge_id"], "edge_param": t, "region": seg["region"]})
    node_owners = {str(nid): owner[uf.find(items[0])]
                   for nid, items in incident.items()}
    # Machine-check exhaustive non-overlapping interval coverage and station indivisibility.
    assert len(edge_segments) == len(edges)
    for eid, ids in edge_segments.items():
        intervals = [segments[i] for i in ids]
        assert intervals[0]["start"] == 0 and intervals[-1]["end"] == 1
        assert all(a["end"] == b["start"]
                   for a, b in zip(intervals, intervals[1:]))
        assert all(s["start"] < s["end"] and s["region"]
                   in REGIONS for s in intervals)
    assert all(len({owner[uf.find(
        i)] for eid in core for i in edge_segments[eid]}) == 1 for core in cores.values())
    assert all(len({owner[uf.find(i)] for i in items})
               == 1 for items in incident.values())
    assert len({s["signal_id"]
               for s in signal_owners}) == len(control["signals"])
    result = {"schema_version": 1, "status": "DRAFT_NOT_CONTROL_CONFIGURATION", "created_at": datetime.now(timezone.utc).isoformat(),
              "save_id": net["save_id"], "topology_generation": manifest.get("generated_at"),
              "topology_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
              "signal_sampled_at": control.get("sampled_at"), "preview_generations": sorted(preview_generations),
              "source_heartbeat_save_id": heartbeat.get("save_id"),
              "source_heartbeat_bridge_dir": heartbeat.get("bridge_dir"),
              "method": "SIGNAL_CUTS_PROTECTED_STATION_CORES_THREE_HUB_FOOTPRINT_WEIGHTED_GRAPH",
              "limitations": ["Snapshot coverage only; not a fresh full game topology export", "Signal orientation is UNKNOWN",
                              "Station throat extent inferred from existing preview scope", "Distance weights approximate corridor proximity, not operational capacity",
                              "Signal control export has no save ID; checked all edge IDs against current-save topology",
                              "No game mutations; no dispatch authority activated"],
              "coverage": {"edges": len(edges), "nodes": len(nodes), "stations": len(stations), "rail_depots": len(depots),
                           "signals": len(control["signals"]), "segments": len(segments), "unassigned_edges": 0, "overlapping_intervals": 0,
                           "split_station_cores": 0, "split_junctions": 0, "unseeded_components": len(unseeded),
                           "physical_components": len(components), "unassigned_nodes": len(set(nodes)-set(node_graph)),
                           "unassigned_signals": len(control["signals"])-len(signal_owners)},
              "regions": {r: {"name": name+"站调度区", "hub_station_id": hub, "color": color,
                              "station_count": sum(s["region"] == r for s in station_rows),
                              "track_km": round(sum(s["length_m"] for s in segments if s["region"] == r)/1000, 3),
                              "edge_count": len({s["edge_id"] for s in segments if s["region"] == r})}
                          for r, (name, hub, color) in REGIONS.items()},
              "stations": station_rows, "depots": depots, "boundaries": boundaries, "unseeded_components": unseeded,
              "physical_components": components,
              "node_owners": node_owners, "signal_owners": signal_owners,
              "segments": segments}
    out.mkdir(parents=True, exist_ok=True)
    freeze_coordinate_anchors(out, result, net)
    result["anchor_file"] = "boundary-anchors.json"
    result["boundary_role"] = "SIGNAL_SURVEY_CANDIDATES_NOT_AUTHORITATIVE_COORDINATE_ANCHORS"
    (out/"territories.json").write_text(json.dumps(result,
                                                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    report = ["# 三调度区拓扑划分草案", "", "只读分析，尚未启用。长度为各轨道长度之和，不是线路里程。", "",
              "边界固定坐标与稳定 ID 见 boundary-anchors.json；下方信号仅为本次勘查候选。自动双向信号校准尚未实现。", "",
              f"存档：`{net['save_id']}`；拓扑 SHA256：`{result['topology_sha256']}`。", "",
              "## 辖站", ""]
    for region, details in result["regions"].items():
        report.extend(
            [f"### {details['name']}：{details['station_count']} 个站实体，{details['track_km']} 轨道公里", ""])
        for s in sorted((s for s in station_rows if s["region"] == region), key=lambda s: (s["name"], s["entity_id"])):
            report.append(
                f"- {s['name']}（{s['entity_id']}；{'/'.join('货' if c else '客' for c in s['cargo'])}）")
        report.extend(["", "机务段/动车所："+"、".join(
            f"{d['name']}（{d['entity_id']}）" for d in depots if d["region"] == region), ""])
    report.extend(["## 信号交接点", "", "位置参数沿 edge 的 node0 → node1；不代表列车运行方向。边界附近停车条件未验证。", "",
                   "|边界|两侧区域|两侧最近辖站（区内图距离）|信号 ID|轨道 edge / 参数|坐标 x,y|最近分岔距离 m|", "|---|---|---|---|---|---|---|"])
    for b in boundaries:
        names = [
            f"{stations[s]['name']}({s})" if s else "无站连接" for s in b["nearest_stations"]]
        report.append(f"|{b['boundary_id']}|{' / '.join(REGIONS[r][0] for r in b['regions'])}|{' / '.join(names)}|{','.join(map(str, b['signal_ids']))}|{b['edge_id']} / {b['edge_param']:.6f}|{b['position']['x']:.1f}, {b['position']['y']:.1f}|{b['nearest_turnout_graph_distance_m']}|")
    report.extend(["", "## 无盲区核对", "", "```json", json.dumps(result["coverage"], ensure_ascii=False, indent=2), "```", "",
                   "未连到三个枢纽种子的独立分量采用临时地理归属，不能据此声称具备可执行控制；需核对：", ""])
    for comp in unseeded:
        report.append(
            f"- {REGIONS[comp['region']][0]}：{len(comp['edge_ids'])} 边，{comp['length_m']:.1f} m，站 {comp['station_ids']}，边样本 {comp['edge_ids'][:10]}")
    (out/"topology-inventory.md").write_text("\n".join(report)+"\n", encoding="utf-8")
    print(json.dumps({"coverage": result["coverage"], "regions": result["regions"], "boundaries": len(boundaries),
                      "stations": {r: [f"{s['name']}({s['entity_id']})" for s in station_rows if s["region"] == r] for r in REGIONS},
                      "unseeded": unseeded}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
