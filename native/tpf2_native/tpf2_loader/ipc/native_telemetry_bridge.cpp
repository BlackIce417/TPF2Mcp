#include "pch.h"
#include "../../shared/native_telemetry_bridge.h"
#include "../lua/lua_abi.h"
#include "shared_bus.h"
#include <cstring>
#include <cmath>

namespace {
SRWLOCK lock = SRWLOCK_INIT;
Tpf2NativeTelemetryContext context;
ULONGLONG lua_tick{}, controller_tick{}, metadata_tick{};
bool requested = true, seed_ready = false;
bool live() { return context.epoch && GetTickCount64() - lua_tick < 3000; }
}
extern "C" int tpf2_loader_lua_native_telemetry_tick(lua_State* state)
{
    const char* session{};
    std::size_t session_size{};
    double world{};
    if (!tpf2::loader::lua_abi::string_argument(state, 1, session, session_size) ||
        !tpf2::loader::lua_abi::number_argument(state, 2, world) || !std::isfinite(world) ||
        world < 0 || world >= 0x40000000 || std::floor(world) != world ||
        !session_size || session_size >= sizeof(context.session)) return 0;
    AcquireSRWLockExclusive(&lock);
    if (std::strlen(context.session) != session_size || std::memcmp(context.session, session, session_size)) {
        ++context.epoch;
        std::memset(context.session, 0, sizeof(context.session));
        std::memcpy(context.session, session, session_size);
        requested = true; seed_ready = false; metadata_tick = controller_tick = 0;
    }
    context.world_entity = static_cast<std::uint32_t>(world);
    lua_tick = GetTickCount64();
    // Old controllers keep the existing Lua producer. Once the native reader
    // joins this epoch it owns sampling; a failed sample expires at the consumer.
    const bool native = controller_tick && lua_tick - controller_tick < 3000;
    const bool due = native && requested && (!metadata_tick || lua_tick - metadata_tick >= 1000);
    if (due) metadata_tick = lua_tick;
    double result[]{native ? 1.0 : 0.0, due ? 1.0 : 0.0};
    ReleaseSRWLockExclusive(&lock);
    return tpf2::loader::lua_abi::return_numbers(state, result, 2);
}
extern "C" int tpf2_loader_native_telemetry_context(Tpf2NativeTelemetryContext* out)
{
    if (!out || out->size != sizeof(context) || out->version != 1) return 0;
    AcquireSRWLockExclusive(&lock);
    bool valid = live();
    if (valid) { *out = context; controller_tick = GetTickCount64(); }
    ReleaseSRWLockExclusive(&lock);
    return valid ? 1 : 0;
}
namespace tpf2::loader::native_telemetry {
bool publish_seed(const char* data, std::size_t size) noexcept
{
    AcquireSRWLockExclusive(&lock);
    constexpr char key[] = "native-train-seed.bin";
    bool ok = live() && shared_bus::publish(key, sizeof(key) - 1, data, size);
    if (ok) { seed_ready = true; requested = false; }
    ReleaseSRWLockExclusive(&lock);
    return ok;
}
}
extern "C" std::size_t tpf2_loader_native_telemetry_seed(std::uint64_t epoch, char* out, std::size_t size, std::uint64_t* revision)
{
    AcquireSRWLockShared(&lock);
    auto result = live() && epoch == context.epoch && seed_ready ?
        tpf2::loader::shared_bus::copy("native-train-seed.bin", out, size, revision) : 0;
    ReleaseSRWLockShared(&lock);
    return result;
}
extern "C" int tpf2_loader_native_telemetry_publish(std::uint64_t epoch, const char* key, const char* data, std::size_t size)
{
    if (!key) return 0;
    if (std::strcmp(key, "train-wrappers-v1.bin") &&
        std::strcmp(key, "operational-telemetry-vehicle_positions.json") &&
        std::strcmp(key, "operational-telemetry-train_footprints.json") &&
        std::strcmp(key, "native-telemetry-performance.json")) return 0;
    AcquireSRWLockShared(&lock);
    bool ok = live() && epoch == context.epoch && seed_ready &&
        tpf2::loader::shared_bus::publish(key, std::strlen(key), data, size);
    ReleaseSRWLockShared(&lock);
    return ok ? 1 : 0;
}
extern "C" void tpf2_loader_native_telemetry_request_metadata(std::uint64_t epoch)
{
    AcquireSRWLockExclusive(&lock);
    if (live() && epoch == context.epoch) requested = true;
    ReleaseSRWLockExclusive(&lock);
}
