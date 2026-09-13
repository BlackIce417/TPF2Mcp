local common = require "tpf2_mcp/collectors/common"
local M = {}

local function entity_number(value) return tonumber(tostring(value)) end

local function game_time_ms()
    local ok_world, world = pcall(api.engine.util.getWorld)
    if not ok_world or world == nil then return nil end
    local value = common.safe_get_component(world, "GAME_TIME", {})
    return common.field(value, "gameTime")
end

local function sequence_count(value)
    local ok, count = pcall(function() return #value end)
    return ok and count or nil
end

local function cargo_type_for(entity)
    for _, component_name in ipairs({ "SIM_CARGO", "SIM_CARGO_AT_TERMINAL" }) do
        local component = common.safe_get_component(entity, component_name, {})
        for _, field_name in ipairs({ "cargoType", "cargoTypeId", "type", "cargo" }) do
            local value = common.field(component, field_name)
            local number = entity_number(value)
            if number ~= nil then return number, component_name .. "." .. field_name end
        end
    end
    return nil, nil
end

local function classify(entities, line_id, current_time, maximum, kind)
    local result = { total_for_line = sequence_count(entities), waiting = 0, onboard = 0, other = 0, truncated = false, vehicles = {}, waiting_seconds_total = 0, waiting_seconds_samples = 0, journey_unknown = 0 }
    local cargo_totals, cargo_sources, cargo_unknown = {}, {}, 0
    local journey_totals = {}
    if entities == nil then result.status = "UNAVAILABLE"; return result end
    local visited = 0
    for _, raw_entity in pairs(entities) do
        if visited >= maximum then result.truncated = true; break end
        visited = visited + 1
        local entity = entity_number(raw_entity)
        if entity ~= nil then
            local at_vehicle = common.safe_get_component(entity, "SIM_ENTITY_AT_VEHICLE", {})
            local vehicle_id = entity_number(common.field(at_vehicle, "vehicle"))
            local bucket = nil
            local cargo_type = nil
            if kind == "cargo" then
                local cargo_source = nil
                cargo_type, cargo_source = cargo_type_for(entity)
                if cargo_type ~= nil then
                    bucket = cargo_totals[cargo_type] or { cargo_id = cargo_type, onboard = 0, waiting = 0, total = 0, vehicles = {} }
                    cargo_totals[cargo_type], cargo_sources[cargo_source] = bucket, true
                    bucket.total = bucket.total + 1
                else
                    cargo_unknown = cargo_unknown + 1
                end
            end
            if vehicle_id ~= nil then
                result.onboard = result.onboard + 1
                result.vehicles[tostring(vehicle_id)] = (result.vehicles[tostring(vehicle_id)] or 0) + 1
                if bucket ~= nil then
                    bucket.onboard = bucket.onboard + 1
                    bucket.vehicles[tostring(vehicle_id)] = (bucket.vehicles[tostring(vehicle_id)] or 0) + 1
                end
            else
                local at_terminal = common.safe_get_component(entity, "SIM_ENTITY_AT_TERMINAL", {})
                local waiting_line = entity_number(common.field(at_terminal, "line"))
                if waiting_line == line_id then
                    result.waiting = result.waiting + 1
                    if bucket ~= nil then bucket.waiting = bucket.waiting + 1 end
                    local arrival = common.field(at_terminal, "arrivalTime")
                    if type(arrival) == "number" and type(current_time) == "number" and current_time >= arrival then
                        result.waiting_seconds_total = result.waiting_seconds_total + (current_time - arrival) / 1000
                        result.waiting_seconds_samples = result.waiting_seconds_samples + 1
                    end
                else
                    result.other = result.other + 1
                end
            end

            local journey_component = vehicle_id ~= nil and at_vehicle or common.safe_get_component(entity, "SIM_ENTITY_AT_TERMINAL", {})
            local journey_line = entity_number(common.field(journey_component, "line"))
            local line_stop_0 = entity_number(common.field(journey_component, "lineStop0"))
            local line_stop_1 = entity_number(common.field(journey_component, "lineStop1"))
            if journey_line == line_id and line_stop_0 ~= nil and line_stop_1 ~= nil then
                local journey_key = tostring(line_stop_0) .. ":" .. tostring(line_stop_1)
                local journey = journey_totals[journey_key]
                if journey == nil then
                    journey = { line_stop_0 = line_stop_0, line_stop_1 = line_stop_1, onboard = 0, waiting = 0, total = 0, cargo_totals = {} }
                    journey_totals[journey_key] = journey
                end
                journey.total = journey.total + 1
                if vehicle_id ~= nil then journey.onboard = journey.onboard + 1 else journey.waiting = journey.waiting + 1 end
                if kind == "cargo" and cargo_type ~= nil then
                    local cargo_journey = journey.cargo_totals[cargo_type] or { cargo_id = cargo_type, onboard = 0, waiting = 0, total = 0 }
                    journey.cargo_totals[cargo_type] = cargo_journey
                    cargo_journey.total = cargo_journey.total + 1
                    if vehicle_id ~= nil then cargo_journey.onboard = cargo_journey.onboard + 1 else cargo_journey.waiting = cargo_journey.waiting + 1 end
                end
            else
                result.journey_unknown = result.journey_unknown + 1
            end
        end
    end
    result.classified = visited
    result.average_waiting_seconds = result.waiting_seconds_samples > 0 and result.waiting_seconds_total / result.waiting_seconds_samples or nil
    result.waiting_seconds_total = nil
    result.journey_granularity = "LINE_STOP_OD"
    result.by_journey = {}
    for _, journey in pairs(journey_totals) do
        local cargo_values = {}
        for _, cargo_journey in pairs(journey.cargo_totals) do cargo_values[#cargo_values + 1] = cargo_journey end
        table.sort(cargo_values, function(a, b) return a.cargo_id < b.cargo_id end)
        journey.cargo_totals = nil
        if kind == "cargo" then journey.by_cargo = cargo_values end
        result.by_journey[#result.by_journey + 1] = journey
    end
    table.sort(result.by_journey, function(a, b)
        if a.line_stop_0 == b.line_stop_0 then return a.line_stop_1 < b.line_stop_1 end
        return a.line_stop_0 < b.line_stop_0
    end)
    if kind == "cargo" then
        result.by_cargo = {}
        for _, item in pairs(cargo_totals) do result.by_cargo[#result.by_cargo + 1] = item end
        table.sort(result.by_cargo, function(a, b) return a.cargo_id < b.cargo_id end)
        result.cargo_type_unknown = cargo_unknown
        result.cargo_type_sources = {}
        for source, _ in pairs(cargo_sources) do result.cargo_type_sources[#result.cargo_type_sources + 1] = source end
        table.sort(result.cargo_type_sources)
    end
    return result
end

function M.collect(line_id, maximum)
    maximum = math.max(100, math.min(50000, tonumber(maximum) or 20000))
    if type(line_id) ~= "number" then return { status = "INVALID_LINE_ID" } end
    local current_time = game_time_ms()
    local person_ok, persons = pcall(api.engine.system.simPersonSystem.getSimPersonsForLine, line_id)
    local cargo_ok, cargos = pcall(api.engine.system.simCargoSystem.getSimCargosForLine, line_id)
    return {
        schema_version = 2, line_id = line_id, source_status = "ENGINE_COMPONENT_CLASSIFIED",
        sampled_game_time_ms = current_time, maximum_entities_per_kind = maximum,
        passengers = classify(person_ok and persons or nil, line_id, current_time, maximum, "passengers"),
        cargo = classify(cargo_ok and cargos or nil, line_id, current_time, maximum, "cargo"),
        errors = { persons = not person_ok and tostring(persons) or nil, cargo = not cargo_ok and tostring(cargos) or nil },
    }
end

return M
