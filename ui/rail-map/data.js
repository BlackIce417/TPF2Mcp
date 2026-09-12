window.STATION_MAP_DATA = {
  "schema_version": 1,
  "snapshot_sequence": 57,
  "snapshot_timestamp": 1789058013,
  "diagram_type": "station_group_line_neighborhood_not_physical_track_plan",
  "focus_station": {
    "station_id": 552273,
    "name": "Chiasso",
    "child_station_count": 1
  },
  "terminals": [
    {
      "terminal_id": 0,
      "station_indices": [
        0
      ],
      "line_ids": [
        583098,
        587218,
        649098
      ],
      "usage": "UNKNOWN",
      "platform_length_m": null
    },
    {
      "terminal_id": 1,
      "station_indices": [
        0
      ],
      "line_ids": [
        583098,
        587218
      ],
      "usage": "UNKNOWN",
      "platform_length_m": null
    },
    {
      "terminal_id": 2,
      "station_indices": [
        0
      ],
      "line_ids": [
        1363778
      ],
      "usage": "UNKNOWN",
      "platform_length_m": null
    },
    {
      "terminal_id": 3,
      "station_indices": [
        0
      ],
      "line_ids": [
        1363778
      ],
      "usage": "UNKNOWN",
      "platform_length_m": null
    }
  ],
  "lines": [
    {
      "line_id": 583098,
      "name": "线路 85",
      "frequency_seconds": 2195.6000866745,
      "throughput": 80,
      "vehicle_count": 1
    },
    {
      "line_id": 587218,
      "name": "线路 64",
      "frequency_seconds": 1065.4000082851,
      "throughput": 165,
      "vehicle_count": 1
    },
    {
      "line_id": 649098,
      "name": "线路 70",
      "frequency_seconds": 910.39991894305,
      "throughput": 193,
      "vehicle_count": 1
    },
    {
      "line_id": 1363778,
      "name": "线路 92",
      "frequency_seconds": 309.60003090978,
      "throughput": 297,
      "vehicle_count": 3
    }
  ],
  "neighbors": [
    {
      "station_id": 7251,
      "name": "Como"
    },
    {
      "station_id": 530373,
      "name": "Mendrisio"
    },
    {
      "station_id": 557702,
      "name": "Como"
    },
    {
      "station_id": 564245,
      "name": "Stabio"
    },
    {
      "station_id": 928070,
      "name": "Paradiso & Lugano"
    }
  ],
  "links": [
    {
      "line_id": 583098,
      "neighbor_station_id": 557702,
      "route_side": "next"
    },
    {
      "line_id": 583098,
      "neighbor_station_id": 557702,
      "route_side": "previous"
    },
    {
      "line_id": 583098,
      "neighbor_station_id": 564245,
      "route_side": "next"
    },
    {
      "line_id": 583098,
      "neighbor_station_id": 564245,
      "route_side": "previous"
    },
    {
      "line_id": 587218,
      "neighbor_station_id": 530373,
      "route_side": "next"
    },
    {
      "line_id": 587218,
      "neighbor_station_id": 530373,
      "route_side": "previous"
    },
    {
      "line_id": 587218,
      "neighbor_station_id": 557702,
      "route_side": "next"
    },
    {
      "line_id": 587218,
      "neighbor_station_id": 557702,
      "route_side": "previous"
    },
    {
      "line_id": 649098,
      "neighbor_station_id": 557702,
      "route_side": "next"
    },
    {
      "line_id": 649098,
      "neighbor_station_id": 557702,
      "route_side": "previous"
    },
    {
      "line_id": 1363778,
      "neighbor_station_id": 7251,
      "route_side": "previous"
    },
    {
      "line_id": 1363778,
      "neighbor_station_id": 928070,
      "route_side": "next"
    },
    {
      "line_id": 1363778,
      "neighbor_station_id": 928070,
      "route_side": "previous"
    }
  ],
  "availability": {
    "terminal_usage_passenger_or_cargo": false,
    "platform_length": false,
    "physical_track_count": false,
    "switch_topology": false,
    "coordinates": false
  },
  "limitations": [
    "Terminals are only those observed in existing line stops; this is not a complete physical platform inventory.",
    "The current snapshot does not expose passenger/cargo terminal use, platform length, track geometry, coordinates, or switches.",
    "Links mean line-stop adjacency, not physical rails or track reachability."
  ]
};
