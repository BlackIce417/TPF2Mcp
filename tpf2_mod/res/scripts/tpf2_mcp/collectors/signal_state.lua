-- Read only documented SignalList entry fields. Animation IDs are not aspects.
local common = require "tpf2_mcp/collectors/common"
local M = {}

function M.entry(entry, index)
    local state = common.field(entry, "state")
    local timer = common.field(entry, "stateTime")
    local observed = type(state) == "number" and state == state and math.abs(state) < math.huge
    return { signal_index = index, signal_type = common.field(entry, "type"),
        raw_state = observed and state or nil,
        state_time = type(timer) == "number" and timer == timer and math.abs(timer) < math.huge and timer or nil,
        source = "SIGNAL_LIST.signals", status = observed and "RAW_ANIMATION_OBSERVED" or "API_FIELD_UNAVAILABLE",
        aspect = "UNKNOWN", aspect_status = "ANIMATION_MAPPING_UNVERIFIED" }
end

function M.collect(ids, errors)
    local result = {}
    for _, id in ipairs(ids) do
        local component = common.safe_get_component(id, "SIGNAL_LIST", errors)
        local entries = common.field(component, "signals") or common.field(component, "items") or component
        local states = {}
        for i, entry in ipairs(common.sequence_values(entries)) do
            local kind = common.field(entry, "type")
            if kind == 0 or kind == 1 then states[#states + 1] = M.entry(entry, i - 1) end
        end
        result[#result + 1] = { entity_id = id, entries = states,
            status = #states > 0 and "API_ENTRIES_OBSERVED" or "SIGNAL_ENTRIES_UNAVAILABLE" }
    end
    return result
end

return M
