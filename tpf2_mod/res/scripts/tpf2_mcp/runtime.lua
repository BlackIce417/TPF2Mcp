local config = require "tpf2_mcp/config"
local json = require "tpf2_mcp/json"
local state = require "tpf2_mcp/state"
local operations = require "tpf2_mcp/operations/dispatcher"
local vehicle_direction = require "tpf2_mcp/operations/vehicle_reverse"
local common = require "tpf2_mcp/collectors/common"
local native_loader = require "tpf2_mcp/native_loader"
local train_telemetry = require "tpf2_mcp/collectors/train_telemetry"

local M = { hot_reload_protocol_version = 1 }
local last_request_id = nil
local sequence = 0
local probe = { attempted = false }
local started = false
local update_count = 0
local last_footprint_update, last_position_update, last_train_binary_update, last_train_identity_update = nil, nil, nil, nil
local train_wrapper_probe_published = false
local telemetry_performance = {}
local runtime_performance, last_train_binary_detail = {}, nil
local function timed(name, fn)
    local started_at = common.clock()
    fn()
    local elapsed = (common.clock() - started_at) * 1000
    local stats = runtime_performance[name] or { count = 0, total_ms = 0, max_ms = 0 }
    stats.count, stats.last_ms = stats.count + 1, elapsed
    stats.total_ms, stats.max_ms = stats.total_ms + elapsed, math.max(stats.max_ms, elapsed)
    runtime_performance[name] = stats
end
local world_publication = { status = "PENDING" }
local network_refresh_pending = true

local function interval_updates(value, fallback)
    value = tonumber(value)
    if value == nil or value ~= value or math.abs(value) == math.huge then value = fallback end
    if value <= 0 then return 0 end
    return math.max(1, math.ceil(value - 1e-9))
end

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
    local written, write_error = handle:write(content)
    -- close flushes the Lua stream; a separate flush immediately before it is redundant.
    local closed, close_error = handle:close()
    if not written then return false, write_error end
    if not closed then return false, close_error end
    return true
end

local function write_json(name, object)
    local started = common.clock()
    local ok, encoded = pcall(json.encode, object)
    local encoded_at = common.clock()
    if not ok then return false, encoded end
    local written, err
    if native_loader.available then
        written = native_loader.publish_json(name, encoded)
        if not written then err = "Loader shared-memory publication failed" end
    else
        written, err = write_file(name, encoded)
    end
    if name:match("^operational%-telemetry%-") and object.section then
        local stats = telemetry_performance[object.section] or {
            count = 0, failures = 0, max_cpu_ms = 0,
            timing_basis = "PROCESS_CPU_NOT_WALL_TIME",
        }
        local finished = common.clock()
        stats.count = stats.count + 1
        stats.failures = stats.failures + (written and 0 or 1)
        stats.collection_cpu_ms = tonumber(object.duration_ms) or 0
        stats.encode_cpu_ms = (encoded_at - started) * 1000
        stats.write_cpu_ms = (finished - encoded_at) * 1000
        stats.last_cpu_ms = stats.collection_cpu_ms + stats.encode_cpu_ms + stats.write_cpu_ms
        stats.max_cpu_ms = math.max(stats.max_cpu_ms, stats.last_cpu_ms)
        stats.bytes = #encoded
        telemetry_performance[object.section] = stats
    end
    return written, err
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
    if type(config.refresh_permissions) == "function" then config.refresh_permissions() end
    local allowed_operations = {}
    for operation_type, enabled in pairs(config.allowed_operations or {}) do
        if enabled == true then allowed_operations[#allowed_operations + 1] = operation_type end
    end
    table.sort(allowed_operations)
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
        allow_write_operations = config.allow_write_operations == true,
        lua_command_protocol = native_loader.commands_available and 2 or 0,
        world_catalog = world_publication,
        session_id = require("tpf2_mcp/collectors/operational_telemetry").session_id(),
        allowed_operations = allowed_operations,
        last_update = now(),
        telemetry_performance = telemetry_performance,
        hot_reload = config.hot_reload_status,
        probe = probe,
    }
end

local function response(request_id, ok, result, error)
    return { schema_version = config.schema_version, request_id = request_id, ok = ok, result = result, error = error, timestamp = now() }
end

local function write_response(request_id, ok, result, error)
    if native_loader.available then
        local value = response(request_id, ok, result, error)
        value.session_id = require("tpf2_mcp/collectors/operational_telemetry").session_id()
        return write_json("command-response.json", value)
    end
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
    if command.command ~= "ping" and command.command ~= "get_control_state" and command.command ~= "get_game_state" and command.command ~= "get_towns" and command.command ~= "get_town" and command.command ~= "get_rail_network" and command.command ~= "get_operational_telemetry" and command.command ~= "get_line_demand" and command.command ~= "get_vehicle_dispatch_state" and command.command ~= "get_timetable_status" and command.command ~= "execute_operation" then return false, "UNKNOWN_COMMAND", command.command end
    return true
end

local function handle(command)
    if command.params._expected_session_id ~= nil and command.params._expected_session_id ~= require("tpf2_mcp/collectors/operational_telemetry").session_id() then
        return false, nil, { code = "SESSION_CHANGED", message = "Command belongs to another save session" }
    end
    if command.command == "ping" then return true, { message = "pong", snapshot_seq = sequence } end
    if command.command == "get_control_state" then
        local params = command.params
        local value = { observed_at = now(), session_id = require("tpf2_mcp/collectors/operational_telemetry").session_id(), direction_control_protocol = 1 }
        if type(params.line_id) == "number" then
            local lines, status = require("tpf2_mcp/collectors/line").collect()
            if not status.ok then return false, nil, { code = "LINE_READ_FAILED", message = "line collection incomplete" } end
            for _, line in ipairs(lines) do if line.entity_id == params.line_id then value.line = line; break end end
            if value.line == nil then return false, nil, { code = "LINE_NOT_FOUND", message = tostring(params.line_id) } end
        elseif type(params.vehicle_id) == "number" then
            local errors = {}
            local vehicle = common.safe_get_component(params.vehicle_id, "TRANSPORT_VEHICLE", errors)
            if vehicle == nil or #errors > 0 then return false, nil, { code = "VEHICLE_NOT_FOUND", message = tostring(params.vehicle_id) } end
            value.vehicle = {
                entity_id = params.vehicle_id,
                name = common.name_from_component(common.safe_get_component(params.vehicle_id, "NAME", errors)),
                line_id = common.entity_id(common.field(vehicle, "line")),
                carrier = common.field(vehicle, "carrier"),
                raw_state = common.field(vehicle, "state"),
                raw_autoDeparture = common.field(vehicle, "autoDeparture"),
                raw_userStopped = common.field(vehicle, "userStopped"),
                departure_control = operations.departure_control(params.vehicle_id),
                movement_control = operations.movement_control(params.vehicle_id),
                direction_control = vehicle_direction.get_state(params.vehicle_id),
                stop_index = common.field(vehicle, "stopIndex"),
            }
        else return false, nil, { code = "INVALID_PARAMETERS", message = "line_id or vehicle_id required" } end
        return true, value
    end
    if command.command == "get_game_state" then
        sequence = sequence + 1
        local force_refresh = command.params.force_refresh == true or command.params.refresh_assets == true
        local snapshot = state.snapshot(sequence, force_refresh)
        snapshot.metadata = snapshot.metadata or {}
        snapshot.metadata.refresh_policy = "ON_DEMAND_ASSETS"
        local ok, err = write_json("state.json", snapshot)
        if not ok then return false, nil, { code = "STATE_WRITE_FAILED", message = tostring(err) } end
        if command.params.refresh_assets == true then network_refresh_pending = true end
        -- Expensive reverse-engineering probes are never part of normal reads.
        if command.params.include_diagnostics ~= true then return true, snapshot end
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
        if section == "station_demand_lines" then
            local station_id = command.params.station_id
            if type(station_id) ~= "number" or station_id <= 0 or station_id % 1 ~= 0 then
                return false, nil, { code = "INVALID_PARAMETERS", message = "Positive station_id required" }
            end
            return true, state.station_demand_lines(station_id)
        end
        if section == "line_demand" then
            local line_id, maximum = command.params.line_id, command.params.maximum_entities or 20000
            if type(line_id) ~= "number" or line_id <= 0 or line_id % 1 ~= 0
                or type(maximum) ~= "number" or maximum < 100 or maximum > 50000 or maximum % 1 ~= 0 then
                return false, nil, { code = "INVALID_PARAMETERS", message = "Positive line_id and maximum_entities 100..50000 required" }
            end
            return true, state.line_demand(line_id, maximum)
        end
        if section ~= "inventory" and section ~= "signals" and section ~= "signal_states" and section ~= "vehicles" and section ~= "vehicles_live" and section ~= "vehicle_positions" and section ~= "train_footprints" and section ~= "stations" then
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
        local successful = telemetry.probe_kind == "UNIFIED_OPERATIONAL_TELEMETRY_DISCOVERY" or telemetry.probe_kind == "OPERATIONAL_VEHICLE_LIVE_FRAME" or telemetry.probe_kind == "OPERATIONAL_VEHICLE_POSITION_FRAME" or telemetry.probe_kind == "OPERATIONAL_TRAIN_FOOTPRINT_FRAME"
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
        local control = command.params
        local expected = control._control_precondition
        if expected ~= nil then
            local errors, matches = {}, false
            local target, parameters = control.target or {}, control.parameters or {}
            if control.operation_type == "SET_LINE_STOP_POLICY" then
                local line = common.safe_get_component(target.line_id, "LINE", errors)
                local stops = common.sequence_values(common.field(line, "stops"))
                local stop = type(parameters.stop_index) == "number" and stops[parameters.stop_index + 1] or nil
                local policy = expected.policy or {}
                matches = stop ~= nil
                    and common.entity_id(common.field(stop, "stationGroup")) == expected.station_id
                    and common.field(stop, "station") == expected.station_index
                    and common.field(stop, "terminal") == expected.terminal_id
                    and common.field(stop, "loadMode") == policy.load_mode
                    and common.field(stop, "minWaitingTime") == policy.min_waiting_time
                    and common.field(stop, "maxWaitingTime") == policy.max_waiting_time
            else
                local vehicle = common.safe_get_component(target.vehicle_id, "TRANSPORT_VEHICLE", errors)
                local name = common.name_from_component(common.safe_get_component(target.vehicle_id, "NAME", errors))
                matches = vehicle ~= nil and name == expected.display_name
                    and common.field(vehicle, "carrier") == 1
                    and common.entity_id(common.field(vehicle, "line")) == expected.line_id
                if control.operation_type == "HOLD_VEHICLE_AT_TERMINAL" then
                    matches = matches and common.field(vehicle, "state") == 2
                end
            end
            if not matches or #errors > 0 then
                return false, nil, { code = "CONTROL_PRECONDITION_CHANGED", message = "Target changed since command preview" }
            end
        end
        if control.operation_type == "STOP_VEHICLE" and type(control.parameters) == "table"
            and control.parameters.reverse_after_stop == true then
            return vehicle_direction.stop_and_reverse(control)
        end
        return operations.dispatch(command.params)
    end
    return false, nil, { code = "UNKNOWN_COMMAND", message = tostring(command.command) }
end

local function report_live_vehicles_if_due()
    local interval = tonumber(config.vehicle_telemetry_report_interval_seconds) or 0.2
    local updates = interval_updates(config.vehicle_telemetry_report_interval_updates,
        interval_updates(interval / 0.2, 1))
    if updates == 0 then return end
    if last_position_update and update_count - last_position_update < updates then return end
    last_position_update = update_count
    local telemetry = state.operational_telemetry("vehicle_positions")
    telemetry.report_mode = "PERIODIC"
    telemetry.report_interval_seconds = updates * 0.2
    telemetry.report_interval_updates = updates
    telemetry.report_interval_basis = "SIMULATION_UPDATES_NOT_WALL_TIME"
    local ok, err = write_json("operational-telemetry-vehicle_positions.json", telemetry)
    if not ok then
        log("WARN", "cannot publish live vehicle telemetry: " .. tostring(err))
    end
end

local function report_train_footprints_if_due()
    local updates = interval_updates(config.train_footprint_report_interval_updates, 1)
    if updates == 0 then return end
    if last_footprint_update and update_count - last_footprint_update < updates then return end
    last_footprint_update = update_count
    local telemetry = state.operational_telemetry("train_footprints")
    telemetry.report_mode = "PERIODIC"
    telemetry.report_interval_seconds = updates * 0.2
    telemetry.report_interval_updates = updates
    telemetry.report_interval_basis = "SIMULATION_UPDATES_NOT_WALL_TIME"
    local ok, err = write_json("operational-telemetry-train_footprints.json", telemetry)
    if not ok then log("WARN", "cannot publish train footprints: " .. tostring(err)) end
end

local function report_train_binary_if_due()
    local updates = interval_updates(config.train_binary_report_interval_updates, 1)
    if updates == 0 then return end
    if last_train_binary_update and update_count - last_train_binary_update < updates then return end
    last_train_binary_update = update_count
    local ok, detail = train_telemetry.publish(update_count)
    last_train_binary_detail = detail
    if not ok then
        log("WARN", "cannot publish binary train wrappers: " .. tostring(detail and detail.error or "unknown error"))
        return
    end
    if not train_wrapper_probe_published and detail and detail.trains and detail.trains > 0 then
        local probe_ok, probe_error = write_json("train-wrapper-probe.json", train_telemetry.probe(4))
        if probe_ok then
            train_wrapper_probe_published = true
        else
            log("WARN", "cannot publish train wrapper probe: " .. tostring(probe_error))
        end
    end
end

local function report_train_identities_if_due()
    local updates = interval_updates(config.train_identity_report_interval_updates, 25)
    if updates == 0 then return end
    if last_train_identity_update and update_count - last_train_identity_update < updates then return end
    last_train_identity_update = update_count
    local ok, err = write_json("train-identities.json", train_telemetry.identities())
    if not ok then log("WARN", "cannot publish train identities: " .. tostring(err)) end
end

function M.start()
    if started then return end
    started = true
    run_probe()
    local ok, err = write_json("heartbeat.json", heartbeat())
    if ok then log("INFO", "bridge probe completed") else log("ERROR", "cannot write heartbeat: " .. tostring(err)) end
end

local function report_world_if_due()
    if world_publication.status == "PUBLISHED" then return end
    local current = now()
    local interval = math.min(30, 2 ^ math.min(5, world_publication.failures or 1))
    if world_publication.last_attempt and current >= world_publication.last_attempt
        and current - world_publication.last_attempt < interval then return end
    world_publication.last_attempt = current
    local session = require("tpf2_mcp/collectors/operational_telemetry").session_id()
    world_publication.session_id = session
    local ok, snapshot = pcall(state.snapshot, sequence + 1, true)
    if ok and type(snapshot) == "table" and snapshot.game and snapshot.game.status == "available"
        and snapshot.metadata and snapshot.metadata.session_id == session then
        snapshot.metadata.refresh_policy = "ON_DEMAND_ASSETS"
        local written, err = write_json("state.json", snapshot)
        if written then
            sequence = sequence + 1
            local complete = true
            for _, name in ipairs({"towns", "industries", "stations", "lines"}) do
                local status = (snapshot.metadata.collector_status or {})[name]
                if status and status.ok == false then complete = false end
            end
            world_publication.status = complete and "PUBLISHED" or "PARTIAL"
            world_publication.failures = complete and 0 or (world_publication.failures or 0) + 1
            world_publication.refresh_policy = "ON_DEMAND_ASSETS"
            world_publication.published_at = current
            world_publication.error = not complete and "Some world collectors are incomplete; retrying" or nil
            return
        end
        snapshot = err
    end
    world_publication.status = "RETRYING"
    world_publication.failures = (world_publication.failures or 0) + 1
    world_publication.error = ok and "World snapshot unavailable or not published" or tostring(snapshot)
    log("WARN", "world catalog publication will retry: " .. world_publication.error)
end

function M.set_track_resources(entries)
    state.set_track_resources(entries)
end

local function refresh_rail_network_if_due()
    if not native_loader.available then return end
    local due = native_loader.network_refresh_due()
    if not network_refresh_pending and not due then return end
    network_refresh_pending = false
    state.invalidate_rail_network()
    local network = state.rail_network()
    network.report_mode = "UNIFIED_PERIODIC_OR_EXPLICIT_REFRESH"
    -- Both inventories are captured in this game-thread callback. Consumers
    -- must match capture_id before combining them; it is not a disk filename.
    local session = require("tpf2_mcp/collectors/operational_telemetry").session_id()
    local capture_id = session .. ":" .. tostring(now()) .. ":" .. tostring(update_count)
    network.session_id = session
    network.capture_id = capture_id
    network.generated_at = now()
    local signals = state.operational_telemetry("signals")
    signals.session_id = session
    signals.capture_id = capture_id
    local ok, err = write_json("rail-network.json", network)
    if not ok then log("WARN", "cannot publish refreshed rail network: " .. tostring(err)) end
    local signals_ok, signals_err = write_json("operational-telemetry-signals.json", signals)
    if not signals_ok then log("WARN", "cannot publish refreshed signal inventory: " .. tostring(signals_err)) end
end

-- Only transient read-side state is transferred. The dispatcher/timetable
-- modules stay loaded, preserving watch-dogs, operation IDs and control leases.
function M.export_reload_state()
    return { version = 1, last_request_id = last_request_id, sequence = sequence,
        probe = probe, started = started, update_count = update_count,
        last_footprint_update = last_footprint_update, last_position_update = last_position_update,
        last_train_binary_update = last_train_binary_update,
        last_train_identity_update = last_train_identity_update,
        train_wrapper_probe_published = train_wrapper_probe_published,
        telemetry_performance = telemetry_performance, world_publication = world_publication,
        network_refresh_pending = network_refresh_pending }
end
function M.import_reload_state(value)
    assert(type(value) == "table" and value.version == 1, "incompatible runtime state")
    last_request_id, sequence = value.last_request_id, value.sequence
    probe, started, update_count = value.probe, value.started, value.update_count
    last_footprint_update, last_position_update = value.last_footprint_update, value.last_position_update
    last_train_binary_update = value.last_train_binary_update
    last_train_identity_update = value.last_train_identity_update
    train_wrapper_probe_published = value.train_wrapper_probe_published == true
    telemetry_performance = value.telemetry_performance
    world_publication = value.world_publication or { status = "PENDING" }
    if world_publication.refresh_policy ~= "ON_DEMAND_ASSETS" then
        world_publication = { status = "PENDING" }
    end
    network_refresh_pending = value.network_refresh_pending ~= false
end

function M.save() return operations.save_state() end
function M.load(value)
    require("tpf2_mcp/collectors/operational_telemetry").begin_session()
    state.reset_session()
    last_request_id, sequence, update_count = nil, 0, 0
    last_footprint_update, last_position_update, last_train_binary_update, last_train_identity_update = nil, nil, nil, nil
    train_wrapper_probe_published = false
    world_publication, network_refresh_pending = { status = "PENDING" }, true
    operations.load_state(value)
    if native_loader.available then
        -- Loader outlives the save. Invalidate its old heartbeat immediately,
        -- before the first update can publish the new world's inventories.
        local loading = heartbeat()
        loading.bridge_ready, loading.lifecycle = false, "LOADING"
        write_json("heartbeat.json", loading)
    end
end

function M.tick()
    local tick_started_at = common.clock()
    update_count = update_count + 1
    timed("operations", operations.tick)
    timed("direction", vehicle_direction.tick)
    if not started then M.start() end
    timed("network", refresh_rail_network_if_due)
    common.begin_read_frame()
    local operational = require("tpf2_mcp/collectors/operational_telemetry")
    local native_active, metadata_due = false, false
    if type(native_loader.native_telemetry_tick) == "function" then
        local world_ok, world = pcall(api.engine.util.getWorld)
        if world_ok then native_active, metadata_due = native_loader.native_telemetry_tick(operational.session_id(), world) end
    end
    if metadata_due then
        timed("native_metadata", function()
            local ok, detail = train_telemetry.publish(update_count, "native-train-seed.bin")
            last_train_binary_detail = detail
            if not ok then log("WARN", "cannot seed native train metadata: " .. tostring(detail and detail.error)) end
        end)
    end
    if not native_active then
        timed("vehicle_positions", report_live_vehicles_if_due)
        timed("train_footprints", report_train_footprints_if_due)
        timed("train_binary", report_train_binary_if_due)
    end
    timed("train_identities", report_train_identities_if_due)
    common.end_read_frame()
    timed("world", report_world_if_due)
    -- Stagger state sampling from full train bodies. Five simulation updates
    -- is a nominal cadence, not a guaranteed wall-clock sampling rate.
    local signal_updates = interval_updates(config.signal_state_report_interval_updates, 5)
    if signal_updates > 0 and update_count % signal_updates == 2 % signal_updates then
        local telemetry = state.operational_telemetry("signal_states")
        telemetry.report_mode = "PERIODIC"
        telemetry.report_interval_updates = signal_updates
        telemetry.report_interval_basis = "SIMULATION_UPDATES_NOT_WALL_TIME"
        local ok, err = write_json("operational-telemetry-signal_states.json", telemetry)
        if not ok then log("WARN", "cannot publish signal states: " .. tostring(err)) end
    end
    -- The Loader owns opcode parsing and the native mailbox. Lua is only
    -- entered here, on the engine's callback thread, never on an IPC worker.
    local command, token, poll_error
    if native_loader.commands_available then command, token, poll_error = native_loader.poll_command() end
    if poll_error then log("WARN", "Loader command rejected: " .. tostring(poll_error)) end
    if command then
        local ran, failure = pcall(function()
            if type(config.refresh_permissions) == "function" then config.refresh_permissions() end
            local valid, code, message = validate_command(command)
            local request_id = type(command.request_id) == "string" and command.request_id or ""
            if not valid then
                write_response(request_id, false, nil, { code = code, message = message })
            elseif request_id ~= last_request_id then
                last_request_id = request_id
                local ok, result, err = handle(command)
                local written, write_err = write_response(request_id, ok, result, err)
                if not written then error(tostring(write_err)) end
            else
                write_response(request_id, false, nil, { code = "DUPLICATE_REQUEST", message = "Use a new transport request ID" })
            end
        end)
        if not ran then
            log("ERROR", "Loader command failed: " .. tostring(failure))
            pcall(write_response, command.request_id or "", false, nil, { code = "LUA_COMMAND_FAILED", message = tostring(failure) })
        end
        native_loader.finish_command(token)
    end
    local poll_interval = tonumber(config.bridge_poll_interval_updates) or 5
    if poll_interval < 1 then poll_interval = 5 end
    if update_count % poll_interval ~= 0 then return end
    write_json("heartbeat.json", heartbeat())
    -- Separate channel: GUI load callbacks must not overwrite simulation timings.
    write_json("runtime-performance.json", { schema_version = 1, generated_at = now(),
        session_id = require("tpf2_mcp/collectors/operational_telemetry").session_id(),
        timing_basis = "LUA_OS_CLOCK", update_count = update_count,
        tick_last_ms = (common.clock() - tick_started_at) * 1000,
        stages = runtime_performance, telemetry = telemetry_performance,
        train_binary = last_train_binary_detail })
end

return M
