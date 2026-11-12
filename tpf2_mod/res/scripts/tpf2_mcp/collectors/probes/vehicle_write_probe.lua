-- Discovery probe. It lists shallow callable names/types and may construct
-- command objects, but it never sends a command or calls a mutating interface.
local M = {}
local common = require "tpf2_mcp/collectors/common"

local function shallow_members(value, maximum)
    local result = {}
    local ok = pcall(function()
        for key, child in pairs(value or {}) do
            if #result >= maximum then break end
            result[#result + 1] = { key = tostring(key), value_type = type(child) }
        end
    end)
    table.sort(result, function(a, b) return a.key < b.key end)
    return { readable = ok, members = result }
end

local function documentation(value)
    local doc = nil
    local ok = pcall(function() doc = value and value.__doc__ end)
    if not ok or type(doc) ~= "string" then return nil end
    return #doc > 4000 and string.sub(doc, 1, 4000) or doc
end

local function empty_constructor_probe(constructor)
    local ok, value = pcall(constructor)
    if not ok then return { constructed = false, error = tostring(value) } end
    return { constructed = true, value_type = type(value), members = shallow_members(value, 100) }
end

function M.probe()
    local command = api and api.cmd or nil
    local make = command and command.make or nil
    local interface = game and game.interface or nil
    local types = api and api.type or nil
    local candidates = {}
    for _, key in ipairs({ "buyVehicle", "sellVehicle", "setLine", "sendToDepot", "createLine", "deleteLine", "updateLine", "replaceVehicle" }) do
        local candidate = make and make[key]
        candidates[key] = shallow_members(candidate, 50)
        candidates[key].documentation = documentation(candidate)
    end
    local vehicle_samples, depot_samples, errors = {}, {}, {}
    local assigned_vehicle = nil
    common.safe_for_each_entity("TRANSPORT_VEHICLE", function(entity)
        if #vehicle_samples >= 3 then return end
        local vehicle = common.safe_get_component(entity, "TRANSPORT_VEHICLE", errors)
        -- The sampled vehicle's LINE field is independently serialized below;
        -- use that first live sample for constructor-only discovery rather than
        -- depending on userdata-to-number conversion.
        if assigned_vehicle == nil then assigned_vehicle = entity end
        local config = common.field(vehicle, "config")
        vehicle_samples[#vehicle_samples + 1] = {
            entity_id = common.entity_id(entity),
            vehicle = common.probe_fields(vehicle, { "line", "depot", "transportMode", "state", "config", "transportVehicleConfig" }),
            config = common.probe_fields(config, { "vehicles", "vehicle", "model", "modelId", "transportMode", "capacities", "carrier", "loadSpeed", "reversed" }),
        }
    end, errors)
    local unassign_candidate = { attempted = false, write_command_sent = false }
    if assigned_vehicle and make and make.setLine ~= nil then
        local ok, value = pcall(make.setLine, assigned_vehicle, -1, 0)
        local construction_error = nil
        if not ok then construction_error = tostring(value) end
        unassign_candidate = { attempted = true, write_command_sent = false, command_constructed = ok and value ~= nil, error = construction_error, vehicle_id = common.entity_id(assigned_vehicle), candidate = "setLine(vehicle, -1, 0)" }
    end
    common.safe_for_each_entity("VEHICLE_DEPOT", function(entity)
        if #depot_samples >= 5 then return end
        local depot = common.safe_get_component(entity, "VEHICLE_DEPOT", errors)
        depot_samples[#depot_samples + 1] = { entity_id = common.entity_id(entity), depot = common.probe_fields(depot, { "vehicles", "transportMode", "type", "config" }) }
    end, errors)
    return {
        probe_kind = "READ_ONLY_SHALLOW_API_DISCOVERY",
        write_command_sent = false,
        api_cmd = shallow_members(command, 100),
        api_cmd_make = shallow_members(make, 200),
        command_candidates = candidates,
        api_cmd_send_command = { members = shallow_members(command and command.sendCommand, 50), documentation = documentation(command and command.sendCommand) },
        api_types = {
            transport_vehicle_config = { members = shallow_members(types and types.TransportVehicleConfig, 100), documentation = documentation(types and types.TransportVehicleConfig), new_documentation = documentation(types and types.TransportVehicleConfig and types.TransportVehicleConfig.new) },
            line = { members = shallow_members(types and types.Line, 100), documentation = documentation(types and types.Line), new_documentation = documentation(types and types.Line and types.Line.new) },
        },
        constructor_probes = {
            transport_vehicle_config = empty_constructor_probe(types and types.TransportVehicleConfig and types.TransportVehicleConfig.new),
            line = empty_constructor_probe(types and types.Line and types.Line.new),
        },
        vehicle_samples = vehicle_samples,
        unassign_candidate = unassign_candidate,
        depot_samples = depot_samples,
        probe_errors = errors,
        game_interface = shallow_members(interface, 200),
        limitations = { "Members are not semantic proof.", "Command construction is not execution proof; sendCommand is never invoked by this probe." },
    }
end

return M
