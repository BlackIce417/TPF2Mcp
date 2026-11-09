#pragma once
#include <cstdint>

struct lua_State;

enum class Tpf2LoaderState : std::uint32_t {
    Idle = 0,
    ControllerBorrowed = 1,
    ControllerOwned = 2,
    Reloading = 3,
    Error = 4,
};

enum class Tpf2LoaderResult : std::uint32_t {
    Ok = 0,
    AlreadyLoaded = 1,
    ControllerNotFound = 2,
    LoadFailed = 3,
    LifecycleListenerFailed = 4,
    ControllerNotOwned = 5,
    InvalidHostProcess = 6,
    PrepareUnloadFailed = 7,
    UnloadFailed = 8,
    ReplaceFailed = 9,
};

extern "C" {
__declspec(dllexport) int luaopen_tpf2_loader(lua_State* state);
__declspec(dllexport) int tpf2_loader_lua_start(lua_State* state);
__declspec(dllexport) int tpf2_loader_lua_publish_json(lua_State* state);
__declspec(dllexport) int tpf2_loader_lua_publish_binary(lua_State* state);
__declspec(dllexport) int tpf2_loader_lua_network_refresh_due(lua_State* state);
__declspec(dllexport) std::uint32_t tpf2_loader_abi_version();
__declspec(dllexport) std::uint32_t tpf2_loader_train_protocol_version();
__declspec(dllexport) std::uint32_t tpf2_loader_train_frame_header_size();
__declspec(dllexport) std::uint32_t tpf2_loader_train_wrapper_size();
__declspec(dllexport) std::uint32_t tpf2_loader_vehicle_part_wrapper_size();
__declspec(dllexport) std::uint32_t tpf2_loader_passenger_load_entry_size();
__declspec(dllexport) std::uint32_t tpf2_loader_freight_load_entry_size();
__declspec(dllexport) Tpf2LoaderResult tpf2_loader_start_controller();
__declspec(dllexport) Tpf2LoaderResult tpf2_loader_reload_controller();
__declspec(dllexport) int tpf2_loader_request_network_refresh();
__declspec(dllexport) Tpf2LoaderState tpf2_loader_get_state();
__declspec(dllexport) std::uint32_t tpf2_loader_last_win32_error();
}
