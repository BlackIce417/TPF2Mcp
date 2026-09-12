-- Constructor-only discovery. It never calls createLine/updateLine/sendCommand.
local common = require "tpf2_mcp/collectors/common"
local M = {}

local function attempt_line_shape()
    local constructor = api and api.type and api.type.Line and api.type.Line.new
    if type(constructor) ~= "function" then return { constructed = false, error = "Line.new unavailable" } end
    local ok, line = pcall(constructor)
    if not ok then return { constructed = false, error = tostring(line) } end
    local result = { constructed = true, value_type = type(line), assignments = {} }
    for _, key in ipairs({ "stops", "transportMode", "owner", "vehicles" }) do
        local value = key == "stops" and {} or 0
        local assigned, error_value = pcall(function() line[key] = value end)
        result.assignments[key] = { ok = assigned, error = assigned and nil or tostring(error_value), after = common.probe_fields(line, { key }) }
    end
    return result
end

local function attempt_stop_descriptor()
    local errors, source, source_stops = {}, nil, nil
    common.safe_for_each_entity("LINE", function(entity)
        if source ~= nil then return end
        local line = common.safe_get_component(entity, "LINE", errors)
        local stops = common.sequence_values(common.field(line, "stops"))
        if stops[1] then
            source = { stationGroup = common.field(stops[1], "stationGroup"), terminal = common.field(stops[1], "terminal") }
            source_stops = common.field(line, "stops")
        end
    end, errors)
    if source == nil then return { attempted = false, errors = errors } end
    local ok, line = pcall(api.type.Line.new)
    if not ok then return { attempted = true, constructed = false, error = tostring(line) } end
    local assigned, assignment_error = pcall(function()
        line.stops = { { stationGroup = source.stationGroup, terminal = source.terminal } }
    end)
    return {
        attempted = true, assigned = assigned, error = assigned and nil or tostring(assignment_error),
        source = { station_id = common.entity_id(source.stationGroup), terminal_id = common.entity_id(source.terminal) },
        resulting_stops = common.probe_fields(line, { "stops" }),
    }
end

local function attempt_native_stop_copy()
    local errors, source_stops = {}, nil
    common.safe_for_each_entity("LINE", function(entity)
        if source_stops ~= nil then return end
        local component = common.safe_get_component(entity, "LINE", errors)
        if common.array_count(common.field(component, "stops")) and common.array_count(common.field(component, "stops")) >= 2 then source_stops = common.field(component, "stops") end
    end, errors)
    if source_stops == nil then return { attempted = false, errors = errors } end
    local ok, line = pcall(api.type.Line.new)
    if not ok then return { attempted = true, constructed = false, error = tostring(line) } end
    local assigned, assignment_error = pcall(function() line.stops = source_stops end)
    return { attempted = true, assigned = assigned, error = assigned and nil or tostring(assignment_error), resulting_stops = common.probe_fields(line, { "stops" }) }
end

local function attempt_color()
    local constructor = api and api.type and api.type.Vec3f and api.type.Vec3f.new
    if type(constructor) ~= "function" then return { constructed = false, error = "Vec3f.new unavailable" } end
    for _, args in ipairs({ { 1, 1, 1 }, {} }) do
        local ok, value = pcall(function() return constructor(table.unpack(args)) end)
        if ok then return { constructed = true, argument_count = #args, value_type = type(value), fields = common.probe_fields(value, { "x", "y", "z" }) } end
    end
    return { constructed = false }
end

local function nested_stop_type_probe()
    local line_type = api and api.type and api.type.Line or nil
    local stop_type = common.field(line_type, "Stop")
    local constructor = common.field(stop_type, "new")
    local result = { stop_type = common.probe_fields(stop_type, { "new", "stationGroup", "station", "terminal" }) }
    if type(constructor) == "function" then
        local ok, value = pcall(constructor)
        result.constructor = ok and { constructed = true, value_type = type(value), fields = common.probe_fields(value, { "stationGroup", "station", "terminal" }) } or { constructed = false, error = tostring(value) }
    end
    return result
end

-- This is the exact prerequisite for arbitrary CREATE_LINE.  It creates no
-- entity and sends no command: only a Line.Stop userdata is built and placed
-- into a temporary Line, using values observed from an existing native stop.
local function attempt_constructed_native_stop()
    local errors, source = {}, nil
    common.safe_for_each_entity("LINE", function(entity)
        if source ~= nil then return end
        local component = common.safe_get_component(entity, "LINE", errors)
        local stop = common.sequence_values(common.field(component, "stops"))[1]
        if stop then source = { stationGroup = common.field(stop, "stationGroup"), station = common.field(stop, "station"), terminal = common.field(stop, "terminal") } end
    end, errors)
    if source == nil then return { attempted = false, errors = errors } end
    local constructor = api and api.type and api.type.Line and api.type.Line.Stop and api.type.Line.Stop.new
    if type(constructor) ~= "function" then return { attempted = true, constructed = false, error = "Line.Stop.new unavailable" } end
    local ok, stop = pcall(constructor)
    if not ok or stop == nil then return { attempted = true, constructed = false, error = tostring(stop) } end
    local fields_ok, fields_error = pcall(function() stop.stationGroup = source.stationGroup; stop.station = source.station; stop.terminal = source.terminal end)
    if not fields_ok then return { attempted = true, constructed = true, assigned_fields = false, error = tostring(fields_error) } end
    local line_ok, line = pcall(api.type.Line.new)
    local stops_ok, stops_error = line_ok and pcall(function() line.stops = { stop } end) or false, nil
    if line_ok then stops_ok, stops_error = pcall(function() line.stops = { stop } end) end
    return { attempted = true, constructed = true, assigned_fields = true, assigned_to_line = stops_ok, error = stops_ok and nil or tostring(stops_error), source = { station_id = common.entity_id(source.stationGroup), station_index = source.station, terminal_id = source.terminal }, resulting_stops = line_ok and common.probe_fields(line, { "stops" }) or nil }
end

-- The API's standalone Line.Stop wrapper is not assignable in this build.
-- Test whether a copied engine-native stop vector remains writable inside a
-- temporary Line.  Neither the source line nor any game entity is modified.
local function attempt_mutable_native_stop_vector()
    local errors, source_stops, source_first = {}, nil, nil
    common.safe_for_each_entity("LINE", function(entity)
        if source_stops ~= nil then return end
        local component = common.safe_get_component(entity, "LINE", errors)
        local stops = common.field(component, "stops")
        local first = common.sequence_values(stops)[1]
        if first then source_stops, source_first = stops, first end
    end, errors)
    if source_stops == nil then return { attempted = false, errors = errors } end
    local line_ok, line = pcall(api.type.Line.new)
    if not line_ok then return { attempted = true, constructed = false, error = tostring(line) } end
    local copied, copy_error = pcall(function() line.stops = source_stops end)
    if not copied then return { attempted = true, copied = false, error = tostring(copy_error) } end
    local changed, change_error = pcall(function()
        local first = line.stops[1]
        first.stationGroup = common.field(source_first, "stationGroup")
        first.station = common.field(source_first, "station")
        first.terminal = common.field(source_first, "terminal")
    end)
    return { attempted = true, copied = true, mutable = changed, error = changed and nil or tostring(change_error), resulting_stops = common.probe_fields(line, { "stops" }) }
end

function M.collect()
    local types = api and api.type or nil
    return {
        probe_kind = "READ_ONLY_CONSTRUCTOR_DISCOVERY",
        write_command_sent = false,
        line_shape = attempt_line_shape(),
        stop_descriptor = attempt_stop_descriptor(),
        native_stop_copy = attempt_native_stop_copy(),
        color = attempt_color(),
        nested_stop_type = nested_stop_type_probe(),
        constructed_native_stop = attempt_constructed_native_stop(),
        mutable_native_stop_vector = attempt_mutable_native_stop_vector(),
        likely_types = common.probe_fields(types, { "Line", "LineStop", "Vec3f", "TransportLine" }),
        signatures = {
            createLine = common.field(api and api.cmd and api.cmd.make, "createLine") and common.field(common.field(api.cmd.make, "createLine"), "__doc__"),
            updateLine = common.field(api and api.cmd and api.cmd.make, "updateLine") and common.field(common.field(api.cmd.make, "updateLine"), "__doc__"),
        },
    }
end

return M
