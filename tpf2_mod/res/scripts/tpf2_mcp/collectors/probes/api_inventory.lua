-- Read-only inventory of the runtime API surface used by Phase 18.
local common = require "tpf2_mcp/collectors/common"
local M = {}

local function inventory(value)
    local items = {}
    if type(value) ~= "table" then return { value_type = type(value), items = items } end
    for key, member in pairs(value) do
        local entry = { name = tostring(key), value_type = type(member) }
        local doc = common.field(member, "__doc__")
        if type(doc) == "string" then entry.signature = doc end
        items[#items + 1] = entry
    end
    table.sort(items, function(a, b) return a.name < b.name end)
    return { value_type = type(value), items = items }
end

function M.type_inventory() return { probe_kind = "READ_ONLY_API_TYPE_INVENTORY", api_type = inventory(api and api.type) } end
function M.command_inventory() return { probe_kind = "READ_ONLY_API_COMMAND_INVENTORY", api_cmd_make = inventory(api and api.cmd and api.cmd.make) } end

return M
