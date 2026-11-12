-- Incremental edits to one stop; never rebuild a route from another line.
local common = require "tpf2_mcp/collectors/common"
local M = {}

local function integer(value, minimum)
    return type(value) == "number" and value == value and value < math.huge
        and value >= minimum and value <= 2147483647 and value % 1 == 0
end

local function same(a, b)
    return a.station == b.station and a.terminal == b.terminal
end

local function terminals(stop)
    local result = {}
    for _, value in ipairs(common.sequence_values(common.field(stop, "alternativeTerminals"))) do
        result[#result + 1] = { station = common.field(value, "station"), terminal = common.field(value, "terminal") }
    end
    return result
end

local function get_stop(line_id, index)
    local errors = {}
    local line = common.safe_get_component(line_id, "LINE", errors)
    local stop = common.sequence_values(common.field(line, "stops"))[index + 1]
    return line, stop
end

function M.matches_precondition(line_id, parameters, expected)
    if not integer(parameters.stop_index, 0) then return false end
    local _, stop = get_stop(line_id, parameters.stop_index)
    if stop == nil or common.entity_id(common.field(stop, "stationGroup")) ~= expected.station_id
        or common.field(stop, "station") ~= expected.station_index
        or common.field(stop, "terminal") ~= expected.terminal_id then return false end
    local actual, before = terminals(stop), expected.alternative_terminals or {}
    if #actual ~= #before then return false end
    for i, value in ipairs(actual) do
        if value.station ~= before[i].station_index or value.terminal ~= before[i].terminal_id then return false end
    end
    local policy = expected.policy or {}
    return common.field(stop, "loadMode") == policy.load_mode
        and common.field(stop, "minWaitingTime") == policy.min_waiting_time
        and common.field(stop, "maxWaitingTime") == policy.max_waiting_time
end

local function validate_terminal(group_id, selected, primary)
    local errors = {}
    local group = common.safe_get_component(group_id, "STATION_GROUP", errors)
    local children = common.sequence_values(common.field(group, "stations"))
    local child_id = children[selected.station + 1]
    if child_id == nil then return false, "STATION_INDEX_NOT_FOUND" end
    local child = common.safe_get_component(child_id, "STATION", errors)
    local available = common.sequence_values(common.field(child, "terminals"))
    if available[selected.terminal + 1] == nil then return false, "PLATFORM_NOT_FOUND" end
    local source_id = children[primary.station + 1]
    local source = source_id and common.safe_get_component(source_id, "STATION", errors)
    if source == nil or #errors > 0 then return false, "STATION_READ_FAILED" end
    if common.field(child, "cargo") ~= common.field(source, "cargo") then return false, "PLATFORM_CARGO_MISMATCH" end
    -- A group can mix transport modes. Check the station's vehicle node modes
    -- through the engine's updateLine validation, not a guessed UI label.
    return true
end

function M.build(line_id, parameters, remove)
    if not integer(line_id, 1) or type(parameters) ~= "table"
        or not integer(parameters.stop_index, 0) or not integer(parameters.station_id, 1)
        or not integer(parameters.station_index, 0) or not integer(parameters.terminal_id, 0) then
        return nil, "INVALID_PLATFORM_PARAMETERS"
    end
    local source, stop = get_stop(line_id, parameters.stop_index)
    if stop == nil then return nil, "STOP_NOT_FOUND" end
    if common.entity_id(common.field(stop, "stationGroup")) ~= parameters.station_id then return nil, "STOP_STATION_MISMATCH" end
    local primary = { station = common.field(stop, "station"), terminal = common.field(stop, "terminal") }
    local selected = { station = parameters.station_index, terminal = parameters.terminal_id }
    local alternatives, found = {}, same(primary, selected)
    for _, value in ipairs(terminals(stop)) do
        if same(value, selected) then found = true end
        if not same(value, primary) and not (remove and same(value, selected)) then
            alternatives[#alternatives + 1] = value
        end
    end
    if remove then
        if same(primary, selected) then
            if #alternatives == 0 then return nil, "CANNOT_REMOVE_LAST_PLATFORM" end
            primary = table.remove(alternatives, 1)
        end
    else
        local valid, error_value = validate_terminal(parameters.station_id, selected, primary)
        if not valid then return nil, error_value end
        if not found then alternatives[#alternatives + 1] = selected end
    end
    local ok, line = pcall(function()
        local result = api.type.Line.new()
        result.stops = source.stops
        if common.field(source, "vehicleInfo") ~= nil then result.vehicleInfo = source.vehicleInfo end
        if common.field(source, "waitingTime") ~= nil then result.waitingTime = source.waitingTime end
        local edited = result.stops[parameters.stop_index + 1]
        local values = {}
        for _, item in ipairs(alternatives) do
            local value = api.type.StationTerminal.new()
            value.station = item.station
            value.terminal = item.terminal
            values[#values + 1] = value
        end
        edited.alternativeTerminals = values
        edited.station = primary.station
        edited.terminal = primary.terminal
        local observed = terminals(edited)
        assert(#observed == #alternatives, "alternative terminal vector size mismatch")
        for i, item in ipairs(observed) do assert(same(item, alternatives[i]), "alternative terminal vector mismatch") end
        assert(edited.station == primary.station and edited.terminal == primary.terminal, "primary terminal mismatch")
        return result
    end)
    if not ok then return nil, "PLATFORM_VECTOR_MUTATION_FAILED:" .. tostring(line) end
    return line
end

return M
