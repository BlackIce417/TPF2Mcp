"""Export a read-only station/line neighborhood for the standalone SVG UI."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from tpf2_mcp.bridge import BridgeClient
from tpf2_mcp.snapshot import SnapshotIndex


def safe_line_name(line: dict) -> str:
    name = line.get("name")
    if isinstance(name, str) and "�" not in name:
        return name
    match = re.search(r"(\d+)\s*$", name or "")
    return f"Line {match.group(1)}" if match else f"Line entity {line['entity_id']}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--station-id", type=int, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()

    index = SnapshotIndex(BridgeClient(timeout_seconds=20).game_state(force_refresh=True))
    station = index.station_by_id.get(args.station_id)
    if station is None:
        raise SystemExit(f"station group {args.station_id} not found")

    line_rows: dict[int, dict] = {}
    terminal_rows: dict[int, dict] = {}
    neighbor_rows: dict[int, dict] = {}
    links: set[tuple[int, int, str]] = set()
    for line in index.line_by_id.values():
        raw_stops = line.get("raw_stops", [])
        occurrences = [position for position, stop in enumerate(raw_stops) if stop.get("station_id") == args.station_id]
        if not occurrences:
            continue
        line_id = line["entity_id"]
        line_rows[line_id] = {
            "line_id": line_id,
            "name": safe_line_name(line),
            "frequency_seconds": line.get("frequency_seconds"),
            "throughput": line.get("throughput"),
            "vehicle_count": len(index.vehicles_by_line.get(line_id, [])),
        }
        for position in occurrences:
            stop = raw_stops[position]
            terminal_id = stop.get("terminal_id")
            if isinstance(terminal_id, int):
                row = terminal_rows.setdefault(terminal_id, {"terminal_id": terminal_id, "station_indices": set(), "line_ids": set()})
                if isinstance(stop.get("station_index"), int):
                    row["station_indices"].add(stop["station_index"])
                row["line_ids"].add(line_id)
            for side, adjacent_position in (("previous", position - 1), ("next", position + 1)):
                if 0 <= adjacent_position < len(raw_stops):
                    neighbor_id = raw_stops[adjacent_position].get("station_id")
                    neighbor = index.station_by_id.get(neighbor_id)
                    if isinstance(neighbor_id, int) and neighbor_id != args.station_id and neighbor:
                        neighbor_rows[neighbor_id] = {"station_id": neighbor_id, "name": neighbor.get("name") or f"Station {neighbor_id}"}
                        links.add((line_id, neighbor_id, side))

    terminals = [{"terminal_id": row["terminal_id"], "station_indices": sorted(row["station_indices"]), "line_ids": sorted(row["line_ids"]), "usage": "UNKNOWN", "platform_length_m": None} for row in terminal_rows.values()]
    result = {
        "schema_version": 1,
        "snapshot_sequence": index.state.get("sequence"),
        "snapshot_timestamp": index.state.get("timestamp"),
        "diagram_type": "station_group_line_neighborhood_not_physical_track_plan",
        "focus_station": {"station_id": args.station_id, "name": station.get("name"), "child_station_count": station.get("station_count")},
        "terminals": sorted(terminals, key=lambda row: row["terminal_id"]),
        "lines": sorted(line_rows.values(), key=lambda row: row["line_id"]),
        "neighbors": sorted(neighbor_rows.values(), key=lambda row: row["station_id"]),
        "links": [{"line_id": line_id, "neighbor_station_id": neighbor_id, "route_side": side} for line_id, neighbor_id, side in sorted(links)],
        "availability": {"terminal_usage_passenger_or_cargo": False, "platform_length": False, "physical_track_count": False, "switch_topology": False, "coordinates": False},
        "limitations": [
            "Terminals are only those observed in existing line stops; this is not a complete physical platform inventory.",
            "The current snapshot does not expose passenger/cargo terminal use, platform length, track geometry, coordinates, or switches.",
            "Links mean line-stop adjacency, not physical rails or track reachability.",
        ],
    }
    args.output_directory.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    (args.output_directory / "local-station.json").write_text(encoded, encoding="utf-8")
    (args.output_directory / "data.js").write_text("window.STATION_MAP_DATA = " + encoded + ";\n", encoding="utf-8")
    print(json.dumps({"station_id": args.station_id, "station_name": station.get("name"), "lines": len(line_rows), "observed_terminals": len(terminals), "neighbors": len(neighbor_rows), "snapshot_sequence": result["snapshot_sequence"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
