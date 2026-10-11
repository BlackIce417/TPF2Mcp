"""Stateful, template-based congestion advice for the dispatch overview."""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Any


class CongestionAdvisor:
    def __init__(self, minimum_duration_seconds: float = 15.0, minimum_samples: int = 3):
        self.minimum_duration_seconds = minimum_duration_seconds
        self.minimum_samples = minimum_samples
        self._active: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _indexes(network: dict[str, Any]) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
        stations = {int(item["entity_id"]): item for item in network.get("stations", []) if isinstance(item.get("entity_id"), int)}
        lines = {int(item["entity_id"]): item for item in network.get("lines", []) if isinstance(item.get("entity_id"), int)}
        return stations, lines

    @staticmethod
    def _next_station(vehicle: dict[str, Any], line: dict[str, Any], stations: dict[int, dict[str, Any]]) -> tuple[int | None, str]:
        stops = line.get("stops") or []
        index = vehicle.get("stop_index")
        if not stops or not isinstance(index, int):
            return None, "未知车站"
        stop = stops[index % len(stops)]
        station_id = stop.get("station_group_id")
        station = stations.get(station_id, {}) if isinstance(station_id, int) else {}
        return station_id if isinstance(station_id, int) else None, str(station.get("name") or stop.get("station_name") or "未知车站")

    def sample(self, network: dict[str, Any], live: dict[str, Any], speed_profile: dict[str, Any] | None = None,
               now: float | None = None) -> list[dict[str, Any]]:
        now = time.time() if now is None else now
        stations, lines = self._indexes(network)
        waiting: dict[int, list[dict[str, Any]]] = defaultdict(list)
        platform_traffic: dict[int, set[int]] = defaultdict(set)
        for vehicle in live.get("vehicles", []):
            line = lines.get(vehicle.get("line_id"), {})
            station_id, station_name = self._next_station(vehicle, line, stations)
            if station_id is None:
                continue
            if vehicle.get("approaching_station") is True:
                platform_traffic[station_id].add(int(vehicle["entity_id"]))
                if isinstance(vehicle.get("speed_kmh"), (int, float)) and float(vehicle["speed_kmh"]) <= 8.0:
                    waiting[station_id].append({**vehicle, "station_name": station_name, "line": line})

        observed: dict[str, dict[str, Any]] = {}
        for station_id, vehicles in waiting.items():
            if len(vehicles) < 2:
                continue
            name = vehicles[0]["station_name"]
            observed[f"throat:{station_id}"] = {
                "template": "STATION_THROAT_CONGESTION", "template_label": "咽喉拥堵", "severity": "ACTION",
                "title": f"{name}站咽喉持续排队",
                "reason": f"检测到 {len(vehicles)} 列进站列车低于 8 km/h 或停车等待",
                "required_action": f"建议增加{name}站进站径路、调整到发间隔或升级低速道岔",
                "station_id": station_id, "station_name": name, "vehicle_ids": sorted(v["entity_id"] for v in vehicles),
            }
        for station_id, vehicle_ids in platform_traffic.items():
            terminal_count = max(1, len(stations.get(station_id, {}).get("terminals", [])))
            ratio = len(vehicle_ids) / terminal_count
            if len(vehicle_ids) >= 2 and ratio >= .8:
                name = str(stations.get(station_id, {}).get("name") or f"车站 {station_id}")
                observed[f"platform:{station_id}"] = {
                    "template": "PLATFORM_SATURATION", "template_label": "站台饱和", "severity": "REVIEW",
                    "title": f"{name}站台能力接近饱和",
                    "reason": f"{len(vehicle_ids)} 列接近列车对应 {terminal_count} 条站台到发线，压力比 {ratio:.1f}",
                    "required_action": f"建议扩建{name}站站台或调整列车到发间隔",
                    "station_id": station_id, "station_name": name,
                }
        diagnostics = {item.get("line_id"): item for item in live.get("line_diagnostics", [])}
        occupancy = {item.get("line_id"): item for item in live.get("line_block_occupancy", [])}
        for line_id, diagnostic in diagnostics.items():
            block_pressure = occupancy.get(line_id, {})
            high_occupancy = (int(block_pressure.get("occupied_blocks") or 0) >= 3
                              and float(block_pressure.get("occupancy_ratio") or 0) >= .25)
            if diagnostic.get("diagnosis") != "POSSIBLE_BUNCHING" and not high_occupancy:
                continue
            line = lines.get(line_id, {})
            stopped = [v for values in waiting.values() for v in values if v.get("line_id") == line_id]
            if len(stopped) < 2 and not high_occupancy:
                continue
            stop_names = []
            for stop in line.get("stops", [])[:2]:
                station = stations.get(stop.get("station_group_id"), {})
                stop_names.append(str(station.get("name") or stop.get("station_name") or "未知车站"))
            corridor = "—".join(stop_names) if len(stop_names) == 2 else str(line.get("name") or f"线路 {line_id}")
            observed[f"section:{line_id}"] = {
                "template": "SECTION_CONGESTION", "template_label": "区间拥堵", "severity": "ACTION",
                "title": f"{corridor}区间拥堵严重",
                "reason": (f"同线 {len(stopped)} 列低速等待，最小车距 {diagnostic.get('minimum_spacing_m')} m；"
                           f"闭塞占用 {block_pressure.get('occupied_blocks', 0)}/{block_pressure.get('total_blocks', 0)}"
                           f"（{round(float(block_pressure.get('occupancy_ratio') or 0) * 100)}%）"),
                "required_action": "建议增加通过线、调整交路或降低进入该区间的列车流量",
                "line_id": line_id, "line_name": line.get("name"), "corridor": corridor,
            }
        if speed_profile:
            turnout_by_station: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for turnout in speed_profile.get("turnouts", []):
                if turnout.get("station_name") and float(turnout.get("side_speed_kmh") or 999) <= 45:
                    turnout_by_station[str(turnout["station_name"])].append(turnout)
            for station_id, vehicles in waiting.items():
                name = vehicles[0]["station_name"]
                if name in turnout_by_station:
                    observed[f"turnout:{station_id}"] = {
                        "template": "TURNOUT_SPEED_BOTTLENECK", "template_label": "道岔瓶颈", "severity": "REVIEW",
                        "title": f"{name}站侧向道岔限速成为瓶颈",
                        "reason": f"保守侧向限速 45 km/h；当前有 {len(vehicles)} 列进站等待",
                        "required_action": "建议核实道岔号数，改造为更大号码道岔或调整直侧线分工",
                        "station_id": station_id, "station_name": name,
                    }

        for key in list(self._active):
            if key not in observed:
                del self._active[key]
        result = []
        for key, item in observed.items():
            state = self._active.setdefault(key, {"first_seen": now, "samples": 0})
            state["samples"] += 1
            state["last_seen"] = now
            duration = max(0.0, now - state["first_seen"])
            if state["samples"] >= self.minimum_samples and duration >= self.minimum_duration_seconds:
                result.append({"created_at": now, **item, "evidence_key": key,
                               "duration_seconds": round(duration, 1), "sample_count": state["samples"],
                               "automation_status": "INFRASTRUCTURE_REVIEW"})
        return result
