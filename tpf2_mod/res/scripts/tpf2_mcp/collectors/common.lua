local M = {}

function M.clock()
    if os and type(os.clock) == "function" then
        local ok, value = pcall(os.clock)
        if ok and type(value) == "number" then return value end
    end
    return 0
end

function M.entity_id(entity)
    return tonumber(tostring(entity)) or tostring(entity)
end

function M.component_type(name)
    local ok, value = pcall(function() return api.type.ComponentType[name] end)
    if not ok or value == nil then return nil, "component type unavailable: " .. tostring(name) end
    return value
end

function M.safe_get_component(entity, component_name, errors)
    local component_type, type_error = M.component_type(component_name)
    if not component_type then
        errors[#errors + 1] = { entity_id = M.entity_id(entity), component = component_name, error = type_error }
        return nil
    end
    local ok, value = pcall(api.engine.getComponent, entity, component_type)
    if not ok then
        errors[#errors + 1] = { entity_id = M.entity_id(entity), component = component_name, error = tostring(value) }
        return nil
    end
    return value
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
    local ok, result = pcall(function() return value[key] end)
    if ok then return result end
    return nil
end

function M.array_count(value)
    if value == nil then return nil end
    -- Engine collections may be userdata rather than ordinary Lua tables.
    -- Their length metamethod is safe to query under pcall.
    local ok, count = pcall(function() return #value end)
    if ok and type(count) == "number" then return count end
    return nil
end

function M.sequence_values(value)
    local count = M.array_count(value)
    if not count then return {} end
    -- Engine repository arrays may be zero based while still exposing a Lua
    -- length. Prefer 0..count-1 when that full range is populated.
    local zero = M.field(value, 0)
    local one_past_zero_range = M.field(value, count)
    local start_index = zero ~= nil and one_past_zero_range == nil and 0 or 1
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
