"""Core MCP tool definitions."""
_TRAIN_CONTROL_TOOLS = [
    {
        "name": "get_train_control_snapshot",
        "title": "Get Train Control Snapshot",
        "description": "Read Loader train motion and dynamic topology occupancy. Each train includes dispatch with topology_id, observed occupied_section_ids (physical track_resource_id shared by reverse arcs), occupied_station_ids (station wrapper node IDs), head/tail/center section and confidence. Missing full-body coverage is PARTIAL; unobserved sections remain UNKNOWN, never assumed clear. sampled_at is Python observation time; sample_time_us is the source simulation clock. Optional display_name filters scope; optional include_parts returns carriage wrappers.",
        "inputSchema": {"type": "object", "properties": {
            "display_name": {"type": "string", "minLength": 1, "maxLength": 256},
            "include_parts": {"type": "boolean", "default": False},
        }, "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "schema_version": {"type": "integer"}, "sample_sequence": {"type": "integer"},
            "sample_time_us": {"type": "integer"}, "train_count": {"type": "integer"},
            "telemetry": {"type": "object"}, "trains": {"type": "array", "items": {"type": "object"}},
            "topology_id": {"type": ["string", "null"]},
            "observed_at": {"type": "number"},
            "occupancy_complete": {"type": "boolean"},
            "occupancy_scope": {"type": "string", "enum": ["FULL_FLEET", "FILTERED_TRAIN"]},
            "section_states": {"type": "array", "items": {"type": "object", "properties": {
                "section_id": {"type": "integer"},
                "directed_edge_ids": {"type": "array", "items": {"type": "integer"}},
                "occupying_trains": {"type": "array", "items": {"type": "object"}},
                "status": {"type": "string", "enum": ["OCCUPIED", "CLEAR", "UNKNOWN"]},
            }, "required": ["section_id", "directed_edge_ids", "occupying_trains", "status"]}},
        }, "required": ["schema_version", "sample_sequence", "train_count", "telemetry", "trains"]},
    },
    {
        "name": "set_train_speed_limit",
        "title": "Set Train Speed Limit",
        "description": "Apply a short-lived Controller speed rule to one train's verified forward route window. Read a fresh snapshot first. Requires the exact confirmation APPLY_SPEED_LIMIT:<command_id>; retries with the same command_id are deduplicated.",
        "inputSchema": {"type": "object", "properties": {
            "command_id": {"type": "string", "pattern": "^[A-Za-z0-9._:-]{1,128}$"},
            "display_name": {"type": "string", "minLength": 1, "maxLength": 256},
            "speed_kmh": {"type": "number", "minimum": 0, "maximum": 500, "description": "0 requests a temporary hold; positive values request a speed limit."},
            "reason": {"type": "object", "oneOf": [
                {"properties": {"kind": {"const": "FRONT_TRAIN_TOO_CLOSE"},
                                "distance_threshold_m": {"type": "number", "exclusiveMinimum": 0}},
                 "required": ["kind", "distance_threshold_m"], "additionalProperties": False},
                {"properties": {"kind": {"const": "WAIT_ENTRY_SIGNAL"},
                                "waiting_for_train": {"type": "string", "minLength": 1, "maxLength": 256}},
                 "required": ["kind", "waiting_for_train"], "additionalProperties": False}
            ], "description": "Dispatch justification: front train closer than threshold, or waiting for entry signal while yielding to a named train. This is caller-provided reasoning, not measured evidence."},
            "lookahead_edges": {"type": "integer", "minimum": 1, "maximum": 192, "default": 24},
            "expires_in_seconds": {"type": "integer", "minimum": 5, "maximum": 120, "default": 20},
            "confirmation": {"type": "string", "description": "Exact value APPLY_SPEED_LIMIT:<command_id>."},
        }, "required": ["command_id", "display_name", "speed_kmh", "confirmation", "reason"], "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "schema_version": {"type": "integer"}, "command_id": {"type": "string"},
            "display_name": {"type": "string"}, "vehicle_id": {"type": "integer"},
            "speed_kmh": {"type": "number"}, "expires_at": {"type": "integer"},
            "status": {"type": "string"}, "result": {"type": "string"},
        }, "required": ["schema_version", "command_id", "display_name", "vehicle_id", "speed_kmh", "expires_at", "status", "result"]},
    },
    {
        "name": "cancel_train_speed_limit",
        "title": "Cancel Train Speed Limit",
        "description": "Cancel one speed rule created by set_train_speed_limit. Requires the exact confirmation CANCEL_SPEED_LIMIT:<command_id> and is safe to retry.",
        "inputSchema": {"type": "object", "properties": {
            "command_id": {"type": "string", "pattern": "^[A-Za-z0-9._:-]{1,128}$"},
            "confirmation": {"type": "string", "description": "Exact value CANCEL_SPEED_LIMIT:<command_id>."},
        }, "required": ["command_id", "confirmation"], "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "schema_version": {"type": "integer"}, "command_id": {"type": "string"},
            "display_name": {"type": "string"}, "result": {"type": "string"},
        }, "required": ["schema_version", "command_id", "result"]},
    },
    {
        "name": "get_active_train_controls",
        "title": "Get Active Train Controls",
        "description": "List unexpired speed controls issued by this MCP server process.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "schema_version": {"type": "integer"}, "active_count": {"type": "integer"},
            "controls": {"type": "array", "items": {"type": "object"}},
        }, "required": ["schema_version", "active_count", "controls"]},
    },
]

_RUNTIME_STATUS_TOOL = {
    "name": "get_bridge_status",
    "title": "Get Native Runtime Status",
    "description": "Report the current tpf2_loader shared-memory telemetry and tpf2_controller command-channel health. This does not inspect the retired heartbeat.json file bridge.",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    "outputSchema": {"type": "object", "properties": {
        "schema_version": {"type": "integer"},
        "transport_generation": {"type": "string"},
        "loader": {"type": "object"},
        "controller": {"type": "object"},
        "legacy_file_bridge": {"type": "object"},
    }, "required": ["schema_version", "transport_generation", "loader", "controller", "legacy_file_bridge"]},
}
