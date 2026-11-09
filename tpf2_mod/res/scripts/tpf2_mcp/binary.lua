-- Little-endian fixed-width encoder for the loader shared-memory ABI.
-- TPF2 embeds Lua 5.2, so string.pack is not assumed to exist.
local M = {}
local floor, huge = math.floor, math.huge

local function byte(value) return string.char(value % 256) end

function M.u8(value) return byte(floor(tonumber(value) or 0)) end
function M.i8(value) return byte(floor(tonumber(value) or 0)) end
function M.u16(value)
    value = floor(tonumber(value) or 0)
    return byte(value) .. byte(floor(value / 256))
end
function M.u32(value)
    value = floor(tonumber(value) or 0) % 4294967296
    return byte(value) .. byte(floor(value / 256)) .. byte(floor(value / 65536)) .. byte(floor(value / 16777216))
end
function M.u64(value)
    value = floor(tonumber(value) or 0)
    local low = value % 4294967296
    local high = floor(value / 4294967296)
    return M.u32(low) .. M.u32(high)
end

function M.f32(value)
    value = tonumber(value)
    if value == nil or value ~= value then return string.char(0, 0, 192, 127) end
    local sign = 0
    if value < 0 then sign, value = 2147483648, -value end
    if value == huge then return M.u32(sign + 2139095040) end
    if value == 0 then return M.u32(sign) end
    local mantissa, exponent = math.frexp(value)
    exponent = exponent + 126
    local fraction
    if exponent <= 0 then
        fraction, exponent = floor(value / 1.401298464324817e-45 + 0.5), 0
    elseif exponent >= 255 then
        return M.u32(sign + 2139095040)
    else
        fraction = floor((mantissa * 2 - 1) * 8388608 + 0.5)
        if fraction >= 8388608 then
            fraction, exponent = 0, exponent + 1
            if exponent >= 255 then return M.u32(sign + 2139095040) end
        end
    end
    return M.u32(sign + exponent * 8388608 + fraction)
end

function M.vec3(value)
    value = value or {}
    return M.f32(value.x) .. M.f32(value.y) .. M.f32(value.z)
end

function M.aabb(value)
    value = value or {}
    return M.vec3(value.min) .. M.vec3(value.max)
end

function M.edge(value)
    value = value or {}
    return M.u64(value.edge_entity_id) .. M.f32(value.position01) .. M.i8(value.direction) ..
        M.u8(value.valid and 1 or 0) .. M.u16(0)
end

return M
