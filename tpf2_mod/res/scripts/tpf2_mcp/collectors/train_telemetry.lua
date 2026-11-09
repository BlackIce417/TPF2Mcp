local binary = require "tpf2_mcp/binary"
local common = require "tpf2_mcp/collectors/common"
local native_loader = require "tpf2_mcp/native_loader"

local M = {}
local FRAME_MAGIC = 0x52545054
local FRAME_HEADER_SIZE, TRAIN_SIZE, PART_SIZE = 72, 220, 224
local PASSENGER_SIZE, FREIGHT_SIZE = 12, 24
local PART_POWERED, PART_PASSENGER, PART_CARGO = 1, 4, 8
local PART_ROLE_VERIFIED, PART_CARGO_VERIFIED = 65536, 131072
local TRAIN_PASSENGER, TRAIN_FREIGHT, TRAIN_MIXED = 1, 2, 4
local TRAIN_PARTS_COMPLETE, TRAIN_CARGO_COMPLETE = 65536, 131072
local nan = 0 / 0
local model_cache, cargo_weight_cache, track_speed_cache, motion_cache = {}, {}, {}, {}

local function number(value, fallback)
    return type(value) == "number" and value == value and value or fallback
end

local function observed(value)
    return type(value) == "number" and value == value and math.abs(value) ~= math.huge and value or nil
end

local function entity_id(value)
    return common.entity_id(value) or 0
end

local function coordinates(value)
    if value == nil then return nil end
    local x, y, z = common.field(value, "x"), common.field(value, "y"), common.field(value, "z")
    if type(x) ~= "number" or type(y) ~= "number" then return nil end
    return { x = x, y = y, z = type(z) == "number" and z or 0 }
end

local function model_coordinates(value)
    local direct = coordinates(value)
    if direct ~= nil then return direct end
    local values = common.sequence_values(value)
    if type(values[1]) ~= "number" or type(values[2]) ~= "number" then return nil end
    return { x = values[1], y = values[2], z = type(values[3]) == "number" and values[3] or 0 }
end

local function bounds_for(entity, errors)
    local volume = common.safe_get_component(entity, "BOUNDING_VOLUME", errors)
    local box = common.field(volume, "bbox")
    local minimum = coordinates(common.field(box, "min")) or coordinates(common.field(box, "bbMin"))
    local maximum = coordinates(common.field(box, "max")) or coordinates(common.field(box, "bbMax"))
    if minimum == nil or maximum == nil then return nil, nil end
    return {
        x = (minimum.x + maximum.x) * 0.5,
        y = (minimum.y + maximum.y) * 0.5,
        z = (minimum.z + maximum.z) * 0.5,
    }, { min = minimum, max = maximum }
end

local function model_descriptor(model_id)
    if model_cache[model_id] ~= nil then return model_cache[model_id] end
    local result = {
        length = nan, width = nan, height = nan, empty_weight = nan,
        top_speed = nan, power = nan, tractive_effort = nan, flags = 0,
    }
    local repository = api and api.res and api.res.modelRep
    local ok, model = false, nil
    if repository and repository.get then ok, model = pcall(function() return repository.get(model_id) end) end
    if not ok then model_cache[model_id] = result; return result end
    local bounds = common.field(model, "boundingInfo")
    local minimum = model_coordinates(common.field(bounds, "bbMin"))
    local maximum = model_coordinates(common.field(bounds, "bbMax"))
    if minimum ~= nil and maximum ~= nil then
        result.length = maximum.x - minimum.x
        result.width = maximum.y - minimum.y
        result.height = maximum.z - minimum.z
    end
    local metadata = common.field(model, "metadata")
    local rail = common.field(metadata, "railVehicle")
    if rail ~= nil then
        result.flags = result.flags + PART_ROLE_VERIFIED
        result.empty_weight = number(common.field(rail, "weight"), nan)
        result.top_speed = number(common.field(rail, "topSpeed"), nan)
        local engines = common.field(rail, "engines") or common.field(rail, "engine")
        local engine = common.sequence_values(engines)[1] or engines
        local power = number(common.field(engine, "power"), nil)
        local effort = number(common.field(engine, "tractiveEffort"), nil)
        if power ~= nil or effort ~= nil then
            result.flags = result.flags + PART_POWERED
            result.power = power or nan
            result.tractive_effort = effort or nan
        end
    end
    local transport = common.field(metadata, "transportVehicle")
    for _, compartment in ipairs(common.sequence_values(common.field(transport, "compartmentsList"))) do
        for _, load_config in ipairs(common.sequence_values(common.field(compartment, "loadConfigs"))) do
            for _, entry in ipairs(common.sequence_values(common.field(load_config, "cargoEntries"))) do
                local cargo_type = common.field(entry, "type")
                if cargo_type == "PASSENGERS" then
                    if result.flags % (PART_PASSENGER * 2) < PART_PASSENGER then result.flags = result.flags + PART_PASSENGER end
                else
                    if result.flags % (PART_CARGO * 2) < PART_CARGO then result.flags = result.flags + PART_CARGO end
                end
            end
        end
    end
    model_cache[model_id] = result
    return result
end

local function cargo_unit_weight(cargo_id)
    if cargo_weight_cache[cargo_id] ~= nil then return cargo_weight_cache[cargo_id] end
    local repository = api and api.res and api.res.cargoTypeRep
    local ok, cargo = false, nil
    if repository and repository.get then ok, cargo = pcall(function() return repository.get(cargo_id) end) end
    local weight = ok and number(common.field(cargo, "weight"), nan) or nan
    cargo_weight_cache[cargo_id] = weight
    return weight
end

local function cargo_id(entry, fallback)
    local value = common.field(entry, "cargoTypeId") or common.field(entry, "cargoType") or common.field(entry, "cargo") or common.field(entry, "type")
    if type(value) == "number" then return value end
    if value == "PASSENGERS" then return 0 end
    if type(value) == "string" then
        local repository = api and api.res and api.res.cargoTypeRep
        local ok, found = false, nil
        if repository and repository.find then ok, found = pcall(function() return repository.find(value) end) end
        if ok and type(found) == "number" and found >= 0 then return found end
    end
    return fallback
end

local function load_rows(info, part_count)
    local by_part, passengers, freight = {}, {}, {}
    for index = 1, part_count do by_part[index] = { passengers = {}, freight = {}, verified = false } end
    local groups = common.sequence_values(common.field(info, "cargoInfos"))
    local aligned, complete = #groups == part_count, #groups == part_count
    for part_index, compartments in ipairs(groups) do
        if part_index <= part_count then
            for compartment_index, cargo_types in ipairs(common.sequence_values(compartments)) do
                for cargo_index, entry in ipairs(common.sequence_values(cargo_types)) do
                    local raw_amount = common.field(entry, "amount") or common.field(entry, "load") or common.field(entry, "count")
                    local amount = number(raw_amount, 0)
                    local capacity = number(common.field(entry, "capacity"), 0)
                    if capacity > 0 and type(raw_amount) ~= "number" then complete = false end
                    local id = cargo_id(entry, cargo_index - 1)
                    -- The live API exposes a fixed cargo-type vector for each
                    -- compartment. Empty unsupported entries have neither
                    -- capacity nor an observed amount and must not become
                    -- thousands of meaningless freight records.
                    local supported = capacity > 0 or type(raw_amount) == "number"
                    if supported and id == 0 then
                        local row = { compartment = compartment_index - 1, amount = amount, capacity = capacity }
                        passengers[#passengers + 1] = row
                        by_part[part_index].passengers[#by_part[part_index].passengers + 1] = row
                    elseif supported then
                        local unit_weight = cargo_unit_weight(id)
                        local row = { cargo_id = id, compartment = compartment_index - 1, config = 0,
                            amount = amount, capacity = capacity, unit_weight = unit_weight,
                            weight = unit_weight == unit_weight and amount * unit_weight or nan }
                        freight[#freight + 1] = row
                        by_part[part_index].freight[#by_part[part_index].freight + 1] = row
                    end
                end
            end
        end
    end
    for index = 1, part_count do by_part[index].verified = aligned and complete end
    return by_part, passengers, freight, aligned and complete
end

local function game_time_seconds()
    local util = api and api.engine and api.engine.util
    if util == nil or util.getWorld == nil then return nil end
    local ok, world = pcall(util.getWorld)
    if not ok or world == nil then return nil end
    local value = common.safe_get_component(world, "GAME_TIME", {})
    local milliseconds = common.field(value, "gameTime")
    return type(milliseconds) == "number" and milliseconds / 1000 or nil
end

local function onboard_passenger_counts(errors)
    local result = {}
    if common.component_type == nil then return result, false end
    local at_vehicle_type = common.component_type("SIM_ENTITY_AT_VEHICLE")
    local person_type = common.component_type("SIM_PERSON")
    if at_vehicle_type == nil or person_type == nil then return result, false end
    local ok, reason = pcall(api.engine.forEachEntityWithComponent, function(entity)
        local person_ok, person = pcall(api.engine.getComponent, entity, person_type)
        if not person_ok or person == nil then return end
        local at_ok, at_vehicle = pcall(api.engine.getComponent, entity, at_vehicle_type)
        if not at_ok or at_vehicle == nil then return end
        local vehicle_id = entity_id(common.field(at_vehicle, "vehicle"))
        if vehicle_id ~= 0 then result[vehicle_id] = (result[vehicle_id] or 0) + 1 end
    end, at_vehicle_type)
    if not ok then
        errors[#errors + 1] = { component = "SIM_ENTITY_AT_VEHICLE.passengers", error = tostring(reason) }
        return {}, false
    end
    return result, true
end

local function track_speed_limit(edge_id, errors)
    if edge_id == 0 then return nan end
    local track = common.safe_get_component(edge_id, "BASE_EDGE_TRACK", errors)
    local track_type = common.field(track, "trackType")
    if type(track_type) ~= "number" then return nan end
    if track_speed_cache[track_type] ~= nil then return track_speed_cache[track_type] end
    local repository = api and api.res and api.res.trackTypeRep
    local get = common.field(repository, "get")
    local ok, detail = false, nil
    if get ~= nil then ok, detail = pcall(function() return get(track_type) end) end
    local limit = ok and number(common.field(detail, "speedLimit"), nan) or nan
    track_speed_cache[track_type] = limit
    return limit
end

local function motion_values(train_id, speed, sample_clock, engine_acceleration)
    local acceleration = math.abs(number(engine_acceleration, math.huge)) <= 20 and engine_acceleration or nan
    local previous = motion_cache[train_id]
    if previous ~= nil and speed == speed and sample_clock ~= nil then
        local elapsed = sample_clock - previous.clock
        if elapsed >= 0.02 and elapsed <= 5 then
            local measured = (speed - previous.speed) / elapsed
            if math.abs(measured) <= 20 then acceleration = measured end
        end
    end
    if speed == speed and sample_clock ~= nil then motion_cache[train_id] = { speed = speed, clock = sample_clock } end
    return acceleration
end

local function invalid_edge() return { edge_entity_id = 0, position01 = nan, direction = 0, valid = false } end

local function encode_passenger(row)
    return binary.u16(row.compartment) .. binary.u16(0) .. binary.u32(row.amount) .. binary.u32(row.capacity)
end

local function encode_freight(row)
    return binary.u32(row.cargo_id) .. binary.u16(row.compartment) .. binary.u16(row.config) ..
        binary.u32(row.amount) .. binary.u32(row.capacity) .. binary.f32(row.unit_weight) .. binary.f32(row.weight)
end

local function encode_part(row)
    return binary.u32(1) .. binary.u32(PART_SIZE) .. binary.u64(row.entity_id) .. binary.u64(row.train_id) ..
        binary.u32(row.model_id) .. binary.u16(row.index) .. binary.u16(row.part_count) .. binary.u32(row.flags) ..
        binary.f32(row.model.length) .. binary.f32(row.model.width) .. binary.f32(row.model.height) ..
        binary.f32(row.model.empty_weight) .. binary.f32(row.model.top_speed) .. binary.f32(row.model.power) ..
        binary.f32(row.model.tractive_effort) .. binary.vec3(row.center) .. binary.vec3(row.front) .. binary.vec3(row.rear) ..
        binary.aabb(row.bounds) .. binary.edge(row.front_edge) .. binary.edge(row.center_edge) .. binary.edge(row.rear_edge) ..
        binary.u32(row.passenger_count) .. binary.u32(row.passenger_capacity) .. binary.u32(row.passenger_offset) ..
        binary.u16(row.passenger_count_rows) .. binary.u16(row.passenger_compartments) ..
        binary.u32(row.freight_amount) .. binary.u32(row.freight_capacity) .. binary.f32(row.freight_weight_t) ..
        binary.u32(row.freight_offset) .. binary.u16(row.freight_count_rows) .. binary.u16(row.freight_compartments) ..
        binary.u64(row.sequence) .. binary.u64(row.time_us)
end

local function encode_train(row)
    return binary.u32(1) .. binary.u32(TRAIN_SIZE) .. binary.u64(row.entity_id) .. binary.u64(row.line_id) ..
        binary.u32(row.flags) .. binary.u32(row.state) .. binary.u32(row.parts_offset) .. binary.u16(row.parts_count) ..
        binary.u16(row.powered_count) .. binary.f32(row.total_length) .. binary.f32(row.empty_weight) ..
        binary.f32(row.passenger_weight) .. binary.f32(row.freight_weight) .. binary.f32(row.gross_weight) ..
        binary.u32(row.passenger_count) .. binary.u32(row.passenger_capacity) .. binary.u32(row.freight_amount) ..
        binary.u32(row.freight_capacity) .. binary.u32(row.freight_offset) .. binary.u16(row.freight_count) .. binary.u16(0) ..
        binary.f32(row.technical_max_speed) .. binary.f32(row.track_limit) .. binary.f32(row.command_limit) ..
        binary.f32(row.effective_limit) .. binary.f32(row.current_speed) .. binary.f32(row.acceleration) ..
        binary.f32(row.brake_deceleration) .. binary.vec3(row.center) .. binary.vec3(row.front) .. binary.vec3(row.rear) ..
        binary.edge(row.front_edge) .. binary.edge(row.center_edge) .. binary.edge(row.rear_edge) ..
        binary.u32(row.path_edge_index) .. binary.u32(row.path_edge_count) .. binary.u64(row.sequence) .. binary.u64(row.time_us)
end

function M.publish(sequence)
    if not native_loader.available then return false, { error = "native loader unavailable" } end
    local trains, parts, passenger_rows, freight_rows, errors = {}, {}, {}, {}, {}
    local sample_clock = game_time_seconds() or (common.clock and common.clock()) or (os and os.time and os.time()) or 0
    local sample_time_us = math.floor(math.max(0, sample_clock or 0) * 1000000)
    local passenger_counts, passenger_counts_verified = onboard_passenger_counts(errors)
    local vehicle_system = api and api.engine and api.engine.system and api.engine.system.transportVehicleSystem
    local get_info = vehicle_system and vehicle_system.getInfo
    common.safe_for_each_entity("TRANSPORT_VEHICLE", function(entity)
        local vehicle = common.safe_get_component(entity, "TRANSPORT_VEHICLE", errors)
        if common.field(vehicle, "carrier") ~= 1 then return end
        local train_component = common.safe_get_component(entity, "TRAIN", errors)
        local part_entities = common.sequence_values(common.field(train_component, "vehicles"))
        if #part_entities == 0 or #part_entities > 256 then return end
        local config_parts = common.sequence_values(common.field(common.field(vehicle, "transportVehicleConfig"), "vehicles"))
        local info_ok, info = false, nil
        if get_info ~= nil then info_ok, info = pcall(function() return get_info(entity) end) end
        local by_part, train_passengers, train_freight, cargo_aligned = load_rows(info, #part_entities)
        local move_path = common.safe_get_component(entity, "MOVE_PATH", errors)
        local path, dyn = common.field(move_path, "path"), common.field(move_path, "dyn") or common.field(move_path, "dyn0")
        local path_pos = common.field(dyn, "pathPos")
        local edge_index = number(common.field(path_pos, "edgeIndex"), 0)
        local edges = common.field(path, "edges")
        local current = common.field(edges, edge_index) or common.field(edges, edge_index + 1)
        local edge_value = common.field(current, "edgeId")
        local edge_id = entity_id(common.field(edge_value, "entity") or common.field(edge_value, "edge") or common.field(edge_value, "id") or edge_value)
        local edge_pos = number(common.field(path_pos, "pos01"), nan)
        local edge_dir = common.field(current, "dir")
        local root_edge = { edge_entity_id = edge_id, position01 = edge_pos,
            direction = edge_dir == false and -1 or edge_dir == true and 1 or 0, valid = edge_id ~= 0 and edge_pos == edge_pos }
        local root_center = bounds_for(entity, errors)
        local train_id = entity_id(entity)
        local current_speed = number(common.field(dyn, "speed"), nan)
        local track_limit = track_speed_limit(edge_id, errors)
        local train = {
            entity_id = train_id, line_id = entity_id(common.field(vehicle, "line")),
            flags = TRAIN_PARTS_COMPLETE + (cargo_aligned and TRAIN_CARGO_COMPLETE or 0), state = number(common.field(vehicle, "state"), 0),
            parts_offset = #parts, parts_count = #part_entities, powered_count = 0,
            total_length = 0, empty_weight = 0, passenger_weight = nan, freight_weight = 0, gross_weight = nan,
            passenger_count = 0, passenger_capacity = 0, freight_amount = 0, freight_capacity = 0,
            freight_offset = #freight_rows, freight_count = #train_freight,
            technical_max_speed = nan, track_limit = track_limit, command_limit = nan, effective_limit = nan,
            current_speed = current_speed,
            acceleration = motion_values(train_id, current_speed, sample_clock, common.field(dyn, "accel")),
            brake_deceleration = number(common.field(dyn, "brakeDecel"), nan), center = root_center,
            front = nil, rear = nil, front_edge = invalid_edge(), center_edge = root_edge, rear_edge = invalid_edge(),
            path_edge_index = edge_index, path_edge_count = common.array_count(edges) or 0, sequence = sequence, time_us = sample_time_us,
        }
        for _, row in ipairs(train_passengers) do
            train.passenger_count = train.passenger_count + row.amount
            train.passenger_capacity = train.passenger_capacity + row.capacity
        end
        if passenger_counts_verified then train.passenger_count = passenger_counts[train.entity_id] or 0 end
        for _, row in ipairs(train_freight) do
            train.freight_amount = train.freight_amount + row.amount
            train.freight_capacity = train.freight_capacity + row.capacity
            if row.weight == row.weight then train.freight_weight = train.freight_weight + row.weight / 1000 end
        end
        if train.passenger_capacity > 0 then train.flags = train.flags + TRAIN_PASSENGER end
        if train.freight_capacity > 0 then train.flags = train.flags + TRAIN_FREIGHT end
        if train.passenger_capacity > 0 and train.freight_capacity > 0 then train.flags = train.flags + TRAIN_MIXED end
        for index, part_entity in ipairs(part_entities) do
            local config_part = common.field(config_parts[index], "part") or config_parts[index]
            local model_id = number(common.field(config_part, "modelId"), 0)
            local model = model_descriptor(model_id)
            local center, bounds = bounds_for(part_entity, errors)
            local loads = by_part[index]
            local part = {
                entity_id = entity_id(part_entity), train_id = train.entity_id, model_id = model_id,
                index = index - 1, part_count = #part_entities, flags = model.flags,
                model = model, center = center, front = nil, rear = nil, bounds = bounds,
                front_edge = invalid_edge(), center_edge = invalid_edge(), rear_edge = invalid_edge(),
                passenger_count = 0, passenger_capacity = 0, passenger_offset = #passenger_rows,
                passenger_count_rows = #loads.passengers, passenger_compartments = #loads.passengers,
                freight_amount = 0, freight_capacity = 0, freight_weight_t = 0, freight_offset = #freight_rows,
                freight_count_rows = #loads.freight, freight_compartments = #loads.freight,
                sequence = sequence, time_us = sample_time_us,
            }
            if loads.verified then part.flags = part.flags + PART_CARGO_VERIFIED end
            for _, row in ipairs(loads.passengers) do
                passenger_rows[#passenger_rows + 1] = row
                part.passenger_count = part.passenger_count + row.amount
                part.passenger_capacity = part.passenger_capacity + row.capacity
            end
            for _, row in ipairs(loads.freight) do
                freight_rows[#freight_rows + 1] = row
                part.freight_amount = part.freight_amount + row.amount
                part.freight_capacity = part.freight_capacity + row.capacity
                if row.weight == row.weight then part.freight_weight_t = part.freight_weight_t + row.weight / 1000 end
            end
            if model.flags % 2 == 1 then train.powered_count = train.powered_count + 1 end
            if model.length == model.length then train.total_length = train.total_length + model.length end
            if model.empty_weight == model.empty_weight then train.empty_weight = train.empty_weight + model.empty_weight end
            if model.top_speed == model.top_speed then
                train.technical_max_speed = train.technical_max_speed == train.technical_max_speed and
                    math.min(train.technical_max_speed, model.top_speed) or model.top_speed
            end
            parts[#parts + 1] = part
        end
        local passenger_unit_weight = cargo_unit_weight(0)
        if passenger_counts_verified and passenger_unit_weight == passenger_unit_weight then
            train.passenger_weight = train.passenger_count * passenger_unit_weight / 1000
        end
        if train.technical_max_speed == train.technical_max_speed then
            train.effective_limit = train.technical_max_speed
            if train.track_limit == train.track_limit then
                train.effective_limit = math.min(train.effective_limit, train.track_limit)
            end
            if train.command_limit == train.command_limit then
                train.effective_limit = math.min(train.effective_limit, train.command_limit)
            end
        end
        local freight_known = train.freight_capacity == 0 or cargo_aligned
        if train.passenger_weight == train.passenger_weight and freight_known then
            train.gross_weight = train.empty_weight + train.passenger_weight + train.freight_weight
        end
        trains[#trains + 1] = train
    end, errors)

    local trains_offset = FRAME_HEADER_SIZE
    local parts_offset = trains_offset + #trains * TRAIN_SIZE
    local passenger_offset = parts_offset + #parts * PART_SIZE
    local freight_offset = passenger_offset + #passenger_rows * PASSENGER_SIZE
    local total_size = freight_offset + #freight_rows * FREIGHT_SIZE
    local chunks = {
        binary.u32(FRAME_MAGIC), binary.u32(1), binary.u32(FRAME_HEADER_SIZE), binary.u32(total_size),
        binary.u64(sequence), binary.u64(sample_time_us), binary.u32(#trains), binary.u32(#parts),
        binary.u32(#passenger_rows), binary.u32(#freight_rows), binary.u32(trains_offset), binary.u32(parts_offset),
        binary.u32(passenger_offset), binary.u32(freight_offset), binary.u32(0), binary.u32(0),
    }
    for _, row in ipairs(trains) do chunks[#chunks + 1] = encode_train(row) end
    for _, row in ipairs(parts) do chunks[#chunks + 1] = encode_part(row) end
    for _, row in ipairs(passenger_rows) do chunks[#chunks + 1] = encode_passenger(row) end
    for _, row in ipairs(freight_rows) do chunks[#chunks + 1] = encode_freight(row) end
    local payload = table.concat(chunks)
    if #payload ~= total_size then return false, { error = "binary size mismatch", actual = #payload, expected = total_size } end
    return native_loader.publish_binary("train-wrappers-v1.bin", payload), {
        trains = #trains, parts = #parts, passenger_loads = #passenger_rows,
        freight_loads = #freight_rows, bytes = #payload, errors = errors,
    }
end

function M.identities()
    local result = { schema_version = 1, source_status = "ENGINE_NAME_COMPONENT", trains = {}, errors = {} }
    common.safe_for_each_entity("TRANSPORT_VEHICLE", function(entity)
        local vehicle = common.safe_get_component(entity, "TRANSPORT_VEHICLE", result.errors)
        if common.field(vehicle, "carrier") ~= 1 then return end
        local display_name = common.name_from_component(common.safe_get_component(entity, "NAME", result.errors))
        result.trains[#result.trains + 1] = {
            entity_id = entity_id(entity),
            display_name = type(display_name) == "string" and display_name or nil,
            line_id = entity_id(common.field(vehicle, "line")),
        }
    end, result.errors)
    table.sort(result.trains, function(a, b) return a.entity_id < b.entity_id end)
    result.count = #result.trains
    return result
end

function M.probe(maximum)
    maximum = maximum or 4
    local result = { schema_version = 1, source_status = "LIVE_MAPPING_PROBE", trains = {}, errors = {} }
    common.safe_for_each_entity("TRANSPORT_VEHICLE", function(entity)
        if #result.trains >= maximum then return end
        local vehicle = common.safe_get_component(entity, "TRANSPORT_VEHICLE", result.errors)
        if common.field(vehicle, "carrier") ~= 1 then return end
        local train = common.safe_get_component(entity, "TRAIN", result.errors)
        local part_entities = common.sequence_values(common.field(train, "vehicles"))
        local configs = common.sequence_values(common.field(common.field(vehicle, "transportVehicleConfig"), "vehicles"))
        local item = {
            entity_id = entity_id(entity), train_part_count = #part_entities,
            config_part_count = #configs, parts = {},
            transport_vehicle = common.probe_fields(vehicle, {
                "cargo", "cargos", "load", "loads", "config", "transportVehicleConfig",
            }),
            cargo_values = {}, config_capacities = {},
        }
        local raw_cargo = common.field(vehicle, "cargo") or common.field(vehicle, "cargos") or
            common.field(vehicle, "load") or common.field(vehicle, "loads")
        for _, value in ipairs(common.sequence_values(raw_cargo)) do
            if #item.cargo_values >= 128 then break end
            if type(value) == "number" or type(value) == "boolean" or type(value) == "string" then
                item.cargo_values[#item.cargo_values + 1] = value
            else
                item.cargo_values[#item.cargo_values + 1] = common.probe_fields(value, {
                    "amount", "count", "cargo", "cargoType", "cargoTypeId", "type", "part", "compartment",
                })
            end
        end
        local capacities = common.field(common.field(vehicle, "config"), "capacities")
        for _, value in ipairs(common.sequence_values(capacities)) do
            if #item.config_capacities >= 64 then break end
            if type(value) == "number" then item.config_capacities[#item.config_capacities + 1] = value end
        end
        local system = api and api.engine and api.engine.system and api.engine.system.transportVehicleSystem
        local ok, info = false, nil
        if system and system.getInfo then ok, info = pcall(function() return system.getInfo(entity) end) end
        item.get_info_ok = ok == true
        item.cargo_info_vehicle_groups = ok and common.array_count(common.field(info, "cargoInfos")) or nil
        item.cargo_info_samples = {}
        if ok then
            for vehicle_index, compartments in ipairs(common.sequence_values(common.field(info, "cargoInfos"))) do
                if vehicle_index > 16 then break end
                for compartment_index, cargo_types in ipairs(common.sequence_values(compartments)) do
                    if compartment_index > 8 then break end
                    for cargo_index, cargo_info in ipairs(common.sequence_values(cargo_types)) do
                        if cargo_index > 32 then break end
                        item.cargo_info_samples[#item.cargo_info_samples + 1] = {
                            vehicle_index = vehicle_index - 1,
                            compartment_index = compartment_index - 1,
                            cargo_index = cargo_index - 1,
                            fields = common.probe_fields(cargo_info, {
                                "capacity", "offset", "amount", "load", "count",
                                "cargo", "cargoType", "cargoTypeId", "type",
                            }),
                        }
                    end
                end
            end
        end
        for index, part_entity in ipairs(part_entities) do
            if index > 16 then break end
            local config_part = common.field(configs[index], "part") or configs[index]
            local model_instances = common.safe_get_component(part_entity, "MODEL_INSTANCE_LIST", result.errors)
            local instance_samples = {}
            local instances = common.field(model_instances, "models") or common.field(model_instances, "modelInstances") or
                common.field(model_instances, "instances") or model_instances
            for instance_index, instance in ipairs(common.sequence_values(instances)) do
                if instance_index > 2 then break end
                local transform = common.field(instance, "transf") or common.field(instance, "transform")
                local transform_values = {}
                for _, value in ipairs(common.sequence_values(transform)) do
                    if #transform_values >= 16 then break end
                    if type(value) == "number" then transform_values[#transform_values + 1] = value end
                end
                instance_samples[#instance_samples + 1] = {
                    model_id = common.field(instance, "modelId") or common.field(instance, "model") or common.field(instance, "id"),
                    transform = #transform_values > 0 and transform_values or nil,
                }
            end
            local model_id = common.field(config_part, "modelId")
            local descriptor = type(model_id) == "number" and model_descriptor(model_id) or nil
            item.parts[#item.parts + 1] = {
                part_index = index - 1, entity_id = entity_id(part_entity),
                model_id = model_id,
                descriptor = descriptor and {
                    length = observed(descriptor.length), width = observed(descriptor.width), height = observed(descriptor.height),
                    empty_weight = observed(descriptor.empty_weight), top_speed = observed(descriptor.top_speed),
                    power = observed(descriptor.power), tractive_effort = observed(descriptor.tractive_effort),
                    flags = descriptor.flags,
                } or nil,
                bounding_volume = common.probe_fields(common.safe_get_component(part_entity, "BOUNDING_VOLUME", result.errors), { "bbox" }),
                move_path = common.probe_fields(common.safe_get_component(part_entity, "MOVE_PATH", result.errors), { "path", "dyn", "dyn0" }),
                rail_vehicle = common.probe_fields(common.safe_get_component(part_entity, "RAIL_VEHICLE", result.errors), { "reversed", "particleSystems" }),
                model_instances = instance_samples,
            }
        end
        result.trains[#result.trains + 1] = item
    end, result.errors)
    result.counts = { trains = #result.trains }
    return result
end

return M
