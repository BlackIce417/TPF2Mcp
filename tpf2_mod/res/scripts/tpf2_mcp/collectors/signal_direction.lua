-- Read-only directional evidence. Never infer direction from the signal model.
local common = require "tpf2_mcp/collectors/common"
local M = {}
local function id(value) return tonumber(tostring(value)) end
local function geometry(value, depth)
    if value == nil or depth > 3 then return nil end
    local result = {}
    for _, key in ipairs({ "pos", "tangent" }) do
        local points = {}
        for _, p in ipairs(common.sequence_values(common.field(value, key))) do
            local x, y, z = common.field(p, "x"), common.field(p, "y"), common.field(p, "z")
            if type(x) == "number" and type(y) == "number" then points[#points + 1] = { x = x, y = y, z = z } end
        end
        if #points > 0 then result[key] = points end
    end
    for _, key in ipairs({ "params", "straight", "cubicSpline", "cubicOffsetSpline", "geometry" }) do
        local child = common.field(value, key)
        if child ~= nil and child ~= value then result[key] = geometry(child, depth + 1) end
    end
    return result
end

function M.collect(entry, object_id, signal_index, errors, parent_edge)
    local pair = common.field(entry, "edgePr")
    local zero = common.field(pair, 0)
    local edge = zero or common.field(pair, 1) or common.field(pair, "first")
    local declared_direction
    if zero ~= nil then declared_direction = common.field(pair, 1)
    else declared_direction = common.field(pair, 2) end
    if type(declared_direction) ~= "boolean" then declared_direction = common.field(pair, "second") end
    local entity = id(common.field(edge, "entity") or common.field(edge, "edgeId"))
    local index = common.field(edge, "index")
    local out = { signal_index = signal_index, declared_direction = declared_direction,
        transport_entity = entity, transport_index = index, type = common.field(entry, "type"),
        status = "DIRECTION_UNRESOLVED", queries = {} }
    if entity == nil or type(index) ~= "number" then
        -- SIGNAL_LIST.Signal need not expose PathPosData.Signal.edgePr. Query
        -- only actual transport edges belonging to the observed parent BASE_EDGE.
        if parent_edge == nil then return out end
        local network = common.safe_get_component(parent_edge, "TRANSPORT_NETWORK", errors)
        local edges = common.sequence_values(common.field(network, "edges"))
        local system = api and api.engine and api.engine.system and api.engine.system.signalSystem
        if #edges > 64 or system == nil or system.getSignal == nil or api.type.EdgeId == nil or api.type.EdgeId.new == nil then return out end
        local matches = {}
        for i, transport_edge in ipairs(edges) do
            local constructed, query_edge = pcall(function() return api.type.EdgeId.new(parent_edge, i - 1) end)
            if constructed then
                for _, reversed in ipairs({ false, true }) do
                    local ok, signal = pcall(function() return system.getSignal(query_edge, reversed) end)
                    if ok and id(common.field(signal, "entity")) == object_id and common.field(signal, "index") == signal_index then
                        matches[#matches + 1] = { edge = query_edge, index = i - 1, reversed = reversed }
                    end
                end
            end
        end
        if #matches ~= 1 then out.match_count = #matches; return out end
        edge, entity, index = matches[1].edge, id(parent_edge), matches[1].index
        out.transport_entity, out.transport_index = entity, index
        out.binding_source = "PARENT_TRANSPORT_NETWORK_QUERY"
    end
    local network = common.safe_get_component(entity, "TRANSPORT_NETWORK", errors)
    local edges = common.sequence_values(common.field(network, "edges"))
    local transport_edge = edges[index + 1]
    out.geometry = geometry(common.field(transport_edge, "geometry") or
        common.field(common.field(transport_edge, "data"), "geometry"), 0)
    local system = api and api.engine and api.engine.system and api.engine.system.signalSystem
    if system == nil or system.getSignal == nil then return out end
    for _, reversed in ipairs({ false, true }) do
        local ok, signal = pcall(function() return system.getSignal(edge, reversed) end)
        local match = ok and id(common.field(signal, "entity")) == object_id
            and common.field(signal, "index") == signal_index
        out.queries[#out.queries + 1] = { reversed = reversed, ok = ok, matched = match,
            signal_entity = ok and id(common.field(signal, "entity")) or nil,
            signal_index = ok and common.field(signal, "index") or nil }
    end
    if out.queries[1].ok and out.queries[2].ok and out.queries[1].matched ~= out.queries[2].matched then
        out.transport_forward = out.queries[1].matched
        out.status = "ENGINE_QUERY_CONFIRMED"
    end
    return out
end
return M
