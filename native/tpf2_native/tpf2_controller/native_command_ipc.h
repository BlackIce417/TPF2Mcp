#pragma once

#include <Windows.h>
#include <stdint.h>

#define TPF2_COMMAND_MAGIC 0x32434D54u
#define TPF2_COMMAND_VERSION 2u
#define TPF2_COMMAND_RING_CAPACITY 64u
#define TPF2_COMMAND_PAYLOAD_CAPACITY (12u * 1024u)
#define TPF2_REPLY_DETAIL_CAPACITY 256u

#define TPF2_COMMAND_MAPPING_NAME L"Local\\tpf2mcp_controller_cmd_v2"
#define TPF2_COMMAND_EVENT_NAME L"Local\\tpf2mcp_controller_cmd_event_v2"
#define TPF2_REPLY_EVENT_NAME L"Local\\tpf2mcp_controller_reply_event_v2"
#define TPF2_COMMAND_MUTEX_NAME L"Local\\tpf2mcp_controller_cmd_mutex_v2"
#define TPF2_MOVEMENT_REQUIRE_RESUMABLE_ROUTE 0x1u

enum Tpf2CommandOpcode : uint32_t
{
    TPF2_CMD_PING = 0x0001,
    TPF2_CMD_GET_STATUS = 0x0002,
    TPF2_CMD_GET_CAPABILITIES = 0x0003,
    TPF2_CMD_BEGIN_TRANSACTION = 0x0010,
    TPF2_CMD_COMMIT_TRANSACTION = 0x0011,
    TPF2_CMD_ABORT_TRANSACTION = 0x0012,
    TPF2_CMD_CLEAR_ALL_RULES = 0x0013,

    TPF2_CMD_UPSERT_SPEED_RULE = 0x0101,
    TPF2_CMD_REMOVE_SPEED_RULE = 0x0102,
    TPF2_CMD_CLEAR_SPEED_RULES = 0x0103,
    TPF2_CMD_UPSERT_STATION_RULE = 0x0201,
    TPF2_CMD_REMOVE_STATION_RULE = 0x0202,
    TPF2_CMD_CLEAR_STATION_RULES = 0x0203,
    TPF2_CMD_UPSERT_ROUTING_RULE = 0x0301,
    TPF2_CMD_REMOVE_ROUTING_RULE = 0x0302,
    TPF2_CMD_CLEAR_ROUTING_RULES = 0x0303,
    TPF2_CMD_UPSERT_PATH_RULE = 0x0401,
    TPF2_CMD_REMOVE_PATH_RULE = 0x0402,
    TPF2_CMD_CLEAR_PATH_RULES = 0x0403,

    TPF2_CMD_MOVE_TRAIN_DISTANCE = 0x0501,
    TPF2_CMD_MOVE_TRAIN_ROUTE = 0x0502,
    TPF2_CMD_RELEASE_TRAIN_MOVEMENT = 0x0503,
    TPF2_CMD_GET_TRAIN_MOVEMENT = 0x0504,
};

enum Tpf2CommandResult : uint32_t
{
    TPF2_COMMAND_OK = 0,
    TPF2_COMMAND_UNKNOWN_OPCODE = 1,
    TPF2_COMMAND_INVALID_PAYLOAD = 2,
    TPF2_COMMAND_RULE_NOT_FOUND = 3,
    TPF2_COMMAND_CAPACITY_EXCEEDED = 4,
    TPF2_COMMAND_TRANSACTION_CONFLICT = 5,
    TPF2_COMMAND_CONTROLLER_DRAINING = 6,
    TPF2_COMMAND_VERSION_MISMATCH = 7,
    TPF2_COMMAND_INTERNAL_ERROR = 8,
    TPF2_COMMAND_MOVEMENT_CONFLICT = 9,
};

#pragma pack(push, 1)
struct Tpf2CommandSlot
{
    uint64_t cmd_id;
    uint32_t opcode;
    uint32_t payload_size;
    uint64_t transaction_id;
    uint32_t flags;
    uint32_t reserved;
    uint8_t payload[TPF2_COMMAND_PAYLOAD_CAPACITY];
};

struct Tpf2CommandReply
{
    uint64_t cmd_id;
    uint32_t opcode;
    uint32_t result;
    uint64_t transaction_id;
    uint64_t controller_generation;
    char detail[TPF2_REPLY_DETAIL_CAPACITY];
};

struct Tpf2ControllerCommandIpc
{
    uint32_t magic;
    uint32_t version;
    uint32_t structure_size;
    uint32_t command_capacity;
    uint32_t reply_capacity;
    uint32_t payload_capacity;
    uint32_t reserved0;
    uint32_t reserved1;
    volatile LONG64 command_write_sequence;
    volatile LONG64 command_read_sequence;
    volatile LONG64 reply_write_sequence;
    volatile LONG64 reply_read_sequence;
    uint64_t controller_epoch;
    uint8_t reserved[192];
    Tpf2CommandSlot commands[TPF2_COMMAND_RING_CAPACITY];
    Tpf2CommandReply replies[TPF2_COMMAND_RING_CAPACITY];
};

struct Tpf2RuleKeyPayload
{
    uint64_t rule_id;
};

struct Tpf2SpeedRulePayload
{
    uint64_t rule_id;
    uint32_t vehicle_id;
    float speed_mps;
    uint32_t hold;
    int32_t path_index_start;
    int32_t path_index_end;
    int64_t expires_at;
    uint32_t edge_count;
    uint32_t edge_ids[2048];
};

struct Tpf2StationRulePayload
{
    uint64_t rule_id;
    uint32_t vehicle_id;
    uint32_t station_group_id;
    uint32_t station_index;
    uint32_t terminal_index;
    int64_t expires_at;
};

struct Tpf2RoutingRulePayload
{
    uint64_t rule_id;
    uint32_t source_line;
    uint32_t target_line;
    int32_t source_stop0;
    int32_t source_stop1;
    int32_t target_stop0;
    int32_t target_stop1;
    int32_t max_assignments;
    int32_t entity_kind;
    int64_t expires_at;
};

struct Tpf2PathRulePayload
{
    uint64_t rule_id;
    uint32_t vehicle_id;
    float penalty_seconds;
    int64_t expires_at;
    uint32_t edge_count;
    uint32_t edge_ids[2048];
};

// Ordered, directed engine transport edges, not simplified topology edge IDs.
struct Tpf2DirectedTrackEdge
{
    uint32_t entity;
    int32_t index;
    uint32_t direction; // Native Path bool, exactly 0 or 1.
};

struct Tpf2MoveTrainDistancePayload
{
    uint64_t movement_id;
    uint32_t vehicle_id;
    float speed_mps;
    float distance_m; // Measured from the train centre when the game accepts it.
    uint32_t expires_in_seconds; // Includes holding at the target; wall-clock watchdog.
};

#define TPF2_MOVEMENT_ROUTE_CAPACITY 512u
struct Tpf2MoveTrainRoutePayload
{
    uint64_t movement_id;
    uint32_t vehicle_id;
    float speed_mps;
    uint32_t expires_in_seconds;
    uint32_t target_index; // Index in edges[], centre of train stops here.
    float target_offset_m; // Along the directed edge, from its entrance.
    uint32_t edge_count;
    Tpf2DirectedTrackEdge edges[TPF2_MOVEMENT_ROUTE_CAPACITY];
};
#pragma pack(pop)

static_assert(sizeof(Tpf2CommandSlot) == 32 + TPF2_COMMAND_PAYLOAD_CAPACITY,
              "command slot layout changed");
static_assert(sizeof(Tpf2CommandReply) == 288, "command reply layout changed");
static_assert(sizeof(Tpf2SpeedRulePayload) <= TPF2_COMMAND_PAYLOAD_CAPACITY,
              "speed payload exceeds command slot");
static_assert(sizeof(Tpf2PathRulePayload) <= TPF2_COMMAND_PAYLOAD_CAPACITY,
              "path payload exceeds command slot");
static_assert(sizeof(Tpf2MoveTrainDistancePayload) == 24);
static_assert(sizeof(Tpf2MoveTrainRoutePayload) == 32 + 12 * TPF2_MOVEMENT_ROUTE_CAPACITY);
static_assert(sizeof(Tpf2MoveTrainRoutePayload) <= TPF2_COMMAND_PAYLOAD_CAPACITY);
