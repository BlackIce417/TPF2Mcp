#pragma once
#include <cstdint>
#include <cstddef>
struct lua_State;
// Stable C ABI between the process-lifetime Loader and reloadable Controller.
struct Tpf2NativeTelemetryContext {
    std::uint32_t size = sizeof(Tpf2NativeTelemetryContext);
    std::uint32_t version = 1;
    std::uint64_t epoch = 0;
    std::uint32_t world_entity = 0;
    std::uint32_t reserved = 0;
    char session[192]{};
    char clock_json[1024]{};
};
#ifdef TPF2LOADER_EXPORTS
#define TPF2_TELEMETRY_API __declspec(dllexport)
#else
#define TPF2_TELEMETRY_API
#endif
extern "C" {
TPF2_TELEMETRY_API int tpf2_loader_lua_native_telemetry_tick(lua_State*);
TPF2_TELEMETRY_API int tpf2_loader_native_telemetry_context(Tpf2NativeTelemetryContext*);
TPF2_TELEMETRY_API std::size_t tpf2_loader_native_telemetry_seed(std::uint64_t, char*, std::size_t, std::uint64_t*);
TPF2_TELEMETRY_API int tpf2_loader_native_telemetry_publish(std::uint64_t, const char*, const char*, std::size_t);
TPF2_TELEMETRY_API void tpf2_loader_native_telemetry_request_metadata(std::uint64_t);
}
namespace tpf2::loader::native_telemetry {
bool publish_seed(const char*, std::size_t) noexcept;
}
