-- Safe discovery only: inspect callable shapes, never invoke a write API.
local M = {}

local function kind(value)
    return type(value)
end

function M.probe()
    local interface = game and game.interface or nil
    local command_api = api and api.cmd or nil
    return {
        probe_kind = "READ_ONLY_INTROSPECTION",
        write_command_sent = false,
        game_interface = kind(interface),
        game_interface_set_name = kind(interface and interface.setName),
        api_cmd = kind(command_api),
        api_cmd_send_command = kind(command_api and command_api.sendCommand),
        api_cmd_make = kind(command_api and command_api.make),
        limitations = { "Function presence does not prove an API is safe or usable.", "No write function is called by this probe." },
    }
end

return M
