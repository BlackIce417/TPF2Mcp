-- Sectioned discovery package for signalling, moving vehicles, station demand,
-- and simulation time.  The desktop runner still exposes one unified command,
-- but each section is collected and serialized in a separate game update.  A
-- previous all-in-one callback caused a native TPF2 crash on a large save.
local common = require "tpf2_mcp/collectors/common"

local M = {}

local COMPONENTS = {
    "SIGNAL", "SIGNAL_LIST", "BASE_EDGE", "BASE_EDGE_TRACK", "BASE_NODE", "TRANSPORT_VEHICLE",
    "MOVE_PATH", "SIM_ENTITY_MOVING", "SIM_ENTITY_AT_TERMINAL", "SIM_ENTITY_AT_VEHICLE",
    "SIM_CARGO_AT_TERMINAL", "SIM_PERSON_AT_TERMINAL", "GAME_TIME", "GAME_SPEED",
    "TICK_EPOCH", "BOUNDING_VOLUME", "MODEL_INSTANCE_LIST", "STATION", "STATION_GROUP",
}

local SIGNAL_FIELDS = { "edge", "edgeId", "edgePos", "position", "pathPos", "dir", "direction", "type", "signalType", "state", "oneWay", "modelId" }
local EDGE_OBJECT_FIELDS = { "entity", "id", "model", "modelId", "edge", "edgeId", "edgePos", "position", "param", "left", "oneWay", "signal" }
local VEHICLE_FIELDS = { "line", "state", "depot", "transportMode", "mode", "vehicleType", "speed", "velocity", "position", "path", "movePath", "edge", "edgeId", "edgePos", "pathPos", "stopIndex", "currentStop", "nextStop", "targetStation", "waitingTime", "arrivalTime", "departureTime" }
local INFO_FIELDS = { "state", "speed", "velocity", "position", "path", "movePath", "edge", "edgeId", "edgePos", "pathPos", "section", "distance", "stopIndex", "currentStop", "nextStop", "targetStation", "waitingTime", "arrivalTime", "departureTime", "cargoInfos" }
local MOVE_FIELDS = { "path", "pathPos", "edge", "edgeId", "edgePos", "position", "dir", "direction", "speed", "velocity", "distance", "segment", "section", "state" }
local PATH_EDGE_FIELDS = { "entity", "edge", "edgeId", "id", "dir", "direction", "length", "offset", "param", "position" }

local function entity_id(value)
    if value == nil then return nil end
    return tonumber(tostring(value)) or (type(value) == "number" and value or nil)
end

local function vec(value)
    if value == nil then return nil end
    local x, y, z = common.field(value, "x"), common.field(value, "y"), common.field(value, "z")
    if type(x) ~= "number" or type(y) ~= "number" then return nil end
    return { x = x, y = y, z = type(z) == "number" and z or 0 }
end

local function bounds_for(entity, errors)
    if entity == nil then return nil, nil end
    local volume = common.safe_get_component(entity, "BOUNDING_VOLUME", errors)
    local bbox = common.field(volume, "bbox")
    local minimum = vec(common.field(bbox, "min")) or vec(common.field(bbox, "bbMin"))
    local maximum = vec(common.field(bbox, "max")) or vec(common.field(bbox, "bbMax"))
    if minimum == nil or maximum == nil then return nil, nil end
    return {
        x = (minimum.x + maximum.x) / 2,
        y = (minimum.y + maximum.y) / 2,
        z = (minimum.z + maximum.z) / 2,
    }, { min = minimum, max = maximum }
end

local function model_name(model_id)
    local repository = api and api.res and api.res.modelRep
    local get_name = common.field(repository, "getName")
    if type(get_name) ~= "function" or type(model_id) ~= "number" then return nil end
    local ok, value = pcall(function() return get_name(model_id) end)
    return ok and type(value) == "string" and value or nil
end

local function model_instances_for(entity, errors)
    local component = common.safe_get_component(entity, "MODEL_INSTANCE_LIST", errors)
    if component == nil then return {} end
    local sequence = common.field(component, "models") or common.field(component, "modelInstances") or common.field(component, "instances") or component
    local result = {}
    for _, instance in ipairs(common.sequence_values(sequence)) do
        if #result >= 8 then break end
        local raw_id = common.field(instance, "modelId") or common.field(instance, "model") or common.field(instance, "id") or instance
        local model_id = type(raw_id) == "number" and raw_id or tonumber(tostring(raw_id))
        result[#result + 1] = {
            model_id = model_id,
            model_name = model_name(model_id),
            fields = common.probe_fields(instance, { "modelId", "model", "id", "transf", "transform" }),
        }
    end
    return result
end

local function looks_like_signal(models)
    for _, model in ipairs(models) do
        local name = string.lower(model.model_name or "")
        if name:find("signal", 1, true) or name:find("semaphore", 1, true) then return true end
    end
    return false
end

local function component_inventory()
    local result = {}
    for _, name in ipairs(COMPONENTS) do
        local value, reason = common.component_type(name)
        result[name] = { available = value ~= nil, value_type = type(value), error = value == nil and tostring(reason) or nil }
    end
    return result
end

local function member_inventory(value)
    local result = { value_type = type(value), members = {} }
    if type(value) ~= "table" then return result end
    for key, member in pairs(value) do
        result.members[#result.members + 1] = { name = tostring(key), value_type = type(member) }
    end
    table.sort(result.members, function(a, b) return a.name < b.name end)
    return result
end

local function systems_inventory()
    local result = {}
    local systems = api and api.engine and api.engine.system
    for _, name in ipairs({ "signalSystem", "transportVehicleSystem", "stationSystem", "simCargoSystem", "simPersonSystem", "lineSystem", "pathSystem", "streetSystem", "transportNetworkSystem" }) do
        result[name] = member_inventory(common.field(systems, name))
    end
    return result
end

local function interface_call(name, ...)
    local interface = game and game.interface
    local fn = common.field(interface, name)
    if type(fn) ~= "function" then return false, "method unavailable" end
    local arguments = { ... }
    return pcall(function() return fn(table.unpack(arguments)) end)
end

local function collect_signals(errors)
    local signals, by_id = {}, {}
    local component_type = common.component_type("SIGNAL")
    if component_type == nil then return signals, by_id end
    local ok, reason = common.safe_for_each_entity("SIGNAL", function(entity)
        local id = entity_id(entity)
        local component = common.safe_get_component(entity, "SIGNAL", errors)
        local item = {
            entity_id = id,
            component = common.probe_fields(component, SIGNAL_FIELDS),
        }
        signals[#signals + 1], by_id[id] = item, item
    end, errors)
    if not ok then errors[#errors + 1] = { component = "SIGNAL", error = tostring(reason) } end
    table.sort(signals, function(a, b) return a.entity_id < b.entity_id end)
    return signals, by_id
end

local function collect_track_edge_objects(signal_by_id, errors)
    local result, signal_result, inspected = {}, {}, 0
    local ok, reason = common.safe_for_each_entity("BASE_EDGE_TRACK", function(edge_entity)
        local base = common.safe_get_component(edge_entity, "BASE_EDGE", errors)
        for object_index, object in ipairs(common.sequence_values(common.field(base, "objects"))) do
            inspected = inspected + 1
            local raw_entity = common.field(object, "entity") or common.field(object, "id") or common.field(object, 1) or common.field(object, 0) or object
            local object_id = entity_id(raw_entity)
            local position, bounds, models = nil, nil, {}
            if object_id ~= nil then
                position, bounds = bounds_for(raw_entity, errors)
                models = model_instances_for(raw_entity, errors)
            end
            -- SignalId.entity is documented as the entity carrying SIGNAL_LIST,
            -- which is the edge-object entity, not its parent BASE_EDGE.  Export
            -- explicit PathPosData.SignalType values so waypoints (2) are not
            -- presented as operational signals (0/1).
            local signal_list = object_id ~= nil and common.safe_get_component(raw_entity, "SIGNAL_LIST", errors) or nil
            local entries = common.field(signal_list, "signals") or common.field(signal_list, "items") or signal_list
            local signal_types, operational_signal = {}, false
            for _, entry in ipairs(common.sequence_values(entries)) do
                local signal_type = common.field(entry, "type") or common.field(entry, "signalType")
                if type(signal_type) == "number" then
                    signal_types[#signal_types + 1] = signal_type
                    if signal_type == 0 or signal_type == 1 then operational_signal = true end
                end
            end
            local raw_param = common.field(object, "param") or common.field(object, "edgePos") or common.field(object, "position")
            local item = {
                object_entity_id = object_id, edge_entity_id = entity_id(edge_entity), object_index = object_index - 1,
                edge_param = type(raw_param) == "number" and raw_param or nil,
                left = common.field(object, "left"), position = position, bounds = bounds, models = models,
                fields = common.probe_fields(object, EDGE_OBJECT_FIELDS),
                signal_component_observed = object_id ~= nil and signal_by_id[object_id] ~= nil,
                signal_list_observed = signal_list ~= nil,
                signal_types = signal_types,
                operational_signal_observed = operational_signal,
                signal_model_observed = looks_like_signal(models),
            }
            result[#result + 1] = item
            if item.signal_component_observed or item.operational_signal_observed or item.signal_model_observed then
                signal_result[#signal_result + 1] = item
            end
        end
    end, errors)
    if not ok then errors[#errors + 1] = { component = "BASE_EDGE_TRACK.objects", error = tostring(reason) } end
    return result, signal_result, inspected
end

local function path_edges_for(path)
    local result = { count = 0, truncated = false, items = {} }
    local edges = common.field(path, "edges")
    result.count = common.array_count(edges) or 0
    for _, edge in ipairs(common.sequence_values(edges)) do
        if #result.items >= 4 then result.truncated = true break end
        local edge_id_value = common.field(edge, "edgeId")
        local raw_id = common.field(edge_id_value, "entity") or common.field(edge_id_value, "edge") or common.field(edge_id_value, "id") or common.field(edge_id_value, 0) or common.field(edge_id_value, 1) or common.field(edge, "entity") or common.field(edge, "edge") or common.field(edge, "id") or edge_id_value or edge
        result.items[#result.items + 1] = {
            edge_id = entity_id(raw_id),
            fields = common.probe_fields(edge, PATH_EDGE_FIELDS),
            edge_id_fields = common.probe_fields(edge_id_value, { "entity", "edge", "id", "index" }),
        }
    end
    return result
end

local function collect_vehicles(inventory, errors)
    local result = {}
    local vehicle_system = common.field(api.engine and api.engine.system, "transportVehicleSystem")
    local get_info = common.field(vehicle_system, "getInfo")
    local ok, reason = common.safe_for_each_entity("TRANSPORT_VEHICLE", function(entity)
        local id = entity_id(entity)
        local vehicle = common.safe_get_component(entity, "TRANSPORT_VEHICLE", errors)
        local center, bounds = bounds_for(entity, errors)
        local item = {
            entity_id = id, name = common.name_from_component(common.safe_get_component(entity, "NAME", errors)),
            position = center, bounds = bounds, component = common.probe_fields(vehicle, VEHICLE_FIELDS),
        }
        for _, component_name in ipairs({ "MOVE_PATH", "SIM_ENTITY_MOVING" }) do
            if inventory[component_name] and inventory[component_name].available then
                item[string.lower(component_name)] = common.probe_fields(common.safe_get_component(entity, component_name, errors), MOVE_FIELDS)
            end
        end
        local move_path = common.safe_get_component(entity, "MOVE_PATH", errors)
        local path = common.field(move_path, "path")
        item.move_path_detail = common.probe_fields(move_path, { "index", "edgeIndex", "pathIndex", "offset", "distance", "param", "position", "pos", "front", "back", "speed", "velocity", "state" })
        item.path_probe = common.probe_fields(path, { "edges", "edgeIds", "nodes", "path", "length", "position", "pos", "index", "edgeIndex", "offset", "current", "front", "back" })
        item.path_edges = path_edges_for(path)
        if get_info ~= nil then
            local info_ok, info = pcall(function() return get_info(entity) end)
            item.get_info_ok = info_ok
            item.info = info_ok and common.probe_fields(info, { "state", "speed", "velocity", "position", "front", "back", "pathPos", "edge", "edgeId", "edgePos", "section", "distance", "moveInfo", "trainMoveInfo" }) or nil
            local move_info = info_ok and (common.field(info, "moveInfo") or common.field(info, "trainMoveInfo")) or nil
            item.move_info = common.probe_fields(move_info, { "speed", "velocity", "position", "front", "back", "pathPos", "edge", "edgeId", "edgePos", "section", "distance", "index", "offset", "param" })
            item.get_info_error = info_ok and nil or tostring(info)
        end
        result[#result + 1] = item
    end, errors)
    if not ok then errors[#errors + 1] = { component = "TRANSPORT_VEHICLE", error = tostring(reason) } end
    table.sort(result, function(a, b) return a.entity_id < b.entity_id end)
    return result
end

-- Compact production frame for the browser's high-frequency live layer.
-- The documented MOVE_PATH.dyn fields are the authoritative source here:
-- dyn.pathPos selects the current edge in path.edges and dyn.speed is the
-- instantaneous simulation speed.  Keep the discovery-heavy `vehicles`
-- section separate so it is never serialized on every map refresh.
local function collect_live_vehicles(errors)
    local result = {}
    local ok, reason = common.safe_for_each_entity("TRANSPORT_VEHICLE", function(entity)
        local id = entity_id(entity)
        local vehicle = common.safe_get_component(entity, "TRANSPORT_VEHICLE", errors)
        local move_path = common.safe_get_component(entity, "MOVE_PATH", errors)
        local path = common.field(move_path, "path")
        local dyn = common.field(move_path, "dyn") or common.field(move_path, "dyn0")
        local path_pos = common.field(dyn, "pathPos")
        local edge_index = common.field(path_pos, "edgeIndex")
        local edges = common.field(path, "edges")
        local current = type(edge_index) == "number" and common.field(edges, edge_index) or nil
        -- Some ordinary Lua fixtures use one-based arrays; engine path vectors
        -- are zero based.  This fallback keeps both representations testable.
        if current == nil and type(edge_index) == "number" then current = common.field(edges, edge_index + 1) end
        local edge_id_value = common.field(current, "edgeId")
        local raw_edge_id = common.field(edge_id_value, "entity") or common.field(edge_id_value, "edge") or common.field(edge_id_value, "id") or edge_id_value
        local pos01 = common.field(path_pos, "pos01")
        local direction = common.field(current, "dir")
        local edge_param = pos01
        if type(pos01) == "number" and direction == false then edge_param = 1 - pos01 end
        local center = bounds_for(entity, errors)
        result[#result + 1] = {
            entity_id = id,
            name = common.name_from_component(common.safe_get_component(entity, "NAME", errors)),
            line_id = entity_id(common.field(vehicle, "line")),
            raw_state = common.field(vehicle, "state"),
            stop_index = common.field(vehicle, "stopIndex"),
            position = center,
            current_edge_id = entity_id(raw_edge_id),
            current_edge_index = type(edge_index) == "number" and edge_index or nil,
            current_edge_direction = direction,
            current_edge_param = type(edge_param) == "number" and edge_param or nil,
            path_pos = type(common.field(path_pos, "pos")) == "number" and common.field(path_pos, "pos") or nil,
            speed_mps = type(common.field(dyn, "speed")) == "number" and common.field(dyn, "speed") or nil,
            acceleration_mps2 = type(common.field(dyn, "accel")) == "number" and common.field(dyn, "accel") or nil,
            approaching_station = type(common.field(dyn, "approachingStation")) == "boolean" and common.field(dyn, "approachingStation") or nil,
            auto_departure = type(common.field(vehicle, "autoDeparture")) == "boolean" and common.field(vehicle, "autoDeparture") or nil,
            doors_open = type(common.field(vehicle, "doorsOpen")) == "boolean" and common.field(vehicle, "doorsOpen") or nil,
            time_until_load = type(common.field(vehicle, "timeUntilLoad")) == "number" and common.field(vehicle, "timeUntilLoad") or nil,
            time_until_close_doors = type(common.field(vehicle, "timeUntilCloseDoors")) == "number" and common.field(vehicle, "timeUntilCloseDoors") or nil,
            time_until_departure = type(common.field(vehicle, "timeUntilDeparture")) == "number" and common.field(vehicle, "timeUntilDeparture") or nil,
        }
    end, errors)
    if not ok then errors[#errors + 1] = { component = "TRANSPORT_VEHICLE.live", error = tostring(reason) } end
    table.sort(result, function(a, b) return a.entity_id < b.entity_id end)
    return result
end

local function collect_simulation_clock(errors)
    local world_ok, world = pcall(api.engine.util.getWorld)
    if not world_ok or world == nil then return { source_status = "UNAVAILABLE", error = tostring(world) } end
    local speed = common.safe_get_component(world, "GAME_SPEED", errors)
    local game_time = common.safe_get_component(world, "GAME_TIME", errors)
    return {
        source_status = "ENGINE_COMPONENT",
        speedup = type(common.field(speed, "speedup")) == "number" and common.field(speed, "speedup") or nil,
        millis_per_day = type(common.field(speed, "millisPerDay")) == "number" and common.field(speed, "millisPerDay") or nil,
        game_time = type(common.field(game_time, "gameTime")) == "number" and common.field(game_time, "gameTime") or nil,
        game_time0 = type(common.field(game_time, "gameTime0")) == "number" and common.field(game_time, "gameTime0") or nil,
        tick_count = type(common.field(game_time, "tickCount")) == "number" and common.field(game_time, "tickCount") or nil,
        update_count = type(common.field(game_time, "updateCount")) == "number" and common.field(game_time, "updateCount") or nil,
    }
end

local function collect_station_demand(errors)
    local result = {}
    local ok, reason = common.safe_for_each_entity("STATION_GROUP", function(group_entity)
        local id = entity_id(group_entity)
        local group = common.safe_get_component(group_entity, "STATION_GROUP", errors)
        local children = {}
        for _, station_entity in ipairs(common.sequence_values(common.field(group, "stations"))) do
            local station = common.safe_get_component(station_entity, "STATION", errors)
            children[#children + 1] = {
                station_entity_id = entity_id(station_entity),
                cargo = common.field(station, "cargo"),
                terminal_count = common.array_count(common.field(station, "terminals")),
            }
        end
        result[#result + 1] = {
            station_group_id = id,
            name = common.name_from_component(common.safe_get_component(group_entity, "NAME", errors)),
            child_stations = children,
            transport_samples_ok = false,
            transport_samples_error = "UNKNOWN: unsafe game.interface station sampling disabled after native crash",
        }
    end, errors)
    if not ok then return result, tostring(reason) end
    table.sort(result, function(a, b) return a.station_group_id < b.station_group_id end)
    return result, nil
end

local function collect_clock_inventory()
    local result = { os_time = os and os.time and os.time() or nil, methods = {} }
    for _, name in ipairs({ "getGameTime", "getSimulationTime", "getDate", "getGameSpeed", "getCalendarSpeed" }) do
        local fn = common.field(game and game.interface, name)
        result.methods[name] = { available = type(fn) == "function", call_ok = false, source_status = "UNKNOWN_NOT_INVOKED" }
    end
    return result
end

local VALID_SECTIONS = { inventory = true, signals = true, vehicles = true, vehicles_live = true, stations = true }

function M.collect(section)
    section = section or "inventory"
    if not VALID_SECTIONS[section] then error("unsupported telemetry section: " .. tostring(section)) end
    local started = common.clock()
    local errors = {}
    local result = {
        schema_version = 1, probe_kind = "UNIFIED_OPERATIONAL_TELEMETRY_DISCOVERY",
        section = section,
        source_status = "ENGINE_OBSERVED_DIAGNOSTIC", generated_at = os and os.time and os.time() or 0,
        errors = errors, write_command_sent = false,
    }
    if section == "inventory" then
        result.component_types = component_inventory()
        result.systems = systems_inventory()
        result.clock = collect_clock_inventory()
        result.counts = {}
    elseif section == "signals" then
        local signals, signal_by_id = collect_signals(errors)
        local objects, linked, inspected = collect_track_edge_objects(signal_by_id, errors)
        result.signals, result.track_edge_objects, result.signal_edge_objects = signals, objects, linked
        result.counts = { signals = #linked, signal_edge_objects = #linked, track_edge_objects = #objects, track_edge_objects_inspected = inspected }
    elseif section == "vehicles" then
        local inventory = component_inventory()
        result.vehicles = collect_vehicles(inventory, errors)
        result.counts = { vehicles = #result.vehicles }
    elseif section == "vehicles_live" then
        result.probe_kind = "OPERATIONAL_VEHICLE_LIVE_FRAME"
        result.source_status = "ENGINE_OBSERVED_DYNAMIC"
        result.vehicles = collect_live_vehicles(errors)
        result.simulation_clock = collect_simulation_clock(errors)
        result.counts = { vehicles = #result.vehicles }
    elseif section == "stations" then
        local station_error
        result.station_demand, station_error = collect_station_demand(errors)
        if station_error then errors[#errors + 1] = { source = "game.interface.getStations", error = station_error } end
        result.counts = { stations = #result.station_demand }
    end
    result.duration_ms = (common.clock() - started) * 1000
    return result
end

return M
