local common = require "tpf2_mcp/collectors/common"
local dispatcher = require "tpf2_mcp/operations/dispatcher"
local M = {}
local model_speed_cache = {}
local model_name_cache = {}
local model_length_cache = {}

local function numeric_sequence(value, maximum)
    local result = {}
    for _, item in ipairs(common.sequence_values(value)) do
        if #result >= (maximum or 256) then break end
        if type(item) == "number" then result[#result + 1] = item end
    end
    return #result > 0 and result or nil
end

local function capacity_total(vehicle)
    local config = common.field(vehicle, "config")
    local capacities = common.sequence_values(common.field(config, "capacities"))
    local total = 0
    for _, value in ipairs(capacities) do
        if type(value) ~= "number" or value < 0 then return nil end
        total = total + value
    end
    return #capacities > 0 and total or nil
end

local function capacity_by_cargo(vehicle)
    local capacities = common.sequence_values(common.field(common.field(vehicle, "config"), "capacities"))
    local result = {}
    for index, value in ipairs(capacities) do
        if type(value) == "number" and value > 0 then
            result[#result + 1] = { cargo_id = index - 1, capacity = value }
        end
    end
    return result
end

local function model_name(model_id)
    if model_name_cache[model_id] ~= nil then return model_name_cache[model_id] or nil end
    local repository = api and api.res and api.res.modelRep
    local get_name = common.field(repository, "getName")
    local ok, value = false, nil
    if get_name ~= nil then ok, value = pcall(function() return get_name(model_id) end) end
    model_name_cache[model_id] = ok and type(value) == "string" and value or false
    return model_name_cache[model_id] or nil
end

local function model_length_m(model_id)
    if model_length_cache[model_id] ~= nil then return model_length_cache[model_id] or nil end
    local repository = api and api.res and api.res.modelRep
    local get = common.field(repository, "get")
    local ok, model = false, nil
    if get ~= nil then ok, model = pcall(function() return get(model_id) end) end
    local bounds = ok and common.field(model, "boundingInfo") or nil
    local minimum = common.sequence_values(common.field(bounds, "bbMin"))
    local maximum = common.sequence_values(common.field(bounds, "bbMax"))
    -- TPF2 rail vehicle models use the local X axis as their longitudinal
    -- direction.  boundingInfo is the engine model resource ground truth.
    local length = type(minimum[1]) == "number" and type(maximum[1]) == "number" and maximum[1] - minimum[1] or nil
    model_length_cache[model_id] = type(length) == "number" and length > 0 and length or false
    return model_length_cache[model_id] or nil
end

local function consist_parts(vehicle)
    local config = common.field(vehicle, "transportVehicleConfig")
    local result, ids, total_length, length_complete = {}, {}, 0, true
    for _, transport_part in ipairs(common.sequence_values(common.field(config, "vehicles"))) do
        local part = common.field(transport_part, "part") or transport_part
        local model_id = common.field(part, "modelId")
        if type(model_id) == "number" then
            ids[#ids + 1] = tostring(model_id)
            local length = model_length_m(model_id)
            result[#result + 1] = { model_id = model_id, model_name = model_name(model_id), model_length_m = length }
            if length ~= nil then total_length = total_length + length else length_complete = false end
        end
    end
    return result, #ids > 0 and table.concat(ids, ":") or nil, length_complete and #ids > 0 and total_length or nil
end

local function model_top_speed_mps(model_id)
    if model_speed_cache[model_id] ~= nil then return model_speed_cache[model_id] or nil end
    local repository = api and api.res and api.res.modelRep
    local get = common.field(repository, "get")
    local ok, model = false, nil
    -- Bound repository methods are callable tables in TPF2's Lua sandbox,
    -- so checking for type == "function" incorrectly rejects them.
    if get ~= nil then ok, model = pcall(function() return get(model_id) end) end
    if not ok then model = nil end
    local metadata = common.field(model, "metadata")
    local rail = common.field(metadata, "railVehicle")
    local speed = common.field(rail, "topSpeed")
    model_speed_cache[model_id] = type(speed) == "number" and speed or false
    return type(speed) == "number" and speed or nil
end

local function consist_top_speed_kmh(vehicle)
    local config = common.field(vehicle, "transportVehicleConfig")
    local values, result = common.sequence_values(common.field(config, "vehicles")), nil
    for _, transport_part in ipairs(values) do
        local part = common.field(transport_part, "part") or transport_part
        local model_id = common.field(part, "modelId")
        if type(model_id) == "number" then
            local speed = model_top_speed_mps(model_id)
            if speed ~= nil then result = result == nil and speed or math.min(result, speed) end
        end
    end
    return result ~= nil and result * 3.6 or nil
end

function M.probe()
    local samples, errors = {}, {}
    common.safe_for_each_entity("TRANSPORT_VEHICLE", function(entity)
        if #samples >= 3 then return end
        local vehicle = common.safe_get_component(entity, "TRANSPORT_VEHICLE", errors)
        samples[#samples + 1] = { entity_id = common.entity_id(entity), vehicle = common.probe_fields(vehicle, { "line", "transportMode", "mode", "vehicleType", "modelId", "stopIndex", "sectionTimes", "lineStopDepartures", "timeUntilCloseDoors" }) }
    end, errors)
    return { samples = samples, errors = errors }
end

function M.collect()
    return common.safe_collect("vehicles", function()
        local items, errors = {}, {}
        local ok, reason = common.safe_for_each_entity("TRANSPORT_VEHICLE", function(entity)
            local item = { entity_id = common.entity_id(entity), entity_type = "vehicle" }
            local name = common.name_from_component(common.safe_get_component(entity, "NAME", errors))
            if name then item.name = name end
            local vehicle = common.safe_get_component(entity, "TRANSPORT_VEHICLE", errors)
            local line = common.field(vehicle, "line")
            if line ~= nil and tonumber(tostring(line)) then item.line_id = tonumber(tostring(line)) end
            local state = common.field(vehicle, "state")
            if type(state) == "number" then item.raw_state = state end
            -- These are raw component observations only. Their semantic
            -- meaning is deliberately not inferred until a live source trace
            -- confirms it for an operation precondition.
            for _, key in ipairs({ "transportMode", "mode", "vehicleType", "modelId", "depot", "age", "maintenance", "condition", "manualDeparture", "userStopped", "autoDeparture", "doorsOpen", "timeUntilLoad", "timeUntilCloseDoors", "timeUntilDeparture" }) do
                local value = common.field(vehicle, key)
                if type(value) == "number" or type(value) == "string" or type(value) == "boolean" then item["raw_" .. key] = value end
            end
            local capacity = capacity_total(vehicle)
            if capacity ~= nil then item.capacity_total = capacity end
            local cargo_capacities = capacity_by_cargo(vehicle)
            if #cargo_capacities > 0 then
                item.capacity_by_cargo = cargo_capacities
                item.supported_cargo_ids = {}
                for _, entry in ipairs(cargo_capacities) do item.supported_cargo_ids[#item.supported_cargo_ids + 1] = entry.cargo_id end
            end
            local parts, signature, consist_length = consist_parts(vehicle)
            if #parts > 0 then item.consist_parts = parts; item.consist_signature = signature end
            if consist_length ~= nil then item.consist_length_m = consist_length end
            local technical_speed = consist_top_speed_kmh(vehicle)
            if technical_speed ~= nil then item.consist_top_speed_kmh = technical_speed end
            -- These arrays are used by timetable research but remain raw until
            -- their units and indexing are confirmed against a running save.
            local section_times = numeric_sequence(common.field(vehicle, "sectionTimes"))
            if section_times ~= nil then item.raw_sectionTimes = section_times end
            local departures = numeric_sequence(common.field(vehicle, "lineStopDepartures"))
            if departures ~= nil then item.raw_lineStopDepartures = departures end
            item.departure_control = dispatcher.departure_control(item.entity_id)
            items[#items + 1] = item
        end, errors)
        if not ok then error(reason) end
        return items, errors
    end)
end
return M
