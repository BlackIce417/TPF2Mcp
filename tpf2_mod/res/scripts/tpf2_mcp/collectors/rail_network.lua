-- One-shot, read-only export of the complete physical railway graph, rail
-- stations and line stop sequences. Kept outside the normal world snapshot so
-- a large map is never rebuilt on the two-second snapshot cadence.
local common = require "tpf2_mcp/collectors/common"

local M = {}
local gui_track_resources = {}

function M.set_track_resources(entries)
    gui_track_resources = {}
    for _, entry in ipairs(entries or {}) do
        if type(entry) == "table" and type(entry.track_type) == "number" and type(entry.file_name) == "string" then
            gui_track_resources[entry.track_type] = { file_name = entry.file_name, speed_limit_mps = entry.speed_limit_mps }
        end
    end
end

local function entity_id(value)
    if value == nil then return nil end
    return tonumber(tostring(value)) or (type(value) == "number" and value or nil)
end

local function number(value)
    return type(value) == "number" and value or nil
end

local function vec(value)
    if value == nil then return nil end
    local x, y, z = common.field(value, "x"), common.field(value, "y"), common.field(value, "z")
    if type(x) ~= "number" or type(y) ~= "number" then return nil end
    return { x = x, y = y, z = type(z) == "number" and z or 0 }
end

local function position_from_node(value)
    return vec(common.field(value, "position"))
        or vec(common.field(value, "pos"))
        or vec(common.field(common.field(value, "data"), "position"))
        or vec(common.field(common.field(value, "data"), "pos"))
end

local function bounds_for(entity, errors)
    local volume = common.safe_get_component(entity, "BOUNDING_VOLUME", errors)
    local bbox = common.field(volume, "bbox")
    local minimum = vec(common.field(bbox, "min")) or vec(common.field(bbox, "bbMin"))
    local maximum = vec(common.field(bbox, "max")) or vec(common.field(bbox, "bbMax"))
    if not minimum or not maximum then return nil, nil end
    return {
        x = (minimum.x + maximum.x) / 2,
        y = (minimum.y + maximum.y) / 2,
        z = (minimum.z + maximum.z) / 2,
    }, { min = minimum, max = maximum }
end

local function collect_tracks(errors)
    local nodes, edges, node_cache, track_resource_cache = {}, {}, {}, {}
    local track_resources_loaded = false
    local function load_track_resources()
        if track_resources_loaded then return end
        track_resources_loaded = true
        for index, detail in pairs(gui_track_resources) do track_resource_cache[index] = detail end
        if next(track_resource_cache) ~= nil then return end
        local repository = api and api.res and api.res.trackTypeRep
        local get_all = common.field(repository, "getAll")
        if get_all == nil then return end
        local ok, values = pcall(function() return get_all() end)
        if not ok or values == nil then return end
        for raw_index, file_name in pairs(values) do
            local index = tonumber(raw_index)
            if index ~= nil and type(file_name) == "string" then
                local detail, speed_limit = nil, nil
                local get = common.field(repository, "get")
                if get ~= nil then
                    local detail_ok, value = pcall(function() return get(index) end)
                    if detail_ok then detail = value end
                end
                if detail ~= nil and type(detail.speedLimit) == "number" then speed_limit = detail.speedLimit end
                track_resource_cache[index] = { file_name = file_name, speed_limit_mps = speed_limit }
            end
        end
    end
    local function track_resource(track_type)
        if type(track_type) ~= "number" then return nil end
        load_track_resources()
        if track_resource_cache[track_type] ~= nil then return track_resource_cache[track_type] or nil end
        track_resource_cache[track_type] = false
        return nil
    end
    local function base_node(raw)
        local id = entity_id(raw)
        if id == nil then return nil end
        if node_cache[id] ~= nil then return node_cache[id] or nil end
        local position = position_from_node(common.safe_get_component(raw, "BASE_NODE", errors))
        node_cache[id] = position or false
        return position
    end
    local ok, reason = common.safe_for_each_entity("BASE_EDGE_TRACK", function(edge_entity)
        local base = common.safe_get_component(edge_entity, "BASE_EDGE", errors)
        local track = common.safe_get_component(edge_entity, "BASE_EDGE_TRACK", errors)
        if base == nil or track == nil then return end
        local raw0, raw1 = common.field(base, "node0"), common.field(base, "node1")
        local id0, id1 = entity_id(raw0), entity_id(raw1)
        local p0, p1 = base_node(raw0), base_node(raw1)
        if id0 == nil or id1 == nil or p0 == nil or p1 == nil then return end
        nodes[id0], nodes[id1] = { entity_id = id0, position = p0 }, { entity_id = id1, position = p1 }
        local track_type = number(common.field(track, "trackType"))
        local track_resource_detail = track_resource(track_type)
        local track_resource_file = type(track_resource_detail) == "table" and track_resource_detail.file_name or nil
        local lower_resource_file = type(track_resource_file) == "string" and string.lower(track_resource_file) or ""
        edges[#edges + 1] = {
            entity_id = entity_id(edge_entity), node0 = id0, node1 = id1,
            tangent0 = vec(common.field(base, "tangent0")),
            tangent1 = vec(common.field(base, "tangent1")),
            track_type = track_type,
            track_resource_file = track_resource_file,
            speed_limit_mps = type(track_resource_detail) == "table" and track_resource_detail.speed_limit_mps or nil,
            freestyle_station_track = string.find(lower_resource_file, "lollo_freestyle_train_station", 1, true) ~= nil,
            catenary = common.field(track, "catenary"),
        }
    end, errors)
    if not ok then errors[#errors + 1] = { component = "BASE_EDGE_TRACK", error = tostring(reason) } end
    local ordered_nodes = {}
    for _, node in pairs(nodes) do ordered_nodes[#ordered_nodes + 1] = node end
    table.sort(ordered_nodes, function(a, b) return a.entity_id < b.entity_id end)
    table.sort(edges, function(a, b) return a.entity_id < b.entity_id end)
    return ordered_nodes, edges, nodes
end

local function terminal_key(group_id, station_index, terminal_index)
    return tostring(group_id) .. ":" .. tostring(station_index) .. ":" .. tostring(terminal_index)
end

local function alternative_terminals(stop)
    local result = {}
    for _, value in ipairs(common.sequence_values(common.field(stop, "alternativeTerminals"))) do
        local station_index = number(common.field(value, "station"))
        local terminal_index = number(common.field(value, "terminal"))
        if station_index ~= nil and terminal_index ~= nil then
            result[#result + 1] = { station_index = station_index, terminal_index = terminal_index }
        end
    end
    return result
end

local function collect_stations(track_nodes, errors)
    local stations, terminal_lookup = {}, {}
    local station_to_construction = nil
    local map_ok, map_or_error = pcall(function()
        return api.engine.system.streetConnectorSystem.getStation2ConstructionMap()
    end)
    if map_ok then
        station_to_construction = map_or_error
    else
        errors[#errors + 1] = { component = "STATION_TO_CONSTRUCTION_MAP", error = tostring(map_or_error) }
    end
    local ok, reason = common.safe_for_each_entity("STATION_GROUP", function(group_entity)
        local group_id = entity_id(group_entity)
        local group = common.safe_get_component(group_entity, "STATION_GROUP", errors)
        if group_id == nil or group == nil then return end
        local center, bounds = bounds_for(group_entity, errors)
        local terminals, child_ids, construction_ids, construction_files = {}, {}, {}, {}
        local seen_construction_ids, seen_construction_files = {}, {}
        for station_offset, station_entity in ipairs(common.sequence_values(common.field(group, "stations"))) do
            local station_index = station_offset - 1
            local station = common.safe_get_component(station_entity, "STATION", errors)
            local station_entity_id = entity_id(station_entity)
            child_ids[#child_ids + 1] = station_entity_id
            local construction_id, construction_file = nil, nil
            if station_to_construction ~= nil then
                local raw_construction_id = common.field(station_to_construction, station_entity)
                    or common.field(station_to_construction, station_entity_id)
                construction_id = entity_id(raw_construction_id)
                if construction_id ~= nil then
                    local construction = common.safe_get_component(construction_id, "CONSTRUCTION", errors)
                    construction_file = common.field(construction, "fileName")
                    if not seen_construction_ids[construction_id] then
                        construction_ids[#construction_ids + 1] = construction_id
                        seen_construction_ids[construction_id] = true
                    end
                    if type(construction_file) == "string" and not seen_construction_files[construction_file] then
                        construction_files[#construction_files + 1] = construction_file
                        seen_construction_files[construction_file] = true
                    end
                end
            end
            for terminal_offset, terminal in ipairs(common.sequence_values(common.field(station, "terminals"))) do
                local terminal_index = terminal_offset - 1
                local vehicle_node = common.field(terminal, "vehicleNodeId")
                local node_id = entity_id(common.field(vehicle_node, "entity"))
                local node = node_id and track_nodes[node_id] or nil
                if node then
                    local item = {
                        station_index = station_index, terminal_index = terminal_index,
                        station_entity_id = station_entity_id, node_id = node_id,
                        position = node.position, cargo = common.field(station, "cargo"),
                        tag = common.field(terminal, "tag"),
                        construction_entity_id = construction_id,
                        construction_file = type(construction_file) == "string" and construction_file or nil,
                    }
                    terminals[#terminals + 1] = item
                    terminal_lookup[terminal_key(group_id, station_index, terminal_index)] = item
                end
            end
        end
        if #terminals == 0 then return end
        table.sort(construction_ids)
        table.sort(construction_files)
        if center == nil then
            local sx, sy, sz = 0, 0, 0
            for _, terminal in ipairs(terminals) do
                sx, sy, sz = sx + terminal.position.x, sy + terminal.position.y, sz + terminal.position.z
            end
            center = { x = sx / #terminals, y = sy / #terminals, z = sz / #terminals }
        end
        stations[#stations + 1] = {
            entity_id = group_id,
            name = common.name_from_component(common.safe_get_component(group_entity, "NAME", errors)) or ("Station " .. tostring(group_id)),
            center = center, bounds = bounds, child_station_ids = child_ids,
            construction_entity_ids = construction_ids, construction_files = construction_files,
            terminals = terminals,
        }
    end, errors)
    if not ok then errors[#errors + 1] = { component = "STATION_GROUP", error = tostring(reason) } end
    table.sort(stations, function(a, b) return a.entity_id < b.entity_id end)
    return stations, terminal_lookup
end

local function collect_lines(terminal_lookup, errors)
    local lines = {}
    local ok, reason = common.safe_for_each_entity("LINE", function(line_entity)
        local line_id = entity_id(line_entity)
        local component = common.safe_get_component(line_entity, "LINE", errors)
        if line_id == nil or component == nil then return end
        local stops, all_rail = {}, true
        for offset, stop in ipairs(common.sequence_values(common.field(component, "stops"))) do
            local group_id = entity_id(common.field(stop, "stationGroup"))
            local station_index = number(common.field(stop, "station")) or 0
            local terminal_index = number(common.field(stop, "terminal")) or 0
            local terminal = terminal_lookup[terminal_key(group_id, station_index, terminal_index)]
            if terminal == nil then all_rail = false end
            stops[#stops + 1] = {
                sequence_index = offset - 1, station_group_id = group_id,
                station_index = station_index, terminal_index = terminal_index,
                alternative_terminals = alternative_terminals(stop),
                node_id = terminal and terminal.node_id or nil,
            }
        end
        if all_rail and #stops >= 2 then
            lines[#lines + 1] = {
                entity_id = line_id,
                name = common.name_from_component(common.safe_get_component(line_entity, "NAME", errors)) or ("Line " .. tostring(line_id)),
                stops = stops,
            }
        end
    end, errors)
    if not ok then errors[#errors + 1] = { component = "LINE", error = tostring(reason) } end
    table.sort(lines, function(a, b) return a.entity_id < b.entity_id end)
    return lines
end

local function collect_depots(lines, errors)
    local line_ids, depots_by_id, depots = {}, {}, {}
    for _, line in ipairs(lines) do line_ids[line.entity_id] = true end
    local vehicle_system = common.field(api.engine and api.engine.system, "transportVehicleSystem")
    local get_depot_vehicles = common.field(vehicle_system, "getDepotVehicles")
    local ok, reason = common.safe_for_each_entity("VEHICLE_DEPOT", function(depot_entity)
        local depot_id = entity_id(depot_entity)
        if depot_id == nil then return end
        local center, bounds = bounds_for(depot_entity, errors)
        local construction = common.safe_get_component(depot_entity, "CONSTRUCTION", errors)
        local construction_file = common.field(construction, "fileName")
        local lower_file = type(construction_file) == "string" and string.lower(construction_file) or ""
        local file_classifies_rail = (string.find(lower_file, "train", 1, true) ~= nil
            or string.find(lower_file, "rail", 1, true) ~= nil)
            and string.find(lower_file, "tram", 1, true) == nil
        local parked_vehicle_ids, parked_source = {}, "UNKNOWN"
        if get_depot_vehicles ~= nil then
            local call_ok, values = pcall(function() return get_depot_vehicles(depot_entity) end)
            if call_ok then
                for _, value in ipairs(common.sequence_values(values)) do
                    local vehicle_id = entity_id(value)
                    if vehicle_id ~= nil then parked_vehicle_ids[#parked_vehicle_ids + 1] = vehicle_id end
                end
                parked_source = "TRANSPORT_VEHICLE_SYSTEM_GET_DEPOT_VEHICLES"
            end
        end
        local item = {
            entity_id = depot_id,
            name = common.name_from_component(common.safe_get_component(depot_entity, "NAME", errors)) or ("Depot " .. tostring(depot_id)),
            center = center, bounds = bounds,
            construction_file = type(construction_file) == "string" and construction_file or nil,
            assigned_vehicle_ids = {}, rail_assigned_vehicle_ids = {},
            parked_vehicle_ids = parked_vehicle_ids,
            parked_vehicle_count_source = parked_source,
            rail_candidate = file_classifies_rail,
            rail_classification_source = file_classifies_rail and "CONSTRUCTION_FILE_CLASSIFIED" or "UNKNOWN",
        }
        depots[#depots + 1] = item
        depots_by_id[depot_id] = item
    end, errors)
    if not ok then errors[#errors + 1] = { component = "VEHICLE_DEPOT", error = tostring(reason) } end

    -- TRANSPORT_VEHICLE.depot is observed on active vehicles too.  Therefore
    -- this is an assignment count, not a claim that the vehicles are parked.
    common.safe_for_each_entity("TRANSPORT_VEHICLE", function(vehicle_entity)
        local vehicle = common.safe_get_component(vehicle_entity, "TRANSPORT_VEHICLE", errors)
        local depot = depots_by_id[entity_id(common.field(vehicle, "depot"))]
        if depot == nil then return end
        local vehicle_id = entity_id(vehicle_entity)
        depot.assigned_vehicle_ids[#depot.assigned_vehicle_ids + 1] = vehicle_id
        if line_ids[entity_id(common.field(vehicle, "line"))] then
            depot.rail_assigned_vehicle_ids[#depot.rail_assigned_vehicle_ids + 1] = vehicle_id
            depot.rail_candidate = true
            if depot.rail_classification_source == "UNKNOWN" then
                depot.rail_classification_source = "ASSIGNED_RAIL_LINE_VEHICLE"
            end
        end
    end, errors)
    table.sort(depots, function(a, b) return a.entity_id < b.entity_id end)
    return depots
end

function M.collect()
    local errors = {}
    local nodes, edges, node_map = collect_tracks(errors)
    local stations, terminal_lookup = collect_stations(node_map, errors)
    local lines = collect_lines(terminal_lookup, errors)
    local depots = collect_depots(lines, errors)
    return {
        schema_version = 1, status = "OK", source_status = "ENGINE_OBSERVED",
        nodes = nodes, edges = edges, stations = stations, lines = lines, depots = depots,
        counts = { nodes = #nodes, edges = #edges, stations = #stations, lines = #lines, depots = #depots },
        errors = errors, write_command_sent = false,
    }
end

return M
