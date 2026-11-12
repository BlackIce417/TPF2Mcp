local config = require "tpf2_mcp/config/settings"

local M = { available = false, abi_version = 3, commands_available = false }
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
    "tpf2_loader_lua_command_poll",
    "tpf2_loader_lua_command_read",
    "tpf2_loader_lua_command_finish",
}) do
    local fn, err = load_export(name)
    if fn == nil then M.error = name .. ": " .. tostring(err); return M end
    functions[name] = fn
end

local started, start_error = pcall(functions.luaopen_tpf2_loader)
if not started then M.error = tostring(start_error); return M end
M.available = true
M.commands_available = true

-- Optional until the process-lifetime Loader has been replaced on restart.
local native_tick = load_export("tpf2_loader_lua_native_telemetry_tick")
function M.native_telemetry_tick(session, world_entity)
    if type(native_tick) ~= "function" then return false, false end
    local ok, active, metadata_due = pcall(native_tick, session, world_entity)
    return ok and active == 1, ok and metadata_due == 1
end

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

local commands = {
    [1] = {"ping"}, [2] = {"get_control_state"}, [3] = {"get_game_state"},
    [4] = {"get_operational_telemetry"},
    [0x101] = {"execute_operation", "SET_LINE_STOP_POLICY"},
    [0x102] = {"execute_operation", "HOLD_VEHICLE_AT_TERMINAL"},
    [0x103] = {"execute_operation", "RELEASE_VEHICLE_FROM_HOLD"},
    [0x104] = {"execute_operation", "STOP_VEHICLE"},
    [0x105] = {"execute_operation", "START_VEHICLE"},
    [0x106] = {"execute_operation", "ADD_LINE_STOP_PLATFORM"},
    [0x107] = {"execute_operation", "REMOVE_LINE_STOP_PLATFORM"},
}

function M.finish_command(token)
    if not M.commands_available then return false end
    local ok, value = pcall(functions.tpf2_loader_lua_command_finish, token)
    return ok and value == true
end

function M.poll_command()
    if not M.commands_available then return nil end
    local ok, opcode, size, token = pcall(functions.tpf2_loader_lua_command_poll)
    if not ok then return nil, nil, tostring(opcode) end
    if opcode == nil then return nil end
    local decoded, command = pcall(function()
        assert(commands[opcode] and type(size) == "number" and size > 0 and size <= 16384, "invalid native command")
        local chunks = {}
        for offset = 0, size - 1, 48 do
            local words = {functions.tpf2_loader_lua_command_read(offset)}
            assert(#words == 8, "native command read failed")
            local bytes = {}
            for index, word in ipairs(words) do
                for byte = 0, 5 do
                    if offset + (index - 1) * 6 + byte < size then
                        bytes[#bytes + 1] = word % 256
                        word = math.floor(word / 256)
                    end
                end
            end
            chunks[#chunks + 1] = string.char((table.unpack or unpack)(bytes))
        end
        local value = require("tpf2_mcp/codecs/json").decode(table.concat(chunks))
        assert(type(value) == "table" and value.command == commands[opcode][1], "opcode/command mismatch")
        assert(type(value.params) == "table" and type(value.params._expected_session_id) == "string", "session required")
        if commands[opcode][2] then
            assert(value.params.operation_type == commands[opcode][2], "opcode/operation mismatch")
        end
        return value
    end)
    if not decoded then M.finish_command(token); return nil, nil, tostring(command) end
    return command, token
end

return M
