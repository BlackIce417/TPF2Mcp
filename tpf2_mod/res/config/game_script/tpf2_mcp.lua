function data()
    local runtime = require "tpf2_mcp/runtime"
    return {
        -- `load` is invoked repeatedly across UI and engine contexts. Starting
        -- file I/O here caused repeated Probe runs and log/CPU pressure.
        load = function(value) runtime.load(value) end,
        save = function() return runtime.save() end,
        -- Resource repositories are exposed in the GUI context, while the
        -- bridge collector runs in the simulation context.  Transfer the
        -- runtime track-id -> resource-file table once after loading a save.
        guiInit = function()
            local entries = {}
            local repository = api and api.res and api.res.trackTypeRep
            local get_all = repository and repository.getAll
            if get_all ~= nil then
                local ok, values = pcall(function() return get_all() end)
                if ok and values ~= nil then
                    for raw_index, file_name in pairs(values) do
                        local index = tonumber(raw_index)
                        if index ~= nil and type(file_name) == "string" then
                            local detail, speed_limit = nil, nil
                            local get = repository.get
                            if get ~= nil then
                                local detail_ok, value = pcall(function() return get(index) end)
                                if detail_ok then detail = value end
                            end
                            if detail ~= nil and type(detail.speedLimit) == "number" then speed_limit = detail.speedLimit end
                            entries[#entries + 1] = { track_type = index, file_name = file_name, speed_limit_mps = speed_limit }
                        end
                    end
                end
            end
            game.interface.sendScriptEvent("tpf2_mcp", "track_type_resources", { entries = entries })
        end,
        handleEvent = function(src, id, name, params)
            if id == "tpf2_mcp" and name == "track_type_resources" then
                runtime.set_track_resources(params and params.entries or {})
            end
        end,
        -- `update` is the engine callback; runtime.tick initializes once per
        -- engine script instance before polling the bridge.
        update = function() runtime.tick() end,
    }
end
