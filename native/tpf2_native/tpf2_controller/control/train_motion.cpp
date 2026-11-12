#include "pch.h"
#include "tpf2.h"
#include "train_motion.h"
#include "train_motion_math.h"
#include "../telemetry/native_telemetry.h"
#include "../ipc/loader_session.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <vector>

namespace
{
constexpr uintptr_t TRAIN_UPDATE = 0xABDC20;
constexpr uintptr_t VEHICLE_UPDATE = 0xAD73A0;
constexpr uintptr_t APPLY_PATH = 0x217D7C0;
constexpr uintptr_t TYPE_ID = 0xD0A40;
constexpr uintptr_t DESTROY_TASKS = 0x150D70;
constexpr uintptr_t STATION_PATH_ONLY = 0x2178820;
constexpr uintptr_t BEGIN_CHANGES = 0x23E4A60;
constexpr uintptr_t END_CHANGES = 0x23E4E10;
constexpr uintptr_t FIND_PATH_TO_STOP = 0x2173C00;
constexpr uintptr_t DESTROY_PATH = 0xBBD10;
constexpr size_t MAX_NATIVE_PATH = 100000;
constexpr size_t MAX_JOBS = 32;
constexpr size_t TRANSPORT_VEHICLE_SIZE = 360; // Verified in 0x1407209A0 / 0x140180330.
constexpr double STOP_EPSILON = 0.01;
using UpdateFn = void (*)(void*, void*, int, float);
using TypeFn = int (*)(void*, const void*);
using ApplyFn = void (*)(void*, void*);
// vehicle_util::def::SetPathToStation. Unlike the high-level station/departure
// wrapper, this emits ONLY MovePath edits and never rewrites departure history.
using StationFn = unsigned char (*)(void*, uint32_t*, uint32_t*, int, void*, void*, unsigned char,
                                    unsigned char, uint64_t, void*, unsigned char);
struct NativeEdge { uint32_t entity; int32_t index; uint8_t direction; uint8_t padding[3]; };
static_assert(sizeof(NativeEdge) == 12);
struct NativeVector { unsigned char* begin{}; unsigned char* end{}; unsigned char* capacity{}; };
static_assert(sizeof(NativeVector) == 24);
struct NativePath { NativeVector edges{}; int32_t stop_edges{1}, terminal{-1}; };
static_assert(sizeof(NativePath) == 32);
using FindPathFn = NativePath* (*)(NativePath*, void*, NativeVector*, NativeVector*, uint32_t,
                                  uint32_t*, int, bool*, float*, void*, bool, bool, uint64_t);
struct EngineApi
{
    TypeFn type{};
    ApplyFn apply{};
    StationFn station{};
    void (*destroy_tasks)(NativeVector*){};
    uint64_t (*session)(){};
    void (*begin_changes)(void*, void*){};
    void (*end_changes)(void*){};
    FindPathFn find_path{};
    void (*destroy_path)(void*){};
} api;
struct alignas(8) PathTask { uintptr_t unused_vtable{}; uint32_t vehicle{}; uint32_t padding{}; unsigned char path[136]{}; };
static_assert(offsetof(PathTask, path) == 16 && sizeof(PathTask) == 152);
enum class Phase { Empty, Pending, Applying, Moving, Held, Restoring, Released, Rejected };
struct Job
{
    Tpf2MoveTrainRoutePayload command{};
    float distance{};
    bool route{};
    uint32_t flags{};
    bool changed_path{};
    bool release{};
    Phase phase{Phase::Empty};
    ULONGLONG deadline{};
    ULONGLONG accepted{};
    uint64_t session{};
    void* path{};
    uint64_t path_hash{};
    int target_index{};
    float target_offset{};
    float cap{};
    float step_seconds{};
    int initial_state{};
    double remaining{};
    const char* detail{"PENDING_GAME_UPDATE"};
};
SRWLOCK jobs_lock = SRWLOCK_INIT;
std::array<Job, MAX_JOBS> jobs;
UpdateFn original_train_update{};
UpdateFn original_vehicle_update{};
uintptr_t image{};
std::array<unsigned char, 112> vehicle_context{};
bool vehicle_context_available{};
DWORD path_vehicle_tls = TLS_OUT_OF_INDEXES;
bool unloading{};
thread_local bool editing{};
train_motion::LoaderSession loader_session;

class JobsLock
{
    bool owned_ = false;
public:
    JobsLock() { lock(); }
    ~JobsLock() { if (owned_) ReleaseSRWLockExclusive(&jobs_lock); }
    void lock() { AcquireSRWLockExclusive(&jobs_lock); owned_ = true; }
    void unlock() { owned_ = false; ReleaseSRWLockExclusive(&jobs_lock); }
};
class WithoutJobsLock
{
    JobsLock& lock_;
public:
    explicit WithoutJobsLock(JobsLock& lock) : lock_(lock) { lock_.unlock(); }
    ~WithoutJobsLock() { lock_.lock(); }
};
class EditingScope
{
    bool previous_ = editing;
public:
    EditingScope() { editing = true; }
    ~EditingScope() { editing = previous_; }
};
class PathVehicleScope
{
    void* previous_{};
public:
    explicit PathVehicleScope(uint32_t vehicle)
    {
        if (path_vehicle_tls != TLS_OUT_OF_INDEXES)
        {
            previous_ = TlsGetValue(path_vehicle_tls);
            TlsSetValue(path_vehicle_tls, reinterpret_cast<void*>(static_cast<uintptr_t>(vehicle)));
        }
    }
    ~PathVehicleScope()
    {
        if (path_vehicle_tls != TLS_OUT_OF_INDEXES) TlsSetValue(path_vehicle_tls, previous_);
    }
};

bool readable(const void* ptr, size_t size)
{
    if (!ptr || !size) return false;
    uintptr_t pos = reinterpret_cast<uintptr_t>(ptr);
    if (pos + size < pos) return false;
    uintptr_t end = pos + size;
    while (pos < end)
    {
        MEMORY_BASIC_INFORMATION m{};
        if (!VirtualQuery(reinterpret_cast<void*>(pos), &m, sizeof(m)) || m.State != MEM_COMMIT ||
            (m.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return false;
        uintptr_t next = reinterpret_cast<uintptr_t>(m.BaseAddress) + m.RegionSize;
        if (next <= pos) return false;
        pos = next;
    }
    return true;
}
template<class T> T load(const void* p, size_t offset = 0)
{
    T value{};
    memcpy(&value, static_cast<const unsigned char*>(p) + offset, sizeof(T));
    return value;
}
template<class T> void store(void* p, size_t offset, T value)
{
    memcpy(static_cast<unsigned char*>(p) + offset, &value, sizeof(T));
}
bool active(const Job& job)
{
    return job.phase == Phase::Pending || job.phase == Phase::Applying || job.phase == Phase::Moving ||
           job.phase == Phase::Held || job.phase == Phase::Restoring;
}
const char* phase_name(Phase phase)
{
    switch (phase)
    {
    case Phase::Pending: return "PENDING";
    case Phase::Applying: return "APPLYING";
    case Phase::Moving: return "MOVING";
    case Phase::Held: return "HELD";
    case Phase::Restoring: return "RESTORING";
    case Phase::Released: return "RELEASED";
    case Phase::Rejected: return "REJECTED";
    default: return "EMPTY";
    }
}
int type_id(void* engine, uintptr_t vtable)
{
    const void* type = reinterpret_cast<void*>(image + vtable);
    return api.type(static_cast<unsigned char*>(engine) + 72, &type);
}
// Engine::GetComponentDataIndex asserts on invalid IDs. Check the entity's
// component list ourselves before reading either contiguous or segmented pools.
void* component(void* engine, uint32_t entity, int type, size_t stride)
{
    if (entity >= 0x40000000 || type < 0 || type > 4096 || !readable(engine, 184)) return nullptr;
    auto entities = load<uintptr_t>(engine, 160);
    auto entities_end = load<uintptr_t>(engine, 168);
    if (entities_end < entities || (entities_end - entities) % 24 ||
        entity >= (entities_end - entities) / 24) return nullptr;
    auto entry = reinterpret_cast<void*>(entities + 24ULL * entity);
    if (!readable(entry, 24)) return nullptr;
    auto begin = load<uintptr_t>(entry);
    auto end = load<uintptr_t>(entry, 8);
    if (end < begin || (end - begin) % 8 || end - begin > 65536 ||
        (end > begin && !readable(reinterpret_cast<void*>(begin), end - begin))) return nullptr;
    int index = -1;
    for (auto p = begin; p < end; p += 8)
        if (load<int>(reinterpret_cast<void*>(p)) == type) { index = load<int>(reinterpret_cast<void*>(p), 4); break; }
    if (index < 0) return nullptr;
    auto pools = load<uintptr_t>(engine, 136);
    auto pools_end = load<uintptr_t>(engine, 144);
    if (pools_end < pools || static_cast<size_t>(type) >= (pools_end - pools) / 8 ||
        !readable(reinterpret_cast<void*>(pools + 8ULL * type), 8)) return nullptr;
    void* pool = load<void*>(reinterpret_cast<void*>(pools + 8ULL * type));
    if (!readable(pool, 144)) return nullptr;
    uintptr_t address{};
    if (index < 0x40000000)
    {
        auto data = load<uintptr_t>(pool, 104);
        auto data_end = load<uintptr_t>(pool, 112);
        if (data_end < data || static_cast<size_t>(index) >= (data_end - data) / stride) return nullptr;
        address = data + stride * index;
    }
    else
    {
        unsigned int slot = index - 0x40000000;
        auto pages = load<uintptr_t>(pool, 128);
        auto pages_end = load<uintptr_t>(pool, 136);
        if (pages_end < pages || slot / 32 >= (pages_end - pages) / 16 ||
            !readable(reinterpret_cast<void*>(pages + 16ULL * (slot / 32)), 8)) return nullptr;
        address = load<uintptr_t>(reinterpret_cast<void*>(pages + 16ULL * (slot / 32))) + stride * (slot % 32);
    }
    return readable(reinterpret_cast<void*>(address), stride) ? reinterpret_cast<void*>(address) : nullptr;
}
struct Track { uint64_t entrance{}, exit{}; double length{}; };
bool track(void* engine, int network_type, const NativeEdge& edge, Track& out)
{
    if (edge.index < 0 || edge.direction > 1) return false;
    void* network = component(engine, edge.entity, network_type, 72);
    if (!network) return false;
    auto begin = load<uintptr_t>(network, 24);
    auto end = load<uintptr_t>(network, 32);
    if (end < begin || (end - begin) % 100 || static_cast<size_t>(edge.index) >= (end - begin) / 100) return false;
    auto data = reinterpret_cast<void*>(begin + 100ULL * edge.index);
    if (!readable(data, 100)) return false;
    out.length = load<float>(data, 72);
    // Native TrainMoveSystem uses endpoints[direction] as the forward endpoint.
    out.exit = load<uint64_t>(data, 8 * edge.direction);
    out.entrance = load<uint64_t>(data, 8 * (1 - edge.direction));
    return std::isfinite(out.length) && out.length > 0.0;
}
bool path_edges(void* path, std::vector<NativeEdge>& edges)
{
    if (!readable(path, 136)) return false;
    auto begin = load<uintptr_t>(path);
    auto end = load<uintptr_t>(path, 8);
    if (end <= begin || (end - begin) % 12 || (end - begin) / 12 > MAX_NATIVE_PATH ||
        !readable(reinterpret_cast<void*>(begin), end - begin)) return false;
    edges.resize((end - begin) / 12);
    memcpy(edges.data(), reinterpret_cast<void*>(begin), end - begin);
    return true;
}
bool same_edge(const NativeEdge& a, const NativeEdge& b)
{
    return a.entity == b.entity && a.index == b.index && a.direction == b.direction;
}
uint64_t hash_path(const std::vector<NativeEdge>& edges)
{
    uint64_t hash = 14695981039346656037ULL;
    for (const auto& edge : edges)
    {
        for (uint32_t value : {edge.entity, static_cast<uint32_t>(edge.index), static_cast<uint32_t>(edge.direction)})
            for (int i = 0; i < 4; ++i) { hash ^= (value >> (8 * i)) & 255; hash *= 1099511628211ULL; }
    }
    return hash;
}
bool distances(void* engine, int network_type, const std::vector<NativeEdge>& edges, std::vector<double>& prefix)
{
    prefix.assign(1, 0.0);
    Track previous{};
    for (size_t i = 0; i < edges.size(); ++i)
    {
        Track current{};
        if (!track(engine, network_type, edges[i], current) ||
            (i && previous.exit != current.entrance)) return false;
        prefix.push_back(prefix.back() + current.length);
        previous = current;
    }
    return true;
}
bool position(void* path, const std::vector<double>& prefix, double& result)
{
    int index = load<int>(path, 52);
    float offset = load<float>(path, 56);
    if (index < 0 || static_cast<size_t>(index + 1) >= prefix.size() || !std::isfinite(offset) ||
        offset < -0.01f || offset > prefix[index + 1] - prefix[index] + 0.01) return false;
    result = prefix[index] + offset;
    return true;
}
float train_length(void* system, uint32_t vehicle)
{
    if (!readable(system, 224)) return 0.0f;
    void* sentinel = load<void*>(system, 176);
    if (!readable(sentinel, 16)) return 0.0f;
    void* node = load<void*>(sentinel);
    for (size_t n = 0; node != sentinel && n < MAX_NATIVE_PATH; ++n)
    {
        if (!readable(node, 32)) return 0.0f;
        if (load<uint32_t>(node, 16) == vehicle)
        {
            float length = load<float>(node, 24);
            return std::isfinite(length) && length > 0.0f && length < 20000.0f ? length : 0.0f;
        }
        node = load<void*>(node);
    }
    return 0.0f;
}
class ChangeBatch
{
    void* guard_{};
    bool owned_{};
    bool valid_{};
public:
    explicit ChangeBatch(void* engine)
    {
        if (!readable(engine, 521)) return;
        void* current = load<void*>(engine, 512);
        if (current)
        {
            // Do not open a nested modification or edit inside notifications.
            valid_ = readable(current, 81) && !load<uint8_t>(current, 80);
            return;
        }
        api.begin_changes(&guard_, engine);
        owned_ = true;
        valid_ = true;
    }
    ~ChangeBatch() noexcept(false) { if (owned_) api.end_changes(&guard_); }
    bool valid() const { return valid_; }
};
bool apply_path(void* engine, uint32_t vehicle, void* source_path, const std::vector<NativeEdge>& edges)
{
    PathTask task{};
    task.vehicle = vehicle;
    memcpy(task.path, source_path, 136);
    auto data = reinterpret_cast<uintptr_t>(edges.data());
    store(task.path, 0, data);
    store(task.path, 8, data + edges.size() * 12);
    store(task.path, 16, data + edges.size() * 12);
    store<int>(task.path, 24, 1);
    store<int>(task.path, 28, -1);
    store<int>(task.path, 40, 0);
    store<uint8_t>(task.path, 132, 0);
    // The original deferred task copies into the engine-owned vector and emits
    // component removal/addition notifications (releases/rebuilds reservations).
    // It neither owns nor destroys this borrowed snapshot/vector.
    ChangeBatch changes(engine);
    if (!changes.valid()) return false;
    api.apply(&task, engine);
    return true;
}
enum class ReturnPath { WaitingForContext, Unreachable, Reachable };
ReturnPath check_return_path(void* engine, void* tv, uint32_t vehicle,
                            const std::array<unsigned char, 112>& captured_context, bool have_context,
                            const std::vector<NativeEdge>& edges, const std::vector<double>& prefix,
                            uint32_t target_index, float target_offset, float length)
{
    if (!have_context) return ReturnPath::WaitingForContext;
    auto context = captured_context;
    store(context.data(), 32, engine);
    double front = prefix[target_index] + target_offset + length * 0.5;
    size_t front_index = static_cast<size_t>(std::upper_bound(prefix.begin(), prefix.end(), front) - prefix.begin() - 1);
    if (front_index >= edges.size()) return ReturnPath::Unreachable;
    // Match def::SetPathToStation's start-prefix contract, but place the whole
    // leading half of the train at the proposed target without editing Engine.
    auto begin = reinterpret_cast<unsigned char*>(const_cast<NativeEdge*>(edges.data() + target_index));
    auto end = reinterpret_cast<unsigned char*>(const_cast<NativeEdge*>(edges.data() + front_index + 1));
    NativeVector start{begin, end, end}, extra{};
    NativePath output{};
    struct Cleanup { NativePath& path; ~Cleanup() { api.destroy_path(&path); } } cleanup{output};
    uint32_t line = load<uint32_t>(tv, 160);
    int stop = load<int>(tv, 164);
    if (stop < 0) return ReturnPath::Unreachable;
    bool terminal = false;
    float cost = 1.0e9f;
    EditingScope editing_scope;
    PathVehicleScope path_scope(vehicle);
    api.find_path(&output, context.data(), &start, &extra, load<uint32_t>(tv, 56), &line, stop,
                  &terminal, &cost, nullptr, true, false, UINT64_MAX);
    return output.edges.begin && output.edges.end > output.edges.begin ? ReturnPath::Reachable : ReturnPath::Unreachable;
}
bool restore(Job& job, void* engine, void* path, void* tv,
             const std::array<unsigned char, 112>& captured_context, bool have_context)
{
    if (!job.changed_path)
    {
        store<int>(path, 40, job.initial_state);
        return true;
    }
    if (!have_context) return false;
    auto context_copy = captured_context;
    auto context = context_copy.data();
    // The normal helper receives a context embedded in a COW system snapshot.
    // Rebind its Engine reference to the live update currently committing edits.
    store(context, 32, engine);
    uint32_t vehicle = job.command.vehicle_id;
    uint32_t line = load<uint32_t>(tv, 160);
    int stop = load<int>(tv, 164);
    if (stop < 0) return false;
    NativeVector tasks{};
    EditingScope editing_scope;
    struct Cleanup
    {
        NativeVector& tasks;
        ~Cleanup() { api.destroy_tasks(&tasks); }
    } cleanup{tasks};
    PathVehicleScope path_scope(vehicle);
    auto found = api.station(
        context, &vehicle, &line, stop, tv, path, 1, 0, UINT64_MAX, &tasks, 0);
    if (found)
    {
        ChangeBatch changes(engine);
        if (!changes.valid())
            return false;
        for (auto slot = tasks.begin; slot < tasks.end; slot += 64)
        {
            void* task = load<void*>(slot, 56);
            auto vtable = load<uintptr_t*>(task);
            reinterpret_cast<ApplyFn>(vtable[2])(task, engine);
        }
    }
    // No path means retain the override and hold; retry next update. Never
    // restore an old path snapshot at a different physical train position.
    return found != 0;
}
void reject(Job& job, const char* reason)
{
    job.phase = Phase::Rejected;
    job.detail = reason;
    job.cap = 0.0f;
    job.path = nullptr;
}
void tick(void* system, void* engine, float dt, bool after)
{
    JobsLock lock;
    bool any_active = false;
    for (const auto& job : jobs) if (active(job)) { any_active = true; break; }
    if (!any_active) return;
    uint64_t session = api.session();
    if (!session) return;
    int mp_type = type_id(engine, 0x41D4860);
    int tv_type = type_id(engine, 0x41D6D40);
    int network_type = type_id(engine, 0x41D6B38);
    ULONGLONG now = GetTickCount64();
    for (auto& job : jobs)
    {
        if (!active(job)) continue;
        if (job.phase == Phase::Pending && (job.release || now >= job.deadline))
        { job.phase = Phase::Released; job.detail = "RELEASED_BEFORE_START"; continue; }
        if (job.session && job.session != session)
        { reject(job, "WORLD_CHANGED"); continue; }
        void* mp = component(engine, job.command.vehicle_id, mp_type, 136);
        void* tv = component(engine, job.command.vehicle_id, tv_type, TRANSPORT_VEHICLE_SIZE);
        if (!mp || !tv) { reject(job, "TRAIN_UNAVAILABLE"); continue; }
        // Snapshot addresses change every update. Refresh them; ownership is
        // verified by session + the ordered path, not pointer identity.
        job.path = mp;
        std::vector<NativeEdge> edges;
        std::vector<double> prefix;
        double current{};
        if (!path_edges(mp, edges) || !distances(engine, network_type, edges, prefix) || !position(mp, prefix, current))
        { reject(job, "INVALID_ENGINE_PATH"); continue; }
        if (job.phase != Phase::Pending && hash_path(edges) != job.path_hash)
        { reject(job, "PATH_CHANGED_EXTERNALLY"); continue; }
        if (job.release || unloading || now >= job.deadline) job.phase = Phase::Restoring;
        if (job.phase == Phase::Restoring)
        {
            job.cap = 0.0f;
            store<float>(mp, 64, 0.0f);
            store<int>(mp, 40, 2); // Suspend motion until a valid normal route is committed.
            bool restored = false;
            if (!after)
            {
                auto captured_context = vehicle_context;
                bool have_context = vehicle_context_available;
                WithoutJobsLock unlocked(lock);
                restored = restore(job, engine, mp, tv, captured_context, have_context);
            }
            if (restored)
            {
                job.phase = Phase::Released;
                job.path = nullptr;
                job.detail = "NORMAL_ROUTE_RESTORED";
            }
            else job.detail = "WAITING_FOR_NORMAL_ROUTE";
            continue;
        }
        if (job.phase == Phase::Pending)
        {
            if (after) continue;
            float length = train_length(system, job.command.vehicle_id);
            if (!length || load<int>(tv, 0) != 1 || load<int>(tv, 144) != 1 ||
                !std::isfinite(dt) || dt <= 0.0f)
            { reject(job, "REQUIRES_EN_ROUTE_RAIL_TRAIN"); continue; }
            job.path = mp;
            job.initial_state = load<int>(mp, 40);
            job.session = session;
            int centre_index = load<int>(mp, 52);
            if (job.route)
            {
                std::vector<NativeEdge> requested;
                for (uint32_t i = 0; i < job.command.edge_count; ++i)
                {
                    auto& e = job.command.edges[i];
                    requested.push_back({e.entity, e.index, static_cast<uint8_t>(e.direction), {0, 0, 0}});
                }
                std::vector<double> route_prefix;
                if (!same_edge(edges[centre_index], requested[0]) ||
                    !distances(engine, network_type, requested, route_prefix))
                { reject(job, "ROUTE_NOT_CONTIGUOUS_FROM_CURRENT_EDGE"); continue; }
                double offset = job.command.target_offset_m;
                if (offset > route_prefix[job.command.target_index + 1] - route_prefix[job.command.target_index])
                { reject(job, "TARGET_OFFSET_OUTSIDE_EDGE"); continue; }
                // Keep the entire track occupied by the train's front unchanged.
                double front = load<float>(mp, 56) + length * 0.5 + 0.1;
                bool occupied_matches = true;
                for (size_t i = 0; route_prefix[i] <= front; ++i)
                {
                    if (i >= requested.size() || centre_index + i >= edges.size() ||
                        !same_edge(requested[i], edges[centre_index + i]))
                    { occupied_matches = false; break; }
                    if (i + 1 == requested.size()) break;
                }
                double target = route_prefix[job.command.target_index] + offset;
                if (!occupied_matches || target <= load<float>(mp, 56) ||
                    route_prefix[requested.size() - 1] - target < length * 0.5 + 10.0)
                { reject(job, "OCCUPIED_PREFIX_OR_TARGET_CLEARANCE_INVALID"); continue; }
                if (job.flags & TPF2_MOVEMENT_REQUIRE_RESUMABLE_ROUTE)
                {
                    auto context = vehicle_context;
                    bool have_context = vehicle_context_available;
                    ReturnPath recovery;
                    job.phase = Phase::Applying;
                    {
                        WithoutJobsLock unlocked(lock);
                        recovery = check_return_path(engine, tv, job.command.vehicle_id, context, have_context,
                            requested, route_prefix, job.command.target_index, job.command.target_offset_m, length);
                    }
                    job.phase = Phase::Pending;
                    if (job.release)
                    { job.phase = Phase::Released; job.detail = "RELEASED_BEFORE_START"; continue; }
                    if (recovery == ReturnPath::WaitingForContext)
                    { job.detail = "WAITING_FOR_ROUTE_CONTEXT"; continue; }
                    if (recovery == ReturnPath::Unreachable)
                    { reject(job, "NORMAL_ROUTE_UNREACHABLE_FROM_TARGET"); continue; }
                }
                edges.resize(centre_index);
                edges.insert(edges.end(), requested.begin(), requested.end());
                job.path_hash = hash_path(edges);
                job.phase = Phase::Applying; // Keep slot pinned while native callbacks run.
                bool applied = false;
                {
                    WithoutJobsLock unlocked(lock);
                    EditingScope editing_scope;
                    applied = apply_path(engine, job.command.vehicle_id, mp, edges);
                }
                if (!applied)
                { job.phase = Phase::Pending; job.detail = "WAITING_FOR_CHANGE_BATCH"; continue; }
                job.changed_path = true;
                mp = component(engine, job.command.vehicle_id, mp_type, 136);
                if (!mp || !path_edges(mp, edges) || !distances(engine, network_type, edges, prefix) || !position(mp, prefix, current))
                { job.phase = Phase::Restoring; job.detail = "PATH_COMMIT_REQUIRES_RECOVERY"; continue; }
                job.target_index = centre_index + job.command.target_index;
                job.target_offset = job.command.target_offset_m;
            }
            else
            {
                double target = current + job.distance;
                // Avoid generating a native arrival event before our target.
                int skip = load<int>(mp, 24);
                if (skip < 0 || static_cast<size_t>(skip) >= edges.size() ||
                    prefix[edges.size() - skip] - target < length * 0.5 + 10.0)
                { reject(job, "TARGET_OUTSIDE_CURRENT_ROUTE_CLEARANCE"); continue; }
                auto it = std::upper_bound(prefix.begin(), prefix.end(), target);
                job.target_index = static_cast<int>(it - prefix.begin()) - 1;
                job.target_offset = static_cast<float>(target - prefix[job.target_index]);
            }
            job.path_hash = hash_path(edges);
            job.phase = Phase::Moving;
            job.detail = "NATIVE_MOTION_ACTIVE";
        }
        if (hash_path(edges) != job.path_hash || job.target_index < 0 ||
            static_cast<size_t>(job.target_index + 1) >= prefix.size())
        {
            job.phase = Phase::Restoring;
            job.detail = "PATH_CHANGED_EXTERNALLY";
            job.cap = 0.0f;
            store<float>(mp, 64, 0.0f);
            continue;
        }
        job.path = mp;
        job.step_seconds = dt;
        job.remaining = prefix[job.target_index] + job.target_offset - current;
        if (job.remaining <= STOP_EPSILON)
        {
            job.phase = Phase::Held;
            job.cap = 0.0f;
            job.detail = "TARGET_REACHED_HOLDING";
            store<float>(mp, 64, 0.0f);
            store<int>(mp, 40, 2);
        }
        else
        {
            // Use the same nominal deceleration as the native train system.
            float deceleration = load<float>(system, 92);
            job.cap = train_motion::speed_cap(job.command.speed_mps, job.remaining, dt, deceleration);
            if (!after)
            {
                float speed = load<float>(mp, 64);
                if (!std::isfinite(speed) || speed < 0.0f)
                { job.phase = Phase::Restoring; job.detail = "INVALID_NATIVE_SPEED"; job.cap = 0.0f; continue; }
                // Native braking can skip GetSpeedLimit entirely. Bound the old
                // velocity here as well as bounding traction at its hook below.
                if (speed > job.cap) store<float>(mp, 64, job.cap);
            }
        }
        if (!after && job.phase == Phase::Moving)
            store<int>(mp, 40, 0); // Override a native user-stop for this movement only.
    }
}
void train_update(void* system, void* engine, int count, float dt)
{
    auto& manager = DetourManager::Instance();
    auto guard = manager.adopt_hook_call();
    if (!manager.is_draining()) tick(system, engine, dt, false);
    original_train_update(system, engine, count, dt);
    if (!manager.is_draining()) tick(system, engine, dt, true);
}
void vehicle_update(void* system, void* engine, int count, float dt)
{
    auto& manager = DetourManager::Instance();
    auto guard = manager.adopt_hook_call();
    if (!manager.is_draining())
    {
        AcquireSRWLockExclusive(&jobs_lock);
        if (readable(system, 192))
        {
            memcpy(vehicle_context.data(), static_cast<unsigned char*>(system) + 64, vehicle_context.size());
            vehicle_context_available = true;
        }
        ReleaseSRWLockExclusive(&jobs_lock);
    }
    original_vehicle_update(system, engine, count, dt);
    if (!manager.is_draining()) native_telemetry::after_vehicle_update(system, engine, count, dt);
}
void status(const Job& job, char* detail, size_t capacity)
{
    _snprintf_s(detail, capacity, _TRUNCATE,
        "{\"movement_id\":%llu,\"state\":\"%s\",\"remaining_m\":%.3f,\"speed_cap_mps\":%.3f,\"detail\":\"%s\"}",
        static_cast<unsigned long long>(job.command.movement_id), phase_name(job.phase),
        job.remaining, job.cap, job.detail);
}
}

bool install_train_motion_hooks(DWORD vehicle_tls)
{
    image = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    if (!readable(reinterpret_cast<void*>(image), sizeof(IMAGE_DOS_HEADER))) return false;
    auto dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(image);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew < 0 ||
        !readable(reinterpret_cast<void*>(image + dos->e_lfanew), sizeof(IMAGE_NT_HEADERS64))) return false;
    auto nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(image + dos->e_lfanew);
    // Layout and RVAs were recovered from SHA256 782b904a...2585175c.
    if (nt->Signature != IMAGE_NT_SIGNATURE || nt->FileHeader.Machine != IMAGE_FILE_MACHINE_AMD64 ||
        nt->FileHeader.TimeDateStamp != 0x675ABCC6 || nt->OptionalHeader.SizeOfImage != 0x46CE000)
        return false;
    struct Signature { uintptr_t rva; const char* bytes; size_t size; };
    const Signature dependencies[] = {
        {APPLY_PATH, "\x40\x56\x57\x41\x56\x48\x83\xec\x40", 9},
        {TYPE_ID, "\x48\x8b\xc4\x57\x48\x81\xec\xa0\x00\x00\x00", 11},
        {STATION_PATH_ONLY, "\x40\x55\x53\x56\x57\x41\x54\x41\x55\x41\x56\x41\x57", 13},
        {DESTROY_TASKS, "\x48\x89\x5c\x24\x18\x57\x48\x83\xec\x20", 10},
        {BEGIN_CHANGES, "\x40\x53\x48\x83\xec\x20\x48\x8b\xd9\x48\x89\x11", 12},
        {END_CHANGES, "\x40\x53\x48\x83\xec\x20\x48\x8b\xd9", 9},
        {FIND_PATH_TO_STOP, "\x4c\x89\x4c\x24\x20\x4c\x89\x44\x24\x18", 10},
        {DESTROY_PATH, "\x40\x53\x48\x83\xec\x20\x48\x8b\xd9\x48\x8b\x09", 12}
    };
    for (auto& sig : dependencies)
        if (!readable(reinterpret_cast<void*>(image + sig.rva), sig.size) ||
            memcmp(reinterpret_cast<void*>(image + sig.rva), sig.bytes, sig.size)) return false;
    api = {reinterpret_cast<TypeFn>(image + TYPE_ID), reinterpret_cast<ApplyFn>(image + APPLY_PATH),
           reinterpret_cast<StationFn>(image + STATION_PATH_ONLY),
           reinterpret_cast<void (*)(NativeVector*)>(image + DESTROY_TASKS), [] { return loader_session.read(); },
           reinterpret_cast<void (*)(void*, void*)>(image + BEGIN_CHANGES),
           reinterpret_cast<void (*)(void*)>(image + END_CHANGES),
           reinterpret_cast<FindPathFn>(image + FIND_PATH_TO_STOP),
           reinterpret_cast<void (*)(void*)>(image + DESTROY_PATH)};
    path_vehicle_tls = vehicle_tls;
    // Exactly 14 bytes, all whole instructions, no RIP-relative operands.
    const unsigned char prologue[] = {0x48,0x8b,0xc4,0x55,0x56,0x57,0x41,0x54,0x41,0x55,0x41,0x56,0x41,0x57};
    auto& manager = DetourManager::Instance();
    return manager.install_detour(reinterpret_cast<unsigned char*>(image + TRAIN_UPDATE), prologue, sizeof(prologue),
               reinterpret_cast<void*>(&train_update), reinterpret_cast<void**>(&original_train_update), "TRAIN_UPDATE_SIGNATURE_MISMATCH") &&
           manager.install_detour(reinterpret_cast<unsigned char*>(image + VEHICLE_UPDATE), prologue, sizeof(prologue),
               reinterpret_cast<void*>(&vehicle_update), reinterpret_cast<void**>(&original_vehicle_update), "VEHICLE_UPDATE_SIGNATURE_MISMATCH");
}

uint32_t train_motion_command(const Tpf2CommandSlot* command, char* detail, size_t capacity)
{
    if (command->transaction_id) return TPF2_COMMAND_TRANSACTION_CONFLICT;
    uint64_t id{};
    bool move = command->opcode == TPF2_CMD_MOVE_TRAIN_DISTANCE || command->opcode == TPF2_CMD_MOVE_TRAIN_ROUTE;
    Job incoming{};
    if (command->flags & ~TPF2_MOVEMENT_REQUIRE_RESUMABLE_ROUTE) return TPF2_COMMAND_INVALID_PAYLOAD;
    if (command->flags && command->opcode != TPF2_CMD_MOVE_TRAIN_ROUTE) return TPF2_COMMAND_INVALID_PAYLOAD;
    incoming.flags = command->flags;
    if (move)
    {
        if (command->opcode == TPF2_CMD_MOVE_TRAIN_DISTANCE)
        {
            if (command->payload_size != sizeof(Tpf2MoveTrainDistancePayload)) return TPF2_COMMAND_INVALID_PAYLOAD;
            auto value = load<Tpf2MoveTrainDistancePayload>(command->payload);
            incoming.command.movement_id = value.movement_id;
            incoming.command.vehicle_id = value.vehicle_id;
            incoming.command.speed_mps = value.speed_mps;
            incoming.command.expires_in_seconds = value.expires_in_seconds;
            incoming.distance = value.distance_m;
            if (!std::isfinite(value.distance_m) || value.distance_m <= 0.0f || value.distance_m > 100000.0f)
                return TPF2_COMMAND_INVALID_PAYLOAD;
        }
        else
        {
            if (command->payload_size != sizeof(Tpf2MoveTrainRoutePayload)) return TPF2_COMMAND_INVALID_PAYLOAD;
            memcpy(&incoming.command, command->payload, sizeof(incoming.command));
            incoming.route = true;
            auto& c = incoming.command;
            if (!c.edge_count || c.edge_count > TPF2_MOVEMENT_ROUTE_CAPACITY || c.target_index >= c.edge_count ||
                !std::isfinite(c.target_offset_m) || c.target_offset_m < 0.0f) return TPF2_COMMAND_INVALID_PAYLOAD;
            for (uint32_t i = 0; i < c.edge_count; ++i)
                if (!c.edges[i].entity || c.edges[i].entity >= 0x40000000 || c.edges[i].index < 0 || c.edges[i].direction > 1)
                    return TPF2_COMMAND_INVALID_PAYLOAD;
            memset(c.edges + c.edge_count, 0, (TPF2_MOVEMENT_ROUTE_CAPACITY - c.edge_count) * sizeof(c.edges[0]));
        }
        auto& c = incoming.command;
        id = c.movement_id;
        if (!id || !c.vehicle_id || c.vehicle_id >= 0x40000000 || !std::isfinite(c.speed_mps) ||
            c.speed_mps <= 0.0f || c.speed_mps > 500.0f / 3.6f || c.expires_in_seconds < 5 || c.expires_in_seconds > 600)
            return TPF2_COMMAND_INVALID_PAYLOAD;
    }
    else
    {
        if (command->payload_size != sizeof(Tpf2RuleKeyPayload)) return TPF2_COMMAND_INVALID_PAYLOAD;
        id = load<uint64_t>(command->payload);
        if (!id) return TPF2_COMMAND_INVALID_PAYLOAD;
    }
    AcquireSRWLockExclusive(&jobs_lock);
    Job* found = nullptr;
    Job* free_slot = nullptr;
    for (auto& job : jobs)
    {
        if (job.phase != Phase::Empty && job.command.movement_id == id) found = &job;
        if (!active(job) && (!free_slot || job.phase == Phase::Empty || job.accepted < free_slot->accepted)) free_slot = &job;
    }
    uint32_t result = TPF2_COMMAND_OK;
    if (found)
    {
        if (move && (found->route != incoming.route || found->flags != incoming.flags || found->distance != incoming.distance ||
                     memcmp(&found->command, &incoming.command, sizeof(incoming.command)))) result = TPF2_COMMAND_MOVEMENT_CONFLICT;
        else if (command->opcode == TPF2_CMD_RELEASE_TRAIN_MOVEMENT && active(*found))
        {
            found->release = true;
            if (found->phase == Phase::Pending)
            { found->phase = Phase::Released; found->detail = "RELEASED_BEFORE_START"; }
            else found->detail = "RELEASE_QUEUED";
        }
        status(*found, detail, capacity);
    }
    else if (!move) result = TPF2_COMMAND_RULE_NOT_FOUND;
    else if (unloading) result = TPF2_COMMAND_CONTROLLER_DRAINING;
    else
    {
        for (auto& job : jobs)
            if (active(job) && job.command.vehicle_id == incoming.command.vehicle_id)
                result = TPF2_COMMAND_MOVEMENT_CONFLICT;
        if (!free_slot) result = TPF2_COMMAND_CAPACITY_EXCEEDED;
        if (result == TPF2_COMMAND_OK)
        {
            incoming.phase = Phase::Pending;
            incoming.accepted = GetTickCount64();
            incoming.deadline = incoming.accepted + incoming.command.expires_in_seconds * 1000ULL;
            *free_slot = incoming;
            status(*free_slot, detail, capacity);
        }
    }
    ReleaseSRWLockExclusive(&jobs_lock);
    return result;
}

float train_motion_speed_limit(void* move_path, float native_limit)
{
    if (editing) return native_limit;
    AcquireSRWLockShared(&jobs_lock);
    float limit = native_limit;
    for (const auto& job : jobs)
        if (active(job) && job.phase != Phase::Pending && job.phase != Phase::Applying && job.path == move_path)
        {
            limit = (std::min)(limit, job.cap);
            // Verified callsite 0x140AB9CA7: acceleration is read from mp+72
            // immediately after GetSpeedLimit returns. Its return value alone
            // only reduces traction, and the native final clamp uses technical
            // max speed instead. Constrain the actual integration input here.
            if (readable(move_path, 136) && job.step_seconds > 0.0f)
            {
                float speed = load<float>(move_path, 64);
                float acceleration = load<float>(move_path, 72);
                float maximum_acceleration = (limit - speed) / job.step_seconds;
                if (std::isfinite(speed) && std::isfinite(acceleration) && acceleration > maximum_acceleration)
                    store<float>(move_path, 72, maximum_acceleration);
            }
        }
    ReleaseSRWLockShared(&jobs_lock);
    return limit;
}

bool train_motion_blocks_station_path(void* context, uint32_t vehicle)
{
    if (editing || !readable(context, 40)) return false;
    AcquireSRWLockShared(&jobs_lock);
    bool blocked = false;
    for (const auto& job : jobs)
        if (active(job) && job.phase != Phase::Pending && job.phase != Phase::Applying && job.command.vehicle_id == vehicle)
            blocked = true;
    ReleaseSRWLockShared(&jobs_lock);
    return blocked;
}

bool prepare_train_motion_unload(DWORD timeout_ms)
{
    ULONGLONG deadline = GetTickCount64() + timeout_ms;
    for (;;)
    {
        AcquireSRWLockExclusive(&jobs_lock);
        unloading = true;
        bool busy = false;
        for (auto& job : jobs)
            if (active(job))
            {
                job.release = true;
                if (job.phase == Phase::Pending)
                { job.phase = Phase::Released; job.detail = "RELEASED_BEFORE_START"; }
                else busy = true;
            }
        ReleaseSRWLockExclusive(&jobs_lock);
        if (!busy) return true;
        if (GetTickCount64() >= deadline)
        {
            AcquireSRWLockExclusive(&jobs_lock);
            unloading = false;
            ReleaseSRWLockExclusive(&jobs_lock);
            return false;
        }
        Sleep(10);
    }
}
