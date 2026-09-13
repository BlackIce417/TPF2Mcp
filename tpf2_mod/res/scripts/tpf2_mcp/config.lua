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
-- Game-script update callbacks can be much more frequent than Bridge work.
M.bridge_poll_interval_updates = 5
-- Phase 11 safety boundary: writes are off unless a dedicated test save
-- explicitly enables them in the generated installation config.
M.allow_write_operations = false
M.allowed_operations = {}

-- The local installer may provide safety switches, but never a machine path.
-- This file is deliberately absent from the Workshop/source package.
local local_ok, local_config = pcall(require, "tpf2_mcp/local_config")
if local_ok and type(local_config) == "table" then
    if type(local_config.allow_write_operations) == "boolean" then M.allow_write_operations = local_config.allow_write_operations end
    if type(local_config.allowed_operations) == "table" then M.allowed_operations = local_config.allowed_operations end
end

return M
