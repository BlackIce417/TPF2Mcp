local common = require "tpf2_mcp/collectors/common"
local M = {}

local function call(method, ...)
    if method == nil then return false, "method unavailable" end
    local arguments = { ... }
    return pcall(function() return method(table.unpack(arguments)) end)
end

function M.collect()
    return common.safe_collect("cargo_types", function()
        local items, errors = {}, {}
        local repository = api.res and api.res.cargoTypeRep
        local get_all = common.field(repository, "getAll")
        local ok, values = call(get_all)
        if not ok then error("cargoTypeRep.getAll: " .. tostring(values)) end
        for index, raw_key in ipairs(common.sequence_values(values)) do
            local key = tostring(raw_key)
            local cargo_id = index - 1
            local item = { cargo_key = key, cargo_id = cargo_id, index = cargo_id }
            local get_name = common.field(repository, "getName")
            local named, display_name = call(get_name, cargo_id)
            if named and type(display_name) == "string" then item.display_name = display_name end
            items[#items + 1] = item
        end
        return items, errors
    end)
end

return M
