-- Read-only extraction of the physical rail graph around one station group.
-- The result is intentionally separate from the stable world snapshot schema.
local common = require "tpf2_mcp/collectors/common"

local M = {}

local function number(value)
    return type(value) == "number" and value or nil
end

local function vec(value)
    if value == nil then return nil end
    local x, y, z = common.field(value, "x"), common.field(value, "y"), common.field(value, "z")
    if type(x) ~= "number" or type(y) ~= "number" then return nil end
    return { x = x, y = y, z = type(z) == "number" and z or 0 }
end

local function entity_id(value)
    if value == nil then return nil end
    local converted = tonumber(tostring(value))
    return converted or (type(value) == "number" and value or nil)
end

local function node_id(value)
    if value == nil then return nil end
    return {
        entity = entity_id(common.field(value, "entity")),
        index = number(common.field(value, "index")),
    }
end

local function bbox_center(entity, errors)
    local volume = common.safe_get_component(entity, "BOUNDING_VOLUME", errors)
    local bbox = common.field(volume, "bbox")
    local minimum = vec(common.field(bbox, "min")) or vec(common.field(bbox, "bbMin"))
    local maximum = vec(common.field(bbox, "max")) or vec(common.field(bbox, "bbMax"))
    if not minimum or not maximum then return nil end
    return {
        x = (minimum.x + maximum.x) / 2,
        y = (minimum.y + maximum.y) / 2,
        z = (minimum.z + maximum.z) / 2,
    }, { min = minimum, max = maximum }
end

local function position_from_node(value)
    return vec(common.field(value, "position"))
        or vec(common.field(value, "pos"))
        or vec(common.field(common.field(value, "data"), "position"))
        or vec(common.field(common.field(value, "data"), "pos"))
end

local function normalize_ref(value)
    if type(value) == "number" then return { index = value } end
    local result = node_id(value)
    if result.entity ~= nil or result.index ~= nil then return result end
    return { entity = entity_id(value) }
end

local function serialize_geometry(value, depth)
    depth = depth or 0
    if value == nil or depth > 3 then return nil end
    local result = {
        length = number(common.field(value, "length")),
        width = number(common.field(value, "width")),
    }
    local pos = common.field(value, "pos")
    local positions = common.sequence_values(pos)
    if #positions > 0 then
        result.pos = {}
        for _, item in ipairs(positions) do
            local point = vec(item)
            if point then result.pos[#result.pos + 1] = point end
        end
    end
    local tangents = common.sequence_values(common.field(value, "tangent"))
    if #tangents > 0 then
        result.tangent = {}
        for _, item in ipairs(tangents) do
            local point = vec(item)
            if point then result.tangent[#result.tangent + 1] = point end
        end
    end
    for _, key in ipairs({ "straight", "arc", "cubicSpline", "cubicOffsetSpline", "params", "geometry" }) do
        local child = common.field(value, key)
        if child ~= nil and child ~= value then
            local serialized = serialize_geometry(child, depth + 1)
            if serialized then result[key] = serialized end
        end
    end
    return result
end

local function network_data(network_entity, errors)
    local network = common.safe_get_component(network_entity, "TRANSPORT_NETWORK", errors)
    if network == nil then return nil end
    local nodes, edges = {}, {}
    for index, node in ipairs(common.sequence_values(common.field(network, "nodes"))) do
        nodes[#nodes + 1] = {
            index = index - 1,
            position = position_from_node(node),
            fields = common.probe_fields(node, { "position", "pos", "data", "ports" }),
        }
    end
    for index, edge in ipairs(common.sequence_values(common.field(network, "edges"))) do
        local data = common.field(edge, "data")
        edges[#edges + 1] = {
            index = index - 1,
            node0 = normalize_ref(common.field(edge, "node0") or common.field(data, "node0")),
            node1 = normalize_ref(common.field(edge, "node1") or common.field(data, "node1")),
            geometry = serialize_geometry(common.field(edge, "geometry") or common.field(data, "geometry") or edge),
            fields = common.probe_fields(edge, { "node0", "node1", "data", "geometry", "transportModes", "speedLimit" }),
        }
    end
    return { entity_id = entity_id(network_entity), nodes = nodes, edges = edges }
end

local function dist2(point, center)
    local dx, dy = point.x - center.x, point.y - center.y
    return dx * dx + dy * dy
end

local function construction_for(method_name, entity, errors)
    local system = api and api.engine and api.engine.system and api.engine.system.streetConnectorSystem
    local method = system and system[method_name]
    if type(method) ~= "function" then return nil end
    local ok, value = pcall(method, entity)
    if not ok then
        errors[#errors + 1] = { entity_id = entity_id(entity), method = method_name, error = tostring(value) }
        return nil
    end
    return entity_id(value)
end

local function system_map(method_name, errors)
    local system = api and api.engine and api.engine.system and api.engine.system.streetConnectorSystem
    local method = system and system[method_name]
    if type(method) ~= "function" then return nil end
    local ok, value = pcall(method)
    if not ok then
        errors[#errors + 1] = { method = method_name, error = tostring(value) }
        return nil
    end
    return value
end

local function map_entity(map, key)
    if map == nil or key == nil then return nil end
    return entity_id(common.field(map, key)) or entity_id(common.field(map, entity_id(key)))
end

local function track_graph(center, radius, errors, node_construction_map)
    local nodes, edges, node_cache = {}, {}, {}
    local limit2 = radius * radius
    local function base_node(node_entity)
        local id = entity_id(node_entity)
        if id == nil then return nil end
        if node_cache[id] ~= nil then return node_cache[id] or nil end
        local component = common.safe_get_component(node_entity, "BASE_NODE", errors)
        local position = position_from_node(component)
        node_cache[id] = position or false
        return position
    end
    local ok, reason = common.safe_for_each_entity("BASE_EDGE_TRACK", function(edge_entity)
        local base = common.safe_get_component(edge_entity, "BASE_EDGE", errors)
        if base == nil then return end
        local raw0, raw1 = common.field(base, "node0"), common.field(base, "node1")
        local p0, p1 = base_node(raw0), base_node(raw1)
        if not p0 or not p1 or (dist2(p0, center) > limit2 and dist2(p1, center) > limit2) then return end
        local id0, id1 = entity_id(raw0), entity_id(raw1)
        nodes[id0] = { entity_id = id0, position = p0 }
        nodes[id1] = { entity_id = id1, position = p1 }
        local track = common.safe_get_component(edge_entity, "BASE_EDGE_TRACK", errors)
        local direct_owner = construction_for("getConstructionEntityForEdge", edge_entity, errors)
        local node0_owner, node1_owner = map_entity(node_construction_map, raw0), map_entity(node_construction_map, raw1)
        local mapped_owner = node0_owner ~= nil and node0_owner == node1_owner and node0_owner or nil
        edges[#edges + 1] = {
            entity_id = entity_id(edge_entity),
            construction_entity_id = direct_owner or mapped_owner,
            node0_construction_entity_id = node0_owner,
            node1_construction_entity_id = node1_owner,
            node0 = entity_id(raw0),
            node1 = entity_id(raw1),
            tangent0 = vec(common.field(base, "tangent0")),
            tangent1 = vec(common.field(base, "tangent1")),
            type = number(common.field(base, "type")),
            type_index = number(common.field(base, "typeIndex")),
            track_type = number(common.field(track, "trackType")),
            catenary = common.field(track, "catenary"),
        }
    end, errors)
    if not ok then errors[#errors + 1] = { component = "BASE_EDGE_TRACK", error = reason } end
    local normalized_nodes = {}
    for _, item in pairs(nodes) do normalized_nodes[#normalized_nodes + 1] = item end
    table.sort(normalized_nodes, function(a, b) return a.entity_id < b.entity_id end)
    table.sort(edges, function(a, b) return a.entity_id < b.entity_id end)
    return normalized_nodes, edges
end

function M.collect(station_group_id, radius)
    station_group_id = tonumber(station_group_id) or 552273
    radius = tonumber(radius) or 1200
    local errors, child_stations, terminals, networks = {}, {}, {}, {}
    local group = common.safe_get_component(station_group_id, "STATION_GROUP", errors)
    if group == nil then
        return { status = "STATION_GROUP_UNAVAILABLE", station_group_id = station_group_id, errors = errors }
    end
    local center, bounds = bbox_center(station_group_id, errors)
    local station_construction_map = system_map("getStation2ConstructionMap", errors)
    local node_construction_map = system_map("getNode2StreetConnectorMap", errors)
    local network_seen = {}
    for station_index, station_entity in ipairs(common.sequence_values(common.field(group, "stations"))) do
        local sid = entity_id(station_entity)
        local station = common.safe_get_component(station_entity, "STATION", errors)
        local station_center, station_bounds = bbox_center(station_entity, errors)
        if center == nil then center, bounds = station_center, station_bounds end
        local child = {
            station_index = station_index - 1, entity_id = sid,
            construction_entity_id = map_entity(station_construction_map, station_entity)
                or construction_for("getConstructionEntityForStation", station_entity, errors),
            cargo = common.field(station, "cargo"), bounds = station_bounds,
        }
        child_stations[#child_stations + 1] = child
        for terminal_index, terminal in ipairs(common.sequence_values(common.field(station, "terminals"))) do
            local vehicle_node = node_id(common.field(terminal, "vehicleNodeId"))
            local direct_length, direct_length_field = nil, nil
            for _, key in ipairs({ "platformLength", "platformLengthM", "length", "vehicleLength", "usableLength" }) do
                local candidate = common.field(terminal, key)
                if type(candidate) == "number" and candidate > 0 then
                    direct_length, direct_length_field = candidate, key
                    break
                end
            end
            terminals[#terminals + 1] = {
                station_index = station_index - 1,
                terminal_index = terminal_index - 1,
                tag = common.field(terminal, "tag"),
                vehicle_node = vehicle_node,
                direct_platform_length_m = direct_length,
                direct_platform_length_field = direct_length_field,
            }
            if vehicle_node and vehicle_node.entity and not network_seen[vehicle_node.entity] then
                network_seen[vehicle_node.entity] = true
                local item = network_data(vehicle_node.entity, errors)
                if item then
                    networks[#networks + 1] = item
                    if center == nil then
                        for _, node in ipairs(item.nodes) do if node.position then center = node.position break end end
                    end
                end
            end
        end
    end
    if center == nil then
        return {
            status = "CENTER_UNAVAILABLE", station_group_id = station_group_id,
            child_stations = child_stations, terminals = terminals, transport_networks = networks, errors = errors,
        }
    end
    local nodes, edges = track_graph(center, radius, errors, node_construction_map)
    return {
        status = "OK", source_status = "ENGINE_OBSERVED", station_group_id = station_group_id,
        radius_m = radius, center = center, bounds = bounds, child_stations = child_stations,
        terminals = terminals, transport_networks = networks, track_nodes = nodes, track_edges = edges,
        counts = { terminals = #terminals, transport_networks = #networks, track_nodes = #nodes, track_edges = #edges },
        errors = errors, write_command_sent = false,
    }
end

return M
