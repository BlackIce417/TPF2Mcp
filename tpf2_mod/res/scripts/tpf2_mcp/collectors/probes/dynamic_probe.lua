-- Phase 7 dynamic transport-source probe.  This collector is deliberately
-- diagnostic-only: it calls a documented read-only API for a maximum of three
-- vehicles and emits primitive, whitelisted fields only.  Nothing here feeds
-- the public snapshot until its meaning is independently verified.
local common = require "tpf2_mcp/collectors/common"
local M = {}

local VEHICLE_INFO_FIELDS = { "cargoInfos", "capacity", "load", "amount", "cargo", "state" }
local CARGO_INFO_FIELDS = { "capacity", "offset", "amount", "load", "count", "cargo", "cargoType", "cargoTypeId", "type" }

local function cargo_info_samples(cargo_infos)
    local result = { value_type = type(cargo_infos), vehicle_groups = common.array_count(cargo_infos), samples = {} }
    -- api.type.TransportVehicleInfo describes cargoInfos as vehicle →
    -- compartment → cargo-type entries.  Keep both traversal and output bounded
    -- even if a future game version returns a much larger structure.
    for vehicle_index, compartments in ipairs(common.sequence_values(cargo_infos)) do
        if vehicle_index > 2 then break end
        for compartment_index, cargo_types in ipairs(common.sequence_values(compartments)) do
            if compartment_index > 3 then break end
            for cargo_index, cargo_info in ipairs(common.sequence_values(cargo_types)) do
                if cargo_index > 6 then break end
                result.samples[#result.samples + 1] = {
                    vehicle_index = vehicle_index,
                    compartment_index = compartment_index,
                    cargo_index = cargo_index,
                    fields = common.probe_fields(cargo_info, CARGO_INFO_FIELDS),
                }
            end
        end
    end
    return result
end

function M.vehicle_load()
    local result = {
        source = "api.engine.system.transportVehicleSystem.getInfo(entity)",
        source_status = "SOURCE_TRACE_ONLY",
        samples = {}, errors = {},
    }
    local system = common.field(api.engine and api.engine.system, "transportVehicleSystem")
    local get_info = common.field(system, "getInfo")
    result.system_type = type(system)
    result.getInfo_type = type(get_info)
    if get_info == nil then
        result.errors[#result.errors + 1] = "transportVehicleSystem.getInfo unavailable"
        return result
    end

    common.safe_for_each_entity("TRANSPORT_VEHICLE", function(entity)
        if #result.samples >= 3 then return end
        local call_ok, info = pcall(function() return get_info(entity) end)
        local item = { entity_id = common.entity_id(entity), call_ok = call_ok }
        if not call_ok then
            item.error = tostring(info)
        else
            item.info_fields = common.probe_fields(info, VEHICLE_INFO_FIELDS)
            item.cargo_infos = cargo_info_samples(common.field(info, "cargoInfos"))
        end
        result.samples[#result.samples + 1] = item
    end, result.errors)
    result.source_status = #result.samples > 0 and result.samples[1].call_ok and "ENGINE_AVAILABLE" or "SOURCE_TRACE_ONLY"
    return result
end

function M.station_terminal_mapping()
    local result = { source_status = "UNRESOLVED", samples = {}, errors = {} }
    common.safe_for_each_entity("STATION_GROUP", function(group_entity)
        if #result.samples >= 3 then return end
        local group_errors = {}
        local group = common.safe_get_component(group_entity, "STATION_GROUP", group_errors)
        local stations = common.sequence_values(common.field(group, "stations"))
        local children = {}
        for index, station_entity in ipairs(stations) do
            if index > 3 then break end
            local provider_errors = {}
            local provider = common.safe_get_component(station_entity, "TRANSPORT_NETWORK_PROVIDER", provider_errors)
            children[#children + 1] = {
                station_id = common.entity_id(station_entity),
                provider_fields = common.probe_fields(provider, { "terminals", "transportNetwork", "transportNetworks" }),
                errors = provider_errors,
            }
        end
        result.samples[#result.samples + 1] = { station_group_id = common.entity_id(group_entity), child_station_count = #stations, child_stations = children, errors = group_errors }
    end, result.errors)
    return result
end

function M.town_station_relation()
    local result = { source_status = "UNRESOLVED", samples = {}, errors = {}, source = "TOWN component / game.interface town entity relation" }
    common.safe_for_each_entity("TOWN", function(entity)
        if #result.samples >= 3 then return end
        local errors = {}
        local town = common.safe_get_component(entity, "TOWN", errors)
        local interface_entity, interface_ok = nil, false
        if game and game.interface and type(game.interface.getEntity) == "function" then
            interface_ok, interface_entity = pcall(function() return game.interface.getEntity(common.entity_id(entity)) end)
        end
        result.samples[#result.samples + 1] = {
            town_id = common.entity_id(entity),
            town_fields = common.probe_fields(town, { "stations", "stationGroups", "buildings" }),
            interface_get_entity_ok = interface_ok,
            interface_fields = common.probe_fields(interface_entity, { "id", "type", "name", "stations", "stationGroups" }),
            errors = errors,
        }
    end, result.errors)
    return result
end

function M.industry_semantics()
    local result = { source_status = "UNRESOLVED", samples = {}, errors = {}, source = "SIM_BUILDING / CONSTRUCTION component" }
    common.safe_for_each_entity("SIM_BUILDING", function(entity)
        if #result.samples >= 3 then return end
        local building_errors, construction_errors = {}, {}
        local building = common.safe_get_component(entity, "SIM_BUILDING", building_errors)
        local construction = common.safe_get_component(entity, "CONSTRUCTION", construction_errors)
        result.samples[#result.samples + 1] = {
            industry_id = common.entity_id(entity),
            sim_building_fields = common.probe_fields(building, { "type", "production", "shipment", "transport", "cargo", "input", "output" }),
            construction_fields = common.probe_fields(construction, { "fileName", "params" }),
            errors = { sim_building = building_errors, construction = construction_errors },
        }
    end, result.errors)
    return result
end

function M.all()
    return { vehicle_load = M.vehicle_load(), station_terminal_mapping = M.station_terminal_mapping(), town_station_relation = M.town_station_relation(), industry_semantics = M.industry_semantics() }
end

return M
