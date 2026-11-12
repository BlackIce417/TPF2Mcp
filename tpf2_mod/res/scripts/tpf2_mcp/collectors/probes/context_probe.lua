local common = require "tpf2_mcp/collectors/common"
local M = {}

local function method(container, key)
    return common.field(container, key)
end

local function call(fn, ...)
    if type(fn) ~= "function" then return false, "method unavailable" end
    local arguments = { ... }
    return pcall(function() return fn(table.unpack(arguments)) end)
end

local function vehicle_samples(interface)
    local result = { get_vehicles_type = type(method(interface, "getVehicles")), samples = {} }
    local vehicles_ok, vehicle_ids = call(method(interface, "getVehicles"))
    result.get_vehicles_ok = vehicles_ok
    if not vehicles_ok then result.get_vehicles_error = tostring(vehicle_ids) return result end
    result.vehicle_count = common.array_count(vehicle_ids)
    for _, vehicle_id in ipairs(common.sequence_values(vehicle_ids)) do
        if #result.samples >= 3 then break end
        local entity_ok, vehicle = call(method(interface, "getEntity"), vehicle_id)
        local sample = { entity_id = common.entity_id(vehicle_id), get_entity_ok = entity_ok }
        if entity_ok then
            sample.fields = common.probe_fields(vehicle, { "type", "id", "name", "fileName", "line", "vehicles" })
            local consist = common.field(vehicle, "vehicles")
            local parts = {}
            for _, part in ipairs(common.sequence_values(consist)) do
                if #parts >= 4 then break end
                parts[#parts + 1] = { file_name = common.field(part, "fileName"), type = common.field(part, "type") }
            end
            if #parts > 0 then sample.consist = parts end
        else
            sample.get_entity_error = tostring(vehicle)
        end
        result.samples[#result.samples + 1] = sample
    end
    return result
end

local function entity_samples(interface, method_name, fields, extra, limit)
    local result = { method = method_name, method_type = type(method(interface, method_name)), samples = {} }
    local ids_ok, ids = call(method(interface, method_name))
    result.call_ok = ids_ok
    if not ids_ok then result.call_error = tostring(ids) return result end
    result.count = common.array_count(ids)
    for _, entity_id in ipairs(common.sequence_values(ids)) do
        if #result.samples >= (limit or 3) then break end
        local entity_ok, entity = call(method(interface, "getEntity"), entity_id)
        local sample = { entity_id = common.entity_id(entity_id), get_entity_ok = entity_ok }
        if entity_ok then
            sample.fields = common.probe_fields(entity, fields)
            if extra then sample.extra = extra(entity_id) end
        else
            sample.get_entity_error = tostring(entity)
        end
        result.samples[#result.samples + 1] = sample
    end
    return result
end

function M.collect()
    -- This runs from the mod's game_script.update callback. It is deliberately
    -- a whitelist: no userdata is recursively enumerated or serialized.
    local result = { context = "game_script.update", game_type = type(game) }
    local interface = game and game.interface
    result.interface_type = type(interface)
    result.get_entity_type = type(method(interface, "getEntity"))
    result.get_player_type = type(method(interface, "getPlayer"))
    local player_ok, player = call(method(interface, "getPlayer"))
    result.get_player_ok = player_ok
    if not player_ok then result.get_player_error = tostring(player) return result end
    result.player_id = common.entity_id(player)
    local entity_ok, entity = call(method(interface, "getEntity"), player)
    result.get_entity_ok = entity_ok
    if not entity_ok then result.get_entity_error = tostring(entity) return result end
    result.player_entity_type = type(entity)
    result.player_fields = common.probe_fields(entity, { "type", "id", "name", "balance", "loan" })
    result.vehicles = vehicle_samples(interface)
    result.lines = entity_samples(interface, "getLines", { "type", "id", "name", "frequency", "rate", "throughput", "income", "revenue", "profit", "cost", "vehicles" }, nil, 128)
    result.stations = entity_samples(interface, "getStations", { "type", "id", "name", "waiting", "cargo", "passengers", "capacity", "terminals" }, function(station_id)
        local samples_ok, samples = call(method(interface, "getStationTransportSamples"), station_id)
        local values = samples_ok and common.sequence_values(samples) or {}
        return { transport_samples_ok = samples_ok, transport_samples = values, error = samples_ok and nil or tostring(samples) }
    end)
    return result
end

return M
