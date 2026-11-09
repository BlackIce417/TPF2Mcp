-- Stable bootstrap. Updating this file itself requires a new game-script instance.
-- Only trusted, locally published read-side modules may be reloaded.
local config = require "tpf2_mcp/config"
local codec = require "tpf2_mcp/json"
local current = require "tpf2_mcp/runtime"
local M = {}
local modules = {
    "tpf2_mcp/collectors/common", "tpf2_mcp/json",
    "tpf2_mcp/collectors/signal_direction", "tpf2_mcp/collectors/signal_state",
    "tpf2_mcp/collectors/operational_telemetry", "tpf2_mcp/collectors/train_telemetry",
    "tpf2_mcp/state", "tpf2_mcp/runtime",
}
local allowed = {}
for _, name in ipairs(modules) do allowed[name] = true end
local initialized, last_poll, last_revision = false, nil, nil
local rollback = nil
local function now() return os and os.time and os.time() or 0 end
local function root()
    assert(type(config.bridge_dir) == "string" and config.bridge_dir ~= "", "bridge path unavailable")
    return config.bridge_dir .. "/hot-reload/"
end
local function read(path, limit)
    local file = io.open(path, "rb")
    if not file then return nil end
    local data = file:read(limit + 1)
    file:close()
    assert(data == nil or #data <= limit, "hot reload file too large")
    return data
end
local function status(state, revision, detail)
    local value = { protocol_version = 1, state = state, revision = revision,
        detail = detail, updated_at = now(), modules = modules }
    config.hot_reload_status = value
    -- Heartbeat is the primary status channel; this receipt is a convenience.
    pcall(function()
        local file = io.open(root() .. "status.json", "w")
        if file then file:write(codec.encode(value)); file:close() end
    end)
end
local function validate_runtime(runtime)
    assert(type(runtime) == "table" and runtime.hot_reload_protocol_version == 1,
        "runtime does not support hot reload v1")
    for _, key in ipairs({"tick", "load", "save", "set_track_resources", "export_reload_state", "import_reload_state"}) do
        assert(type(runtime[key]) == "function", "runtime missing " .. key)
    end
end
local function stage(request)
    assert(type(load) == "function", "Lua text loader unavailable in this game environment")
    assert(type(request.files) == "table", "missing module manifest")
    local sources, staged, loading = {}, {}, {}
    for name in pairs(request.files) do assert(allowed[name], "unsupported module: " .. tostring(name)) end
    -- Read all sources before evaluating any: a partially published bundle cannot activate.
    for _, name in ipairs(modules) do
        local expected = request.files[name]
        assert(type(expected) == "number" and expected >= 1 and expected <= 524288, "invalid module length: " .. name)
        local source = read(root() .. "bundles/" .. request.revision .. "/" .. name .. ".lua", 524288)
        assert(source and #source == expected, "missing or incomplete module: " .. name)
        sources[name] = source
    end
    local staged_require
    staged_require = function(name)
        if not allowed[name] then return require(name) end
        if staged[name] then return staged[name] end
        assert(not loading[name], "cyclic hot reload dependency: " .. name)
        loading[name] = true
        -- Isolate module globals/package.loaded while evaluating trusted project code.
        -- This is transactional loading, not a security sandbox.
        local loaded = setmetatable({}, {__index = function(_, key)
            return staged[key] or package.loaded[key]
        end})
        local env = setmetatable({require = staged_require, package = setmetatable({loaded = loaded}, {__index = package})},
            {__index = _G})
        env._G = env
        local chunk, err = load(sources[name], "@hot-reload/" .. name .. ".lua", "t", env)
        assert(chunk, err)
        local value = chunk()
        assert(type(value) == "table", "module did not return a table: " .. name)
        staged[name], loading[name] = value, nil
        return value
    end
    for _, name in ipairs(modules) do staged_require(name) end
    validate_runtime(staged["tpf2_mcp/runtime"])
    local telemetry = staged["tpf2_mcp/collectors/operational_telemetry"]
    assert(type(telemetry.import_reload_state) == "function", "collector cannot preserve session")
    assert(type(telemetry.export_reload_state) == "function", "collector cannot export session")
    telemetry.import_reload_state(require("tpf2_mcp/collectors/operational_telemetry").export_reload_state())
    staged["tpf2_mcp/runtime"].import_reload_state(current.export_reload_state())
    return staged
end
local function apply(request)
    assert(request.protocol_version == 1, "unsupported hot reload protocol")
    assert(type(request.revision) == "string" and #request.revision == 32
        and request.revision:match("^[0-9a-f]+$"), "invalid revision")
    local staged = stage(request)
    local previous = {runtime = current, loaded = {}, revision = request.revision}
    for _, name in ipairs(modules) do previous.loaded[name] = package.loaded[name] end
    for _, name in ipairs(modules) do package.loaded[name] = staged[name] end
    current, rollback = staged["tpf2_mcp/runtime"], previous
    status("VALIDATING_RUNTIME", request.revision, "modules switched; awaiting first successful callback")
end
local function poll()
    local clock = now()
    if last_poll and clock >= last_poll and clock - last_poll < 2 then return end
    last_poll = clock
    local raw = read(root() .. "request.json", 16384)
    local request = raw and codec.decode(raw) or nil
    if not initialized then
        initialized = true
        -- Never replay a prior session's request or silently downgrade on game load.
        last_revision = type(request) == "table" and request.revision or nil
        status("READY", nil, "bootstrap active; awaiting a new revision")
        return
    end
    if type(request) ~= "table" or request.revision == last_revision then return end
    last_revision = request.revision
    local ok, err = pcall(apply, request)
    if not ok then status("REJECTED", request.revision, tostring(err)) end
end
function M.tick()
    local ok, err = pcall(poll)
    if not ok then status("POLL_ERROR", last_revision, tostring(err)) end
    if not rollback then return current.tick() end
    local ran, failure = pcall(current.tick)
    if ran then
        if not rollback.confirmed then
            rollback.confirmed = true
            status("APPLIED", rollback.revision, "module validation and first callback passed")
        end
        return
    end
    local previous = rollback
    -- Preserve consumed request IDs/counters to avoid replaying commands after an error.
    local exported, runtime_state = pcall(current.export_reload_state)
    local imported = exported and pcall(previous.runtime.import_reload_state, runtime_state)
    if not imported then error("cannot safely roll back runtime: " .. tostring(failure)) end
    local active_telemetry = package.loaded["tpf2_mcp/collectors/operational_telemetry"]
    local telemetry_ok, telemetry_state = pcall(active_telemetry.export_reload_state)
    if telemetry_ok then
        pcall(previous.loaded["tpf2_mcp/collectors/operational_telemetry"].import_reload_state, telemetry_state)
    end
    for name, value in pairs(previous.loaded) do package.loaded[name] = value end
    current, rollback = previous.runtime, nil
    status("ROLLED_BACK", previous.revision, tostring(failure))
    -- Do not execute another tick in the same callback (watchdogs/commands may have run).
end
function M.load(value) return current.load(value) end
function M.save() return current.save() end
function M.set_track_resources(entries) return current.set_track_resources(entries) end
return M
