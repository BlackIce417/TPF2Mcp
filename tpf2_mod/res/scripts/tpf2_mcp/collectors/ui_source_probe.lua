local common = require "tpf2_mcp/collectors/common"
local M = {}

local function callable_probe(container, method, argument)
    local value = common.field(container, method)
    local result = { method = method, type = type(value) }
    if value ~= nil then
        local ok, returned = pcall(function() return argument == nil and value() or value(argument) end)
        result.call_ok = ok
        if not ok then result.error = tostring(returned) else result.return_type = type(returned); result.length = common.array_count(returned) end
    end
    return result
end

function M.collect()
    local result = { repositories = {}, vehicle_samples = {}, systems = {} }
    for _, name in ipairs({ "cargoTypeRep", "modelRep", "constructionRep" }) do
        local repository = api.res and api.res[name]
        result.repositories[name] = { type = type(repository), getAll = callable_probe(repository, "getAll") }
        if name == "cargoTypeRep" then
            local all_method = common.field(repository, "getAll")
            local all_ok, values = pcall(function() return all_method() end)
            local first_id = all_ok and 0 or nil
            result.repositories[name].getName = callable_probe(repository, "getName", first_id)
        end
    end
    local errors = {}
    common.safe_for_each_entity("TRANSPORT_VEHICLE", function(entity)
        if #result.vehicle_samples >= 3 then return end
        local instances = common.safe_get_component(entity, "MODEL_INSTANCE_LIST", errors)
        result.vehicle_samples[#result.vehicle_samples + 1] = {
            entity_id = common.entity_id(entity),
            transport_vehicle = common.probe_fields(common.safe_get_component(entity, "TRANSPORT_VEHICLE", errors), { "line", "state", "model", "modelId", "models", "vehicles" }),
            model_instance_list = common.probe_fields(instances, { "models", "modelInstances", "instances" }),
        }
    end, errors)
    result.errors = errors
    for _, name in ipairs({ "lineSystem", "transportVehicleSystem", "stationSystem", "simCargoSystem" }) do
        result.systems[name] = { type = type(common.field(api.engine and api.engine.system, name)) }
    end
    return result
end

return M
