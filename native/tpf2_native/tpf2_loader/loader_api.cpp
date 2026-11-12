#include "pch.h"
#include "loader_api.h"
#include "loader_runtime.h"
#include "lua_abi.h"
#include "scheduler.h"
#include "shared_bus.h"
#include "train_telemetry_protocol.h"
#include "command_bus.h"
#include "native_telemetry_bridge.h"
#include <cstring>
#include <cmath>

extern "C" int luaopen_tpf2_loader(lua_State*)
{
    // Lua owns the closures returned by package.loadlib.  Different game Lua
    // states can release their module references independently, while the
    // scheduler thread and closures in another state still execute our code.
    // The loader intentionally has process lifetime and owns the Controller
    // load/unload lifecycle.
    if (!tpf2::loader::pin_module()) return 0;
    tpf2::loader::shared_bus::initialize();
    tpf2::loader::commands::initialize();
    tpf2::loader::scheduler::initialize();
    tpf2::loader::start_lifecycle_listener();
    tpf2::loader::start_controller();
    return 0;
}

extern "C" int tpf2_loader_lua_start(lua_State*)
{
    tpf2::loader::start_controller();
    return 0;
}

extern "C" int tpf2_loader_lua_publish_json(lua_State* state)
{
    const char *key = nullptr, *json = nullptr;
    std::size_t key_size = 0, json_size = 0;
    const bool valid = tpf2::loader::lua_abi::string_argument(state, 1, key, key_size) &&
        tpf2::loader::lua_abi::string_argument(state, 2, json, json_size);
    return tpf2::loader::lua_abi::return_boolean(state,
        valid && tpf2::loader::shared_bus::publish(key, key_size, json, json_size));
}

extern "C" int tpf2_loader_lua_publish_binary(lua_State* state)
{
    const char *key = nullptr, *payload = nullptr;
    std::size_t key_size = 0, payload_size = 0;
    const bool valid = tpf2::loader::lua_abi::string_argument(state, 1, key, key_size) &&
        tpf2::loader::lua_abi::string_argument(state, 2, payload, payload_size);
    constexpr char seed_key[] = "native-train-seed.bin";
    const bool seed = valid && key_size == sizeof(seed_key) - 1 && !std::memcmp(key, seed_key, key_size);
    return tpf2::loader::lua_abi::return_boolean(state, valid && (seed ?
        tpf2::loader::native_telemetry::publish_seed(payload, payload_size) :
        tpf2::loader::shared_bus::publish(key, key_size, payload, payload_size)));
}

extern "C" int tpf2_loader_lua_network_refresh_due(lua_State* state)
{
    return tpf2::loader::lua_abi::return_boolean(state, tpf2::loader::scheduler::consume_network_refresh());
}

extern "C" int tpf2_loader_lua_command_poll(lua_State* state)
{
    double values[3]{};
    const auto count = tpf2::loader::commands::poll(values);
    const int returned = tpf2::loader::lua_abi::return_numbers(state, values, count);
    if (count && !returned) tpf2::loader::commands::finish(static_cast<std::uint64_t>(values[2]));
    return returned;
}
extern "C" int tpf2_loader_lua_command_read(lua_State* state)
{
    double offset = 0, values[8]{};
    if (!tpf2::loader::lua_abi::number_argument(state, 1, offset) || !std::isfinite(offset) ||
        offset < 0 || offset >= tpf2::loader::commands::kPayloadCapacity || std::floor(offset) != offset) return 0;
    const auto count = tpf2::loader::commands::read_words(static_cast<std::size_t>(offset), values);
    return tpf2::loader::lua_abi::return_numbers(state, values, count);
}
extern "C" int tpf2_loader_lua_command_finish(lua_State* state)
{
    double sequence = 0;
    const bool valid = tpf2::loader::lua_abi::number_argument(state, 1, sequence) &&
        std::isfinite(sequence) && sequence > 0 && sequence <= 9007199254740991.0 && std::floor(sequence) == sequence;
    return tpf2::loader::lua_abi::return_boolean(state,
        valid && tpf2::loader::commands::finish(static_cast<std::uint64_t>(sequence)));
}

extern "C" std::uint32_t tpf2_loader_abi_version() { return 3; }
extern "C" std::uint32_t tpf2_loader_train_protocol_version() { return tpf2::loader::telemetry::kProtocolVersion; }
extern "C" std::uint32_t tpf2_loader_train_frame_header_size() { return sizeof(tpf2::loader::telemetry::TrainTelemetryFrameHeader); }
extern "C" std::uint32_t tpf2_loader_train_wrapper_size() { return sizeof(tpf2::loader::telemetry::TrainWrapper); }
extern "C" std::uint32_t tpf2_loader_vehicle_part_wrapper_size() { return sizeof(tpf2::loader::telemetry::VehiclePartWrapper); }
extern "C" std::uint32_t tpf2_loader_passenger_load_entry_size() { return sizeof(tpf2::loader::telemetry::PassengerLoadEntry); }
extern "C" std::uint32_t tpf2_loader_freight_load_entry_size() { return sizeof(tpf2::loader::telemetry::FreightLoadEntry); }
extern "C" Tpf2LoaderResult tpf2_loader_start_controller() { return tpf2::loader::start_controller(); }
extern "C" Tpf2LoaderResult tpf2_loader_reload_controller() { return tpf2::loader::reload_controller(); }
extern "C" int tpf2_loader_request_network_refresh()
{
    if (!tpf2::loader::pin_module()) return 0;
    return tpf2::loader::scheduler::request_network_refresh() ? 1 : 0;
}
extern "C" Tpf2LoaderState tpf2_loader_get_state() { return tpf2::loader::state(); }
extern "C" std::uint32_t tpf2_loader_last_win32_error() { return tpf2::loader::last_error(); }
