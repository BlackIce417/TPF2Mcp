#include "pch.h"
#include "native_telemetry.h"
#include "../../shared/native_telemetry_bridge.h"
#include "../../shared/train_telemetry_protocol.h"
#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstring>
#include <ctime>
#include <limits>
#include <string>
#include <unordered_map>
#include <vector>

namespace native_telemetry {
namespace {
using namespace tpf2::loader::telemetry;
constexpr float unknown = std::numeric_limits<float>::quiet_NaN();
struct Vector { uintptr_t begin, end, capacity; };
struct PathEdge { uint32_t entity; int32_t index; uint8_t direction, pad[3]; };
struct Bounds { Vec3f min, max; };
static_assert(sizeof(Vector) == 24 && sizeof(PathEdge) == 12 && sizeof(Bounds) == 24);
template<class T> T load(const void* p, size_t offset = 0) {
    T value{}; std::memcpy(&value, static_cast<const char*>(p) + offset, sizeof(T)); return value;
}
template<class T> void store(void* p, size_t offset, const T& value) {
    std::memcpy(static_cast<char*>(p) + offset, &value, sizeof(T));
}
// Per-callback region cache. Never retain component/System addresses between updates.
struct Memory {
    struct Region { uintptr_t start, end; };
    std::vector<Region> regions;
    bool readable(const void* p, size_t size) {
        uintptr_t pos = reinterpret_cast<uintptr_t>(p), end = pos + size;
        if (!pos || !size || end < pos) return false;
        while (pos < end) {
            auto it = std::find_if(regions.begin(), regions.end(), [pos](auto r) { return r.start <= pos && pos < r.end; });
            if (it != regions.end()) { pos = it->end; continue; }
            MEMORY_BASIC_INFORMATION m{};
            if (!VirtualQuery(reinterpret_cast<void*>(pos), &m, sizeof(m)) || m.State != MEM_COMMIT ||
                (m.Protect & (PAGE_GUARD | PAGE_NOACCESS))) return false;
            Region region{reinterpret_cast<uintptr_t>(m.BaseAddress), reinterpret_cast<uintptr_t>(m.BaseAddress) + m.RegionSize};
            if (region.end <= pos) return false;
            regions.push_back(region); pos = region.end;
        }
        return true;
    }
    size_t vector_size(Vector v, size_t stride, size_t maximum) {
        if (!stride || v.end < v.begin || v.capacity < v.end || (v.end - v.begin) % stride) throw "INVALID_VECTOR";
        size_t n = (v.end - v.begin) / stride;
        if (n > maximum || (n && !readable(reinterpret_cast<void*>(v.begin), n * stride))) throw "INVALID_VECTOR";
        return n;
    }
    void* component(void* engine, uint32_t entity, int type, size_t stride) {
        if (type < 0 || type > 4096 || !readable(engine, 184)) return nullptr;
        auto entities = load<uintptr_t>(engine, 160), entities_end = load<uintptr_t>(engine, 168);
        if (entities_end < entities || (entities_end - entities) % 24 || entity >= (entities_end - entities) / 24) return nullptr;
        void* entry = reinterpret_cast<void*>(entities + 24ULL * entity);
        if (!readable(entry, 24)) return nullptr;
        Vector list{load<uintptr_t>(entry), load<uintptr_t>(entry, 8), load<uintptr_t>(entry, 8)};
        size_t n = vector_size(list, 8, 8192);
        int index = -1;
        for (size_t i = 0; i < n; ++i) {
            auto p = reinterpret_cast<void*>(list.begin + i * 8);
            if (load<int>(p) == type) { index = load<int>(p, 4); break; }
        }
        if (index < 0) return nullptr;
        auto pools = load<uintptr_t>(engine, 136), end = load<uintptr_t>(engine, 144);
        if (end < pools || static_cast<size_t>(type) >= (end - pools) / 8 || !readable(reinterpret_cast<void*>(pools + 8ULL * type), 8)) return nullptr;
        void* pool = load<void*>(reinterpret_cast<void*>(pools + 8ULL * type));
        if (!readable(pool, 144)) return nullptr;
        uintptr_t address{};
        if (index < 0x40000000) {
            auto begin = load<uintptr_t>(pool, 104), finish = load<uintptr_t>(pool, 112);
            if (finish < begin || static_cast<size_t>(index) >= (finish - begin) / stride) return nullptr;
            address = begin + stride * index;
        } else {
            unsigned slot = index - 0x40000000;
            auto begin = load<uintptr_t>(pool, 128), finish = load<uintptr_t>(pool, 136);
            if (finish < begin || slot / 32 >= (finish - begin) / 16 || !readable(reinterpret_cast<void*>(begin + 16ULL * (slot / 32)), 8)) return nullptr;
            address = load<uintptr_t>(reinterpret_cast<void*>(begin + 16ULL * (slot / 32))) + stride * (slot % 32);
        }
        return readable(reinterpret_cast<void*>(address), stride) ? reinterpret_cast<void*>(address) : nullptr;
    }
};
struct Json {
    std::string text;
    Json& raw(const char* s) { text += s; return *this; }
    Json& integer(int64_t n) { char b[32]; auto r = std::to_chars(b, b + sizeof(b), n); text.append(b, r.ptr); return *this; }
    Json& number(double n) {
        if (!std::isfinite(n)) return raw("null");
        char b[64]; auto r = std::to_chars(b, b + sizeof(b), n); text.append(b, r.ptr); return *this;
    }
    Json& boolean(bool value) { return raw(value ? "true" : "false"); }
    Json& string(const char* value) {
        raw("\"");
        for (const unsigned char* p = reinterpret_cast<const unsigned char*>(value); *p; ++p) {
            if (*p == '"' || *p == '\\') { text += '\\'; text += char(*p); }
            else if (*p < 32) { char b[7]; sprintf_s(b, "\\u%04x", *p); text += b; }
            else text += char(*p);
        }
        return raw("\"");
    }
    Json& vec(Vec3f v) { return raw("{\"x\":").number(v.x).raw(",\"y\":").number(v.y).raw(",\"z\":").number(v.z).raw("}"); }
};
using ContextFn = int (*)(Tpf2NativeTelemetryContext*);
using SeedFn = size_t (*)(uint64_t, char*, size_t, uint64_t*);
using PublishFn = int (*)(uint64_t, const char*, const char*, size_t);
using RequestFn = void (*)(uint64_t);
ContextFn get_context{}; SeedFn get_seed{}; PublishFn publish{}; RequestFn request{};
uint64_t epoch{}, revision{}, sequence{};
std::vector<char> seed, scratch(16 * 1024 * 1024);
std::unordered_map<uint32_t, float> track_limits;
std::unordered_map<uint32_t, float> cargo_weights;
float passenger_unit_weight = unknown;
struct Motion { float speed; uint64_t time_us; };
std::unordered_map<uint32_t, Motion> motion;
struct Quality {
    uint32_t unverified_passenger_trains{}, missing_seat_entities{};
    uint32_t first_vehicle{}, first_expected{}, first_assigned{};
} quality;
bool faulted{};
SRWLOCK sample_lock = SRWLOCK_INIT;

bool bind() {
    if (get_context) return true;
    auto module = GetModuleHandleW(L"tpf2_loader.dll");
    if (!module) return false;
    auto a = reinterpret_cast<ContextFn>(GetProcAddress(module, "tpf2_loader_native_telemetry_context"));
    auto b = reinterpret_cast<SeedFn>(GetProcAddress(module, "tpf2_loader_native_telemetry_seed"));
    auto c = reinterpret_cast<PublishFn>(GetProcAddress(module, "tpf2_loader_native_telemetry_publish"));
    auto d = reinterpret_cast<RequestFn>(GetProcAddress(module, "tpf2_loader_native_telemetry_request_metadata"));
    if (!a || !b || !c || !d) return false;
    get_seed = b; publish = c; request = d; get_context = a; return true;
}
template<class T> void range(const TrainTelemetryFrameHeader& h, uint32_t offset, uint32_t count) {
    if (offset < sizeof(h) || uint64_t(offset) + uint64_t(count) * sizeof(T) > h.total_size) throw "INVALID_SEED_RANGE";
}
void validate_seed(const std::vector<char>& data) {
    if (data.size() < sizeof(TrainTelemetryFrameHeader)) throw "INVALID_SEED_HEADER";
    auto h = load<TrainTelemetryFrameHeader>(data.data());
    if (h.magic != kFrameMagic || h.protocol_version != 1 || h.header_size != sizeof(h) ||
        h.total_size > data.size() || h.train_count > 2048 || h.part_count > 2048 * 256) throw "INVALID_SEED_HEADER";
    if (h.trains_offset != sizeof(h) || h.parts_offset != uint64_t(h.trains_offset) + uint64_t(h.train_count)*sizeof(TrainWrapper) ||
        h.passenger_loads_offset != uint64_t(h.parts_offset) + uint64_t(h.part_count)*sizeof(VehiclePartWrapper) ||
        h.freight_loads_offset != uint64_t(h.passenger_loads_offset) + uint64_t(h.passenger_load_count)*sizeof(PassengerLoadEntry) ||
        h.total_size != uint64_t(h.freight_loads_offset) + uint64_t(h.freight_load_count)*sizeof(FreightLoadEntry)) throw "INVALID_SEED_LAYOUT";
    range<TrainWrapper>(h, h.trains_offset, h.train_count); range<VehiclePartWrapper>(h, h.parts_offset, h.part_count);
    range<PassengerLoadEntry>(h, h.passenger_loads_offset, h.passenger_load_count); range<FreightLoadEntry>(h, h.freight_loads_offset, h.freight_load_count);
    for (uint32_t i = 0; i < h.train_count; ++i) {
        auto t = load<TrainWrapper>(data.data(), h.trains_offset + i * sizeof(TrainWrapper));
        if (t.struct_version != 1 || t.struct_size != sizeof(t) || !t.parts_count || t.parts_count > 256 ||
            uint64_t(t.parts_offset) + t.parts_count > h.part_count) throw "INVALID_SEED_TRAIN";
    }
    for (uint32_t i = 0; i < h.part_count; ++i) {
        auto p = load<VehiclePartWrapper>(data.data(), h.parts_offset + i * sizeof(VehiclePartWrapper));
        if (p.struct_version != 1 || p.struct_size != sizeof(p) || uint64_t(p.passenger_load_offset) + p.passenger_load_count > h.passenger_load_count ||
            uint64_t(p.freight_load_offset) + p.freight_load_count > h.freight_load_count) throw "INVALID_SEED_PART";
    }
}
struct Types { int vehicle, train, path, bounds, person, game_time, game_speed; };
Types types(void* engine) {
    using Fn = int (*)(void*, const void*);
    auto image = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    auto fn = reinterpret_cast<Fn>(image + 0xD0A40);
    auto get = [&](uintptr_t rva) { const void* type = reinterpret_cast<void*>(image + rva); return fn(static_cast<char*>(engine) + 72, &type); };
    return {get(0x41D6D40), get(0x41D6E80), get(0x41D4860), get(0x41D48C8), get(0x41D7138), get(0x41D4A48), get(0x41D4BE0)};
}
std::unordered_map<uint32_t, void*> hash_values(Memory& m, void* base, size_t maximum) {
    std::unordered_map<uint32_t, void*> out;
    if (!m.readable(base, 24)) throw "INVALID_HASH_MAP";
    auto head = load<void*>(base, 8); auto count = load<size_t>(base, 16);
    if (count > maximum || !m.readable(head, 16)) throw "INVALID_HASH_MAP";
    auto node = load<void*>(head);
    for (size_t i = 0; i < count; ++i) {
        if (node == head || !m.readable(node, 48)) throw "INVALID_HASH_NODE";
        if (!out.emplace(load<uint32_t>(node, 16), static_cast<char*>(node) + 24).second) throw "DUPLICATE_HASH_NODE";
        node = load<void*>(node);
    }
    if (node != head) throw "INVALID_HASH_LENGTH";
    return out;
}
std::unordered_map<uint32_t, Vector> cargo_infos(Memory& m, void* system) {
    std::unordered_map<uint32_t, Vector> out;
    if (!m.readable(system, 696)) throw "INVALID_VEHICLE_SYSTEM";
    auto ctrl = load<const signed char*>(system, 664); auto slots = load<const char*>(system, 672);
    auto size = load<size_t>(system, 680), mask = load<size_t>(system, 688);
    if (!size) return out;
    if (mask > 1048575 || size > mask || !m.readable(ctrl, mask + 1) || !m.readable(slots, mask * 32)) throw "INVALID_CARGO_INFO_MAP";
    for (size_t i = 0; i < mask; ++i) if (ctrl[i] >= 0) {
        auto slot = slots + i * 32; out.emplace(load<uint32_t>(slot), load<Vector>(slot, 8));
    }
    if (out.size() != size) throw "INVALID_CARGO_INFO_SIZE";
    return out;
}
bool bounds(Memory& m, void* engine, uint32_t id, const Types& t, Bounds& out) {
    auto p = m.component(engine, id, t.bounds, 24);
    if (!p) return false;
    out = load<Bounds>(p);
    return std::isfinite(out.min.x) && std::isfinite(out.min.y) && std::isfinite(out.min.z) &&
        std::isfinite(out.max.x) && std::isfinite(out.max.y) && std::isfinite(out.max.z) &&
        out.min.x <= out.max.x && out.min.y <= out.max.y && out.min.z <= out.max.z;
}
Vec3f center(Bounds b) { return {(b.min.x+b.max.x)*.5f, (b.min.y+b.max.y)*.5f, (b.min.z+b.max.z)*.5f}; }
int allocated(int total, int offset, int capacity) {
    if (offset < 0 || capacity < 0 || total < 0) throw "INVALID_CARGO_COUNT";
    return static_cast<int>((std::min)(int64_t(capacity), (std::max)(int64_t(0), int64_t(total) - offset)));
}
void prefix(Json& j, const Tpf2NativeTelemetryContext& c, const char* section, const char* kind) {
    j.raw("{\"schema_version\":1,\"collector_revision\":\"native-v1\",\"source_status\":\"ENGINE_OBSERVED_DYNAMIC\",\"write_command_sent\":false,\"section\":").string(section)
        .raw(",\"probe_kind\":").string(kind).raw(",\"session_id\":").string(c.session).raw(",\"generated_at\":").integer(std::time(nullptr))
        .raw(",\"simulation_clock\":").raw(c.clock_json[0] ? c.clock_json : "{}")
        .raw(",\"report_mode\":\"PERIODIC\",\"report_interval_updates\":1,\"report_interval_seconds\":0.2,\"report_interval_basis\":\"SIMULATION_UPDATES_NOT_WALL_TIME\",\"errors\":[],\"vehicles\":[");
}
// All game pointer reads and serialization happen while the owning update is
// current. Only owned byte buffers reach the Loader; no game pointers escape.
void collect(void* system, void* engine, const Types& ty, const Tpf2NativeTelemetryContext& c) {
    LARGE_INTEGER started{}, finished{}, frequency{};
    QueryPerformanceCounter(&started); QueryPerformanceFrequency(&frequency);
    Memory m;
    quality = {};
    auto game_time = m.component(engine, c.world_entity, ty.game_time, 56);
    auto game_speed = m.component(engine, c.world_entity, ty.game_speed, 8);
    if (!game_time || !game_speed) throw "SIMULATION_CLOCK_UNAVAILABLE";
    int64_t millis = load<int64_t>(game_time);
    if (millis < 0 || millis > INT64_MAX / 1000) throw "INVALID_GAME_TIME";
    Json clock;
    clock.raw("{\"source_status\":\"ENGINE_COMPONENT\",\"game_time\":").integer(millis)
        .raw(",\"tick_count\":").integer(load<int>(game_time, 48)).raw(",\"update_count\":").integer(load<int>(game_time, 52))
        .raw(",\"speedup\":").integer(load<int>(game_speed, 4)).raw(",\"millis_per_day\":").integer(load<int>(game_speed))
        .raw(",\"game_time0\":");
    if (load<uint8_t>(game_time, 16)) clock.integer(load<int64_t>(game_time, 8)); else clock.raw("null");
    clock.raw("}");
    auto sampled = c;
    if (clock.text.size() >= sizeof(sampled.clock_json)) throw "CLOCK_JSON_TOO_LARGE";
    std::memcpy(sampled.clock_json, clock.text.c_str(), clock.text.size() + 1);
    if (!m.readable(system, 696)) throw "INVALID_SYSTEM";
    void* joined = load<void*>(system, 8);
    if (!m.readable(joined, 24)) throw "INVALID_VEHICLE_JOIN";
    Vector rows = load<Vector>(joined); size_t row_count = m.vector_size(rows, 8, 100000);
    std::vector<uint32_t> ids;
    for (size_t i = 0; i < row_count; ++i) ids.push_back(load<uint32_t>(reinterpret_cast<void*>(rows.begin + 8 * i)));
    std::sort(ids.begin(), ids.end());
    if (std::adjacent_find(ids.begin(), ids.end()) != ids.end()) throw "DUPLICATE_VEHICLE";
    auto info = cargo_infos(m, system);
    auto cargo_system = load<void*>(system, 184);
    if (!m.readable(cargo_system, 216)) throw "INVALID_CARGO_SYSTEM";
    auto counts = hash_values(m, static_cast<char*>(cargo_system) + 152, 100000);
    auto sets = hash_values(m, static_cast<char*>(cargo_system) + 24, 100000);
    std::vector<char> frame(seed.begin(), seed.begin() + load<TrainTelemetryFrameHeader>(seed.data()).total_size);
    auto h = load<TrainTelemetryFrameHeader>(frame.data());
    frame.resize(h.passenger_loads_offset);
    std::vector<PassengerLoadEntry> passenger_entries;
    std::vector<FreightLoadEntry> freight_entries;
    h.sample_sequence = ++sequence;
    h.sample_time_us = static_cast<uint64_t>(millis) * 1000;
    std::unordered_map<uint32_t, uint32_t> train_rows;
    for (uint32_t i = 0; i < h.train_count; ++i) train_rows.emplace(static_cast<uint32_t>(load<TrainWrapper>(frame.data(), h.trains_offset + i * sizeof(TrainWrapper)).entity_id), i);
    Json positions, footprints;
    prefix(positions, sampled, "vehicle_positions", "OPERATIONAL_VEHICLE_POSITION_FRAME");
    prefix(footprints, sampled, "train_footprints", "OPERATIONAL_TRAIN_FOOTPRINT_FRAME");
    size_t trains_seen = 0;
    for (size_t vi = 0; vi < ids.size(); ++vi) {
        uint32_t id = ids[vi];
        void* tv = m.component(engine, id, ty.vehicle, 360);
        if (!tv) throw "VEHICLE_COMPONENT_MISSING";
        auto path = m.component(engine, id, ty.path, 136);
        Vector edges{}; size_t edge_count = 0; int index = -1; PathEdge edge{};
        float speed = unknown, accel = unknown, brake = unknown, pos01 = unknown;
        if (path) {
            edges = load<Vector>(path); edge_count = m.vector_size(edges, sizeof(PathEdge), 100000);
            index = load<int>(path, 52); pos01 = load<float>(path, 60);
            speed = load<float>(path, 64); brake = load<float>(path, 68); accel = load<float>(path, 72);
            if (index >= 0 && size_t(index) < edge_count) edge = load<PathEdge>(reinterpret_cast<void*>(edges.begin + sizeof(PathEdge) * index));
        }
        const bool valid_edge = edge.entity && index >= 0 && size_t(index) < edge_count && edge.direction <= 1;
        Bounds root_bounds{}; bool root_valid = bounds(m, engine, id, ty, root_bounds);
        if (vi < 2048) {
        if (vi) positions.raw(",");
        positions.raw("{\"entity_id\":").integer(id).raw(",\"line_id\":").integer(load<uint32_t>(tv, 160)).raw(",\"raw_state\":").integer(load<int>(tv, 144))
            .raw(",\"stop_index\":").integer(load<int>(tv, 164)).raw(",\"arrival_station_index\":").integer(load<int>(tv, 168))
            .raw(",\"arrival_terminal_index\":").integer(load<int>(tv, 172)).raw(",\"position\":");
        if (root_valid) positions.vec(center(root_bounds)); else positions.raw("null");
        positions.raw(",\"current_edge_id\":").integer(valid_edge ? edge.entity : 0).raw(",\"current_edge_index\":");
        if (path) positions.integer(index); else positions.raw("null");
        positions.raw(",\"current_edge_direction\":"); if (valid_edge) positions.boolean(edge.direction != 0); else positions.raw("null");
        positions.raw(",\"current_edge_param\":").number(valid_edge ? (edge.direction ? pos01 : 1 - pos01) : unknown)
            .raw(",\"speed_mps\":").number(speed).raw(",\"acceleration_mps2\":").number(accel).raw(",\"approaching_station\":");
        if (path) positions.boolean(load<uint8_t>(path, 88) != 0); else positions.raw("null");
        positions.raw("}");
        }
        if (load<int>(tv) != 1) continue;
        auto train = m.component(engine, id, ty.train, 32);
        if (!train) continue; // Same as Lua: trains without a body are omitted.
        Vector parts = load<Vector>(train); size_t part_count = m.vector_size(parts, 4, 256);
        if (!part_count) continue;
        auto row_it = train_rows.find(id);
        if (row_it == train_rows.end()) { request(c.epoch); throw "CONSIST_METADATA_REQUIRED"; }
        auto offset = h.trains_offset + row_it->second * sizeof(TrainWrapper);
        auto t = load<TrainWrapper>(frame.data(), offset);
        if (t.parts_count != part_count) { request(c.epoch); throw "CONSIST_METADATA_REQUIRED"; }
        auto configs = load<Vector>(tv, 8);
        if (m.vector_size(configs, 128, 256) != part_count) throw "CONSIST_CONFIG_MISMATCH";
        auto info_it = info.find(id);
        if (info_it == info.end() || m.vector_size(info_it->second, 24, 256) != part_count) throw "CARGO_INFO_UNAVAILABLE";
        Vector total_counts{};
        auto counts_it = counts.find(id);
        if (counts_it != counts.end()) total_counts = load<Vector>(counts_it->second);
        size_t count_types = m.vector_size(total_counts, 4, 256);
        auto count = [&](size_t cargo) { return cargo < count_types ? load<int>(reinterpret_cast<void*>(total_counts.begin + 4 * cargo)) : 0; };
        // Actual passenger carriage assignment; do not mistake cargo-model
        // fill offsets for the seats occupied by individual passengers.
        std::vector<uint32_t> passengers(part_count, 0);
        bool assignment_complete = true;
        auto set_it = sets.find(id);
        if (set_it != sets.end()) {
            auto categories = load<Vector>(set_it->second);
            if (m.vector_size(categories, 64, 256)) {
                auto passenger_set = reinterpret_cast<void*>(categories.begin);
                auto head = load<void*>(passenger_set, 8); size_t size = load<size_t>(passenger_set, 16);
                if (size > 100000 || !m.readable(head, 16)) throw "INVALID_PASSENGER_SET";
                auto node = load<void*>(head);
                for (size_t i = 0; i < size; ++i) {
                    if (node == head || !m.readable(node, 20)) throw "INVALID_PASSENGER_NODE";
                    auto at = m.component(engine, load<uint32_t>(node, 16), ty.person, 12);
                    if (at) {
                        int part = load<int>(at, 4);
                        if (load<uint32_t>(at) != id || part < 0 || size_t(part) >= part_count) assignment_complete = false;
                        else ++passengers[part];
                    } else { assignment_complete = false; ++quality.missing_seat_entities; }
                    node = load<void*>(node);
                }
                if (node != head) throw "INVALID_PASSENGER_SET_LENGTH";
            }
        }
        uint64_t seated = 0;
        for (auto n : passengers) seated += n;
        if (count(0) < 0) throw "INVALID_PASSENGER_COUNT";
        assignment_complete = assignment_complete && seated == static_cast<uint64_t>(count(0));
        if (!assignment_complete) {
            if (!quality.unverified_passenger_trains) {
                quality.first_vehicle = id; quality.first_expected = count(0); quality.first_assigned = static_cast<uint32_t>(seated);
            }
            ++quality.unverified_passenger_trains;
            // The seat component may be absent (e.g. visual/unseated persons).
            // Keep authoritative whole-train counts. Unknown carriage counts
            // retain the old v1 representation: zero with verification cleared.
            std::fill(passengers.begin(), passengers.end(), 0);
        }
        if (trains_seen++) footprints.raw(",");
        footprints.raw("{\"entity_id\":").integer(id).raw(",\"brake_decel_mps2\":").number(brake)
            .raw(",\"route_window\":{\"current_index\":");
        if (path) footprints.integer(index); else footprints.raw("null");
        int first = (std::max)(0, index - 96), last = (std::min)(static_cast<int>(edge_count) - 1, index + 96);
        footprints.raw(",\"start_index\":"); if (path && index >= 0) footprints.integer(first); else footprints.raw("null");
        auto array = [&](const char* name, int field) {
            footprints.raw(name).raw("[");
            if (path && index >= 0) for (int i = first; i <= last; ++i) {
                if (i != first) footprints.raw(","); auto e = load<PathEdge>(reinterpret_cast<void*>(edges.begin + sizeof(PathEdge) * i));
                if (e.direction > 1) throw "INVALID_PATH_DIRECTION";
                if (field == 0) footprints.integer(e.entity); else if (field == 1) footprints.integer(e.index); else footprints.boolean(e.direction != 0);
            }
            footprints.raw("]");
        };
        array(",\"edge_ids\":", 0); array(",\"transport_indices\":", 1); array(",\"directions\":", 2);
        footprints.raw("},\"train_envelope\":{\"source_status\":\"ENGINE_TRAIN_COMPONENT\",\"expected_parts\":").integer(part_count)
            .raw(",\"reservation_fields\":{\"value_type\":\"userdata\",\"reservedFrom\":{\"type\":\"number\",\"value\":").integer(load<int>(train, 24))
            .raw("},\"reservedTo\":{\"type\":\"number\",\"value\":").integer(load<int>(train, 28)).raw("}},\"parts\":[");
        bool complete = true, cargo_complete = true;
        t.line_entity_id = load<uint32_t>(tv, 160); t.state = load<uint32_t>(tv, 144);
        t.current_speed_mps = speed; t.acceleration_mps2 = accel; t.brake_deceleration_mps2 = brake;
        auto previous = motion.find(id);
        if (previous != motion.end() && h.sample_time_us > previous->second.time_us) {
            double elapsed = double(h.sample_time_us - previous->second.time_us) / 1000000;
            double measured = (speed - previous->second.speed) / elapsed;
            if (elapsed >= .02 && elapsed <= 5 && std::abs(measured) <= 20) t.acceleration_mps2 = static_cast<float>(measured);
        }
        t.center = root_valid ? center(root_bounds) : Vec3f{unknown, unknown, unknown};
        t.center_edge = {valid_edge ? uint64_t(edge.entity) : 0, pos01, int8_t(valid_edge ? (edge.direction ? 1 : -1) : 0), uint8_t(valid_edge && std::isfinite(pos01)), 0};
        t.path_edge_index = index < 0 ? 0 : index; t.path_edge_count = static_cast<uint32_t>(edge_count);
        t.sample_sequence = h.sample_sequence; t.sample_time_us = h.sample_time_us;
        t.flags &= ~(TrainCargoComplete | TrainPartsComplete | TrainReversible | TrainPassenger | TrainFreight | TrainMixedLoad);
        if (load<uint8_t>(tv, 136)) t.flags |= TrainReversible;
        t.passenger_count = count(0); t.freight_amount = 0; t.freight_weight_t = 0;
        t.passenger_capacity = t.freight_capacity = 0;
        t.freight_summary_offset = static_cast<uint32_t>(freight_entries.size());
        t.passenger_weight_t = t.passenger_count * passenger_unit_weight / 1000;
        auto limit = track_limits.find(edge.entity);
        t.track_speed_limit_mps = limit == track_limits.end() ? unknown : limit->second;
        t.commanded_speed_limit_mps = unknown; // Controller rules remain a separate authority.
        t.effective_speed_limit_mps = t.technical_max_speed_mps;
        if (std::isfinite(t.track_speed_limit_mps)) t.effective_speed_limit_mps = (std::min)(t.effective_speed_limit_mps, t.track_speed_limit_mps);
        for (size_t pi = 0; pi < part_count; ++pi) {
            uint32_t part_id = load<uint32_t>(reinterpret_cast<void*>(parts.begin + 4 * pi));
            auto po = h.parts_offset + (t.parts_offset + pi) * sizeof(VehiclePartWrapper);
            auto p = load<VehiclePartWrapper>(frame.data(), po);
            auto config = reinterpret_cast<void*>(configs.begin + 128 * pi);
            if (p.entity_id != part_id || p.model_id != load<uint32_t>(config)) { request(c.epoch); throw "CONSIST_METADATA_REQUIRED"; }
            p.flags &= ~(PartReversed | PartCargoVerified);
            if (load<uint8_t>(config, 4)) p.flags |= PartReversed;
            Bounds b{}; bool valid = bounds(m, engine, part_id, ty, b); complete = complete && valid;
            p.center = valid ? center(b) : Vec3f{unknown, unknown, unknown};
            p.world_aabb = valid ? Aabb3f{b.min,b.max} : Aabb3f{{unknown,unknown,unknown},{unknown,unknown,unknown}};
            p.sample_sequence = h.sample_sequence; p.sample_time_us = h.sample_time_us;
            p.passenger_count = passengers[pi]; p.freight_amount = 0; p.freight_weight_t = 0;
            p.passenger_capacity = p.freight_capacity = 0;
            p.passenger_load_offset = static_cast<uint32_t>(passenger_entries.size());
            p.freight_load_offset = static_cast<uint32_t>(freight_entries.size());
            auto compartments = load<Vector>(reinterpret_cast<void*>(info_it->second.begin + pi * 24));
            size_t compartment_count = m.vector_size(compartments, 24, 256);
            for (size_t ci = 0; ci < compartment_count; ++ci) {
                auto entries = load<Vector>(reinterpret_cast<void*>(compartments.begin + ci * 24));
                size_t types_count = m.vector_size(entries, 160, 256);
                for (size_t cargo = 0; cargo < types_count; ++cargo) {
                    auto entry = reinterpret_cast<void*>(entries.begin + cargo * 160);
                    int capacity = load<int>(entry);
                    if (capacity < 0) throw "INVALID_CARGO_CAPACITY";
                    if (!capacity) continue;
                    if (cargo == 0) {
                        passenger_entries.push_back({static_cast<uint16_t>(ci),0,0,static_cast<uint32_t>(capacity)});
                        p.passenger_capacity += capacity;
                    } else {
                        auto weight = cargo_weights.find(static_cast<uint32_t>(cargo));
                        float unit = weight == cargo_weights.end() ? unknown : weight->second;
                        if (weight == cargo_weights.end()) request(c.epoch);
                        auto amount = static_cast<uint32_t>(allocated(count(cargo),load<int>(entry,4),capacity));
                        freight_entries.push_back({static_cast<uint32_t>(cargo),static_cast<uint16_t>(ci),0,amount,static_cast<uint32_t>(capacity),unit,amount*unit});
                        p.freight_amount += amount; p.freight_capacity += capacity;
                        p.freight_weight_t += amount * unit / 1000;
                    }
                }
            }
            size_t passenger_rows = passenger_entries.size() - p.passenger_load_offset;
            size_t freight_rows = freight_entries.size() - p.freight_load_offset;
            if (passenger_rows > UINT16_MAX || freight_rows > UINT16_MAX) throw "TOO_MANY_LOAD_ROWS";
            p.passenger_load_count = p.passenger_compartment_count = static_cast<uint16_t>(passenger_rows);
            p.freight_load_count = p.freight_compartment_count = static_cast<uint16_t>(freight_rows);
            if (passenger_rows == 1) passenger_entries[p.passenger_load_offset].passenger_count = p.passenger_count;
            if (passenger_rows <= 1 && (assignment_complete || !p.passenger_capacity)) p.flags |= PartCargoVerified;
            else cargo_complete = false;
            t.passenger_capacity += p.passenger_capacity; t.freight_capacity += p.freight_capacity;
            t.freight_amount += p.freight_amount; t.freight_weight_t += p.freight_weight_t;
            if (pi) footprints.raw(","); footprints.raw("{\"entity_id\":").integer(part_id).raw(",\"position\":");
            if (valid) footprints.vec(p.center).raw(",\"bounds\":{\"min\":").vec(b.min).raw(",\"max\":").vec(b.max).raw("}");
            else footprints.raw("null,\"bounds\":null");
            footprints.raw("}"); store(frame.data(), po, p);
        }
        if (complete) t.flags |= TrainPartsComplete;
        if (cargo_complete) t.flags |= TrainCargoComplete;
        if (t.passenger_capacity) t.flags |= TrainPassenger;
        if (t.freight_capacity) t.flags |= TrainFreight;
        if (t.passenger_capacity && t.freight_capacity) t.flags |= TrainMixedLoad;
        size_t freight_count = freight_entries.size() - t.freight_summary_offset;
        if (freight_count > UINT16_MAX) throw "TOO_MANY_LOAD_ROWS";
        t.freight_summary_count = static_cast<uint16_t>(freight_count);
        t.gross_weight_t = t.empty_weight_t + t.passenger_weight_t + t.freight_weight_t;
        store(frame.data(), offset, t);
        footprints.raw("],\"complete\":").boolean(complete).raw("}}");
    }
    if (trains_seen != h.train_count) { request(c.epoch); throw "TRAIN_SET_CHANGED"; }
    auto append = [&](const auto& entries) {
        if (entries.empty()) return;
        auto begin = reinterpret_cast<const char*>(entries.data());
        frame.insert(frame.end(),begin,begin + entries.size()*sizeof(entries[0]));
    };
    h.passenger_loads_offset = static_cast<uint32_t>(frame.size());
    h.passenger_load_count = static_cast<uint32_t>(passenger_entries.size());
    append(passenger_entries);
    h.freight_loads_offset = static_cast<uint32_t>(frame.size());
    h.freight_load_count = static_cast<uint32_t>(freight_entries.size());
    append(freight_entries);
    if (frame.size() > 16*1024*1024) throw "FRAME_TOO_LARGE";
    h.total_size = static_cast<uint32_t>(frame.size());
    store(frame.data(), 0, h);
    QueryPerformanceCounter(&finished);
    double duration = double(finished.QuadPart - started.QuadPart) * 1000 / frequency.QuadPart;
    positions.raw("],\"counts\":{\"vehicles\":").integer((std::min)(ids.size(), size_t(2048))).raw(",\"maximum\":2048,\"truncated\":").boolean(ids.size() > 2048).raw("},\"duration_ms\":").number(duration).raw("}");
    footprints.raw("],\"counts\":{\"vehicles\":").integer(trains_seen).raw("},\"duration_ms\":").number(duration).raw("}");
    if (!publish(c.epoch, "train-wrappers-v1.bin", frame.data(), frame.size()) ||
        !publish(c.epoch, "operational-telemetry-vehicle_positions.json", positions.text.data(), positions.text.size()) ||
        !publish(c.epoch, "operational-telemetry-train_footprints.json", footprints.text.data(), footprints.text.size())) throw "PUBLICATION_REJECTED";
    motion.clear();
    for (uint32_t i = 0; i < h.train_count; ++i) {
        auto t = load<TrainWrapper>(frame.data(), h.trains_offset + i * sizeof(TrainWrapper));
        if (std::isfinite(t.current_speed_mps)) motion.emplace(static_cast<uint32_t>(t.entity_id), Motion{t.current_speed_mps, h.sample_time_us});
    }
}
void sample(void* system, void* engine) {
    if (!bind()) return;
    Tpf2NativeTelemetryContext c;
    if (!get_context(&c)) return;
    LARGE_INTEGER begin{}, end{}, frequency{}; QueryPerformanceCounter(&begin); QueryPerformanceFrequency(&frequency);
    const char* error = nullptr;
    try {
        if (epoch != c.epoch) { epoch = c.epoch; revision = sequence = 0; seed.clear(); track_limits.clear(); cargo_weights.clear(); motion.clear(); passenger_unit_weight = unknown; }
        uint64_t next = revision;
        auto size = get_seed(c.epoch, scratch.data(), scratch.size(), &next);
        if (size > scratch.size()) throw "SEED_TOO_LARGE";
        if (size && next != revision) {
            std::vector<char> incoming(scratch.begin(), scratch.begin() + size); validate_seed(incoming);
            auto h = load<TrainTelemetryFrameHeader>(incoming.data());
            // Optional static-resource tail is private to the seed; never sent
            // to Python. Normal frame total_size and all public offsets stay v1.
            if (size < h.total_size + 8ULL) throw "STATIC_RESOURCES_REQUIRED";
            auto base = incoming.data() + h.total_size;
            uint32_t n = load<uint32_t>(base, 4);
            if (h.total_size + 8ULL + n * 8ULL != size || n > 1000000) throw "INVALID_STATIC_RESOURCES";
            passenger_unit_weight = load<float>(base);
            cargo_weights.clear();
            for (uint32_t i = 0; i < h.freight_load_count; ++i) {
                auto row = load<FreightLoadEntry>(incoming.data(), h.freight_loads_offset + i * sizeof(FreightLoadEntry));
                cargo_weights.emplace(row.cargo_type_id, row.cargo_unit_weight_kg);
            }
            track_limits.clear();
            for (uint32_t i = 0; i < n; ++i) track_limits.emplace(load<uint32_t>(base, 8 + i * 8), load<float>(base, 12 + i * 8));
            seed.swap(incoming); revision = next;
        }
        if (seed.empty()) { request(c.epoch); return; }
        collect(system, engine, types(engine), c);
    } catch (const char* message) { error = message; } catch (...) { error = "NATIVE_TELEMETRY_EXCEPTION"; }
    QueryPerformanceCounter(&end);
    Json status; status.raw("{\"schema_version\":1,\"source\":\"NATIVE_ENGINE_UPDATE\",\"session_id\":").string(c.session)
        .raw(",\"generated_at\":").integer(std::time(nullptr)).raw(",\"sample_sequence\":").integer(sequence)
        .raw(",\"duration_ms\":").number(double(end.QuadPart - begin.QuadPart) * 1000 / frequency.QuadPart)
        .raw(",\"unverified_passenger_trains\":").integer(quality.unverified_passenger_trains)
        .raw(",\"missing_seat_entities\":").integer(quality.missing_seat_entities)
        .raw(",\"first_unverified_vehicle\":").integer(quality.first_vehicle)
        .raw(",\"first_expected_passengers\":").integer(quality.first_expected)
        .raw(",\"first_assigned_passengers\":").integer(quality.first_assigned)
        .raw(",\"status\":").string(error ? error : "OK").raw("}");
    publish(c.epoch, "native-telemetry-performance.json", status.text.data(), status.text.size());
}
// A layout mismatch must never unwind through a game hook. Stop this reader
// on an access violation; do not hide the error by publishing a stale frame.
void guarded_sample(void* system, void* engine) {
    __try { sample(system, engine); }
    __except (GetExceptionCode() == EXCEPTION_ACCESS_VIOLATION ? EXCEPTION_EXECUTE_HANDLER : EXCEPTION_CONTINUE_SEARCH) { faulted = true; }
}
}
void after_vehicle_update(void* system, void* engine, int, float) noexcept {
    if (!TryAcquireSRWLockExclusive(&sample_lock)) return;
    if (!faulted) {
        try {
            guarded_sample(system, engine);
            if (faulted && get_context && publish) {
                Tpf2NativeTelemetryContext c;
                if (get_context(&c)) {
                    Json status; status.raw("{\"schema_version\":1,\"status\":\"NATIVE_MEMORY_READ_FAULT\",\"session_id\":").string(c.session)
                        .raw(",\"generated_at\":").integer(std::time(nullptr)).raw("}");
                    publish(c.epoch, "native-telemetry-performance.json", status.text.data(), status.text.size());
                }
            }
        } catch (...) { faulted = true; }
    }
    ReleaseSRWLockExclusive(&sample_lock);
}
}
