-- Bounded STOP_VEHICLE variant: stop first, then use the game's reverseVehicle
-- command while keeping userStopped set. Never edit path coordinates or times.
local common = require "tpf2_mcp/collectors/common"
local operations = require "tpf2_mcp/operations/dispatcher"
local M = {}
local requests, latest = {}, {}
local function now() return os.time() end
local function session() return require("tpf2_mcp/collectors/operational_telemetry").session_id() end

function M.get_state(vehicle)
    local id = latest[vehicle]
    return id and requests[id] or nil
end

function M.stop_and_reverse(command)
    local id = command.operation_id
    local vehicle = type(command.target) == "table" and command.target.vehicle_id
    if type(id) ~= "string" or id == "" or #id > 128 or type(vehicle) ~= "number"
        or vehicle < 1 or vehicle ~= math.floor(vehicle) then
        return false, { code = "INVALID_REQUEST", message = "operation_id and vehicle_id required" }
    end
    if requests[id] then
        if requests[id].vehicle_id ~= vehicle then return false, { code = "COMMAND_ID_CONFLICT" } end
        return true, requests[id]
    end
    local previous = M.get_state(vehicle)
    if previous and (previous.state == "WAITING_STOP" or previous.state == "REVERSING") then
        return false, { code = "REVERSAL_IN_PROGRESS" }
    end
    local make = api and api.cmd and api.cmd.make
    -- TPF2 exposes command factories as callable tables as well as functions.
    if not make or make.reverseVehicle == nil then
        return false, { code = "REVERSE_COMMAND_UNAVAILABLE" }
    end
    local accepted, result = operations.dispatch(command)
    if not accepted then return accepted, result end
    local value = { operation_id = id, vehicle_id = vehicle, session_id = session(),
        state = "WAITING_STOP", accepted = true, reverse_command_sent = false,
        deadline = now() + 110, stop_result = result }
    requests[id], latest[vehicle] = value, id
    return true, value
end

function M.tick()
    for _, value in pairs(requests) do
        if value.state == "WAITING_STOP" or value.state == "REVERSING" then
            if value.session_id ~= session() then
                value.state, value.detail = "FAILED", "SESSION_CHANGED"
            elseif now() >= value.deadline then
                -- Do not resend an uncertain reversal: reversing twice undoes it.
                value.state, value.detail = "FAILED", "REVERSAL_TIMEOUT"
            elseif value.state == "WAITING_STOP" then
                local errors = {}
                local tv = common.safe_get_component(value.vehicle_id, "TRANSPORT_VEHICLE", errors)
                local mp = common.safe_get_component(value.vehicle_id, "MOVE_PATH", errors)
                local speed = common.field(common.field(mp, "dyn"), "speed")
                if #errors == 0 and common.field(tv, "userStopped") == true
                    and type(speed) == "number" and math.abs(speed) <= 0.01 then
                    local made, command = pcall(api.cmd.make.reverseVehicle, value.vehicle_id)
                    if not made or command == nil then
                        value.state, value.detail = "FAILED", "REVERSE_COMMAND_BUILD_FAILED:" .. tostring(command)
                    else
                        value.state, value.reverse_command_sent = "REVERSING", true
                        local sent, error_message = pcall(api.cmd.sendCommand, command, function(_, success)
                            if value.state ~= "REVERSING" or value.session_id ~= session() then return end
                            value.state = success == true and "REVERSED" or "FAILED"
                            value.detail = success == true and "ENGINE_REVERSE_CONFIRMED" or "ENGINE_REVERSE_REJECTED"
                        end)
                        if not sent then value.state, value.detail = "FAILED", tostring(error_message) end
                    end
                end
            end
        end
    end
end

return M
