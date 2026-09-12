local common = require "tpf2_mcp/collectors/common"
local M = {}
function M.collect()
    return common.safe_collect("stations", function()
        local items, errors = {}, {}
        local ok, reason = common.safe_for_each_entity("STATION_GROUP", function(entity)
            -- MCP station resources are player-visible station groups. Child
            -- STATION entities have different IDs and must not be mixed here.
            local item = { entity_id = common.entity_id(entity), entity_type = "station_group" }
            local name = common.name_from_component(common.safe_get_component(entity, "NAME", errors))
            if name then item.name = name end
            local group = common.safe_get_component(entity, "STATION_GROUP", errors)
            local count = common.array_count(common.field(group, "stations"))
            if count then item.station_count = count end
            items[#items + 1] = item
        end, errors)
        if not ok then error(reason) end
        return items, errors
    end)
end
return M
