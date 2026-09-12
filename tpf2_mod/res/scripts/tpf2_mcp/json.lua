-- Small JSON codec for the bridge protocol. It intentionally supports JSON values only.
local M = {}

function M.object(value)
    return setmetatable(value or {}, { __json_kind = "object" })
end

local function escape(value)
    return value:gsub("\\", "\\\\"):gsub('"', '\\"'):gsub("\n", "\\n"):gsub("\r", "\\r"):gsub("\t", "\\t")
end

function M.encode(value)
    local kind = type(value)
    if value == nil then return "null" end
    if kind == "boolean" then return value and "true" or "false" end
    if kind == "number" then return tostring(value) end
    if kind == "string" then return '"' .. escape(value) .. '"' end
    if kind ~= "table" then error("unsupported JSON type: " .. kind) end
    local marker = getmetatable(value)
    local is_array, length = marker == nil or marker.__json_kind ~= "object", 0
    for key, _ in pairs(value) do
        if type(key) ~= "number" or key < 1 or key % 1 ~= 0 then is_array = false break end
        if key > length then length = key end
    end
    local out = {}
    if is_array then
        for index = 1, length do out[#out + 1] = M.encode(value[index]) end
        return "[" .. table.concat(out, ",") .. "]"
    end
    for key, item in pairs(value) do out[#out + 1] = M.encode(tostring(key)) .. ":" .. M.encode(item) end
    return "{" .. table.concat(out, ",") .. "}"
end

local function decoder(input)
    local pos, size = 1, #input
    local function skip()
        while pos <= size and input:sub(pos, pos):match("%s") do pos = pos + 1 end
    end
    local parse_value
    local function parse_string()
        pos = pos + 1
        local result = {}
        while pos <= size do
            local char = input:sub(pos, pos); pos = pos + 1
            if char == '"' then return table.concat(result) end
            if char == "\\" then
                local escaped = input:sub(pos, pos); pos = pos + 1
                local map = { ['"'] = '"', ["\\"] = "\\", ["/"] = "/", b = "\b", f = "\f", n = "\n", r = "\r", t = "\t" }
                if not map[escaped] then error("unsupported JSON escape") end
                result[#result + 1] = map[escaped]
            else result[#result + 1] = char end
        end
        error("unterminated JSON string")
    end
    local function parse_array()
        local result = {}; pos = pos + 1; skip()
        if input:sub(pos, pos) == "]" then pos = pos + 1 return result end
        while true do
            result[#result + 1] = parse_value(); skip()
            local char = input:sub(pos, pos); pos = pos + 1
            if char == "]" then return result end
            if char ~= "," then error("invalid JSON array") end
            skip()
        end
    end
    local function parse_object()
        local result = {}; pos = pos + 1; skip()
        if input:sub(pos, pos) == "}" then pos = pos + 1 return result end
        while true do
            if input:sub(pos, pos) ~= '"' then error("invalid JSON object key") end
            local key = parse_string(); skip()
            if input:sub(pos, pos) ~= ":" then error("missing JSON colon") end
            pos = pos + 1; skip(); result[key] = parse_value(); skip()
            local char = input:sub(pos, pos); pos = pos + 1
            if char == "}" then return result end
            if char ~= "," then error("invalid JSON object") end
            skip()
        end
    end
    function parse_value()
        skip(); local char = input:sub(pos, pos)
        if char == '"' then return parse_string() end
        if char == "{" then return parse_object() end
        if char == "[" then return parse_array() end
        local literal = input:sub(pos)
        if literal:sub(1, 4) == "true" then pos = pos + 4 return true end
        if literal:sub(1, 5) == "false" then pos = pos + 5 return false end
        if literal:sub(1, 4) == "null" then pos = pos + 4 return nil end
        local token = literal:match("^-?%d+%.?%d*[eE]?[-+]?%d*")
        if token and #token > 0 then pos = pos + #token return tonumber(token) end
        error("invalid JSON value at " .. tostring(pos))
    end
    local result = parse_value(); skip()
    if pos <= size then error("trailing JSON data") end
    return result
end

function M.decode(input) return decoder(input) end

return M
