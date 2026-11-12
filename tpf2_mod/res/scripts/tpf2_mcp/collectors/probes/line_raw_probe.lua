-- Read-only probe: records descriptor fields/types without serialising engine userdata.
local common = require "tpf2_mcp/collectors/common"
local M = {}

function M.collect()
    local samples, errors = {}, {}
    common.safe_for_each_entity("LINE", function(entity)
        if #samples >= 5 then return end
        local component = common.safe_get_component(entity, "LINE", errors)
        local stops = common.sequence_values(common.field(component, "stops"))
        local normalized = {}
        for index, stop in ipairs(stops) do
            local station = common.field(stop, "stationGroup")
            local terminal = common.field(stop, "terminal")
            normalized[#normalized + 1] = {
                sequence_index = index - 1,
                station_id = station ~= nil and common.entity_id(station) or nil,
                terminal_id = terminal ~= nil and common.entity_id(terminal) or nil,
                raw = common.probe_fields(stop, { "stationGroup", "station", "terminal", "terminalIndex", "transportMode" }),
            }
        end
        samples[#samples + 1] = {
            line_id = common.entity_id(entity),
            component = common.probe_fields(component, { "stops", "transportMode", "owner", "vehicles" }),
            ordered_stops = normalized,
        }
    end, errors)
    return { sample_limit = 5, samples = samples, errors = errors, write_command_sent = false }
end

return M
