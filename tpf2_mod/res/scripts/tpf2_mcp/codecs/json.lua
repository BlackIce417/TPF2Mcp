-- Small JSON codec for the bridge protocol. It intentionally supports JSON values only.
local M = {}

function M.object(value)
    return setmetatable(value or {}, { __json_kind = "object" })
end

local function escape(value)
    return value:gsub("\\", "\\\\"):gsub('"', '\\"'):gsub("\n", "\\n"):gsub("\r", "\\r"):gsub("\t", "\\t")
end

-- One append-only buffer per message; cache repeated object keys only for
-- this encoding. No persistent growth and no intermediate JSON per nested table.
function M.encode(value)
    local out, keys, active = {}, {}, {}
    local count = 0
    local function append(token)
        count = count + 1
        out[count] = token
    end
    local encode
    encode = function(item)
        local kind = type(item)
        if item == nil then append("null")
        elseif kind == "boolean" then append(item and "true" or "false")
        elseif kind == "number" then append(tostring(item))
        elseif kind == "string" then append('"' .. escape(item) .. '"')
        elseif kind == "table" then
            if active[item] then error("cyclic JSON table") end
            active[item] = true
            local marker = getmetatable(item)
            local is_array, length = marker == nil or marker.__json_kind ~= "object", 0
            for key in pairs(item) do
                if type(key) ~= "number" or key < 1 or key % 1 ~= 0 then is_array = false break end
                if key > length then length = key end
            end
            if is_array then
                append("[")
                for index = 1, length do
                    if index > 1 then append(",") end
                    encode(item[index])
                end
                append("]")
            else
                append("{")
                local first = true
                for key, member in pairs(item) do
                    if not first then append(",") end
                    first = false
                    local name = tostring(key)
                    local token = keys[name]
                    if token == nil then token = '"' .. escape(name) .. '":'; keys[name] = token end
                    append(token)
                    encode(member)
                end
                append("}")
            end
            active[item] = nil
        else error("unsupported JSON type: " .. kind) end
    end
    encode(value)
    return table.concat(out)
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
