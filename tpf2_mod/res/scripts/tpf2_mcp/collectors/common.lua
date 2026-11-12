local M = {}
-- Reuse protected access functions instead of allocating a closure per field.
-- Engine userdata and metatables remain protected; ordinary tables need no pcall.
local function read_field(value, key) return value[key] end
local function read_length(value) return #value end
local cached_component_registry, component_types = nil, {}
local frame_components, frame_bounds = nil, nil
local missing_component = {}

-- Engine userdata must never survive a simulation callback in a read cache.
function M.begin_read_frame() frame_components, frame_bounds = {}, {} end
function M.end_read_frame() frame_components, frame_bounds = nil, nil end

function M.clock()
    if os and type(os.clock) == "function" then
        local ok, value = pcall(os.clock)
        if ok and type(value) == "number" then return value end
    end
    return 0
end

function M.entity_id(entity)
    if type(entity) == "number" then return entity end
    return tonumber(tostring(entity)) or tostring(entity)
end

function M.component_type(name)
    local registry = api and api.type and api.type.ComponentType
    if registry ~= cached_component_registry then
        cached_component_registry, component_types = registry, {}
    end
    local value = component_types[name]
    if value ~= nil then return value end
    local ok
    ok, value = pcall(read_field, registry, name)
    if not ok or value == nil then return nil, "component type unavailable: " .. tostring(name) end
    component_types[name] = value
    return value
end

function M.safe_get_component(entity, component_name, errors)
    local component_type, type_error = M.component_type(component_name)
    if not component_type then
        errors[#errors + 1] = { entity_id = M.entity_id(entity), component = component_name, error = type_error }
        return nil
    end
    local key = frame_components and M.entity_id(entity)
    local cached = key and frame_components[key]
    if cached and cached[component_name] ~= nil then
        local value = cached[component_name]
        if value == missing_component then return nil end
        return value
    end
    local ok, value = pcall(api.engine.getComponent, entity, component_type)
    if not ok then
        errors[#errors + 1] = { entity_id = M.entity_id(entity), component = component_name, error = tostring(value) }
        return nil
    end
    if key then
        cached = cached or {}; frame_components[key] = cached
        cached[component_name] = value == nil and missing_component or value
    end
    return value
end

function M.bounds_for(entity, errors)
    if entity == nil then return nil, nil end
    local key = frame_bounds and M.entity_id(entity)
    local cached = key and frame_bounds[key]
    if cached then return cached[1], cached[2] end
    local volume = M.safe_get_component(entity, "BOUNDING_VOLUME", errors)
    local box = M.field(volume, "bbox")
    local function vec(value)
        local x, y, z = M.field(value, "x"), M.field(value, "y"), M.field(value, "z")
        if type(x) ~= "number" or type(y) ~= "number" then return nil end
        return { x = x, y = y, z = type(z) == "number" and z or 0 }
    end
    local minimum = vec(M.field(box, "min")) or vec(M.field(box, "bbMin"))
    local maximum = vec(M.field(box, "max")) or vec(M.field(box, "bbMax"))
    if not minimum or not maximum then return nil, nil end
    local center = { x = (minimum.x + maximum.x) * .5, y = (minimum.y + maximum.y) * .5,
                     z = (minimum.z + maximum.z) * .5 }
    local bounds = { min = minimum, max = maximum }
    if key then frame_bounds[key] = {center, bounds} end
    return center, bounds
end

function M.safe_for_each_entity(component_name, callback, errors)
    local component_type, type_error = M.component_type(component_name)
    if not component_type then return false, type_error end
    local count = 0
    local ok, iterate_error = pcall(api.engine.forEachEntityWithComponent, function(entity)
        count = count + 1
        local entity_ok, entity_error = pcall(callback, entity)
        if not entity_ok then
            errors[#errors + 1] = { entity_id = M.entity_id(entity), component = component_name, error = tostring(entity_error) }
        end
    end, component_type)
    if not ok then return false, tostring(iterate_error) end
    return true, count
end

function M.safe_collect(collector_name, collect_fn)
    local started = M.clock()
    local ok, entities, errors = pcall(collect_fn)
    local duration_ms = (M.clock() - started) * 1000
    if not ok then
        return {}, { ok = false, count = 0, duration_ms = duration_ms, error = tostring(entities) }
    end
    return entities, { ok = #errors == 0, count = #entities, duration_ms = duration_ms, errors = errors }
end

function M.name_from_component(component)
    if component == nil then return nil end
    if type(component) == "string" then return component end
    -- TPF2 components are userdata in the live game state. Field access must
    -- be protected just like ordinary table access.
    local name_ok, name = pcall(function() return component.name end)
    if name_ok and type(name) == "string" then return name end
    local value_ok, value = pcall(function() return component.value end)
    if value_ok and type(value) == "string" then return value end
    return nil
end

function M.field(value, key)
    if value == nil then return nil end
    if type(value) == "table" then
        local result = rawget(value, key)
        if result ~= nil or getmetatable(value) == nil then return result end
    end
    local ok, result = pcall(read_field, value, key)
    if ok then return result end
    return nil
end

function M.array_count(value)
    if value == nil then return nil end
    -- Engine collections may be userdata rather than ordinary Lua tables.
    -- Their length metamethod is safe to query under pcall.
    if type(value) == "table" and getmetatable(value) == nil then return #value end
    local ok, count = pcall(read_length, value)
    if ok and type(count) == "number" then return count end
    return nil
end

-- Return the length and storage base without copying the engine vector.
function M.sequence_layout(value)
    local count = M.array_count(value)
    if not count then return 0, 1 end
    local zero = M.field(value, 0)
    local one_past_zero_range = M.field(value, count)
    return count, zero ~= nil and one_past_zero_range == nil and 0 or 1
end

function M.sequence_values(value)
    local count, start_index = M.sequence_layout(value)
    local result = {}
    for index = start_index, start_index + count - 1 do
        local item = M.field(value, index)
        if item ~= nil then result[#result + 1] = item end
    end
    return result
end

function M.safe_type(value)
    return type(value)
end

function M.probe_fields(value, keys)
    local result = { value_type = type(value) }
    for _, key in ipairs(keys) do
        local field = M.field(value, key)
        local detail = { type = type(field) }
        if type(field) == "number" or type(field) == "string" or type(field) == "boolean" then detail.value = field end
        local count = M.array_count(field)
        if count ~= nil then detail.length = count end
        result[tostring(key)] = detail
    end
    return result
end

return M
