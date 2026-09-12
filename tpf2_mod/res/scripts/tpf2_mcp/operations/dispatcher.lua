-- Deliberately fail closed. A future ENGINE_VERIFIED implementation may add
-- narrowly validated handlers here; arbitrary Lua is never accepted.
local config = require "tpf2_mcp/config"
local stop_builder = require "tpf2_mcp/operations/line_stop_builder"
local timetable = require "tpf2_mcp/operations/timetable_controller"
local M = {}
local executed = {}
local departure_control = {}

local function now() return os and os.time and os.time() or 0 end

local function send_departure_command(vehicle_id, manual, force_departure)
    local make_ok, manual_command = pcall(api.cmd.make.setVehicleManualDeparture, vehicle_id, manual)
    if not make_ok or manual_command == nil then return false, "SET_MANUAL_DEPARTURE_FAILED:" .. tostring(manual_command) end
    departure_control[vehicle_id] = {
        manual = manual, command_confirmed = false, updated_at = now(),
        force_departure_requested = force_departure == true,
    }
    local send_ok, send_error = pcall(api.cmd.sendCommand, manual_command, function(_, success)
        local state = departure_control[vehicle_id]
        if state ~= nil and state.manual == manual then state.command_confirmed = success == true end
        if success == true and force_departure == true then
            local depart_ok, depart_command = pcall(api.cmd.make.setVehicleShouldDepart, vehicle_id)
            if depart_ok and depart_command ~= nil then pcall(api.cmd.sendCommand, depart_command, function() end) end
        end
    end)
    if not send_ok then departure_control[vehicle_id] = nil; return false, tostring(send_error) end
    return true
end

function M.departure_control(vehicle_id)
    local value = departure_control[vehicle_id]
    if value == nil then return nil end
    return {
        manual = value.manual, command_confirmed = value.command_confirmed,
        updated_at = value.updated_at, expires_at = value.expires_at,
        force_departure_requested = value.force_departure_requested,
    }
end

-- Fail safe: a bridge/browser failure must never hold a train indefinitely.
function M.tick()
    local timetable_ok, timetable_error = pcall(timetable.tick)
    if not timetable_ok then timetable.record_error(timetable_error) end
    local current = now()
    for vehicle_id, value in pairs(departure_control) do
        if value.manual == true and type(value.expires_at) == "number" and current >= value.expires_at then
            send_departure_command(vehicle_id, false, true)
        end
    end
end

local function reject(code, message)
    return false, { accepted = false, engine_command_sent = false, code = code, message = message }
end

function M.dispatch(command)
    if config.allow_write_operations ~= true then
        return reject("WRITE_DISABLED", "Global write kill switch is disabled.")
    end
    local operation_type = type(command) == "table" and command.operation_type or nil
    if type(operation_type) ~= "string" or config.allowed_operations[operation_type] ~= true then
        return reject("UNSUPPORTED_OPERATION", "Operation is not allowlisted.")
    end
    if type(command.operation_id) ~= "string" or command.operation_id == "" then return reject("INVALID_REQUEST", "operation_id is required") end
    if executed[command.operation_id] then return true, { accepted = true, engine_command_sent = false, code = "ALREADY_EXECUTED", operation_id = command.operation_id } end
    if operation_type == "CREATE_LINE" then
        local parameters = command.parameters
        if type(parameters) ~= "table" or type(parameters.name) ~= "string" or parameters.name == "" then return reject("INVALID_PARAMETERS", "CREATE_LINE requires non-empty name") end
        local stations, station_indices, terminals = parameters.station_ids, parameters.station_indices, parameters.terminal_ids
        local line, build_error = stop_builder.build_line(stations, station_indices, terminals)
        if line == nil then return reject(build_error, "Unable to resolve native stop vector") end
        local color_ok, color = pcall(api.type.Vec3f.new, parameters.color_r or 1, parameters.color_g or 1, parameters.color_b or 1)
        if not color_ok then return reject("ENGINE_ERROR", tostring(color)) end
        local command_ok, engine_command = pcall(api.cmd.make.createLine, parameters.name, color, api.engine.util.getPlayer(), line)
        if not command_ok then return reject("ENGINE_ERROR", tostring(engine_command)) end
        local send_ok, send_error = pcall(api.cmd.sendCommand, engine_command, function() end)
        if not send_ok then return reject("ENGINE_ERROR", tostring(send_error)) end
        executed[command.operation_id] = true
        return true, { accepted = true, engine_command_sent = true, code = "EXECUTED", operation_id = command.operation_id }
    end
    if operation_type == "CREATE_LINE_FROM_SOURCE_ROUTE" then
        local target, parameters = command.target, command.parameters
        if type(target) ~= "table" or type(target.source_line_id) ~= "number" or type(parameters) ~= "table" or type(parameters.name) ~= "string" or parameters.name == "" then return reject("INVALID_PARAMETERS", "CREATE_LINE_FROM_SOURCE_ROUTE requires source_line_id and non-empty name") end
        local source_ok, source = pcall(api.engine.getComponent, target.source_line_id, api.type.ComponentType.LINE)
        local stops = source_ok and source and source.stops or nil
        if stops == nil or #stops < 2 then return reject("SOURCE_ROUTE_UNAVAILABLE", "Source line needs at least two native stop descriptors") end
        local line_ok, line = pcall(api.type.Line.new)
        if not line_ok or line == nil then return reject("ENGINE_ERROR", "Line constructor unavailable") end
        local copy_ok, copy_error = pcall(function() line.stops = stops end)
        if not copy_ok then return reject("ENGINE_ERROR", tostring(copy_error)) end
        local color_ok, color = pcall(api.type.Vec3f.new, parameters.color_r or 1, parameters.color_g or 1, parameters.color_b or 1)
        if not color_ok then return reject("ENGINE_ERROR", tostring(color)) end
        local command_ok, engine_command = pcall(api.cmd.make.createLine, parameters.name, color, api.engine.util.getPlayer(), line)
        if not command_ok or engine_command == nil then return reject("ENGINE_ERROR", tostring(engine_command)) end
        local send_ok, send_error = pcall(api.cmd.sendCommand, engine_command, function() end)
        if not send_ok then return reject("ENGINE_ERROR", tostring(send_error)) end
        executed[command.operation_id] = true
        return true, { accepted = true, engine_command_sent = true, code = "EXECUTED", operation_id = command.operation_id, source_line_id = target.source_line_id }
    end
    if operation_type == "SET_LINE_STOPS" then
        local target, parameters = command.target, command.parameters
        if type(target) ~= "table" or type(target.line_id) ~= "number" or type(parameters) ~= "table" then return reject("INVALID_PARAMETERS", "SET_LINE_STOPS requires line_id and route parameters") end
        local line, build_error = stop_builder.build_line(parameters.station_ids, parameters.station_indices, parameters.terminal_ids)
        if line == nil then return reject(build_error, "Unable to resolve native stop vector") end
        local command_ok, engine_command = pcall(api.cmd.make.updateLine, target.line_id, line)
        if not command_ok or engine_command == nil then return reject("ENGINE_ERROR", tostring(engine_command)) end
        local send_ok, send_error = pcall(api.cmd.sendCommand, engine_command, function() end)
        if not send_ok then return reject("ENGINE_ERROR", tostring(send_error)) end
        executed[command.operation_id] = true
        return true, { accepted = true, engine_command_sent = true, code = "EXECUTED", operation_id = command.operation_id, line_id = target.line_id }
    end
    if operation_type == "SET_LINE_STOP_POLICY" then
        local target, parameters = command.target, command.parameters
        if type(target) ~= "table" or type(target.line_id) ~= "number" or type(parameters) ~= "table" then return reject("INVALID_PARAMETERS", "SET_LINE_STOP_POLICY requires line_id and policy parameters") end
        local line, build_error = stop_builder.build_line_with_stop_policy(target.line_id, parameters.stop_index, parameters.load_mode, parameters.min_waiting_time, parameters.max_waiting_time)
        if line == nil then return reject(build_error, "Unable to construct native stop policy update") end
        local command_ok, engine_command = pcall(api.cmd.make.updateLine, target.line_id, line)
        if not command_ok or engine_command == nil then return reject("ENGINE_ERROR", tostring(engine_command)) end
        local send_ok, send_error = pcall(api.cmd.sendCommand, engine_command, function() end)
        if not send_ok then return reject("ENGINE_ERROR", tostring(send_error)) end
        executed[command.operation_id] = true
        return true, { accepted = true, engine_command_sent = true, code = "EXECUTED", operation_id = command.operation_id, line_id = target.line_id, stop_index = parameters.stop_index }
    end
    if operation_type == "HOLD_VEHICLE_AT_TERMINAL" then
        local target, parameters = command.target, command.parameters
        local maximum = type(parameters) == "table" and parameters.max_hold_seconds or nil
        if type(target) ~= "table" or type(target.vehicle_id) ~= "number" or type(maximum) ~= "number" or maximum < 10 or maximum > 600 then return reject("INVALID_PARAMETERS", "HOLD_VEHICLE_AT_TERMINAL requires vehicle_id and max_hold_seconds 10..600") end
        local vehicle_ok, vehicle = pcall(game.interface.getEntity, target.vehicle_id)
        if not vehicle_ok or vehicle == nil then return reject("VEHICLE_NOT_FOUND", "Vehicle was not found") end
        local component_ok, component = pcall(api.engine.getComponent, target.vehicle_id, api.type.ComponentType.TRANSPORT_VEHICLE)
        if component_ok and component and timetable.controls_line(tonumber(tostring(component.line))) then return reject("TIMETABLE_CONTROLS_LINE", "Disable the line timetable before applying an ad-hoc vehicle hold") end
        local sent, send_error = send_departure_command(target.vehicle_id, true, false)
        if not sent then return reject("ENGINE_ERROR", send_error) end
        departure_control[target.vehicle_id].expires_at = now() + maximum
        executed[command.operation_id] = true
        return true, { accepted = true, engine_command_sent = true, code = "EXECUTED", operation_id = command.operation_id, vehicle_id = target.vehicle_id, max_hold_seconds = maximum }
    end
    if operation_type == "RELEASE_VEHICLE_FROM_HOLD" then
        local target = command.target
        if type(target) ~= "table" or type(target.vehicle_id) ~= "number" then return reject("INVALID_PARAMETERS", "RELEASE_VEHICLE_FROM_HOLD requires vehicle_id") end
        local vehicle_ok, vehicle = pcall(game.interface.getEntity, target.vehicle_id)
        if not vehicle_ok or vehicle == nil then return reject("VEHICLE_NOT_FOUND", "Vehicle was not found") end
        local sent, send_error = send_departure_command(target.vehicle_id, false, true)
        if not sent then return reject("ENGINE_ERROR", send_error) end
        executed[command.operation_id] = true
        return true, { accepted = true, engine_command_sent = true, code = "EXECUTED", operation_id = command.operation_id, vehicle_id = target.vehicle_id }
    end
    if operation_type == "APPLY_LINE_TIMETABLE" then
        local target, parameters = command.target, command.parameters
        if type(target) ~= "table" or type(target.line_id) ~= "number" then return reject("INVALID_PARAMETERS", "APPLY_LINE_TIMETABLE requires line_id") end
        local line_ok, line = pcall(game.interface.getEntity, target.line_id)
        if not line_ok or line == nil then return reject("ENTITY_NOT_FOUND", "Line was not found") end
        local applied, value = timetable.apply(target.line_id, parameters)
        if not applied then return reject("INVALID_PARAMETERS", tostring(value)) end
        executed[command.operation_id] = true
        return true, { accepted = true, engine_command_sent = false, resident_controller_updated = true, code = "EXECUTED", operation_id = command.operation_id, timetable = timetable.status(target.line_id) }
    end
    if operation_type == "CLEAR_LINE_TIMETABLE" then
        local target = command.target
        if type(target) ~= "table" or type(target.line_id) ~= "number" then return reject("INVALID_PARAMETERS", "CLEAR_LINE_TIMETABLE requires line_id") end
        timetable.clear(target.line_id)
        executed[command.operation_id] = true
        return true, { accepted = true, engine_command_sent = true, resident_controller_updated = true, code = "EXECUTED", operation_id = command.operation_id, line_id = target.line_id }
    end
    if operation_type == "BUY_VEHICLE" then
        local target = command.target
        if type(target) ~= "table" or type(target.source_vehicle_id) ~= "number" or type(target.depot_id) ~= "number" then return reject("INVALID_PARAMETERS", "BUY_VEHICLE requires source_vehicle_id and depot_id") end
        local component_type = api.type.ComponentType.TRANSPORT_VEHICLE
        local component_ok, vehicle = pcall(api.engine.getComponent, target.source_vehicle_id, component_type)
        local config = component_ok and vehicle and vehicle.transportVehicleConfig or nil
        if config == nil then return reject("VEHICLE_NOT_FOUND", "Source vehicle or config was unavailable") end
        local command_ok, engine_command = pcall(api.cmd.make.buyVehicle, api.engine.util.getPlayer(), target.depot_id, config)
        if not command_ok or engine_command == nil then return reject("ENGINE_ERROR", tostring(engine_command)) end
        local send_ok, send_error = pcall(api.cmd.sendCommand, engine_command, function() end)
        if not send_ok then return reject("ENGINE_ERROR", tostring(send_error)) end
        executed[command.operation_id] = true
        return true, { accepted = true, engine_command_sent = true, code = "EXECUTED", operation_id = command.operation_id, source_vehicle_id = target.source_vehicle_id, depot_id = target.depot_id }
    end
    if operation_type == "ASSIGN_VEHICLE_TO_LINE" then
        local target = command.target
        local stop_index = type(command.parameters) == "table" and command.parameters.stop_index or 0
        if type(target) ~= "table" or type(target.vehicle_id) ~= "number" or type(target.line_id) ~= "number" or type(stop_index) ~= "number" then return reject("INVALID_PARAMETERS", "ASSIGN_VEHICLE_TO_LINE requires vehicle_id, line_id, and numeric stop_index") end
        local vehicle_ok, vehicle = pcall(game.interface.getEntity, target.vehicle_id)
        local line_ok, line = pcall(game.interface.getEntity, target.line_id)
        if not vehicle_ok or vehicle == nil then return reject("VEHICLE_NOT_FOUND", "Vehicle was not found") end
        if not line_ok or line == nil then return reject("ENTITY_NOT_FOUND", "Line was not found") end
        local command_ok, engine_command = pcall(api.cmd.make.setLine, target.vehicle_id, target.line_id, stop_index)
        if not command_ok or engine_command == nil then return reject("ENGINE_ERROR", tostring(engine_command)) end
        local send_ok, send_error = pcall(api.cmd.sendCommand, engine_command, function() end)
        if not send_ok then return reject("ENGINE_ERROR", tostring(send_error)) end
        executed[command.operation_id] = true
        return true, { accepted = true, engine_command_sent = true, code = "EXECUTED", operation_id = command.operation_id, vehicle_id = target.vehicle_id, line_id = target.line_id, stop_index = stop_index }
    end
    if operation_type == "SELL_VEHICLE" then
        local target, parameters = command.target, command.parameters
        if type(target) ~= "table" or type(target.vehicle_id) ~= "number" or type(parameters) ~= "table" then return reject("INVALID_PARAMETERS", "SELL_VEHICLE requires vehicle_id and confirmation") end
        if parameters.confirmation ~= "SELL_VEHICLE:" .. tostring(target.vehicle_id) then return reject("CONFIRMATION_REQUIRED", "Exact vehicle confirmation is required") end
        local vehicle_ok, vehicle = pcall(game.interface.getEntity, target.vehicle_id)
        if not vehicle_ok or vehicle == nil then return reject("VEHICLE_NOT_FOUND", "Vehicle was not found") end
        local command_ok, engine_command = pcall(api.cmd.make.sellVehicle, target.vehicle_id)
        if not command_ok or engine_command == nil then return reject("ENGINE_ERROR", tostring(engine_command)) end
        local send_ok, send_error = pcall(api.cmd.sendCommand, engine_command, function() end)
        if not send_ok then return reject("ENGINE_ERROR", tostring(send_error)) end
        executed[command.operation_id] = true
        return true, { accepted = true, engine_command_sent = true, code = "EXECUTED", operation_id = command.operation_id, vehicle_id = target.vehicle_id }
    end
    if operation_type ~= "RENAME_LINE" then return reject("OPERATION_NOT_VERIFIED", "No verified handler exists.") end
    local target, parameters = command.target, command.parameters
    if type(target) ~= "table" or type(target.line_id) ~= "number" or type(parameters) ~= "table" or type(parameters.name) ~= "string" or parameters.name == "" or #parameters.name > 128 then
        return reject("INVALID_PARAMETERS", "RENAME_LINE requires line_id and non-empty name up to 128 bytes")
    end
    local entity_ok, entity = pcall(game.interface.getEntity, target.line_id)
    if not entity_ok or entity == nil then return reject("ENTITY_NOT_FOUND", "Line was not found") end
    local write_ok, write_error = pcall(game.interface.setName, target.line_id, parameters.name)
    if not write_ok then return reject("ENGINE_ERROR", tostring(write_error)) end
    executed[command.operation_id] = true
    return true, { accepted = true, engine_command_sent = true, code = "EXECUTED", operation_id = command.operation_id }
end

function M.save_state() return { timetable = timetable.save() } end
function M.load_state(value) timetable.load(type(value) == "table" and value.timetable or nil) end
function M.timetable_status(line_id) return timetable.status(line_id) end

return M
