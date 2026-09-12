local common = require "tpf2_mcp/collectors/common"

local M = {}

function M.collect()
    return common.safe_collect("towns", function()
        local towns, errors = {}, {}
        local ok, iterate_error = common.safe_for_each_entity("TOWN", function(entity)
            local item = { entity_id = common.entity_id(entity), entity_type = "town" }
            local name = common.name_from_component(common.safe_get_component(entity, "NAME", errors))
            if name then item.name = name end

            -- The public town-building API reports land-use person capacities,
            -- not confirmed population. Preserve the source semantics.
            local capacities_ok, capacities = pcall(api.engine.system.townBuildingSystem.getLandUsePersonCapacities, entity)
            if capacities_ok and type(capacities) == "table" then
                item.land_use_person_capacities = { capacities[1], capacities[2], capacities[3] }
            end
            towns[#towns + 1] = item
        end, errors)
        if not ok then error(iterate_error) end
        return towns, errors
    end)
end

return M
