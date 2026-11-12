local config = require "tpf2_mcp/config/settings"
local json = require "tpf2_mcp/codecs/json"
local common = require "tpf2_mcp/collectors/common"
local town_collector = require "tpf2_mcp/collectors/town"
local industry_collector = require "tpf2_mcp/collectors/industry"
local station_collector = require "tpf2_mcp/collectors/station"
local line_collector = require "tpf2_mcp/collectors/line"
local vehicle_collector = require "tpf2_mcp/collectors/vehicle"
local company_collector = require "tpf2_mcp/collectors/company"
local operations_probe = require "tpf2_mcp/collectors/probes/operations_probe"
local cargo_collector = require "tpf2_mcp/collectors/cargo"
local ui_source_probe = require "tpf2_mcp/collectors/probes/ui_source_probe"
local context_probe = require "tpf2_mcp/collectors/probes/context_probe"
local dynamic_probe = require "tpf2_mcp/collectors/probes/dynamic_probe"
local write_api_probe = require "tpf2_mcp/collectors/probes/write_api_probe"
local vehicle_write_probe = require "tpf2_mcp/collectors/probes/vehicle_write_probe"
local line_raw_probe = require "tpf2_mcp/collectors/probes/line_raw_probe"
local line_creation_probe = require "tpf2_mcp/collectors/probes/line_creation_probe"
local api_inventory = require "tpf2_mcp/collectors/probes/api_inventory"
local station_geometry = require "tpf2_mcp/collectors/station_geometry"
local rail_network = require "tpf2_mcp/collectors/rail_network"
local operational_telemetry = require "tpf2_mcp/collectors/operational_telemetry"
local simulation_collector = require "tpf2_mcp/collectors/simulation"
local line_demand = require "tpf2_mcp/collectors/line_demand"

local M = {}
local cached_snapshot = nil
local cached_at = 0
local cached_station_geometry = nil
local cached_rail_network = nil

function M.reset_session()
    cached_snapshot, cached_at = nil, 0
    cached_station_geometry, cached_rail_network = nil, nil
end

local function now()
    return os and os.time and os.time() or 0
end

function M.snapshot(sequence, force_refresh)
    local current_time = now()
    if not force_refresh and cached_snapshot then
        return cached_snapshot
    end
    local game = { status = "available", api_status = "runtime_verified" }
    local api_ok, api_error = pcall(function()
        game.world_entity = tostring(api.engine.util.getWorld())
        game.player_entity = tostring(api.engine.util.getPlayer())
    end)
    if not api_ok then
        game.status = "unavailable"
        game.api_status = "runtime_error"
        game.reason = tostring(api_error)
    end
    local towns, town_status = town_collector.collect()
    local industries, industry_status = industry_collector.collect()
    local stations, station_status = station_collector.collect()
    local lines, line_status = line_collector.collect()
    local vehicles, vehicle_status = vehicle_collector.collect()
    local companies, company_status = company_collector.collect()
    local cargo_types, cargo_status = cargo_collector.collect()
    local simulation, simulation_status = simulation_collector.collect()
    local snapshot = {
        -- File bridge protocol stays at v1. This is the independently versioned
        -- normalized world-snapshot contract.
        schema_version = tonumber(config.snapshot_schema_version) or 5,
        sequence = sequence,
        timestamp = current_time,
        metadata = {
            refresh_policy = "ON_DEMAND_ASSETS",
            session_id = operational_telemetry.session_id(),
            sequence = sequence,
            timestamp = current_time,
            field_sources = {
                cargo_types = "api.res.cargoTypeRep.getAll",
                ["vehicles[].capacity_total"] = "api.engine.component.TRANSPORT_VEHICLE.config.capacities",
                ["lines[].frequency_seconds"] = "game.interface.getEntity(line_id).frequency (1 / raw value)",
                ["lines[].throughput"] = "game.interface.getEntity(line_id).rate",
            },
            collector_status = { towns = town_status, industries = industry_status, stations = station_status, lines = line_status, vehicles = vehicle_status, company = company_status, cargo_types = cargo_status, simulation = simulation_status },
        },
        game = game, simulation = simulation,
        company = companies[1] or json.object({}), towns = towns, industries = industries, stations = stations, lines = lines, vehicles = vehicles, cargo_types = cargo_types,
    }
    cached_snapshot = snapshot
    cached_at = current_time
    return snapshot
end

-- Reuse the lines already read for command verification. Static assets keep
-- their original capture timestamp and are not recollected after a platform edit.
function M.update_line_catalog(lines, status, sequence)
    if cached_snapshot == nil or status.ok ~= true then return nil end
    if cached_snapshot.metadata.session_id ~= operational_telemetry.session_id() then return nil end
    cached_snapshot.lines = lines
    cached_snapshot.sequence = sequence
    cached_snapshot.metadata.sequence = sequence
    cached_snapshot.metadata.line_configuration_updated_at = now()
    cached_snapshot.metadata.collector_status.lines = status
    return cached_snapshot
end

function M.company_probe()
    local ok, result = pcall(company_collector.probe)
    if ok then return result end
    return { error = tostring(result) }
end

function M.write_api_probe()
    local ok, value = pcall(write_api_probe.probe)
    return ok and value or { error = tostring(value), write_command_sent = false }
end

function M.vehicle_write_probe()
    local ok, value = pcall(vehicle_write_probe.probe)
    return ok and value or { error = tostring(value), write_command_sent = false }
end

function M.semantic_probe()
    local function run(collector)
        local ok, value = pcall(collector.probe)
        return ok and value or { error = tostring(value) }
    end
    return { lines = run(line_collector), vehicles = run(vehicle_collector), industries = run(industry_collector) }
end

function M.operations_probe()
    local ok, result = pcall(operations_probe.all)
    return ok and result or { error = tostring(result) }
end

function M.ui_source_probe()
    local ok, result = pcall(ui_source_probe.collect)
    return ok and result or { error = tostring(result) }
end

function M.context_probe()
    local ok, result = pcall(context_probe.collect)
    return ok and result or { context = "game_script.update", error = tostring(result) }
end

function M.dynamic_probe()
    local ok, result = pcall(dynamic_probe.all)
    return ok and result or { error = tostring(result) }
end

function M.line_raw_probe()
    local ok, result = pcall(line_raw_probe.collect)
    return ok and result or { error = tostring(result), write_command_sent = false }
end

function M.line_creation_probe()
    local ok, result = pcall(line_creation_probe.collect)
    return ok and result or { error = tostring(result), write_command_sent = false }
end

function M.api_type_inventory() local ok, value = pcall(api_inventory.type_inventory); return ok and value or { error = tostring(value) } end
function M.api_command_inventory() local ok, value = pcall(api_inventory.command_inventory); return ok and value or { error = tostring(value) } end
function M.station_geometry()
    if cached_station_geometry ~= nil then return cached_station_geometry end
    local ok, value = pcall(station_geometry.collect, 552273, 1200)
    cached_station_geometry = ok and value or { status = "ERROR", error = tostring(value), write_command_sent = false }
    return cached_station_geometry
end

function M.rail_network()
    if cached_rail_network ~= nil then return cached_rail_network end
    local ok, value = pcall(rail_network.collect)
    cached_rail_network = ok and value or { status = "ERROR", error = tostring(value), write_command_sent = false }
    return cached_rail_network
end

function M.invalidate_rail_network()
    cached_rail_network = nil
end

function M.set_track_resources(entries)
    rail_network.set_track_resources(entries)
    cached_rail_network = nil
end

function M.operational_telemetry(section)
    local ok, value = pcall(operational_telemetry.collect, section)
    return ok and value or { status = "ERROR", error = tostring(value), write_command_sent = false }
end

function M.line_demand(line_id, maximum)
    local started, started_at = common.clock(), now()
    local ok, value = pcall(line_demand.collect, line_id, maximum)
    if not ok then value = { status = "ERROR", line_id = line_id, error = tostring(value) } end
    value.session_id, value.generated_at = operational_telemetry.session_id(), now()
    -- Read the stop vector in the same engine callback as the demand. A
    -- 30-second catalog cannot safely resolve OD indices after a route edit.
    local errors = {}
    local line = common.safe_get_component(line_id, "LINE", errors)
    local metadata = { line_id = line_id, stops = {}, errors = errors }
    metadata.display_name = common.name_from_component(common.safe_get_component(line_id, "NAME", errors))
    for offset, stop in ipairs(common.sequence_values(common.field(line, "stops"))) do
        metadata.stops[#metadata.stops + 1] = {
            stop_index = offset - 1,
            station_id = common.entity_id(common.field(stop, "stationGroup")),
            station_index = common.field(stop, "station"),
            terminal_index = common.field(stop, "terminal"),
        }
    end
    metadata.available = line ~= nil and #errors == 0
    value.line_metadata = metadata
    value.collection_started_at, value.duration_ms = started_at, (common.clock() - started) * 1000
    return value
end

function M.station_demand_lines(station_id)
    local errors = {}
    local station = common.safe_get_component(station_id, "STATION_GROUP", errors)
    if station == nil or #errors > 0 then return { status = "ERROR", error = "STATION_NOT_FOUND" } end
    local lines, status = line_collector.collect()
    if status.ok ~= true then return { status = "ERROR", error = "LINE_COLLECTION_INCOMPLETE", collector_status = status } end
    local connected = {}
    for _, line in ipairs(lines) do
        for _, stop in ipairs(line.stops or {}) do
            if stop.station_id == station_id then connected[#connected + 1] = line; break end
        end
    end
    return { session_id = operational_telemetry.session_id(), generated_at = now(),
        station_id = station_id, lines = connected }
end

function M.vehicle_dispatch_state(vehicle_id, maximum)
    local telemetry = M.operational_telemetry("vehicles_live")
    local live = nil
    for _, vehicle in ipairs(telemetry.vehicles or {}) do
        if vehicle.entity_id == vehicle_id then live = vehicle break end
    end
    if live == nil then return { status = "ENTITY_NOT_FOUND", vehicle_id = vehicle_id } end
    return {
        schema_version = 1,
        source_status = "ENGINE_OBSERVED_DYNAMIC_WITH_CLASSIFIED_LOAD",
        vehicle = live,
        demand = type(live.line_id) == "number" and M.line_demand(live.line_id, maximum) or nil,
    }
end

return M
