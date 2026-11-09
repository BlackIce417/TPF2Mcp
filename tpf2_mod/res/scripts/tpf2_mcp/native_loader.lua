local config = require "tpf2_mcp/config"

local M = { available = false, abi_version = 2 }
local functions = {}

local function load_export(name)
    if not package or type(package.loadlib) ~= "function" then return nil, "package.loadlib unavailable" end
    if type(config.mod_dir) ~= "string" or config.mod_dir == "" then return nil, "mod directory unavailable" end
    local path = config.mod_dir .. "/native/tpf2_loader.dll"
    local ok, fn, detail = pcall(package.loadlib, path, name)
    if not ok then return nil, tostring(fn) end
    if type(fn) ~= "function" then return nil, tostring(detail or "export unavailable") end
    return fn
end

for _, name in ipairs({
    "luaopen_tpf2_loader",
    "tpf2_loader_lua_publish_json",
    "tpf2_loader_lua_publish_binary",
    "tpf2_loader_lua_network_refresh_due",
}) do
    local fn, err = load_export(name)
    if fn == nil then M.error = name .. ": " .. tostring(err); return M end
    functions[name] = fn
end

local started, start_error = pcall(functions.luaopen_tpf2_loader)
if not started then M.error = tostring(start_error); return M end
M.available = true

function M.publish_json(key, encoded)
    if not M.available or type(key) ~= "string" or type(encoded) ~= "string" then return false end
    local ok, value = pcall(functions.tpf2_loader_lua_publish_json, key, encoded)
    return ok and value == true
end

function M.publish_binary(key, encoded)
    if not M.available or type(key) ~= "string" or type(encoded) ~= "string" then return false end
    local ok, value = pcall(functions.tpf2_loader_lua_publish_binary, key, encoded)
    return ok and value == true
end

function M.network_refresh_due()
    if not M.available then return false end
    local ok, value = pcall(functions.tpf2_loader_lua_network_refresh_due)
    return ok and value == true
end

return M
