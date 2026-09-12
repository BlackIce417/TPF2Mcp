local common = require "tpf2_mcp/collectors/common"
local M = {}

local function optional_number(value)
    return type(value) == "number" and value or nil
end

local function stop_service(stop)
    local how = common.field(stop, "how")
    if how == nil then return nil end
    return {
        load = common.sequence_values(common.field(how, "load")),
        unload = common.sequence_values(common.field(how, "unload")),
        max_load = common.sequence_values(common.field(how, "maxLoad")),
    }
end

local function alternative_terminals(stop)
    local result = {}
    for _, value in ipairs(common.sequence_values(common.field(stop, "alternativeTerminals"))) do
        local station = optional_number(common.field(value, "station"))
        local terminal = optional_number(common.field(value, "terminal"))
        if station ~= nil and terminal ~= nil then
            result[#result + 1] = { station_index = station, terminal_id = terminal }
        end
    end
    return result
end

local function add_ui_metrics(item)
    -- game.interface is live-verified in this game_script.update context.
    -- Whitelist only the two fields cross-checked against paused native UI.
    local interface = game and game.interface
    local get_entity = common.field(interface, "getEntity")
    if type(get_entity) ~= "function" then return end
    local ok, ui_line = pcall(function() return get_entity(item.entity_id) end)
    if not ok or ui_line == nil then return end
    local raw_frequency = common.field(ui_line, "frequency")
    if type(raw_frequency) == "number" and raw_frequency > 0 then
        item.frequency_seconds = 1 / raw_frequency
    end
    local rate = common.field(ui_line, "rate")
    if type(rate) == "number" and rate >= 0 then item.throughput = rate end
end

function M.probe()
    local samples, errors = {}, {}
    common.safe_for_each_entity("LINE", function(entity)
        if #samples >= 3 then return end
        local line = common.safe_get_component(entity, "LINE", errors)
        local stops = common.sequence_values(common.field(line, "stops"))
        local stop_probe = {}
        if stops[1] then stop_probe = common.probe_fields(stops[1], { "stationGroup", "station", "terminal", "alternativeTerminals", "transportMode", "loadMode", "minWaitingTime", "maxWaitingTime", "how" }) end
        samples[#samples + 1] = {
            entity_id = common.entity_id(entity),
            line = common.probe_fields(line, { "stops", "transportMode", "vehicleInfo", "vehicles" }),
            first_stop = stop_probe,
            station_terminal_type = common.probe_fields(api and api.type and api.type.StationTerminal, { "new" }),
        }
    end, errors)
    return { samples = samples, errors = errors }
end

function M.collect()
    return common.safe_collect("lines", function()
        local items, errors = {}, {}
        local ok, reason = common.safe_for_each_entity("LINE", function(entity)
            local item = { entity_id = common.entity_id(entity), entity_type = "line" }
            local name = common.name_from_component(common.safe_get_component(entity, "NAME", errors))
            if name then item.name = name end
            local line = common.safe_get_component(entity, "LINE", errors)
            local stops = common.sequence_values(common.field(line, "stops"))
            item.stop_count = #stops
            item.stops = {}
            item.raw_stops = {}
            for index, stop in ipairs(stops) do
                local station_group = common.field(stop, "stationGroup")
                local station_id = common.entity_id(station_group)
                if type(station_id) == "number" then
                    local terminal = common.field(stop, "terminal")
                    local station_index = common.field(stop, "station")
                    local alternatives = alternative_terminals(stop)
                    local policy = {
                        load_mode = optional_number(common.field(stop, "loadMode")),
                        min_waiting_time = optional_number(common.field(stop, "minWaitingTime")),
                        max_waiting_time = optional_number(common.field(stop, "maxWaitingTime")),
                    }
                    local service = stop_service(stop)
                    item.stops[#item.stops + 1] = { index = index - 1, station_id = station_id, policy = policy, service = service, alternative_terminals = alternatives }
                    item.raw_stops[#item.raw_stops + 1] = { sequence_index = index - 1, station_id = station_id, station_index = type(station_index) == "number" and station_index or nil, terminal_id = type(terminal) == "number" and terminal or nil, alternative_terminals = alternatives, policy = policy, service = service }
                else
                    errors[#errors + 1] = { entity_id = item.entity_id, component = "LINE.stops", error = "stationGroup is not an entity" }
                end
            end
            add_ui_metrics(item)
            items[#items + 1] = item
        end, errors)
        if not ok then error(reason) end
        return items, errors
    end)
end
return M
