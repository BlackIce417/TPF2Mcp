local common = require "tpf2_mcp/collectors/common"
local M = {}

local function component_probe(entity, component_name)
    local errors = {}
    local component = common.safe_get_component(entity, component_name, errors)
    local result = { component = component_name, component_type = type(component), errors = errors }
    if component_name == "ACCOUNT" and component ~= nil then
        -- These are the requested public-field probes. Values are only emitted
        -- when they are numeric, never stringified from engine userdata.
        for _, key in ipairs({ "money", "balance", "loan" }) do
            local value = common.field(component, key)
            result[key .. "_type"] = type(value)
            if type(value) == "number" then result[key] = value end
        end
    end
    return result
end

function M.probe()
    local player = api.engine.util.getPlayer()
    return {
        player_entity = common.entity_id(player),
        components = {
            component_probe(player, "PLAYER"),
            component_probe(player, "ACCOUNT"),
            component_probe(player, "NAME"),
        },
    }
end

function M.collect()
    return common.safe_collect("company", function()
        local errors, items = {}, {}
        local player = api.engine.util.getPlayer()
        local item = { entity_id = common.entity_id(player), entity_type = "company" }
        -- Player name encoding is not yet reliable in the live save; omit it
        -- rather than exposing mojibake as normalized data.
        common.safe_get_component(player, "NAME", errors)
        local account = common.safe_get_component(player, "ACCOUNT", errors)
        if account == nil then errors[#errors + 1] = { entity_id = item.entity_id, component = "ACCOUNT", error = "account unavailable" } end
        local loan = common.field(account, "loan")
        if type(loan) == "number" then item.loan = loan end
        local balance = common.field(account, "balance")
        if type(balance) == "number" then item.balance = balance end
        items[1] = item
        return items, errors
    end)
end
return M
