-- Reuses an observed native stop descriptor; userdata never crosses the bridge.
local common = require "tpf2_mcp/collectors/common"
local M = {}

function M.build_stop(station_id, terminal_id)
    local errors, found = {}, nil
    common.safe_for_each_entity("LINE", function(entity)
        if found ~= nil then return end
        local component = common.safe_get_component(entity, "LINE", errors)
        for _, stop in ipairs(common.sequence_values(common.field(component, "stops"))) do
            if common.field(stop, "stationGroup") == station_id and common.field(stop, "terminal") == terminal_id then found = stop; return end
        end
    end, errors)
    if found == nil then return nil, "NO_OBSERVED_NATIVE_STOP" end
    return found
end

-- API documentation defines Line.Stop as the native configuration type.  The
-- binding name differs across game builds, so this is fail-closed: it only
-- returns a constructed object if all documented fields can be assigned.
function M.construct_stop(station_group, station, terminal)
    local line_type = api and api.type and api.type.Line or nil
    local nested = line_type and line_type.Stop or nil
    local candidates = { nested and nested.new, api and api.type and api.type.LineStop and api.type.LineStop.new }
    for _, constructor in ipairs(candidates) do
        if type(constructor) == "function" then
            local ok, value = pcall(constructor)
            if ok and value ~= nil then
                local assigned = pcall(function()
                    value.stationGroup = station_group
                    value.station = station
                    value.terminal = terminal
                end)
                if assigned then return value end
            end
        end
    end
    return nil, "NATIVE_STOP_CONSTRUCTOR_UNAVAILABLE"
end

function M.build_route(stations, station_indices, terminals)
    if type(stations) ~= "table" or type(station_indices) ~= "table" or type(terminals) ~= "table" or #stations ~= #station_indices or #stations ~= #terminals or #stations < 2 then return nil, "INVALID_ROUTE" end
    local result = {}
    for index, station_id in ipairs(stations) do
        -- An observed stop table is a Lua proxy, not the native Line.Stop
        -- userdata accepted by Line.stops.  Always construct a fresh native
        -- descriptor; never silently fall back to the known-invalid proxy.
        local stop, error_value = M.construct_stop(station_id, station_indices[index], terminals[index])
        if stop == nil then return nil, error_value end
        result[#result + 1] = stop
    end
    return result
end

-- In this TPF2 build api.type.Line.Stop.new() exposes a wrapper userdata that
-- Line.stops rejects.  A LINE component's stops vector is accepted natively.
-- Build a temporary Line from a sufficiently long observed native vector and
-- alter only that temporary Line's entries.  No existing line is mutated.
function M.build_line(stations, station_indices, terminals)
    if type(stations) ~= "table" or type(station_indices) ~= "table" or type(terminals) ~= "table" or #stations ~= #station_indices or #stations ~= #terminals or #stations < 2 then return nil, "INVALID_ROUTE" end
    local errors, template = {}, nil
    common.safe_for_each_entity("LINE", function(entity)
        if template ~= nil then return end
        local component = common.safe_get_component(entity, "LINE", errors)
        local stops = common.field(component, "stops")
        -- The native vector is fixed-length in this build.  Reusing a longer
        -- vector silently preserves trailing stops, so only an exact-size
        -- template is safe for a requested business route.
        if common.array_count(stops) == #stations then template = stops end
    end, errors)
    if template == nil then return nil, "NO_EXACT_NATIVE_STOP_VECTOR_TEMPLATE" end
    local line_ok, line = pcall(api.type.Line.new)
    if not line_ok or line == nil then return nil, "LINE_CONSTRUCTOR_UNAVAILABLE" end
    local copy_ok, copy_error = pcall(function() line.stops = template end)
    if not copy_ok then return nil, "NATIVE_STOP_VECTOR_COPY_FAILED:" .. tostring(copy_error) end
    local mutate_ok, mutate_error = pcall(function()
        for index, station_id in ipairs(stations) do
            local stop = line.stops[index]
            stop.stationGroup = station_id
            stop.station = station_indices[index]
            stop.terminal = terminals[index]
        end
    end)
    if not mutate_ok then return nil, "NATIVE_STOP_VECTOR_MUTATION_FAILED:" .. tostring(mutate_error) end
    return line
end

function M.build_line_with_stop_policy(line_id, stop_index, load_mode, min_waiting_time, max_waiting_time)
    if type(line_id) ~= "number" or type(stop_index) ~= "number" or stop_index < 0 or stop_index % 1 ~= 0 then return nil, "INVALID_STOP_INDEX" end
    if type(load_mode) ~= "number" or load_mode % 1 ~= 0 or load_mode < 0 or load_mode > 2 then return nil, "INVALID_LOAD_MODE" end
    if type(min_waiting_time) ~= "number" or type(max_waiting_time) ~= "number" or min_waiting_time < 0 or max_waiting_time < min_waiting_time then return nil, "INVALID_WAITING_TIME" end
    local source_ok, source = pcall(api.engine.getComponent, line_id, api.type.ComponentType.LINE)
    local stops = source_ok and source and source.stops or nil
    if stops == nil or stop_index >= common.array_count(stops) then return nil, "STOP_NOT_FOUND" end
    local line_ok, line = pcall(api.type.Line.new)
    if not line_ok or line == nil then return nil, "LINE_CONSTRUCTOR_UNAVAILABLE" end
    local copy_ok, copy_error = pcall(function() line.stops = stops end)
    if not copy_ok then return nil, "NATIVE_STOP_VECTOR_COPY_FAILED:" .. tostring(copy_error) end
    local mutate_ok, mutate_error = pcall(function()
        local stop = line.stops[stop_index + 1]
        stop.loadMode = load_mode
        stop.minWaitingTime = min_waiting_time
        stop.maxWaitingTime = max_waiting_time
    end)
    if not mutate_ok then return nil, "STOP_POLICY_MUTATION_FAILED:" .. tostring(mutate_error) end
    return line
end

return M
