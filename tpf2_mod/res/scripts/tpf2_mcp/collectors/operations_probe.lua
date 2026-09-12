local common = require "tpf2_mcp/collectors/common"
local M = {}

local function component(entity, name, fields)
    local errors = {}
    local value = common.safe_get_component(entity, name, errors)
    return { entity_id = common.entity_id(entity), component = name, fields = common.probe_fields(value, fields), errors = errors }
end

local function samples(component_name, limit, callback)
    local result, errors = {}, {}
    common.safe_for_each_entity(component_name, function(entity)
        if #result < limit then result[#result + 1] = callback(entity) end
    end, errors)
    return { samples = result, errors = errors }
end

function M.vehicle()
    return samples("TRANSPORT_VEHICLE", 3, function(entity)
        local errors = {}
        local transport_vehicle = common.safe_get_component(entity, "TRANSPORT_VEHICLE", errors)
        local config = common.field(transport_vehicle, "config")
        local capacities = common.sequence_values(common.field(config, "capacities"))
        return { entity_id = common.entity_id(entity), components = {
            { entity_id = common.entity_id(entity), component = "TRANSPORT_VEHICLE", fields = common.probe_fields(transport_vehicle, { "line", "config", "capacity", "load", "cargo", "cargoList", "compartments", "speed", "state", "age", "maintenance", "position" }), errors = errors },
            component(entity, "TRANSPORT_HISTORY", { "entries", "revenue", "cost", "profit" }),
            component(entity, "SIM_ENTITY_AT_VEHICLE", { "cargo", "amount", "type" }),
        }, config = { fields = common.probe_fields(config, { "capacities" }), capacities = capacities }}
    end)
end

function M.station()
    return samples("STATION_GROUP", 3, function(entity)
        local group = common.safe_get_component(entity, "STATION_GROUP", {})
        local stations = common.sequence_values(common.field(group, "stations"))
        local child = stations[1]
        local components = { component(entity, "STATION_GROUP", { "stations", "waiting", "cargo", "capacity", "terminals" }) }
        if child then components[#components + 1] = component(child, "STATION", { "terminals", "waiting", "cargo", "capacity", "stockList" }) end
        return { entity_id = common.entity_id(entity), child_station_id = child and common.entity_id(child) or nil, components = components }
    end)
end

function M.industry()
    return samples("SIM_BUILDING", 3, function(entity)
        return { entity_id = common.entity_id(entity), components = {
            component(entity, "SIM_BUILDING", { "production", "shipment", "transport", "stock", "input", "output", "cargo", "type" }),
            component(entity, "STOCK_LIST", { "stocks", "capacity", "cargo" }),
            component(entity, "CONSTRUCTION", { "fileName", "params", "config" }),
        }}
    end)
end

function M.company()
    local player = api.engine.util.getPlayer()
    return { player_entity = common.entity_id(player), components = {
        component(player, "PLAYER", { "balance", "money", "loan", "finance", "account" }),
        component(player, "ACCOUNT", { "balance", "money", "cash", "loan", "finance", "history" }),
    }}
end

function M.cargo_registry()
    local result = { repository_type = "nil" }
    local ok, repository = pcall(function() return api.res and api.res.cargoTypeRep end)
    if not ok or repository == nil then return result end
    result.repository_type = type(repository)
    for _, method in ipairs({ "getAll", "get", "getName" }) do
        result[method .. "_type"] = type(common.field(repository, method))
    end
    local get_all = common.field(repository, "getAll")
    if get_all ~= nil then
        -- Bound engine methods are callable tables in this Lua sandbox.
        local called, values = pcall(function() return get_all() end)
        result.getAll_ok = called
        if called then
            result.entry_count = common.array_count(values)
            local ids = common.sequence_values(values)
            result.sample_ids = {}
            for index = 1, math.min(3, #ids) do result.sample_ids[#result.sample_ids + 1] = ids[index] end
        else result.getAll_error = tostring(values) end
    end
    return result
end

function M.all()
    return { vehicle = M.vehicle(), station = M.station(), industry = M.industry(), company = M.company(), cargo_registry = M.cargo_registry() }
end

return M
