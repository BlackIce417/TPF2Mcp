local M = {}

local function normalize(path)
    if type(path) ~= "string" then return nil end
    path = string.gsub(path, "^@", "")
    path = string.gsub(path, "\\", "/")
    return path
end

local function module_path()
    if package and type(package.searchpath) == "function" and type(package.path) == "string" then
        local ok, value = pcall(package.searchpath, "tpf2_mcp/config", package.path)
        if ok and type(value) == "string" then return normalize(value) end
    end
    if debug and type(debug.getinfo) == "function" then
        local ok, info = pcall(debug.getinfo, 1, "S")
        if ok and type(info) == "table" then return normalize(info.source) end
    end
    return nil
end

local source = module_path()
M.mod_dir = source and string.match(source, "^(.*)/res/scripts/tpf2_mcp/config%.lua$") or nil
M.bridge_dir = M.mod_dir and (M.mod_dir .. "/bridge") or ""
M.module_path = source
M.path_resolution = M.mod_dir and "MODULE_SOURCE" or "UNAVAILABLE"
M.schema_version = 1
M.snapshot_schema_version = 5
M.snapshot_refresh_interval_seconds = 2
-- Publish the lightweight train-position frame independently of Bridge
-- commands so the map can follow moving trains without mailbox round trips.
M.vehicle_telemetry_report_interval_seconds = 0.2
-- Game-script update callbacks can be much more frequent than Bridge work.
M.bridge_poll_interval_updates = 5
-- Phase 11 safety boundary: writes are off unless a dedicated test save
-- explicitly enables them in the generated installation config.
M.allow_write_operations = false
M.allowed_operations = {}
M.write_kill_latched = false

local local_config_path = source and string.gsub(source, "config%.lua$", "local_config.lua") or nil

local function parse_permissions(content)
    if type(content) ~= "string" then return false, {} end
    local enabled = string.match(content, "M%.allow_write_operations%s*=%s*true") ~= nil
    local body = string.match(content, "M%.allowed_operations%s*=%s*{(.-)}")
    local operations = {}
    if type(body) == "string" then
        for name in string.gmatch(body, "([A-Z][A-Z0-9_]*)%s*=%s*true") do operations[name] = true end
    end
    return enabled, operations
end

-- Reload only the two generated permission fields.  Parsing a strict
-- whitelist keeps hot refresh from executing arbitrary Lua, and a missing or
-- partially written file fails closed.  Machine paths are never accepted.
function M.refresh_permissions()
    if M.write_kill_latched then
        M.allow_write_operations, M.allowed_operations = false, {}
        return false
    end
    local content = nil
    if type(local_config_path) == "string" and io and type(io.open) == "function" then
        local ok, file = pcall(io.open, local_config_path, "r")
        if ok and file ~= nil then
            local read_ok, value = pcall(file.read, file, "*a")
            pcall(file.close, file)
            if read_ok then content = value end
        end
    end
    M.allow_write_operations, M.allowed_operations = parse_permissions(content)
    return true
end

function M.disable_write_operations()
    M.write_kill_latched = true
    M.allow_write_operations, M.allowed_operations = false, {}
end

M.refresh_permissions()

return M
