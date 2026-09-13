local config = require "tpf2_mcp/config"
local json = require "tpf2_mcp/json"
local state = require "tpf2_mcp/state"
local operations = require "tpf2_mcp/operations/dispatcher"

local M = {}
local last_request_id = nil
local sequence = 0
local probe = { attempted = false }
local started = false
local update_count = 0

local function path(name)
    if type(config.bridge_dir) ~= "string" or config.bridge_dir == "" then return nil end
    return config.bridge_dir .. "/" .. name
end
local function now() return os and os.time and os.time() or 0 end

local function read_file(name)
    if not io or type(io.open) ~= "function" then return nil, "io.open unavailable" end
    local target = path(name)
    if target == nil then return nil, "bridge directory unavailable" end
    local handle, err = io.open(target, "r")
    if not handle then return nil, err end
    local content = handle:read("*a")
    handle:close()
    return content
end

local function write_file(name, content)
    if not io or type(io.open) ~= "function" then return false, "io.open unavailable" end
    local target = path(name)
    if target == nil then return false, "bridge directory unavailable" end
    local handle, err = io.open(target, "w")
    if not handle then return false, err end
    handle:write(content)
    handle:flush()
    handle:close()
    return true
end

local function write_json(name, object)
    local ok, encoded = pcall(json.encode, object)
    if not ok then return false, encoded end
    return write_file(name, encoded)
end

local function log(level, message)
    print("[tpf2-mcp][" .. level .. "] " .. message)
end

local function probe_call(result, key, fn)
    local call_ok, value, detail = pcall(fn)
    result[key] = call_ok and value == true
    if not result[key] then result[key .. "_error"] = tostring(detail or value) end
end

local function raw_write(name, content)
    if not io or type(io.open) ~= "function" then return false, "io.open unavailable" end
    local target = path(name)
    if target == nil then return false, "bridge directory unavailable" end
    local handle, err = io.open(target, "w")
    if not handle then return false, err end
    handle:write(content)
    handle:close()
    return true
end

local function run_probe()
    local result = {
        attempted = true, lua_version = _VERSION or "UNKNOWN", require = false,
        io_open = false, io_read = false, io_write = false, os_rename = false,
        os_remove = false, absolute_path = false, path_resolved = false,
        api = false, api_engine = false,
        get_world = false, get_player = false,
    }
    probe_call(result, "require", function()
        local loaded = require "tpf2_mcp/config"
        return type(loaded) == "table"
    end)
    probe_call(result, "io_open", function() return io and type(io.open) == "function" end)
    probe_call(result, "absolute_path", function()
        local candidate = path("probe-absolute.tmp")
        if not candidate:match("^[A-Za-z]:/") then return false, "bridge path is not an absolute drive path" end
        return raw_write("probe-absolute.tmp", "absolute")
    end)
    result.path_resolved = config.path_resolution == "MODULE_SOURCE"
        and type(config.mod_dir) == "string" and config.mod_dir ~= ""
        and type(config.bridge_dir) == "string" and config.bridge_dir ~= ""
    probe_call(result, "io_write", function() return raw_write("probe-write.tmp", "tpf2-mcp probe\n") end)
    probe_call(result, "io_read", function()
        local content, err = read_file("probe-write.tmp")
        if content ~= "tpf2-mcp probe\n" then return false, err end
        return true
    end)
    probe_call(result, "os_rename", function()
        if not os or type(os.rename) ~= "function" then return false, "os.rename unavailable" end
        local written, err = raw_write("probe-rename-source.tmp", "rename")
        if not written then return false, err end
        local renamed, rename_err = os.rename(path("probe-rename-source.tmp"), path("probe-rename-target.tmp"))
        if not renamed then return false, rename_err end
        return true
    end)
    probe_call(result, "os_remove", function()
        if not os or type(os.remove) ~= "function" then return false, "os.remove unavailable" end
        local written, err = raw_write("probe-remove.tmp", "remove")
        if not written then return false, err end
        local removed, remove_err = os.remove(path("probe-remove.tmp"))
        if not removed then return false, remove_err end
        return true
    end)
    probe_call(result, "api", function() return api ~= nil end)
    probe_call(result, "api_engine", function() return api and api.engine ~= nil end)
    probe_call(result, "get_world", function()
        local world = api.engine.util.getWorld()
        return world ~= nil
    end)
    probe_call(result, "get_player", function()
        local player = api.engine.util.getPlayer()
        return player ~= nil
    end)
    probe = result
    return result
end

local function heartbeat()
    return {
        schema_version = config.schema_version,
        game_running = true,
        -- The live TPF2 sandbox has no os.rename/os.remove. Lua writes each
        -- response once under its request ID, then writes a ready marker.
        -- TPF2 may report the loaded module path relative to the game root.
        -- Successful read/write is the authoritative check that the resolved
        -- per-Mod bridge directory is usable; a drive-letter path is optional.
        bridge_ready = probe.io_read and probe.io_write and probe.path_resolved,
        bridge_dir = config.bridge_dir,
        mod_dir = config.mod_dir,
        module_path = config.module_path,
        path_resolution = config.path_resolution,
        snapshot_seq = sequence,
        last_update = now(),
        probe = probe,
    }
end

local function response(request_id, ok, result, error)
    return { schema_version = config.schema_version, request_id = request_id, ok = ok, result = result, error = error, timestamp = now() }
end

local function write_response(request_id, ok, result, error)
    local response_name = "responses/" .. request_id .. ".json"
    local written, write_err = write_json(response_name, response(request_id, ok, result, error))
    if not written then return false, write_err end
    return write_file("responses/" .. request_id .. ".ready", "ready\n")
end

local function validate_command(command)
    if type(command) ~= "table" then return false, "INVALID_REQUEST", "command must be an object" end
    if command.schema_version == nil or command.request_id == nil or command.command == nil or command.params == nil then
        return false, "INVALID_REQUEST", "schema_version, request_id, command, and params are required"
    end
    if command.schema_version ~= config.schema_version then
        return false, "UNSUPPORTED_SCHEMA_VERSION", "unsupported schema version: " .. tostring(command.schema_version)
    end
    if type(command.request_id) ~= "string" or command.request_id == "" then return false, "INVALID_REQUEST", "request_id must be a non-empty string" end
    if type(command.command) ~= "string" then return false, "INVALID_REQUEST", "command must be a string" end
    if type(command.params) ~= "table" then return false, "INVALID_REQUEST", "params must be an object" end
    if command.command ~= "ping" and command.command ~= "get_game_state" and command.command ~= "get_towns" and command.command ~= "get_town" and command.command ~= "get_rail_network" and command.command ~= "get_operational_telemetry" and command.command ~= "get_line_demand" and command.command ~= "get_vehicle_dispatch_state" and command.command ~= "get_timetable_status" and command.command ~= "execute_operation" then return false, "UNKNOWN_COMMAND", command.command end
    return true
end

local function handle(command)
    if command.command == "ping" then return true, { message = "pong", snapshot_seq = sequence } end
    if command.command == "get_game_state" then
        sequence = sequence + 1
        local force_refresh = command.params.force_refresh == true
        local snapshot = state.snapshot(sequence, force_refresh)
        local ok, err = write_json("state.json", snapshot)
        if not ok then return false, nil, { code = "STATE_WRITE_FAILED", message = tostring(err) } end
        -- Standalone engineering probe; it is intentionally outside the normal
        -- snapshot schema and contains only safe component metadata.
        write_json("company-probe.json", state.company_probe())
        write_json("semantic-probe.json", state.semantic_probe())
        write_json("operations-probe.json", state.operations_probe())
        write_json("ui-source-probe.json", state.ui_source_probe())
        write_json("context-probe.json", state.context_probe())
        write_json("dynamic-transport-probe.json", state.dynamic_probe())
        write_json("write-api-probe.json", state.write_api_probe())
        write_json("vehicle-write-api-probe.json", state.vehicle_write_probe())
        write_json("line-raw-probe.json", state.line_raw_probe())
        write_json("line-creation-probe.json", state.line_creation_probe())
        write_json("api-type-inventory.json", state.api_type_inventory())
        write_json("api-command-inventory.json", state.api_command_inventory())
        write_json("station-geometry.json", state.station_geometry())
        return true, snapshot
    end
    if command.command == "get_towns" then
        return true, state.snapshot(sequence, false).towns
    end
    if command.command == "get_town" then
        local entity_id = command.params.entity_id
        if type(entity_id) ~= "number" then return false, nil, { code = "INVALID_REQUEST", message = "entity_id must be a number" } end
        for _, town in ipairs(state.snapshot(sequence, false).towns) do
            if town.entity_id == entity_id then return true, town end
        end
        return false, nil, { code = "ENTITY_NOT_FOUND", message = "town " .. tostring(entity_id) .. " not found" }
    end
    if command.command == "get_rail_network" then
        local network = state.rail_network()
        local ok, err = write_json("rail-network.json", network)
        if not ok then return false, nil, { code = "RAIL_NETWORK_WRITE_FAILED", message = tostring(err) } end
        return network.status == "OK", { status = network.status, source_status = network.source_status, counts = network.counts }, network.status == "OK" and nil or { code = "RAIL_NETWORK_FAILED", message = tostring(network.error) }
    end
    if command.command == "get_operational_telemetry" then
        local section = command.params.section or "inventory"
        if section ~= "inventory" and section ~= "signals" and section ~= "vehicles" and section ~= "vehicles_live" and section ~= "stations" then
            return false, nil, { code = "INVALID_REQUEST", message = "unsupported telemetry section: " .. tostring(section) }
        end
        write_json("operational-telemetry-progress.json", { status = "RUNNING", section = section, started_at = now() })
        log("INFO", "operational telemetry section started: " .. section)
        local telemetry = state.operational_telemetry(section)
        local file_name = "operational-telemetry-" .. section .. ".json"
        local ok, err = write_json(file_name, telemetry)
        if not ok then return false, nil, { code = "TELEMETRY_WRITE_FAILED", message = tostring(err) } end
        write_json("operational-telemetry-progress.json", { status = "COMPLETE", section = section, completed_at = now(), counts = telemetry.counts })
        log("INFO", "operational telemetry section completed: " .. section)
        local successful = telemetry.probe_kind == "UNIFIED_OPERATIONAL_TELEMETRY_DISCOVERY" or telemetry.probe_kind == "OPERATIONAL_VEHICLE_LIVE_FRAME"
        return successful, { section = section, file_name = file_name, source_status = telemetry.source_status, counts = telemetry.counts, duration_ms = telemetry.duration_ms, errors = telemetry.errors }, successful and nil or { code = "TELEMETRY_FAILED", message = tostring(telemetry.error) }
    end
    if command.command == "get_timetable_status" then
        local line_id = command.params.line_id
        if type(line_id) ~= "number" then return false, nil, { code = "INVALID_REQUEST", message = "line_id must be a number" } end
        return true, operations.timetable_status(line_id) or { line_id = line_id, enabled = false }
    end
    if command.command == "get_line_demand" then
        local line_id = command.params.line_id
        if type(line_id) ~= "number" then return false, nil, { code = "INVALID_REQUEST", message = "line_id must be a number" } end
        return true, state.line_demand(line_id, command.params.maximum_entities)
    end
    if command.command == "get_vehicle_dispatch_state" then
        local vehicle_id = command.params.vehicle_id
        if type(vehicle_id) ~= "number" then return false, nil, { code = "INVALID_REQUEST", message = "vehicle_id must be a number" } end
        local result = state.vehicle_dispatch_state(vehicle_id, command.params.maximum_entities)
        if result.status == "ENTITY_NOT_FOUND" then return false, nil, { code = "ENTITY_NOT_FOUND", message = "vehicle " .. tostring(vehicle_id) .. " not found" } end
        return true, result
    end
    if command.command == "execute_operation" then
        return operations.dispatch(command.params)
    end
    return false, nil, { code = "UNKNOWN_COMMAND", message = tostring(command.command) }
end

function M.start()
    if started then return end
    started = true
    run_probe()
    -- A command file is a mailbox slot, not a durable job queue.  Ignore the
    -- request already present when a save starts; otherwise a command that
    -- crashed or completed in the previous session is replayed automatically.
    local existing_content = read_file("command.json")
    if existing_content then
        local decoded_ok, existing = pcall(json.decode, existing_content)
        if decoded_ok and type(existing) == "table" and type(existing.request_id) == "string" then
            last_request_id = existing.request_id
            log("INFO", "ignored pre-existing bridge request: " .. last_request_id)
        end
    end
    local ok, err = write_json("heartbeat.json", heartbeat())
    if ok then log("INFO", "bridge probe completed") else log("ERROR", "cannot write heartbeat: " .. tostring(err)) end
end

function M.set_track_resources(entries)
    state.set_track_resources(entries)
end

function M.save() return operations.save_state() end
function M.load(value) operations.load_state(value) end

function M.tick()
    update_count = update_count + 1
    operations.tick()
    local poll_interval = tonumber(config.bridge_poll_interval_updates) or 5
    if poll_interval < 1 then poll_interval = 5 end
    if update_count % poll_interval ~= 0 then return end
    if not started then M.start() end
    local content, read_err = read_file("command.json")
    if content then
        local decoded_ok, command = pcall(json.decode, content)
        if not decoded_ok then
            log("WARN", "invalid command JSON: " .. tostring(command))
        else
            local valid, code, message = validate_command(command)
            local request_id = type(command.request_id) == "string" and command.request_id or ""
            if not valid then
                local written, write_err = write_response(request_id, false, nil, { code = code, message = message })
                if not written then log("ERROR", "cannot write validation response: " .. tostring(write_err)) end
            elseif command.request_id ~= last_request_id then
                last_request_id = command.request_id
                local ok, result, err = handle(command)
                local written, write_err = write_response(command.request_id, ok, result, err)
                if not written then log("ERROR", "cannot write response: " .. tostring(write_err)) end
            end
        end
    elseif read_err then
        -- A missing command is normal and intentionally not logged every tick.
    end
    write_json("heartbeat.json", heartbeat())
end

return M
