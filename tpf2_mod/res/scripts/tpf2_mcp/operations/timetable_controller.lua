local M = {}

local plans = {}
local vehicles = {}
local claims = {}
local last_error = nil

local function wall_time()
    return os and os.time and os.time() or 0
end

local function entity_number(value)
    return tonumber(tostring(value))
end

local function game_time_seconds()
    local ok_world, world = pcall(api.engine.util.getWorld)
    if not ok_world or world == nil then return nil end
    local ok_time, value = pcall(api.engine.getComponent, world, api.type.ComponentType.GAME_TIME)
    if not ok_time or value == nil or type(value.gameTime) ~= "number" then return nil end
    return value.gameTime / 1000
end

local function send(vehicle_id, manual, force_departure)
    local make_ok, command = pcall(api.cmd.make.setVehicleManualDeparture, vehicle_id, manual)
    if not make_ok or command == nil then return false end
    local send_ok = pcall(api.cmd.sendCommand, command, function(_, success)
        local state = vehicles[vehicle_id]
        if state ~= nil and state.manual == manual then state.command_confirmed = success == true end
        if success == true and force_departure == true then
            local force_ok, force = pcall(api.cmd.make.setVehicleShouldDepart, vehicle_id)
            if force_ok and force ~= nil then pcall(api.cmd.sendCommand, force, function() end) end
        end
    end)
    if send_ok then
        local state = vehicles[vehicle_id] or {}
        state.manual = manual
        state.command_confirmed = false
        state.updated_at = wall_time()
        vehicles[vehicle_id] = state
    end
    return send_ok
end

local function release(vehicle_id, state)
    if state ~= nil and state.manual == true then send(vehicle_id, false, true) end
    vehicles[vehicle_id] = nil
end

local function normalized_offsets(values, cycle)
    if type(values) ~= "table" then return nil end
    local result, seen = {}, {}
    for _, raw in ipairs(values) do
        local value = tonumber(raw)
        if value ~= nil and value >= 0 and value < cycle then
            value = math.floor(value * 10 + .5) / 10
            if not seen[value] then seen[value] = true; result[#result + 1] = value end
        end
    end
    table.sort(result)
    return #result > 0 and result or nil
end

local function validate(line_id, parameters)
    if type(line_id) ~= "number" or type(parameters) ~= "table" then return nil, "line_id and timetable parameters are required" end
    local cycle = tonumber(parameters.cycle_seconds)
    local epoch = tonumber(parameters.epoch_game_time_ms)
    if cycle == nil or cycle < 60 or cycle > 86400 or epoch == nil or epoch < 0 then return nil, "cycle_seconds 60..86400 and epoch_game_time_ms are required" end
    if type(parameters.stops) ~= "table" then return nil, "stops are required" end
    local stops = {}
    for _, value in ipairs(parameters.stops) do
        local index = type(value) == "table" and tonumber(value.stop_index) or nil
        local maximum = type(value) == "table" and tonumber(value.max_hold_seconds) or nil
        local offsets = type(value) == "table" and normalized_offsets(value.departure_offsets_seconds, cycle) or nil
        if index == nil or index < 0 or index % 1 ~= 0 or maximum == nil or maximum < 10 or maximum > 600 or offsets == nil then
            return nil, "each stop needs integer stop_index, departure offsets, and max_hold_seconds 10..600"
        end
        stops[index] = { stop_index = index, departure_offsets_seconds = offsets, max_hold_seconds = maximum }
    end
    if next(stops) == nil then return nil, "at least one scheduled stop is required" end
    return {
        line_id = line_id, enabled = parameters.enabled == true,
        cycle_seconds = cycle, epoch_game_time_ms = epoch,
        late_release_seconds = math.max(0, math.min(120, tonumber(parameters.late_release_seconds) or 30)),
        priority = type(parameters.priority) == "table" and parameters.priority or {}, stops = stops,
    }
end

local function external_timetable_active(line_id)
    local loaded, module = pcall(require, "celmi/timetables/timetable")
    if not loaded or type(module) ~= "table" or type(module.hasTimetable) ~= "function" then return false end
    local ok, active = pcall(module.hasTimetable, line_id)
    return ok and active == true
end

local function minimum_headway(stop, cycle)
    local offsets = stop.departure_offsets_seconds
    if #offsets == 1 then return cycle end
    local result = cycle
    for index, value in ipairs(offsets) do
        local following = offsets[index + 1] or offsets[1] + cycle
        result = math.min(result, following - value)
    end
    return result
end

local function target_key(value) return tostring(math.floor(value * 10 + .5)) end

local function next_target(plan, stop, current, vehicle_id)
    local cycle = plan.cycle_seconds
    local epoch = plan.epoch_game_time_ms / 1000
    local cycle_index = math.floor((current - epoch) / cycle)
    claims[plan.line_id] = claims[plan.line_id] or {}
    claims[plan.line_id][stop.stop_index] = claims[plan.line_id][stop.stop_index] or {}
    local stop_claims = claims[plan.line_id][stop.stop_index]
    for key, claim in pairs(stop_claims) do
        if claim.target < current - plan.late_release_seconds then stop_claims[key] = nil end
    end
    local separation = minimum_headway(stop, cycle)
    local last_release = stop.last_release_game_time
    local candidates = {}
    for window = -1, 2 do
        for _, offset in ipairs(stop.departure_offsets_seconds) do
            candidates[#candidates + 1] = epoch + (cycle_index + window) * cycle + offset
        end
    end
    table.sort(candidates)
    for _, target in ipairs(candidates) do
        if target >= current - plan.late_release_seconds then
            local late = target < current
            local actual = late and current or target
            local key = target_key(target)
            local release_gap_ok = last_release == nil or actual - last_release >= separation * .75
            if stop_claims[key] == nil and (not late or release_gap_ok) then
                stop_claims[key] = { vehicle_id = vehicle_id, target = target }
                return actual, key
            end
        end
    end
    return nil, nil
end

function M.apply(line_id, parameters)
    local plan, reason = validate(line_id, parameters)
    if plan == nil then return false, reason end
    if plan.enabled and external_timetable_active(line_id) then return false, "EXTERNAL_TIMETABLE_ALREADY_CONTROLS_LINE" end
    if plans[line_id] ~= nil and plans[line_id].enabled and not plan.enabled then M.clear(line_id) end
    plans[line_id] = plan
    return true, plan
end

function M.clear(line_id)
    plans[line_id] = nil
    claims[line_id] = nil
    for vehicle_id, state in pairs(vehicles) do
        if state.line_id == line_id then release(vehicle_id, state) end
    end
    return true
end

function M.controls_line(line_id)
    return plans[line_id] ~= nil and plans[line_id].enabled == true
end

function M.tick()
    local current = game_time_seconds()
    if current == nil then return end
    for line_id, plan in pairs(plans) do
        if plan.enabled == true then
            if external_timetable_active(line_id) then
                last_error = "EXTERNAL_TIMETABLE_CONFLICT_ON_LINE:" .. tostring(line_id)
                for vehicle_id, state in pairs(vehicles) do if state.line_id == line_id then release(vehicle_id, state) end end
                plan.enabled = false
            else
            local ok_list, line_vehicles = pcall(api.engine.system.transportVehicleSystem.getLineVehicles, line_id)
            if ok_list and line_vehicles ~= nil then
                for _, raw_vehicle_id in pairs(line_vehicles) do
                    local vehicle_id = entity_number(raw_vehicle_id)
                    if vehicle_id ~= nil then
                        local ok_component, component = pcall(api.engine.getComponent, vehicle_id, api.type.ComponentType.TRANSPORT_VEHICLE)
                        local stop_index = ok_component and component and tonumber(component.stopIndex) or nil
                        local in_station = ok_component and component and component.state == 2
                        local stop = stop_index ~= nil and plan.stops[stop_index] or nil
                        local state = vehicles[vehicle_id]
                        if in_station and stop ~= nil then
                            if state == nil or state.line_id ~= line_id or state.stop_index ~= stop_index or state.in_station ~= true then
                                local target, slot_key = next_target(plan, stop, current, vehicle_id)
                                local wait = target ~= nil and target - current or 0
                                state = { line_id = line_id, stop_index = stop_index, in_station = true, target_game_time = target, slot_key = slot_key, armed_at_wall_time = wall_time(), manual = false }
                                vehicles[vehicle_id] = state
                                if target ~= nil and wait >= .5 and wait <= stop.max_hold_seconds then
                                    send(vehicle_id, true, false)
                                else
                                    stop.last_release_game_time = current
                                    if slot_key ~= nil then claims[line_id][stop_index][slot_key] = nil end
                                end
                            end
                            state = vehicles[vehicle_id]
                            if state ~= nil and state.manual == true and current + .25 >= state.target_game_time then stop.last_release_game_time = current; release(vehicle_id, state) end
                            if state ~= nil and state.manual == true and wall_time() - (state.armed_at_wall_time or wall_time()) >= 600 then release(vehicle_id, state) end
                        elseif state ~= nil and state.line_id == line_id then
                            release(vehicle_id, state)
                        end
                    end
                end
            end
            end
        end
    end
end

function M.record_error(value) last_error = tostring(value) end

function M.status(line_id)
    local plan = plans[line_id]
    if plan == nil then return nil end
    local active = {}
    for vehicle_id, state in pairs(vehicles) do
        if state.line_id == line_id then active[#active + 1] = { vehicle_id = vehicle_id, stop_index = state.stop_index, target_game_time = state.target_game_time, manual = state.manual, command_confirmed = state.command_confirmed } end
    end
    return { controller_version = 2, line_id = line_id, enabled = plan.enabled, cycle_seconds = plan.cycle_seconds, epoch_game_time_ms = plan.epoch_game_time_ms, priority = plan.priority, active_vehicle_controls = active, last_error = last_error }
end

function M.save()
    return { plans = plans }
end

function M.load(value)
    plans = type(value) == "table" and type(value.plans) == "table" and value.plans or {}
    vehicles = {}
    claims = {}
end

return M
