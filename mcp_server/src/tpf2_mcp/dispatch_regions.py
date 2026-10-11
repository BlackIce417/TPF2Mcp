"""Pure presentation compiler for territory snapshots; never issues game commands."""
from __future__ import annotations

from collections import defaultdict
import math


def current_region_view(view: dict, save_id: str | None, manifest: dict) -> dict:
    if not view:
        return {"schema_version": 1, "error": "REGIONS_NOT_CONFIGURED"}
    if view.get("schema_version") != 1:
        return {"schema_version": 1, "error": "REGIONS_SCHEMA_UNSUPPORTED"}
    if not save_id or view.get("save_id") != save_id or manifest.get("save_id") != save_id:
        return {"schema_version": 1, "error": "REGIONS_SAVE_MISMATCH"}
    if view.get("topology_generation") != manifest.get("generated_at"):
        return {"schema_version": 1, "error": "REGIONS_TOPOLOGY_STALE"}
    return view


def build_region_view(territories: dict, anchor_data: dict, network: dict, network_sha256: str) -> dict:
    save_id = network.get("save_id")
    if not save_id or territories.get("save_id") != save_id or anchor_data.get("save_id") != save_id:
        raise ValueError("region sources must belong to the same save")
    if network_sha256 != territories.get("topology_sha256"):
        raise ValueError("territories do not match the supplied topology")
    regions = territories["regions"]
    edges = {e["entity_id"]: e for e in network["edges"]}
    nodes = {n["entity_id"]: n["position"] for n in network["nodes"]}
    station_ids = {s["entity_id"] for s in network["stations"]}
    station_rows = territories["stations"]
    if {s["entity_id"] for s in station_rows} != station_ids or len(station_rows) != len(station_ids):
        raise ValueError("station coverage is incomplete or duplicated")
    by_edge = defaultdict(list)
    for segment in territories["segments"]:
        if segment["region"] not in regions:
            raise ValueError("unknown region")
        by_edge[segment["edge_id"]].append(segment)
    if set(by_edge) != set(edges):
        raise ValueError("rail edge coverage is incomplete")
    for segments in by_edge.values():
        segments.sort(key=lambda s: s["start"])
        if (segments[0]["start"] != 0 or segments[-1]["end"] != 1
                or any(not 0 <= s["start"] < s["end"] <= 1 for s in segments)
                or any(a["end"] != b["start"] for a, b in zip(segments, segments[1:]))):
            raise ValueError("rail intervals overlap or have gaps")
    bounds = network["bounds"]
    width = max(1, bounds["max"]["x"] - bounds["min"]["x"])
    height = max(1, bounds["max"]["y"] - bounds["min"]["y"])
    scale = min(1080 / width, 620 / height)
    ox = 600 - (bounds["min"]["x"] + bounds["max"]["x"]) * scale / 2
    oy = 360 + (bounds["min"]["y"] + bounds["max"]["y"]) * scale / 2

    def project(position):
        return {"x": round(ox + position["x"] * scale, 3), "y": round(oy - position["y"] * scale, 3)}

    def curve(edge, t, derivative=False):
        a, b = nodes[edge["node0"]], nodes[edge["node1"]]
        delta = {k: b[k] - a[k] for k in ("x", "y")}
        u, v = edge.get("tangent0") or delta, edge.get("tangent1") or delta
        if derivative:
            return {k: (6*t*t-6*t)*a[k] + (3*t*t-4*t+1)*u[k]
                    + (-6*t*t+6*t)*b[k] + (3*t*t-2*t)*v[k] for k in delta}
        return {k: (2*t**3-3*t*t+1)*a[k] + (t**3-2*t*t+t)*u[k]
                + (-2*t**3+3*t*t)*b[k] + (t**3-t*t)*v[k] for k in delta}

    def simplify(points, tolerance=60.0):
        if len(points) <= 2:
            return points
        ax, ay = points[0]
        bx, by = points[-1]
        dx, dy = bx - ax, by - ay
        denominator = dx * dx + dy * dy
        furthest_index, furthest_distance = 0, -1.0
        for index, (x, y) in enumerate(points[1:-1], 1):
            if denominator == 0:
                distance = math.hypot(x - ax, y - ay)
            else:
                t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / denominator))
                distance = math.hypot(x - (ax + t * dx), y - (ay + t * dy))
            if distance > furthest_distance:
                furthest_index, furthest_distance = index, distance
        if furthest_distance <= tolerance:
            return [points[0], points[-1]]
        return simplify(points[:furthest_index + 1], tolerance)[:-1] + simplify(points[furthest_index:], tolerance)

    def overview_chains(region):
        """Collapse same-region edge intervals exactly like the global overview base."""
        rows, adjacency = [], defaultdict(list)

        def endpoint_key(edge, edge_id, value):
            if value == 0:
                return ("node", edge["node0"])
            if value == 1:
                return ("node", edge["node1"])
            return ("cut", edge_id, round(value, 9))

        for segment in territories["segments"]:
            if segment["region"] != region:
                continue
            edge = edges[segment["edge_id"]]
            start, end = segment["start"], segment["end"]
            left = endpoint_key(edge, segment["edge_id"], start)
            right = endpoint_key(edge, segment["edge_id"], end)
            a, b = curve(edge, start), curve(edge, end)
            row = (left, right, [a["x"], a["y"]], [b["x"], b["y"]])
            row_id = len(rows)
            rows.append(row)
            adjacency[left].append(row_id)
            adjacency[right].append(row_id)

        terminal_nodes = {
            ("node", terminal["node_id"])
            for station in network.get("stations", [])
            for terminal in station.get("terminals", [])
            if isinstance(terminal.get("node_id"), int)
        }
        anchors = {key for key, links in adjacency.items() if len(links) != 2} | terminal_nodes
        visited, chains = set(), []

        def walk(start, first_row):
            current, row_id = start, first_row
            points = []
            while row_id not in visited:
                visited.add(row_id)
                left, right, a, b = rows[row_id]
                if current == left:
                    if not points:
                        points.append(a)
                    points.append(b)
                    current = right
                else:
                    if not points:
                        points.append(b)
                    points.append(a)
                    current = left
                if current in anchors:
                    break
                onward = [candidate for candidate in adjacency[current] if candidate not in visited]
                if not onward:
                    break
                row_id = onward[0]
            return simplify(points)

        for start in sorted(anchors, key=str):
            for row_id in adjacency.get(start, []):
                if row_id not in visited:
                    chain = walk(start, row_id)
                    if len(chain) >= 2:
                        chains.append(chain)
        for row_id, row in enumerate(rows):
            if row_id not in visited:
                chain = walk(row[0], row_id)
                if len(chain) >= 2:
                    chains.append(chain)
        return chains

    paths, extents = defaultdict(list), defaultdict(list)
    for segments in by_edge.values():
        for s in segments:
            edge, t0, t1 = edges[s["edge_id"]], s["start"], s["end"]
            a, b = curve(edge, t0), curve(edge, t1)
            u, v = curve(edge, t0, True), curve(edge, t1, True)
            control1 = {k: a[k] + u[k] * (t1-t0)/3 for k in a}
            control2 = {k: b[k] - v[k] * (t1-t0)/3 for k in b}
            points = [project(p) for p in (a, control1, control2, b)]
            if not all(math.isfinite(value) for p in points for value in p.values()):
                raise ValueError("nonfinite geometry")
            coords = [f'{p["x"]:.3f},{p["y"]:.3f}' for p in points]
            paths[s["region"]].append(f'M{coords[0]}C{coords[1]} {coords[2]} {coords[3]}')
            extents[s["region"]].extend(points)
    display_regions = []
    for key, region in regions.items():
        pts = extents[key]
        if not pts:
            raise ValueError("region contains no tracks")
        display_regions.append({"id": key, "name": region["name"], "color": region["color"],
                                "track_km": region["track_km"],
                                "station_count": sum(s["region"] == key for s in station_rows),
                                "overview_segments": overview_chains(key),
                                "bounds": {"min_x": min(p["x"] for p in pts), "max_x": max(p["x"] for p in pts),
                                           "min_y": min(p["y"] for p in pts), "max_y": max(p["y"] for p in pts)}})
    anchors = anchor_data["anchors"]
    if len({a["anchor_id"] for a in anchors}) != len(anchors):
        raise ValueError("duplicate coordinate anchor identity")
    # This compiler displays the surveyed draft only if the frozen coordinates still
    # coincide with its cuts. It cannot silently move the boundary with a new signal.
    remaining = list(territories["boundaries"])
    display_anchors = []
    for a in anchors:
        pair = {a["negative_region"], a["positive_region"]}
        if not pair <= set(regions):
            raise ValueError("anchor refers to an unknown region")
        match = next((b for b in remaining if set(b["regions"]) == pair and
                      math.dist([a["position"][k] for k in ("x", "y", "z")],
                                [b["position"][k] for k in ("x", "y", "z")]) < .5), None)
        if match is None:
            raise ValueError("survey cuts no longer match fixed anchors; repartition or calibrate first")
        remaining.remove(match)
        display_anchors.append({"anchor_id": a["anchor_id"], "label": a["label"], "point": project(a["position"]),
                                "position": a["position"], "regions": [a["negative_region"], a["positive_region"]],
                                "status": a.get("calibration", {}).get("status", "PENDING"),
                                "reference_stations": [r["name"] for r in a.get("corridor_references", [])]})
    if remaining:
        raise ValueError("survey contains unanchored cross-region cuts")
    return {"schema_version": 1, "status": "DRAFT", "save_id": save_id,
            "topology_generation": territories["topology_generation"], "topology_sha256": network_sha256,
            "generated_at": territories["created_at"], "coverage": territories["coverage"],
            "regions": display_regions, "anchors": display_anchors,
            "track_intervals": [[segment["edge_id"], segment["start"], segment["end"], segment["region"]]
                                for segment in territories["segments"]],
            "stations": [{"entity_id": s["entity_id"], "name": s["name"], "region": s["region"],
                          "point": project(s["center"]), "cargo": s.get("cargo", [])} for s in station_rows],
            "depots": territories["depots"],
            "isolated_tracks": [{"region": c["region"], "edge_count": len(c["edge_ids"]),
                                 "length_m": round(c["length_m"], 1), "point": project(c["center"])}
                                for c in territories.get("unseeded_components", [])]}
