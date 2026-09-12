local common = require "tpf2_mcp/collectors/common"
local M = {}

function M.probe()
    local samples, errors = {}, {}
    common.safe_for_each_entity("SIM_BUILDING", function(entity)
        if #samples >= 3 then return end
        local construction = common.safe_get_component(entity, "CONSTRUCTION", errors)
        local building = common.safe_get_component(entity, "SIM_BUILDING", errors)
        samples[#samples + 1] = { entity_id = common.entity_id(entity), construction = common.probe_fields(construction, { "fileName", "name", "params" }), sim_building = common.probe_fields(building, { "type", "production", "cargo" }) }
    end, errors)
    return { samples = samples, errors = errors }
end

function M.collect()
    return common.safe_collect("industries", function()
        local items, errors = {}, {}
        local ok, reason = common.safe_for_each_entity("SIM_BUILDING", function(entity)
            local item = { entity_id = common.entity_id(entity), entity_type = "industry" }
            item.industry_type = "UNKNOWN"
            local name = common.name_from_component(common.safe_get_component(entity, "NAME", errors))
            if name then item.name = name end
            local construction = common.safe_get_component(entity, "CONSTRUCTION", errors)
            local file_name = common.field(construction, "fileName")
            if type(file_name) == "string" then item.construction_file = file_name end
            items[#items + 1] = item
        end, errors)
        if not ok then error(reason) end
        return items, errors
    end)
end
return M
