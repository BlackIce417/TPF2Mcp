local common = require "tpf2_mcp/collectors/common"

local M = {}

function M.collect()
    local errors = {}
    local world_ok, world = pcall(api.engine.util.getWorld)
    if not world_ok or world == nil then
        return { source_status = "UNAVAILABLE", paused = nil, error = tostring(world) }, "unavailable"
    end
    local speed = common.safe_get_component(world, "GAME_SPEED", errors)
    local game_time = common.safe_get_component(world, "GAME_TIME", errors)
    local speedup = common.field(speed, "speedup")
    local paused = nil
    if type(speedup) == "number" then paused = speedup == 0 end
    local result = {
        source_status = "ENGINE_COMPONENT",
        speed_multiplier = type(speedup) == "number" and speedup or nil,
        paused = paused,
        millis_per_day = common.field(speed, "millisPerDay"),
        game_time = common.field(game_time, "gameTime"),
        game_time0 = common.field(game_time, "gameTime0"),
        tick_count = common.field(game_time, "tickCount"),
        update_count = common.field(game_time, "updateCount"),
        errors = errors,
    }
    return result, result.speed_multiplier ~= nil and "available" or "partial"
end

return M
