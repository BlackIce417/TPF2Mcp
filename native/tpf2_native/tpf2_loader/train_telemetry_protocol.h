#pragma once

#include <cstdint>

namespace tpf2::loader::telemetry {

constexpr std::uint32_t kFrameMagic = 0x52545054; // TPTR
constexpr std::uint32_t kProtocolVersion = 1;

enum PartFlags : std::uint32_t {
    PartNone = 0,
    PartPowered = 1u << 0,
    PartHasCab = 1u << 1,
    PartPassengerCapable = 1u << 2,
    PartCargoCapable = 1u << 3,
    PartReversed = 1u << 4,
    PartRoleVerified = 1u << 16,
    PartCargoVerified = 1u << 17,
    PartEdgeVerified = 1u << 18,
};

enum TrainFlags : std::uint32_t {
    TrainNone = 0,
    TrainPassenger = 1u << 0,
    TrainFreight = 1u << 1,
    TrainMixedLoad = 1u << 2,
    TrainReversible = 1u << 3,
    TrainHasSpeedCommand = 1u << 8,
    TrainEmergencyBraking = 1u << 9,
    TrainPartsComplete = 1u << 16,
    TrainCargoComplete = 1u << 17,
    TrainEdgeMappingComplete = 1u << 18,
};

#pragma pack(push, 1)
struct Vec3f {
    float x;
    float y;
    float z;
};

struct Aabb3f {
    Vec3f minimum;
    Vec3f maximum;
};

struct EdgeLocation {
    std::uint64_t edge_entity_id;
    float position01;
    std::int8_t direction;
    std::uint8_t valid;
    std::uint16_t reserved;
};

struct PassengerLoadEntry {
    std::uint16_t compartment_index;
    std::uint16_t reserved;
    std::uint32_t passenger_count;
    std::uint32_t passenger_capacity;
};

struct FreightLoadEntry {
    std::uint32_t cargo_type_id;
    std::uint16_t compartment_index;
    std::uint16_t load_config_index;
    std::uint32_t cargo_amount;
    std::uint32_t cargo_capacity;
    float cargo_unit_weight_kg;
    float current_cargo_weight_kg;
};

struct VehiclePartWrapper {
    std::uint32_t struct_version;
    std::uint32_t struct_size;
    std::uint64_t entity_id;
    std::uint64_t train_entity_id;
    std::uint32_t model_id;
    std::uint16_t part_index;
    std::uint16_t part_count;
    std::uint32_t flags;
    float model_length_m;
    float model_width_m;
    float model_height_m;
    float empty_weight_t;
    float technical_max_speed_mps;
    float engine_power_kw;
    float tractive_effort_kn;
    Vec3f center;
    Vec3f front;
    Vec3f rear;
    Aabb3f world_aabb;
    EdgeLocation front_edge;
    EdgeLocation center_edge;
    EdgeLocation rear_edge;
    std::uint32_t passenger_count;
    std::uint32_t passenger_capacity;
    std::uint32_t passenger_load_offset;
    std::uint16_t passenger_load_count;
    std::uint16_t passenger_compartment_count;
    std::uint32_t freight_amount;
    std::uint32_t freight_capacity;
    float freight_weight_t;
    std::uint32_t freight_load_offset;
    std::uint16_t freight_load_count;
    std::uint16_t freight_compartment_count;
    std::uint64_t sample_sequence;
    std::uint64_t sample_time_us;
};

struct TrainWrapper {
    std::uint32_t struct_version;
    std::uint32_t struct_size;
    std::uint64_t entity_id;
    std::uint64_t line_entity_id;
    std::uint32_t flags;
    std::uint32_t state;
    std::uint32_t parts_offset;
    std::uint16_t parts_count;
    std::uint16_t powered_parts_count;
    float total_length_m;
    float empty_weight_t;
    float passenger_weight_t;
    float freight_weight_t;
    float gross_weight_t;
    std::uint32_t passenger_count;
    std::uint32_t passenger_capacity;
    std::uint32_t freight_amount;
    std::uint32_t freight_capacity;
    std::uint32_t freight_summary_offset;
    std::uint16_t freight_summary_count;
    std::uint16_t reserved;
    float technical_max_speed_mps;
    float track_speed_limit_mps;
    float commanded_speed_limit_mps;
    float effective_speed_limit_mps;
    float current_speed_mps;
    float acceleration_mps2;
    float brake_deceleration_mps2;
    Vec3f center;
    Vec3f front;
    Vec3f rear;
    EdgeLocation front_edge;
    EdgeLocation center_edge;
    EdgeLocation rear_edge;
    std::uint32_t path_edge_index;
    std::uint32_t path_edge_count;
    std::uint64_t sample_sequence;
    std::uint64_t sample_time_us;
};

struct TrainTelemetryFrameHeader {
    std::uint32_t magic;
    std::uint32_t protocol_version;
    std::uint32_t header_size;
    std::uint32_t total_size;
    std::uint64_t sample_sequence;
    std::uint64_t sample_time_us;
    std::uint32_t train_count;
    std::uint32_t part_count;
    std::uint32_t passenger_load_count;
    std::uint32_t freight_load_count;
    std::uint32_t trains_offset;
    std::uint32_t parts_offset;
    std::uint32_t passenger_loads_offset;
    std::uint32_t freight_loads_offset;
    std::uint32_t flags;
    std::uint32_t reserved;
};
#pragma pack(pop)

static_assert(sizeof(EdgeLocation) == 16);
static_assert(sizeof(PassengerLoadEntry) == 12);
static_assert(sizeof(FreightLoadEntry) == 24);
static_assert(sizeof(VehiclePartWrapper) == 224);
static_assert(sizeof(TrainWrapper) == 220);
static_assert(sizeof(TrainTelemetryFrameHeader) == 72);

}
