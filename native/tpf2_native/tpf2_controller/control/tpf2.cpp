#include "pch.h"
#include "tpf2.h"
#include "../ipc/native_ipc.h"
#include "../../shared/native_command_ipc.h"
#include "train_motion.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <wchar.h>
#include <cmath>

#define SPEED_RVA 0x2215560ULL
#define STATION_RVA 0x2164580ULL
#define CARGO_ASSIGN_RVA 0xA7BFA0ULL
#define PERSON_ASSIGN_RVA 0xA995A0ULL
#define PATH_COST_RVA 0x2171790ULL
#define MAX_SPEED_RULES 256
#define MAX_RULE_EDGES 2048
#define MAX_STATION_RULES 64
#define MAX_ROUTING_RULES 32
#define MAX_PATH_RULES 64

typedef struct
{
    uint64_t rule_id;
    LONG enabled;
    LONG hold;
    uint32_t vehicle;
    float speed_mps;
    uint32_t edges[MAX_RULE_EDGES];
    int edge_count;
    /* Optional MOVE_PATH occurrence bounds.  -1 keeps legacy edge-only rules. */
    int path_index_start, path_index_end;
    int64_t expires_at;
    ULONGLONG last_adjust;
} SpeedRule;

typedef struct
{
    uint64_t rule_id;
    LONG enabled;
    LONG consumed;
    uint32_t vehicle, station_group_id, station_index, terminal_index;
    int64_t expires_at;
} StationRule;

typedef struct
{
    uint64_t rule_id;
    LONG enabled;
    uint32_t source_line, target_line;
    int source_stop0, source_stop1, target_stop0, target_stop1, maximum;
    int entity_kind; /* 1 = person, 2 = cargo; cargo type still requires a verified reader. */
    volatile LONG successes;
    int64_t expires_at;
} RoutingRule;

typedef struct
{
    uint64_t rule_id;
    LONG enabled;
    uint32_t vehicle;
    float penalty_seconds;
    uint32_t edges[MAX_RULE_EDGES];
    int edge_count;
    int64_t expires_at;
} PathRule;

typedef float (*SpeedFn)(void *, int, void *, int, int, float, void *, int, int);
typedef unsigned char (*StationFn)(void *, uint32_t *, uint32_t *, int, void *, unsigned char, int,
                                   uint64_t, unsigned char, uint64_t, void *, unsigned char);
typedef unsigned char (*CargoAssignFn)(void *, void *, void *, uint32_t *, unsigned int, int, int64_t);
typedef int64_t (*PersonAssignFn)(void *, void *, void *, void *, void *, uint32_t *, void *, uint32_t *,
                                  unsigned int, int, int64_t, int64_t, int64_t);
typedef float (*PathCostFn)(void *, void *, int, int);
extern "C" float speed_hook_entry(void *, int, void *, int, int, float, void *, int, int);

static DetourManager& dtmgr = DetourManager::Instance();

static SpeedFn original_speed;
static StationFn original_station;
static CargoAssignFn original_cargo_assign;
static PersonAssignFn original_person_assign;
static PathCostFn original_path_cost;
static wchar_t config_path[MAX_PATH], status_path[MAX_PATH];
static volatile LONG loading;
static SRWLOCK rules_lock = SRWLOCK_INIT;
static SRWLOCK status_lock = SRWLOCK_INIT;
static SpeedRule speed_rules[MAX_SPEED_RULES];
static StationRule station_rules[MAX_STATION_RULES];
static RoutingRule routing_rules[MAX_ROUTING_RULES];
static PathRule path_rules[MAX_PATH_RULES];
static SpeedRule pending_speed_rules[MAX_SPEED_RULES];
static StationRule pending_station_rules[MAX_STATION_RULES];
static RoutingRule pending_routing_rules[MAX_ROUTING_RULES];
static PathRule pending_path_rules[MAX_PATH_RULES];
static int speed_rule_count, station_rule_count, routing_rule_count, path_rule_count;
static LONG config_generation;
static volatile LONG64 speed_calls, vehicle_matches, edge_matches;
static volatile LONG last_candidate, last_first, last_last, last_edge;
static ULONGLONG last_diagnostic_status;
static volatile LONG routing_calls, routing_attempts, routing_successes;
static volatile LONG routing_last_line, routing_last_stop0, routing_last_stop1;
static ULONGLONG routing_last_status;
static volatile LONG64 path_cost_calls, path_vehicle_matches, path_edge_matches, path_penalties;
static volatile LONG path_last_vehicle, path_last_edge;
static DWORD path_vehicle_tls = TLS_OUT_OF_INDEXES;
static ULONGLONG path_last_status;
static HANDLE ipc_mapping;
static HANDLE ipc_config_event;
static HANDLE ipc_status_event;
static Tpf2NativeIpc *ipc;
static const char *config_values;
static char shared_config_buffer[TPF2_IPC_CONFIG_CAPACITY + 1];
static char shared_status_buffer[TPF2_IPC_STATUS_CAPACITY];
static HANDLE command_mapping;
static HANDLE command_event;
static HANDLE reply_event;
static Tpf2ControllerCommandIpc *command_ipc;
static uint64_t controller_generation;
static uint64_t active_transaction_id;
static int transaction_speed_count, transaction_station_count, transaction_routing_count, transaction_path_count;
static HANDLE shutdown_event;
static HANDLE controller_thread;
static SRWLOCK lifecycle_lock = SRWLOCK_INIT;
static volatile LONG controller_safe_to_unload;

static int readable(const void *p, SIZE_T size)
{
    MEMORY_BASIC_INFORMATION info;
    if (!p || !VirtualQuery(p, &info, sizeof(info)) || info.State != MEM_COMMIT || (info.Protect & (PAGE_NOACCESS | PAGE_GUARD)))
        return 0;
    uintptr_t address = reinterpret_cast<uintptr_t>(p);
    uintptr_t region = reinterpret_cast<uintptr_t>(info.BaseAddress);
    if (address < region || address - region > info.RegionSize)
        return 0;
    return size <= info.RegionSize - (address - region);
}

static int initialize_ipc(void)
{
    ipc_mapping = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE, 0,
                                    sizeof(Tpf2NativeIpc), TPF2_IPC_MAPPING_NAME);
    if (ipc_mapping == nullptr)
        return 0;
    ipc = static_cast<Tpf2NativeIpc *>(MapViewOfFile(ipc_mapping, FILE_MAP_ALL_ACCESS, 0, 0,
                                                     sizeof(Tpf2NativeIpc)));
    if (ipc == nullptr)
    {
        CloseHandle(ipc_mapping);
        ipc_mapping = nullptr;
        return 0;
    }
    if (ipc->magic != TPF2_IPC_MAGIC || ipc->version != TPF2_IPC_VERSION ||
        ipc->structure_size != sizeof(Tpf2NativeIpc))
    {
        ZeroMemory(ipc, sizeof(*ipc));
        ipc->magic = TPF2_IPC_MAGIC;
        ipc->version = TPF2_IPC_VERSION;
        ipc->structure_size = sizeof(Tpf2NativeIpc);
        ipc->config_capacity = TPF2_IPC_CONFIG_CAPACITY;
        ipc->status_capacity = TPF2_IPC_STATUS_CAPACITY;
    }
    ipc_config_event = CreateEventW(nullptr, FALSE, FALSE, TPF2_IPC_CONFIG_EVENT_NAME);
    ipc_status_event = CreateEventW(nullptr, FALSE, FALSE, TPF2_IPC_STATUS_EVENT_NAME);
    if (ipc_config_event == nullptr || ipc_status_event == nullptr)
    {
        if (ipc_config_event)
            CloseHandle(ipc_config_event);
        if (ipc_status_event)
            CloseHandle(ipc_status_event);
        UnmapViewOfFile(ipc);
        CloseHandle(ipc_mapping);
        ipc = nullptr;
        ipc_mapping = nullptr;
        ipc_config_event = nullptr;
        ipc_status_event = nullptr;
        return 0;
    }
    return 1;
}

static int initialize_command_ipc(void)
{
    command_mapping = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE, 0,
                                         sizeof(Tpf2ControllerCommandIpc), TPF2_COMMAND_MAPPING_NAME);
    if (command_mapping == nullptr)
        return 0;
    command_ipc = static_cast<Tpf2ControllerCommandIpc *>(
        MapViewOfFile(command_mapping, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(Tpf2ControllerCommandIpc)));
    if (command_ipc == nullptr)
    {
        CloseHandle(command_mapping);
        command_mapping = nullptr;
        return 0;
    }
    if (command_ipc->magic != TPF2_COMMAND_MAGIC || command_ipc->version != TPF2_COMMAND_VERSION ||
        command_ipc->structure_size != sizeof(Tpf2ControllerCommandIpc))
    {
        ZeroMemory(command_ipc, sizeof(*command_ipc));
        command_ipc->magic = TPF2_COMMAND_MAGIC;
        command_ipc->version = TPF2_COMMAND_VERSION;
        command_ipc->structure_size = sizeof(Tpf2ControllerCommandIpc);
        command_ipc->command_capacity = TPF2_COMMAND_RING_CAPACITY;
        command_ipc->reply_capacity = TPF2_COMMAND_RING_CAPACITY;
        command_ipc->payload_capacity = TPF2_COMMAND_PAYLOAD_CAPACITY;
    }
    command_ipc->controller_epoch = GetTickCount64();
    command_event = CreateEventW(nullptr, FALSE, FALSE, TPF2_COMMAND_EVENT_NAME);
    reply_event = CreateEventW(nullptr, FALSE, FALSE, TPF2_REPLY_EVENT_NAME);
    if (command_event == nullptr || reply_event == nullptr)
    {
        if (command_event) CloseHandle(command_event);
        if (reply_event) CloseHandle(reply_event);
        UnmapViewOfFile(command_ipc);
        CloseHandle(command_mapping);
        command_event = nullptr;
        reply_event = nullptr;
        command_ipc = nullptr;
        command_mapping = nullptr;
        return 0;
    }
    controller_generation = 1;
    return 1;
}

static void close_ipc(void)
{
    if (command_ipc)
    {
        UnmapViewOfFile(command_ipc);
        command_ipc = nullptr;
    }
    if (command_event) { CloseHandle(command_event); command_event = nullptr; }
    if (reply_event) { CloseHandle(reply_event); reply_event = nullptr; }
    if (command_mapping) { CloseHandle(command_mapping); command_mapping = nullptr; }

    if (ipc)
    {
        UnmapViewOfFile(ipc);
        ipc = nullptr;
    }
    if (ipc_config_event) { CloseHandle(ipc_config_event); ipc_config_event = nullptr; }
    if (ipc_status_event) { CloseHandle(ipc_status_event); ipc_status_event = nullptr; }
    if (ipc_mapping) { CloseHandle(ipc_mapping); ipc_mapping = nullptr; }
}

static void publish_command_reply(const Tpf2CommandSlot *command, uint32_t result, const char *detail)
{
    if (command_ipc == nullptr || reply_event == nullptr)
        return;
    LONG64 write = InterlockedCompareExchange64(&command_ipc->reply_write_sequence, 0, 0);
    LONG64 read = InterlockedCompareExchange64(&command_ipc->reply_read_sequence, 0, 0);
    if (write - read >= TPF2_COMMAND_RING_CAPACITY)
    {
        read = write - TPF2_COMMAND_RING_CAPACITY + 1;
        InterlockedExchange64(&command_ipc->reply_read_sequence, read);
    }
    Tpf2CommandReply *reply = &command_ipc->replies[write % TPF2_COMMAND_RING_CAPACITY];
    ZeroMemory(reply, sizeof(*reply));
    reply->cmd_id = command->cmd_id;
    reply->opcode = command->opcode;
    reply->result = result;
    reply->transaction_id = command->transaction_id;
    reply->controller_generation = controller_generation;
    if (detail)
        strncpy_s(reply->detail, detail, _TRUNCATE);
    MemoryBarrier();
    InterlockedExchange64(&command_ipc->reply_write_sequence, write + 1);
    SetEvent(reply_event);
}

static int publish_shared_status(const char *state, const char *detail)
{
    if (ipc == nullptr)
        return 0;
    int length = _snprintf_s(
        shared_status_buffer, sizeof(shared_status_buffer), _TRUNCATE,
        "schema_version=5\nstate=%s\ndetail=%s\nconfig_generation=%ld\n"
        "speed_rule_count=%d\nstation_rule_count=%d\nrouting_rule_count=%d\npath_rule_count=%d\n"
        "speed_calls=%lld\nvehicle_matches=%lld\nedge_matches=%lld\nlast_candidate=%ld\n"
        "last_first=%ld\nlast_last=%ld\nlast_edge=%ld\nrouting_calls=%ld\nrouting_attempts=%ld\n"
        "routing_successes=%ld\nrouting_last_line=%ld\nrouting_last_stop0=%ld\nrouting_last_stop1=%ld\n"
        "path_cost_calls=%lld\npath_vehicle_matches=%lld\npath_edge_matches=%lld\npath_penalties=%lld\n"
        "path_last_vehicle=%ld\npath_last_edge=%ld\n",
        state, detail ? detail : "", config_generation, speed_rule_count, station_rule_count,
        routing_rule_count, path_rule_count,
        (long long)InterlockedCompareExchange64(&speed_calls, 0, 0),
        (long long)InterlockedCompareExchange64(&vehicle_matches, 0, 0),
        (long long)InterlockedCompareExchange64(&edge_matches, 0, 0),
        InterlockedCompareExchange(&last_candidate, 0, 0),
        InterlockedCompareExchange(&last_first, 0, 0),
        InterlockedCompareExchange(&last_last, 0, 0),
        InterlockedCompareExchange(&last_edge, 0, 0),
        InterlockedCompareExchange(&routing_calls, 0, 0),
        InterlockedCompareExchange(&routing_attempts, 0, 0),
        InterlockedCompareExchange(&routing_successes, 0, 0),
        InterlockedCompareExchange(&routing_last_line, 0, 0),
        InterlockedCompareExchange(&routing_last_stop0, 0, 0),
        InterlockedCompareExchange(&routing_last_stop1, 0, 0),
        (long long)InterlockedCompareExchange64(&path_cost_calls, 0, 0),
        (long long)InterlockedCompareExchange64(&path_vehicle_matches, 0, 0),
        (long long)InterlockedCompareExchange64(&path_edge_matches, 0, 0),
        (long long)InterlockedCompareExchange64(&path_penalties, 0, 0),
        InterlockedCompareExchange(&path_last_vehicle, 0, 0),
        InterlockedCompareExchange(&path_last_edge, 0, 0));
    if (length < 0 || static_cast<size_t>(length) >= sizeof(shared_status_buffer))
        return 0;
    InterlockedIncrement(&ipc->status_sequence);
    memcpy(ipc->status, shared_status_buffer, length);
    InterlockedExchange(&ipc->status_length, length);
    InterlockedIncrement(&ipc->status_sequence);
    SetEvent(ipc_status_event);
    return 1;
}

static void write_status(const char *state, const char *detail)
{
    AcquireSRWLockExclusive(&status_lock);
    if (publish_shared_status(state, detail))
    {
        ReleaseSRWLockExclusive(&status_lock);
        return;
    }
    wchar_t tmp[MAX_PATH];
    _snwprintf_s(tmp, MAX_PATH, _TRUNCATE, L"%ls.tmp", status_path);
    FILE *f = nullptr;
    _wfopen_s(&f, tmp, L"wb");
    if (!f)
    {
        ReleaseSRWLockExclusive(&status_lock);
        return;
    }
    fprintf(f, "{\"schema_version\":4,\"state\":\"%s\",\"detail\":\"%s\",\"config_generation\":%ld,\"speed_rule_count\":%d,\"station_rule_count\":%d,\"routing_rule_count\":%d,\"path_rule_count\":%d,"
               "\"speed_calls\":%lld,\"vehicle_matches\":%lld,\"edge_matches\":%lld,\"last_candidate\":%ld,\"last_first\":%ld,\"last_last\":%ld,\"last_edge\":%ld,"
               "\"routing_calls\":%ld,\"routing_attempts\":%ld,\"routing_successes\":%ld,"
               "\"routing_last_line\":%ld,\"routing_last_stop0\":%ld,\"routing_last_stop1\":%ld,"
               "\"path_cost_calls\":%lld,\"path_vehicle_matches\":%lld,\"path_edge_matches\":%lld,\"path_penalties\":%lld,"
               "\"path_last_vehicle\":%ld,\"path_last_edge\":%ld}\n",
            state, detail ? detail : "", config_generation, speed_rule_count, station_rule_count, routing_rule_count, path_rule_count,
            (long long)InterlockedCompareExchange64(&speed_calls, 0, 0),
            (long long)InterlockedCompareExchange64(&vehicle_matches, 0, 0),
            (long long)InterlockedCompareExchange64(&edge_matches, 0, 0),
            InterlockedCompareExchange(&last_candidate, 0, 0),
            InterlockedCompareExchange(&last_first, 0, 0),
            InterlockedCompareExchange(&last_last, 0, 0),
            InterlockedCompareExchange(&last_edge, 0, 0),
            InterlockedCompareExchange(&routing_calls, 0, 0), InterlockedCompareExchange(&routing_attempts, 0, 0),
            InterlockedCompareExchange(&routing_successes, 0, 0),
            InterlockedCompareExchange(&routing_last_line, 0, 0),
            InterlockedCompareExchange(&routing_last_stop0, 0, 0),
            InterlockedCompareExchange(&routing_last_stop1, 0, 0),
            (long long)InterlockedCompareExchange64(&path_cost_calls, 0, 0),
            (long long)InterlockedCompareExchange64(&path_vehicle_matches, 0, 0),
            (long long)InterlockedCompareExchange64(&path_edge_matches, 0, 0),
            (long long)InterlockedCompareExchange64(&path_penalties, 0, 0),
            InterlockedCompareExchange(&path_last_vehicle, 0, 0),
            InterlockedCompareExchange(&path_last_edge, 0, 0));
    fclose(f);
    MoveFileExW(tmp, status_path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
    ReleaseSRWLockExclusive(&status_lock);
}

static void paths(HMODULE self)
{
    wchar_t dll[MAX_PATH], *slash;
    GetModuleFileNameW(self, dll, MAX_PATH);
    slash = wcsrchr(dll, L'\\');
    if (slash)
        *slash = 0;
    _snwprintf_s(config_path, MAX_PATH, _TRUNCATE, L"%ls\\..\\bridge\\native-control.ini", dll);
    _snwprintf_s(status_path, MAX_PATH, _TRUNCATE, L"%ls\\..\\bridge\\native-control-status.json", dll);
}

static DWORD config_string(const wchar_t *section, const wchar_t *key, const wchar_t *fallback,
                           wchar_t *output, DWORD capacity)
{
    if (config_values == nullptr)
        return GetPrivateProfileStringW(section, key, fallback, output, capacity, config_path);
    char section_a[64], key_a[64], prefix[136];
    if (!WideCharToMultiByte(CP_UTF8, 0, section, -1, section_a, sizeof(section_a), nullptr, nullptr) ||
        !WideCharToMultiByte(CP_UTF8, 0, key, -1, key_a, sizeof(key_a), nullptr, nullptr))
    {
        wcsncpy_s(output, capacity, fallback, _TRUNCATE);
        return static_cast<DWORD>(wcslen(output));
    }
    _snprintf_s(prefix, sizeof(prefix), _TRUNCATE, "%s.%s=", section_a, key_a);
    size_t prefix_length = strlen(prefix);
    const char *line = config_values;
    while (*line)
    {
        const char *end = strchr(line, '\n');
        if (end == nullptr)
            end = line + strlen(line);
        if (static_cast<size_t>(end - line) >= prefix_length && memcmp(line, prefix, prefix_length) == 0)
        {
            int byte_length = static_cast<int>(end - line - prefix_length);
            int written = MultiByteToWideChar(CP_UTF8, 0, line + prefix_length, byte_length,
                                              output, static_cast<int>(capacity - 1));
            if (written < 0)
                written = 0;
            output[written] = 0;
            return static_cast<DWORD>(written);
        }
        line = *end ? end + 1 : end;
    }
    wcsncpy_s(output, capacity, fallback, _TRUNCATE);
    return static_cast<DWORD>(wcslen(output));
}

static int config_int(const wchar_t *section, const wchar_t *key, int fallback)
{
    wchar_t value[64], fallback_text[32];
    _snwprintf_s(fallback_text, 32, _TRUNCATE, L"%d", fallback);
    config_string(section, key, fallback_text, value, 64);
    return static_cast<int>(wcstol(value, nullptr, 10));
}

static int64_t profile_i64(const wchar_t *section, const wchar_t *key)
{
    wchar_t value[64];
    config_string(section, key, L"0", value, 64);
    return _wtoi64(value);
}

static float profile_float(const wchar_t *section, const wchar_t *key)
{
    wchar_t value[64];
    config_string(section, key, L"0", value, 64);
    return (float)_wtof(value);
}

static void load_speed_rule(SpeedRule *rule, const wchar_t *section)
{
    wchar_t edges[32768];
    memset(rule, 0, sizeof(*rule));
    rule->rule_id = (uint64_t)profile_i64(section, L"rule_id");
    rule->vehicle = (uint32_t)config_int(section, L"vehicle_id", 0);
    rule->speed_mps = profile_float(section, L"speed_mps");
    rule->hold = config_int(section, L"hold", 0) != 0;
    rule->path_index_start = config_int(section, L"path_index_start", -1);
    rule->path_index_end = config_int(section, L"path_index_end", -1);
    rule->expires_at = profile_i64(section, L"expires_at");
    config_string(section, L"edge_ids", L"", edges, 32768);
    wchar_t *context = NULL, *token = wcstok_s(edges, L",", &context);
    while (token && rule->edge_count < MAX_RULE_EDGES)
    {
        unsigned long value = wcstoul(token, NULL, 10);
        if (value)
            rule->edges[rule->edge_count++] = (uint32_t)value;
        token = wcstok_s(NULL, L",", &context);
    }
    rule->enabled = config_int(section, L"enabled", 0) && rule->vehicle &&
                    (rule->speed_mps > 0 || rule->hold) && rule->speed_mps >= 0 && rule->edge_count > 0;
}

static void load_station_rule(StationRule *rule, const wchar_t *section)
{
    memset(rule, 0, sizeof(*rule));
    rule->rule_id = (uint64_t)profile_i64(section, L"rule_id");
    rule->vehicle = (uint32_t)config_int(section, L"vehicle_id", 0);
    rule->station_group_id = (uint32_t)config_int(section, L"station_group_id", 0);
    rule->station_index = (uint32_t)config_int(section, L"station_index", -1);
    rule->terminal_index = (uint32_t)config_int(section, L"terminal_index", -1);
    rule->expires_at = profile_i64(section, L"expires_at");
    rule->enabled = config_int(section, L"enabled", 0) && rule->vehicle &&
                    rule->station_index != UINT32_MAX && rule->terminal_index != UINT32_MAX;
}

static void load_routing_rule(RoutingRule *rule, const wchar_t *section)
{
    memset(rule, 0, sizeof(*rule));
    rule->rule_id = (uint64_t)profile_i64(section, L"rule_id");
    rule->source_line = (uint32_t)config_int(section, L"source_line", 0);
    rule->target_line = (uint32_t)config_int(section, L"target_line", 0);
    rule->source_stop0 = config_int(section, L"source_stop0", -1);
    rule->source_stop1 = config_int(section, L"source_stop1", -1);
    rule->target_stop0 = config_int(section, L"target_stop0", -1);
    rule->target_stop1 = config_int(section, L"target_stop1", -1);
    rule->maximum = config_int(section, L"max_assignments", 0);
    wchar_t entity_kind[16];
    config_string(section, L"entity_kind", L"", entity_kind, 16);
    rule->entity_kind = _wcsicmp(entity_kind, L"PERSON") == 0 ? 1 : (_wcsicmp(entity_kind, L"CARGO") == 0 ? 2 : 0);
    rule->expires_at = profile_i64(section, L"expires_at");
    rule->enabled = config_int(section, L"enabled", 0) && rule->source_line &&
                    rule->target_line && rule->entity_kind && rule->source_stop0 >= 0 && rule->source_stop1 >= 0 &&
                    rule->target_stop0 >= 0 && rule->target_stop1 >= 0 && rule->maximum > 0;
}

static void load_path_rule(PathRule *rule, const wchar_t *section)
{
    wchar_t edges[32768];
    memset(rule, 0, sizeof(*rule));
    rule->rule_id = (uint64_t)profile_i64(section, L"rule_id");
    rule->vehicle = (uint32_t)config_int(section, L"vehicle_id", 0);
    rule->penalty_seconds = profile_float(section, L"penalty_seconds");
    rule->expires_at = profile_i64(section, L"expires_at");
    config_string(section, L"edge_ids", L"", edges, 32768);
    wchar_t *context = NULL, *token = wcstok_s(edges, L",", &context);
    while (token && rule->edge_count < MAX_RULE_EDGES)
    {
        unsigned long value = wcstoul(token, NULL, 10);
        if (value)
            rule->edges[rule->edge_count++] = (uint32_t)value;
        token = wcstok_s(NULL, L",", &context);
    }
    rule->enabled = config_int(section, L"enabled", 0) && rule->vehicle &&
                    rule->penalty_seconds > 0.0f && rule->penalty_seconds <= 3600.0f && rule->edge_count > 0;
}

static int same_station(const StationRule *a, const StationRule *b)
{
    return a->vehicle == b->vehicle && a->station_group_id == b->station_group_id &&
           a->station_index == b->station_index && a->terminal_index == b->terminal_index;
}

static int same_route(const RoutingRule *a, const RoutingRule *b)
{
    return a->source_line == b->source_line && a->target_line == b->target_line &&
           a->entity_kind == b->entity_kind &&
           a->source_stop0 == b->source_stop0 && a->source_stop1 == b->source_stop1 &&
           a->target_stop0 == b->target_stop0 && a->target_stop1 == b->target_stop1;
}

static void load_config(void)
{
    if (InterlockedCompareExchange(&loading, 1, 0) != 0)
        return;
    LONG generation = config_int(L"meta", L"generation", 0);
    if (generation && generation == config_generation)
    {
        InterlockedExchange(&loading, 0);
        return;
    }
    int speed_count = config_int(L"meta", L"speed_count", -1);
    int station_count = config_int(L"meta", L"station_count", -1);
    int routing_count = config_int(L"meta", L"routing_count", -1);
    int path_count = config_int(L"meta", L"path_count", -1);
    active_transaction_id = 0;
    memset(pending_speed_rules, 0, sizeof(pending_speed_rules));
    memset(pending_station_rules, 0, sizeof(pending_station_rules));
    memset(pending_routing_rules, 0, sizeof(pending_routing_rules));
    memset(pending_path_rules, 0, sizeof(pending_path_rules));
    if (speed_count < 0)
    {
        speed_count = 1;
        load_speed_rule(&pending_speed_rules[0], L"speed");
    }
    else
        for (int i = 0; i < speed_count && i < MAX_SPEED_RULES; ++i)
        {
            wchar_t section[32];
            _snwprintf_s(section, 32, _TRUNCATE, L"speed_%d", i);
            load_speed_rule(&pending_speed_rules[i], section);
            if (!pending_speed_rules[i].rule_id) pending_speed_rules[i].rule_id = 0x0100000000000000ULL | (uint64_t)(i + 1);
        }
    if (station_count < 0)
    {
        station_count = 1;
        load_station_rule(&pending_station_rules[0], L"station");
    }
    else
        for (int i = 0; i < station_count && i < MAX_STATION_RULES; ++i)
        {
            wchar_t section[32];
            _snwprintf_s(section, 32, _TRUNCATE, L"station_%d", i);
            load_station_rule(&pending_station_rules[i], section);
            if (!pending_station_rules[i].rule_id) pending_station_rules[i].rule_id = 0x0200000000000000ULL | (uint64_t)(i + 1);
        }
    if (routing_count < 0)
    {
        routing_count = 1;
        load_routing_rule(&pending_routing_rules[0], L"routing");
    }
    else
        for (int i = 0; i < routing_count && i < MAX_ROUTING_RULES; ++i)
        {
            wchar_t section[32];
            _snwprintf_s(section, 32, _TRUNCATE, L"routing_%d", i);
            load_routing_rule(&pending_routing_rules[i], section);
            if (!pending_routing_rules[i].rule_id) pending_routing_rules[i].rule_id = 0x0300000000000000ULL | (uint64_t)(i + 1);
        }
    if (path_count < 0)
    {
        path_count = 1;
        load_path_rule(&pending_path_rules[0], L"path");
    }
    else
        for (int i = 0; i < path_count && i < MAX_PATH_RULES; ++i)
        {
            wchar_t section[32];
            _snwprintf_s(section, 32, _TRUNCATE, L"path_%d", i);
            load_path_rule(&pending_path_rules[i], section);
            if (!pending_path_rules[i].rule_id) pending_path_rules[i].rule_id = 0x0400000000000000ULL | (uint64_t)(i + 1);
        }
    if (speed_count > MAX_SPEED_RULES)
        speed_count = MAX_SPEED_RULES;
    if (station_count > MAX_STATION_RULES)
        station_count = MAX_STATION_RULES;
    if (routing_count > MAX_ROUTING_RULES)
        routing_count = MAX_ROUTING_RULES;
    if (path_count > MAX_PATH_RULES)
        path_count = MAX_PATH_RULES;
    AcquireSRWLockExclusive(&rules_lock);
    for (int i = 0; i < speed_count; ++i)
        for (int j = 0; j < speed_rule_count; ++j)
            if (pending_speed_rules[i].vehicle == speed_rules[j].vehicle &&
                pending_speed_rules[i].speed_mps == speed_rules[j].speed_mps &&
                pending_speed_rules[i].path_index_start == speed_rules[j].path_index_start &&
                pending_speed_rules[i].path_index_end == speed_rules[j].path_index_end)
                pending_speed_rules[i].last_adjust = speed_rules[j].last_adjust;
    for (int i = 0; i < station_count; ++i)
        for (int j = 0; j < station_rule_count; ++j)
            if (same_station(&pending_station_rules[i], &station_rules[j]))
                pending_station_rules[i].consumed = station_rules[j].consumed;
    for (int i = 0; i < routing_count; ++i)
        for (int j = 0; j < routing_rule_count; ++j)
            if (same_route(&pending_routing_rules[i], &routing_rules[j]))
                pending_routing_rules[i].successes = routing_rules[j].successes;
    memcpy(speed_rules, pending_speed_rules, sizeof(pending_speed_rules));
    memcpy(station_rules, pending_station_rules, sizeof(pending_station_rules));
    memcpy(routing_rules, pending_routing_rules, sizeof(pending_routing_rules));
    memcpy(path_rules, pending_path_rules, sizeof(pending_path_rules));
    speed_rule_count = speed_count;
    station_rule_count = station_count;
    routing_rule_count = routing_count;
    path_rule_count = path_count;
    config_generation = generation;
    ReleaseSRWLockExclusive(&rules_lock);
    InterlockedExchange(&loading, 0);
    write_status("ACTIVE", "CONFIG_RELOADED");
}

static int load_shared_config(void)
{
    if (ipc == nullptr)
        return 0;
    for (int attempt = 0; attempt < 4; ++attempt)
    {
        LONG before = InterlockedCompareExchange(&ipc->config_sequence, 0, 0);
        if (before & 1)
        {
            SwitchToThread();
            continue;
        }
        LONG length = InterlockedCompareExchange(&ipc->config_length, 0, 0);
        if (length <= 0 || static_cast<uint32_t>(length) >= TPF2_IPC_CONFIG_CAPACITY)
            return 0;
        memcpy(shared_config_buffer, ipc->config, length);
        shared_config_buffer[length] = 0;
        MemoryBarrier();
        LONG after = InterlockedCompareExchange(&ipc->config_sequence, 0, 0);
        if (before == after && !(after & 1))
        {
            config_values = shared_config_buffer;
            load_config();
            config_values = nullptr;
            return 1;
        }
    }
    return 0;
}

struct CommandRuleSet
{
    SpeedRule *speeds;
    StationRule *stations;
    RoutingRule *routes;
    PathRule *paths;
    int *speed_count;
    int *station_count;
    int *route_count;
    int *path_count;
};

static uint32_t command_rule_set(uint64_t transaction_id, CommandRuleSet *set)
{
    if (transaction_id)
    {
        if (transaction_id != active_transaction_id)
            return TPF2_COMMAND_TRANSACTION_CONFLICT;
        set->speeds = pending_speed_rules;
        set->stations = pending_station_rules;
        set->routes = pending_routing_rules;
        set->paths = pending_path_rules;
        set->speed_count = &transaction_speed_count;
        set->station_count = &transaction_station_count;
        set->route_count = &transaction_routing_count;
        set->path_count = &transaction_path_count;
        return TPF2_COMMAND_OK;
    }
    if (active_transaction_id)
        return TPF2_COMMAND_TRANSACTION_CONFLICT;
    set->speeds = speed_rules;
    set->stations = station_rules;
    set->routes = routing_rules;
    set->paths = path_rules;
    set->speed_count = &speed_rule_count;
    set->station_count = &station_rule_count;
    set->route_count = &routing_rule_count;
    set->path_count = &path_rule_count;
    return TPF2_COMMAND_OK;
}

template <typename T>
static int find_rule(T *rules, int count, uint64_t rule_id)
{
    for (int i = 0; i < count; ++i)
        if (rules[i].rule_id == rule_id)
            return i;
    return -1;
}

template <typename T>
static uint32_t remove_rule(T *rules, int *count, uint64_t rule_id)
{
    int index = find_rule(rules, *count, rule_id);
    if (index < 0)
        return TPF2_COMMAND_RULE_NOT_FOUND;
    if (index + 1 < *count)
        memmove(&rules[index], &rules[index + 1], (SIZE_T)(*count - index - 1) * sizeof(T));
    ZeroMemory(&rules[*count - 1], sizeof(T));
    --*count;
    return TPF2_COMMAND_OK;
}

static int valid_edges(const uint32_t *edges, uint32_t count)
{
    if (!count || count > MAX_RULE_EDGES)
        return 0;
    for (uint32_t i = 0; i < count; ++i)
        if (!edges[i])
            return 0;
    return 1;
}

static uint32_t begin_transaction(const Tpf2CommandSlot *command)
{
    if (!command->transaction_id || command->payload_size != 0 || active_transaction_id)
        return command->payload_size ? TPF2_COMMAND_INVALID_PAYLOAD : TPF2_COMMAND_TRANSACTION_CONFLICT;
    AcquireSRWLockExclusive(&rules_lock);
    memcpy(pending_speed_rules, speed_rules, sizeof(speed_rules));
    memcpy(pending_station_rules, station_rules, sizeof(station_rules));
    memcpy(pending_routing_rules, routing_rules, sizeof(routing_rules));
    memcpy(pending_path_rules, path_rules, sizeof(path_rules));
    transaction_speed_count = speed_rule_count;
    transaction_station_count = station_rule_count;
    transaction_routing_count = routing_rule_count;
    transaction_path_count = path_rule_count;
    active_transaction_id = command->transaction_id;
    ReleaseSRWLockExclusive(&rules_lock);
    return TPF2_COMMAND_OK;
}

static uint32_t commit_transaction(const Tpf2CommandSlot *command)
{
    if (command->payload_size != 0)
        return TPF2_COMMAND_INVALID_PAYLOAD;
    if (!command->transaction_id || command->transaction_id != active_transaction_id)
        return TPF2_COMMAND_TRANSACTION_CONFLICT;
    AcquireSRWLockExclusive(&rules_lock);
    memcpy(speed_rules, pending_speed_rules, sizeof(speed_rules));
    memcpy(station_rules, pending_station_rules, sizeof(station_rules));
    memcpy(routing_rules, pending_routing_rules, sizeof(routing_rules));
    memcpy(path_rules, pending_path_rules, sizeof(path_rules));
    speed_rule_count = transaction_speed_count;
    station_rule_count = transaction_station_count;
    routing_rule_count = transaction_routing_count;
    path_rule_count = transaction_path_count;
    active_transaction_id = 0;
    ++controller_generation;
    ReleaseSRWLockExclusive(&rules_lock);
    return TPF2_COMMAND_OK;
}

static uint32_t abort_transaction(const Tpf2CommandSlot *command)
{
    if (command->payload_size != 0)
        return TPF2_COMMAND_INVALID_PAYLOAD;
    if (!command->transaction_id || command->transaction_id != active_transaction_id)
        return TPF2_COMMAND_TRANSACTION_CONFLICT;
    active_transaction_id = 0;
    return TPF2_COMMAND_OK;
}

static uint32_t upsert_speed_rule(const Tpf2CommandSlot *command)
{
    if (command->payload_size != sizeof(Tpf2SpeedRulePayload))
        return TPF2_COMMAND_INVALID_PAYLOAD;
    const auto *value = reinterpret_cast<const Tpf2SpeedRulePayload *>(command->payload);
    if (!value->rule_id || !value->vehicle_id || !std::isfinite(value->speed_mps) || value->speed_mps < 0 ||
        (!value->hold && value->speed_mps <= 0) || !valid_edges(value->edge_ids, value->edge_count))
        return TPF2_COMMAND_INVALID_PAYLOAD;
    AcquireSRWLockExclusive(&rules_lock);
    CommandRuleSet set{};
    uint32_t result = command_rule_set(command->transaction_id, &set);
    int index = result == TPF2_COMMAND_OK ? find_rule(set.speeds, *set.speed_count, value->rule_id) : -1;
    if (result == TPF2_COMMAND_OK && index < 0)
    {
        if (*set.speed_count >= MAX_SPEED_RULES)
            result = TPF2_COMMAND_CAPACITY_EXCEEDED;
        else
            index = (*set.speed_count)++;
    }
    if (result == TPF2_COMMAND_OK)
    {
        SpeedRule replacement{};
        replacement.rule_id = value->rule_id;
        replacement.enabled = 1;
        replacement.hold = value->hold != 0;
        replacement.vehicle = value->vehicle_id;
        replacement.speed_mps = value->speed_mps;
        replacement.edge_count = (int)value->edge_count;
        replacement.path_index_start = value->path_index_start;
        replacement.path_index_end = value->path_index_end;
        replacement.expires_at = value->expires_at;
        memcpy(replacement.edges, value->edge_ids, value->edge_count * sizeof(uint32_t));
        set.speeds[index] = replacement;
        if (!command->transaction_id) ++controller_generation;
    }
    ReleaseSRWLockExclusive(&rules_lock);
    return result;
}

static uint32_t upsert_station_rule(const Tpf2CommandSlot *command)
{
    if (command->payload_size != sizeof(Tpf2StationRulePayload))
        return TPF2_COMMAND_INVALID_PAYLOAD;
    const auto *value = reinterpret_cast<const Tpf2StationRulePayload *>(command->payload);
    if (!value->rule_id || !value->vehicle_id || value->station_index == UINT32_MAX || value->terminal_index == UINT32_MAX)
        return TPF2_COMMAND_INVALID_PAYLOAD;
    AcquireSRWLockExclusive(&rules_lock);
    CommandRuleSet set{};
    uint32_t result = command_rule_set(command->transaction_id, &set);
    int index = result == TPF2_COMMAND_OK ? find_rule(set.stations, *set.station_count, value->rule_id) : -1;
    if (result == TPF2_COMMAND_OK && index < 0)
    {
        if (*set.station_count >= MAX_STATION_RULES) result = TPF2_COMMAND_CAPACITY_EXCEEDED;
        else index = (*set.station_count)++;
    }
    if (result == TPF2_COMMAND_OK)
    {
        StationRule replacement{};
        replacement.rule_id = value->rule_id;
        replacement.enabled = 1;
        replacement.vehicle = value->vehicle_id;
        replacement.station_group_id = value->station_group_id;
        replacement.station_index = value->station_index;
        replacement.terminal_index = value->terminal_index;
        replacement.expires_at = value->expires_at;
        set.stations[index] = replacement;
        if (!command->transaction_id) ++controller_generation;
    }
    ReleaseSRWLockExclusive(&rules_lock);
    return result;
}

static uint32_t upsert_routing_rule(const Tpf2CommandSlot *command)
{
    if (command->payload_size != sizeof(Tpf2RoutingRulePayload))
        return TPF2_COMMAND_INVALID_PAYLOAD;
    const auto *value = reinterpret_cast<const Tpf2RoutingRulePayload *>(command->payload);
    if (!value->rule_id || !value->source_line || !value->target_line || value->source_line == value->target_line ||
        value->source_stop0 < 0 || value->source_stop1 < 0 || value->target_stop0 < 0 || value->target_stop1 < 0 ||
        value->max_assignments <= 0 || (value->entity_kind != 1 && value->entity_kind != 2))
        return TPF2_COMMAND_INVALID_PAYLOAD;
    AcquireSRWLockExclusive(&rules_lock);
    CommandRuleSet set{};
    uint32_t result = command_rule_set(command->transaction_id, &set);
    int index = result == TPF2_COMMAND_OK ? find_rule(set.routes, *set.route_count, value->rule_id) : -1;
    if (result == TPF2_COMMAND_OK && index < 0)
    {
        if (*set.route_count >= MAX_ROUTING_RULES) result = TPF2_COMMAND_CAPACITY_EXCEEDED;
        else index = (*set.route_count)++;
    }
    if (result == TPF2_COMMAND_OK)
    {
        RoutingRule replacement{};
        replacement.rule_id = value->rule_id;
        replacement.enabled = 1;
        replacement.source_line = value->source_line;
        replacement.target_line = value->target_line;
        replacement.source_stop0 = value->source_stop0;
        replacement.source_stop1 = value->source_stop1;
        replacement.target_stop0 = value->target_stop0;
        replacement.target_stop1 = value->target_stop1;
        replacement.maximum = value->max_assignments;
        replacement.entity_kind = value->entity_kind;
        replacement.expires_at = value->expires_at;
        set.routes[index] = replacement;
        if (!command->transaction_id) ++controller_generation;
    }
    ReleaseSRWLockExclusive(&rules_lock);
    return result;
}

static uint32_t upsert_path_rule(const Tpf2CommandSlot *command)
{
    if (command->payload_size != sizeof(Tpf2PathRulePayload))
        return TPF2_COMMAND_INVALID_PAYLOAD;
    const auto *value = reinterpret_cast<const Tpf2PathRulePayload *>(command->payload);
    if (!value->rule_id || !value->vehicle_id || !std::isfinite(value->penalty_seconds) ||
        value->penalty_seconds <= 0 || value->penalty_seconds > 3600 ||
        !valid_edges(value->edge_ids, value->edge_count))
        return TPF2_COMMAND_INVALID_PAYLOAD;
    AcquireSRWLockExclusive(&rules_lock);
    CommandRuleSet set{};
    uint32_t result = command_rule_set(command->transaction_id, &set);
    int index = result == TPF2_COMMAND_OK ? find_rule(set.paths, *set.path_count, value->rule_id) : -1;
    if (result == TPF2_COMMAND_OK && index < 0)
    {
        if (*set.path_count >= MAX_PATH_RULES) result = TPF2_COMMAND_CAPACITY_EXCEEDED;
        else index = (*set.path_count)++;
    }
    if (result == TPF2_COMMAND_OK)
    {
        PathRule replacement{};
        replacement.rule_id = value->rule_id;
        replacement.enabled = 1;
        replacement.vehicle = value->vehicle_id;
        replacement.penalty_seconds = value->penalty_seconds;
        replacement.expires_at = value->expires_at;
        replacement.edge_count = (int)value->edge_count;
        memcpy(replacement.edges, value->edge_ids, value->edge_count * sizeof(uint32_t));
        set.paths[index] = replacement;
        if (!command->transaction_id) ++controller_generation;
    }
    ReleaseSRWLockExclusive(&rules_lock);
    return result;
}

static uint32_t remove_command_rule(const Tpf2CommandSlot *command)
{
    if (command->payload_size != sizeof(Tpf2RuleKeyPayload))
        return TPF2_COMMAND_INVALID_PAYLOAD;
    const auto *value = reinterpret_cast<const Tpf2RuleKeyPayload *>(command->payload);
    if (!value->rule_id)
        return TPF2_COMMAND_INVALID_PAYLOAD;
    AcquireSRWLockExclusive(&rules_lock);
    CommandRuleSet set{};
    uint32_t result = command_rule_set(command->transaction_id, &set);
    if (result == TPF2_COMMAND_OK)
    {
        switch (command->opcode)
        {
        case TPF2_CMD_REMOVE_SPEED_RULE: result = remove_rule(set.speeds, set.speed_count, value->rule_id); break;
        case TPF2_CMD_REMOVE_STATION_RULE: result = remove_rule(set.stations, set.station_count, value->rule_id); break;
        case TPF2_CMD_REMOVE_ROUTING_RULE: result = remove_rule(set.routes, set.route_count, value->rule_id); break;
        case TPF2_CMD_REMOVE_PATH_RULE: result = remove_rule(set.paths, set.path_count, value->rule_id); break;
        default: result = TPF2_COMMAND_UNKNOWN_OPCODE; break;
        }
        if (result == TPF2_COMMAND_OK && !command->transaction_id) ++controller_generation;
    }
    ReleaseSRWLockExclusive(&rules_lock);
    return result;
}

static uint32_t clear_command_rules(const Tpf2CommandSlot *command)
{
    if (command->payload_size != 0)
        return TPF2_COMMAND_INVALID_PAYLOAD;
    AcquireSRWLockExclusive(&rules_lock);
    CommandRuleSet set{};
    uint32_t result = command_rule_set(command->transaction_id, &set);
    if (result == TPF2_COMMAND_OK)
    {
        switch (command->opcode)
        {
        case TPF2_CMD_CLEAR_SPEED_RULES: ZeroMemory(set.speeds, sizeof(speed_rules)); *set.speed_count = 0; break;
        case TPF2_CMD_CLEAR_STATION_RULES: ZeroMemory(set.stations, sizeof(station_rules)); *set.station_count = 0; break;
        case TPF2_CMD_CLEAR_ROUTING_RULES: ZeroMemory(set.routes, sizeof(routing_rules)); *set.route_count = 0; break;
        case TPF2_CMD_CLEAR_PATH_RULES: ZeroMemory(set.paths, sizeof(path_rules)); *set.path_count = 0; break;
        case TPF2_CMD_CLEAR_ALL_RULES:
            ZeroMemory(set.speeds, sizeof(speed_rules));
            ZeroMemory(set.stations, sizeof(station_rules));
            ZeroMemory(set.routes, sizeof(routing_rules));
            ZeroMemory(set.paths, sizeof(path_rules));
            *set.speed_count = *set.station_count = *set.route_count = *set.path_count = 0;
            break;
        default: result = TPF2_COMMAND_UNKNOWN_OPCODE; break;
        }
        if (result == TPF2_COMMAND_OK && !command->transaction_id) ++controller_generation;
    }
    ReleaseSRWLockExclusive(&rules_lock);
    return result;
}

static uint32_t dispatch_command(const Tpf2CommandSlot *command, char *detail, size_t detail_size)
{
    if (!command->cmd_id || command->payload_size > TPF2_COMMAND_PAYLOAD_CAPACITY)
        return TPF2_COMMAND_INVALID_PAYLOAD;
    switch (command->opcode)
    {
    case TPF2_CMD_PING:
        if (command->payload_size) return TPF2_COMMAND_INVALID_PAYLOAD;
        strncpy_s(detail, detail_size, "PONG", _TRUNCATE);
        return TPF2_COMMAND_OK;
    case TPF2_CMD_GET_STATUS:
        if (command->payload_size) return TPF2_COMMAND_INVALID_PAYLOAD;
        _snprintf_s(detail, detail_size, _TRUNCATE, "speed=%d;station=%d;routing=%d;path=%d;transaction=%llu",
                    speed_rule_count, station_rule_count, routing_rule_count, path_rule_count,
                    (unsigned long long)active_transaction_id);
        return TPF2_COMMAND_OK;
    case TPF2_CMD_GET_CAPABILITIES:
        if (command->payload_size) return TPF2_COMMAND_INVALID_PAYLOAD;
        strncpy_s(detail, detail_size, "v2;transaction;speed;station;routing;path;train_movement_experimental;movement_return_check", _TRUNCATE);
        return TPF2_COMMAND_OK;
    case TPF2_CMD_BEGIN_TRANSACTION: return begin_transaction(command);
    case TPF2_CMD_COMMIT_TRANSACTION: return commit_transaction(command);
    case TPF2_CMD_ABORT_TRANSACTION: return abort_transaction(command);
    case TPF2_CMD_UPSERT_SPEED_RULE: return upsert_speed_rule(command);
    case TPF2_CMD_UPSERT_STATION_RULE: return upsert_station_rule(command);
    case TPF2_CMD_UPSERT_ROUTING_RULE: return upsert_routing_rule(command);
    case TPF2_CMD_UPSERT_PATH_RULE: return upsert_path_rule(command);
    case TPF2_CMD_MOVE_TRAIN_DISTANCE:
    case TPF2_CMD_MOVE_TRAIN_ROUTE:
    case TPF2_CMD_RELEASE_TRAIN_MOVEMENT:
    case TPF2_CMD_GET_TRAIN_MOVEMENT:
        return train_motion_command(command, detail, detail_size);
    case TPF2_CMD_REMOVE_SPEED_RULE:
    case TPF2_CMD_REMOVE_STATION_RULE:
    case TPF2_CMD_REMOVE_ROUTING_RULE:
    case TPF2_CMD_REMOVE_PATH_RULE:
        return remove_command_rule(command);
    case TPF2_CMD_CLEAR_ALL_RULES:
    case TPF2_CMD_CLEAR_SPEED_RULES:
    case TPF2_CMD_CLEAR_STATION_RULES:
    case TPF2_CMD_CLEAR_ROUTING_RULES:
    case TPF2_CMD_CLEAR_PATH_RULES:
        return clear_command_rules(command);
    default:
        return TPF2_COMMAND_UNKNOWN_OPCODE;
    }
}

static int process_command_queue(void)
{
    if (command_ipc == nullptr)
        return 0;
    LONG64 read = InterlockedCompareExchange64(&command_ipc->command_read_sequence, 0, 0);
    LONG64 write = InterlockedCompareExchange64(&command_ipc->command_write_sequence, 0, 0);
    while (read < write)
    {
        Tpf2CommandSlot command{};
        memcpy(&command, &command_ipc->commands[read % TPF2_COMMAND_RING_CAPACITY], sizeof(command));
        char detail[TPF2_REPLY_DETAIL_CAPACITY]{};
        uint32_t result = dispatch_command(&command, detail, sizeof(detail));
        publish_command_reply(&command, result, detail[0] ? detail : (result == TPF2_COMMAND_OK ? "OK" : "REJECTED"));
        ++read;
        InterlockedExchange64(&command_ipc->command_read_sequence, read);
        write = InterlockedCompareExchange64(&command_ipc->command_write_sequence, 0, 0);
    }
    return 0;
}

static int reserve_route(uint32_t line, int stop0, int stop1, int entity_kind, RoutingRule *selected)
{
    int64_t now = (int64_t)time(NULL);
    int found = 0;
    AcquireSRWLockShared(&rules_lock);
    for (int i = 0; i < routing_rule_count; ++i)
    {
        RoutingRule *rule = &routing_rules[i];
        if (!rule->enabled || (rule->expires_at && rule->expires_at <= now) || rule->entity_kind != entity_kind || rule->source_line != line ||
            rule->source_stop0 != stop0 || rule->source_stop1 != stop1)
            continue;
        LONG slot = InterlockedIncrement(&rule->successes);
        if (slot > rule->maximum)
        {
            InterlockedDecrement(&rule->successes);
            continue;
        }
        *selected = *rule;
        found = 1;
        break;
    }
    ReleaseSRWLockShared(&rules_lock);
    return found;
}

static void release_route_reservation(const RoutingRule *selected)
{
    AcquireSRWLockShared(&rules_lock);
    for (int i = 0; i < routing_rule_count; ++i)
    {
        if (same_route(selected, &routing_rules[i]))
        {
            InterlockedDecrement(&routing_rules[i].successes);
            break;
        }
    }
    ReleaseSRWLockShared(&rules_lock);
}

static void note_route_call(uint32_t *line, int stop0, int stop1, const char *kind)
{
    InterlockedIncrement(&routing_calls);
    InterlockedExchange(&routing_last_line, readable(line, sizeof(uint32_t)) ? (LONG)*line : 0);
    InterlockedExchange(&routing_last_stop0, stop0);
    InterlockedExchange(&routing_last_stop1, stop1);
    ULONGLONG now = GetTickCount64();
    if (routing_rule_count && now - routing_last_status > 1000)
    {
        routing_last_status = now;
        write_status("ACTIVE", kind);
    }
}

unsigned char cargo_assign_hook(void *engine, void *system, void *entity, uint32_t *line,
                                unsigned int stop0, int stop1, int64_t arrival)
{
    auto guard = dtmgr.adopt_hook_call();
    if (dtmgr.is_draining())
        return original_cargo_assign(engine, system, entity, line, stop0, stop1, arrival);
    note_route_call(line, (int)stop0, stop1, "CARGO_ASSIGN_OBSERVED");
    RoutingRule rule;
    if (!readable(line, sizeof(uint32_t)) || !reserve_route(*line, (int)stop0, stop1, 2, &rule))
        return original_cargo_assign(engine, system, entity, line, stop0, stop1, arrival);
    uint32_t target = rule.target_line;
    InterlockedIncrement(&routing_attempts);
    unsigned char result = original_cargo_assign(engine, system, entity, &target,
                                                 (unsigned)rule.target_stop0, rule.target_stop1, arrival);
    if (result)
        InterlockedIncrement(&routing_successes);
    else
        release_route_reservation(&rule);
    write_status("ACTIVE", result ? "CARGO_OD_REASSIGNED" : "CARGO_OD_REASSIGN_REJECTED");
    return result;
}

int64_t person_assign_hook(void *a1, void *engine, void *a3, void *a4, void *a5, uint32_t *entity,
                           void *from_edges, uint32_t *line, unsigned int stop0, int stop1,
                           int64_t a11, int64_t a12, int64_t a13)
{
    auto guard = dtmgr.adopt_hook_call();
    if (dtmgr.is_draining())
        return original_person_assign(a1, engine, a3, a4, a5, entity, from_edges, line, stop0, stop1, a11, a12, a13);
    note_route_call(line, (int)stop0, stop1, "PERSON_ASSIGN_OBSERVED");
    RoutingRule rule;
    if (!readable(line, sizeof(uint32_t)) || !reserve_route(*line, (int)stop0, stop1, 1, &rule))
        return original_person_assign(a1, engine, a3, a4, a5, entity, from_edges, line, stop0, stop1, a11, a12, a13);
    uint32_t target = rule.target_line;
    InterlockedIncrement(&routing_attempts);
    int64_t result = original_person_assign(a1, engine, a3, a4, a5, entity, from_edges, &target,
                                            (unsigned)rule.target_stop0, rule.target_stop1, a11, a12, a13);
    InterlockedIncrement(&routing_successes);
    write_status("ACTIVE", "PERSON_OD_REASSIGNED");
    return result;
}

unsigned char station_hook_c(void *context, uint32_t *vehicle, uint32_t *next_station_entity, int next_station,
                             void *sim_system, unsigned char flag6, int arg7, uint64_t arg8,
                             unsigned char assigned_only, uint64_t station_terminal, void *deferred, unsigned char flag12)
{
    auto guard = dtmgr.adopt_hook_call();
    if (dtmgr.is_draining())
        return original_station(context, vehicle, next_station_entity, next_station, sim_system,
                                flag6, arg7, arg8, assigned_only, station_terminal, deferred, flag12);
    StationRule selected;
    if (readable(vehicle, sizeof(uint32_t)) && train_motion_blocks_station_path(context, *vehicle))
        return 1; // This train's temporary route is owned by train_motion until release.
    int applies = 0, selected_index = -1;
    int64_t now = (int64_t)time(NULL);
    if (readable(vehicle, sizeof(uint32_t)))
    {
        AcquireSRWLockShared(&rules_lock);
        for (int i = 0; i < station_rule_count; ++i)
        {
            StationRule *rule = &station_rules[i];
            int station_matches = !rule->station_group_id || (readable(next_station_entity, sizeof(uint32_t)) && *next_station_entity == rule->station_group_id);
            if (rule->enabled && (!rule->expires_at || rule->expires_at > now) && rule->vehicle == *vehicle && station_matches &&
                InterlockedCompareExchange(&rule->consumed, 1, 0) == 0)
            {
                selected = *rule;
                selected_index = i;
                applies = 1;
                break;
            }
        }
        ReleaseSRWLockShared(&rules_lock);
    }
    if (applies)
    {
        assigned_only = 1;
        station_terminal = ((uint64_t)selected.terminal_index << 32) | selected.station_index;
    }
    void *previous_path_vehicle = path_vehicle_tls != TLS_OUT_OF_INDEXES ? TlsGetValue(path_vehicle_tls) : NULL;
    if (path_vehicle_tls != TLS_OUT_OF_INDEXES && readable(vehicle, sizeof(uint32_t)))
        TlsSetValue(path_vehicle_tls, (void *)(uintptr_t)*vehicle);
    unsigned char result = original_station(context, vehicle, next_station_entity, next_station, sim_system,
                                            flag6, arg7, arg8, assigned_only, station_terminal, deferred, flag12);
    if (path_vehicle_tls != TLS_OUT_OF_INDEXES)
        TlsSetValue(path_vehicle_tls, previous_path_vehicle);
    if (applies)
    {
        if (result)
            write_status("ACTIVE", "STATION_ASSIGNMENT_ACCEPTED_ONE_SHOT");
        else
            /* Consume a rejected override. The game's next request uses its
               default assignment instead of retrying the same bad target. */
            write_status("ACTIVE", "STATION_ASSIGNMENT_REJECTED_DEFAULT_NEXT_CALL");
    }
    return result;
}

static int path_rule_has_edge(const PathRule *rule, uint32_t edge)
{
    for (int i = 0; i < rule->edge_count; ++i)
        if (rule->edges[i] == edge)
            return 1;
    return 0;
}

float path_cost_hook(void *expander, void *path_vector, int first, int last)
{
    auto guard = dtmgr.adopt_hook_call();
    if (dtmgr.is_draining())
        return original_path_cost(expander, path_vector, first, last);
    float native_cost = original_path_cost(expander, path_vector, first, last);
    InterlockedIncrement64(&path_cost_calls);
    uint32_t vehicle = path_vehicle_tls != TLS_OUT_OF_INDEXES ? (uint32_t)(uintptr_t)TlsGetValue(path_vehicle_tls) : 0;
    InterlockedExchange(&path_last_vehicle, (LONG)vehicle);
    if (!vehicle || first < 0 || last <= first || !readable(path_vector, 16))
        return native_cost;
    unsigned char *begin = *(unsigned char **)path_vector;
    unsigned char *end = *(unsigned char **)((unsigned char *)path_vector + 8);
    if (!begin || end < begin || (SIZE_T)(end - begin) % 12 != 0)
        return native_cost;
    int count = (int)((end - begin) / 12);
    if (count <= 0 || count > 100000 || last > count || !readable(begin, (SIZE_T)count * 12))
        return native_cost;
    int64_t now = (int64_t)time(NULL);
    float penalty = 0.0f;
    int vehicle_matched = 0, edge_matched = 0;
    AcquireSRWLockShared(&rules_lock);
    for (int rule_index = 0; rule_index < path_rule_count; ++rule_index)
    {
        PathRule *rule = &path_rules[rule_index];
        if (!rule->enabled || rule->vehicle != vehicle || (rule->expires_at && rule->expires_at <= now))
            continue;
        vehicle_matched = 1;
        for (int index = first; index < last; ++index)
        {
            uint32_t edge = *(uint32_t *)(begin + (SIZE_T)index * 12);
            InterlockedExchange(&path_last_edge, (LONG)edge);
            if (path_rule_has_edge(rule, edge))
            {
                edge_matched = 1;
                if (rule->penalty_seconds > penalty)
                    penalty = rule->penalty_seconds;
            }
        }
    }
    ReleaseSRWLockShared(&rules_lock);
    if (vehicle_matched)
        InterlockedIncrement64(&path_vehicle_matches);
    if (!edge_matched)
        return native_cost;
    InterlockedIncrement64(&path_edge_matches);
    InterlockedIncrement64(&path_penalties);
    ULONGLONG ticks = GetTickCount64();
    if (ticks - path_last_status > 1000)
    {
        path_last_status = ticks;
        write_status("ACTIVE", "PATH_COST_PENALTY_APPLIED");
    }
    return native_cost + penalty;
}

static int configured_edge(const SpeedRule *rule, uint32_t edge, int path_index)
{
    if ((rule->path_index_start >= 0 && path_index < rule->path_index_start) ||
        (rule->path_index_end >= 0 && path_index > rule->path_index_end))
        return 0;
    for (int i = 0; i < rule->edge_count; ++i)
        if (rule->edges[i] == edge)
            return 1;
    return 0;
}

extern "C" float speed_hook_c(void *engine, int component, void *path_vector, int first, int last,
                              float factor, void *network, int filter0, int filter1, uint64_t vehicle_pointer)
{
    auto guard = dtmgr.adopt_hook_call();
    if (dtmgr.is_draining())
        return original_speed(engine, component, path_vector, first, last, factor, network, filter0, filter1);
    float native_limit = original_speed(engine, component, path_vector, first, last, factor, network, filter0, filter1);
    native_limit = train_motion_speed_limit(path_vector, native_limit);
    InterlockedIncrement64(&speed_calls);
    uint32_t candidate = readable((void *)vehicle_pointer, sizeof(uint32_t)) ? *(uint32_t *)vehicle_pointer : 0;
    InterlockedExchange(&last_candidate, (LONG)candidate);
    if (!candidate || first > last || !readable(path_vector, 16))
        return native_limit;
    int64_t wall_now = (int64_t)time(NULL);
    SpeedRule *active_rule = NULL;
    SpeedRule *ahead_rule = NULL;
    int nearest_ahead = -1;
    int matching_vehicle = 0;
    AcquireSRWLockShared(&rules_lock);
    unsigned char *begin = *(unsigned char **)path_vector;
    if (!readable(begin, (SIZE_T)(last + 1) * 12))
    {
        ReleaseSRWLockShared(&rules_lock);
        return native_limit;
    }
    unsigned char *end = *(unsigned char **)((unsigned char *)path_vector + 8);
    int path_count = end >= begin && (SIZE_T)(end - begin) % 12 == 0 ? (int)((end - begin) / 12) : 0;
    if (path_count <= 0 || path_count > 100000 || first < 0 || last >= path_count ||
        !readable(begin, (SIZE_T)path_count * 12))
    {
        ReleaseSRWLockShared(&rules_lock);
        return native_limit;
    }
    InterlockedExchange(&last_first, first);
    InterlockedExchange(&last_last, last);
    for (int i = 0; i < speed_rule_count; ++i)
    {
        SpeedRule *rule = &speed_rules[i];
        if (!rule->enabled || rule->vehicle != candidate || (rule->expires_at && rule->expires_at <= wall_now))
            continue;
        matching_vehicle = 1;
        int applies_now = 0;
        for (int index = first; index <= last; ++index)
        {
            uint32_t edge = *(uint32_t *)(begin + (SIZE_T)index * 12);
            InterlockedExchange(&last_edge, (LONG)edge);
            if (configured_edge(rule, edge, index))
            {
                applies_now = 1;
                break;
            }
        }
        if (applies_now)
        {
            if (!active_rule || rule->speed_mps < active_rule->speed_mps)
                active_rule = rule;
            InterlockedExchange64((volatile LONG64 *)&rule->last_adjust, 0);
            continue;
        }
        int scan_from = last >= 0 ? last : 0;
        int distance = -1;
        for (int index = scan_from; index < path_count; ++index)
        {
            if (configured_edge(rule, *(uint32_t *)(begin + (SIZE_T)index * 12), index))
            {
                distance = index - scan_from;
                break;
            }
        }
        if (distance >= 0 && (nearest_ahead < 0 || distance < nearest_ahead ||
                              (distance == nearest_ahead && (!ahead_rule || rule->speed_mps < ahead_rule->speed_mps))))
        {
            if (ahead_rule)
                InterlockedExchange64((volatile LONG64 *)&ahead_rule->last_adjust, 0);
            nearest_ahead = distance;
            ahead_rule = rule;
        }
        else
        {
            InterlockedExchange64((volatile LONG64 *)&rule->last_adjust, 0);
        }
    }
    if (!matching_vehicle)
    {
        ReleaseSRWLockShared(&rules_lock);
        return native_limit;
    }
    if (active_rule && ahead_rule)
        InterlockedExchange64((volatile LONG64 *)&ahead_rule->last_adjust, 0);
    InterlockedIncrement64(&vehicle_matches);
    /* GetSpeedLimit's caller does not actively brake an already overspeeding
       train in this build.  MOVE_PATH.dyn.speed is the same authoritative
       field exported by the Lua telemetry collector (verified at +64 in this
       exact binary).  Begin a 1.2 m/s^2 service brake while the configured
       zone is within roughly 24 path elements, then let the native traction
       model recover after the zone. */
    if (!active_rule && ahead_rule && nearest_ahead <= 24 && readable((unsigned char *)path_vector + 64, sizeof(float)))
    {
        float *speed = (float *)((unsigned char *)path_vector + 64);
        ULONGLONG now = GetTickCount64();
        ULONGLONG previous_adjust = ahead_rule->last_adjust;
        if (!previous_adjust)
        {
            InterlockedExchange64((volatile LONG64 *)&ahead_rule->last_adjust, (LONG64)now);
            previous_adjust = now;
        }
        float elapsed = (float)(now - previous_adjust) / 1000.0f;
        if (elapsed > 0.0f)
        {
            float next = *speed - 1.2f * (elapsed > 0.1f ? 0.1f : elapsed);
            if (next < ahead_rule->speed_mps)
                next = ahead_rule->speed_mps;
            if (*speed > ahead_rule->speed_mps)
                *speed = next;
            InterlockedExchange64((volatile LONG64 *)&ahead_rule->last_adjust, (LONG64)now);
        }
    }
    if (active_rule)
    {
        InterlockedIncrement64(&edge_matches);
        if (readable((unsigned char *)path_vector + 64, sizeof(float)))
        {
            float *speed = (float *)((unsigned char *)path_vector + 64);
            /* The simulation integrates traction between limit samples.
               A small internal margin keeps the externally observed speed
               at or below the configured limit instead of oscillating
               about 1.5 km/h above it. */
            float enforced = active_rule->speed_mps > 0.5f ? active_rule->speed_mps - 0.5f : active_rule->speed_mps;
            if (*speed > enforced)
                *speed = enforced;
        }
        ULONGLONG now = GetTickCount64();
        if (now - last_diagnostic_status > 1000)
        {
            last_diagnostic_status = now;
            write_status("ACTIVE", "SPEED_LIMIT_APPLIED");
        }
        float result = native_limit < active_rule->speed_mps ? native_limit : active_rule->speed_mps;
        ReleaseSRWLockShared(&rules_lock);
        return result;
    }
    ReleaseSRWLockShared(&rules_lock);
    return native_limit;
}

static int install_hooks(void)
{
    static const unsigned char speed_expected[15] = {
        0x48, 0x8b, 0xc4, 0x55, 0x41, 0x54, 0x41, 0x55, 0x48, 0x81, 0xec, 0x80, 0x00, 0x00, 0x00
    };
    static const unsigned char path_cost_expected[16] = {
        0x41, 0x56, 0x41, 0x57, 0x48, 0x83, 0xec, 0x38, 0xf3, 0x0f, 0x10, 0x41, 0x74, 0x4c, 0x8b, 0xfa
    };
    static const unsigned char station_expected[18] = {
        0x40, 0x55, 0x53, 0x56, 0x57, 0x41, 0x54, 0x41, 0x55,
        0x41, 0x56, 0x41, 0x57, 0x48, 0x8d, 0x6c, 0x24, 0xe8
    };
    static const unsigned char cargo_expected[14] = {
        0x48, 0x89, 0x5c, 0x24, 0x10, 0x55, 0x56, 0x57, 0x41, 0x54, 0x41, 0x55, 0x41, 0x56
    };
    static const unsigned char person_expected[15] = {
        0x48, 0x8b, 0xc4, 0x55, 0x53, 0x56, 0x57, 0x41, 0x54, 0x41, 0x55, 0x41, 0x56, 0x41, 0x57
    };

    unsigned char *base = reinterpret_cast<unsigned char *>(GetModuleHandleW(nullptr));
    if (!readable(base, sizeof(IMAGE_DOS_HEADER)))
    {
        write_status("DISABLED", "PE_IDENTITY_MISMATCH");
        return 0;
    }
    IMAGE_DOS_HEADER *dos = reinterpret_cast<IMAGE_DOS_HEADER *>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE ||
        !readable(base + dos->e_lfanew, sizeof(IMAGE_NT_HEADERS64)))
    {
        write_status("DISABLED", "PE_IDENTITY_MISMATCH");
        return 0;
    }
    IMAGE_NT_HEADERS64 *nt = reinterpret_cast<IMAGE_NT_HEADERS64 *>(base + dos->e_lfanew);
    const uint64_t highest_rva = SPEED_RVA;
    if (nt->Signature != IMAGE_NT_SIGNATURE ||
        nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC ||
        nt->OptionalHeader.SizeOfImage <= highest_rva + sizeof(speed_expected))
    {
        write_status("DISABLED", "PE_IDENTITY_MISMATCH");
        return 0;
    }

    struct HookSpec
    {
        unsigned char *target;
        const unsigned char *expected;
        SIZE_T length;
        void *hook;
        void **original;
        const char *failure;
    };
    HookSpec hooks[] = {
        {base + SPEED_RVA, speed_expected, sizeof(speed_expected),
         reinterpret_cast<void *>(&speed_hook_entry), reinterpret_cast<void **>(&original_speed),
         "SPEED_SIGNATURE_MISMATCH"},
        {base + PATH_COST_RVA, path_cost_expected, sizeof(path_cost_expected),
         reinterpret_cast<void *>(&path_cost_hook), reinterpret_cast<void **>(&original_path_cost),
         "PATH_COST_SIGNATURE_MISMATCH"},
        {base + STATION_RVA, station_expected, sizeof(station_expected),
         reinterpret_cast<void *>(&station_hook_c), reinterpret_cast<void **>(&original_station),
         "STATION_SIGNATURE_MISMATCH"},
        {base + CARGO_ASSIGN_RVA, cargo_expected, sizeof(cargo_expected),
         reinterpret_cast<void *>(&cargo_assign_hook), reinterpret_cast<void **>(&original_cargo_assign),
         "CARGO_ASSIGN_SIGNATURE_MISMATCH"},
        {base + PERSON_ASSIGN_RVA, person_expected, sizeof(person_expected),
         reinterpret_cast<void *>(&person_assign_hook), reinterpret_cast<void **>(&original_person_assign),
         "PERSON_ASSIGN_SIGNATURE_MISMATCH"}
    };

    for (const HookSpec& hook : hooks)
    {
        if (!dtmgr.install_detour(hook.target, hook.expected, hook.length,
                                  hook.hook, hook.original, hook.failure))
        {
            const int cleaned = dtmgr.uninstall_all_detours();
            InterlockedExchange(&controller_safe_to_unload, cleaned ? 1 : 0);
            write_status("DISABLED", cleaned ? hook.failure : "PARTIAL_HOOK_CLEANUP_FAILED");
            return 0;
        }
    }
    if (!install_train_motion_hooks(path_vehicle_tls))
    {
        const int cleaned = dtmgr.uninstall_all_detours();
        InterlockedExchange(&controller_safe_to_unload, cleaned ? 1 : 0);
        write_status("DISABLED", cleaned ? "TRAIN_MOTION_SIGNATURE_MISMATCH" : "PARTIAL_HOOK_CLEANUP_FAILED");
        return 0;
    }
    write_status("ACTIVE", "VERSION_LOCKED_STATION_AND_PATH_CONTROL_HOOKS");
    return 1;
}

static DWORD wait_for_shutdown(void)
{
    if (shutdown_event == nullptr)
    {
        write_status("DISABLED", "SHUTDOWN_EVENT_UNAVAILABLE");
        return dtmgr.uninstall_all_detours() ? 1 : 0;
    }

    HANDLE events[3] = {shutdown_event, nullptr, nullptr};
    DWORD event_count = 1;
    DWORD config_index = MAXDWORD;
    DWORD command_index = MAXDWORD;
    if (ipc_config_event)
    {
        config_index = event_count;
        events[event_count++] = ipc_config_event;
    }
    if (command_event)
    {
        command_index = event_count;
        events[event_count++] = command_event;
    }
    DWORD wait_result = WAIT_FAILED;
    for (;;)
    {
        wait_result = WaitForMultipleObjects(event_count, events, FALSE, INFINITE);
        DWORD selected = wait_result >= WAIT_OBJECT_0 ? wait_result - WAIT_OBJECT_0 : MAXDWORD;
        if (selected == config_index)
        {
            if (!load_shared_config())
                write_status("ACTIVE", "SHARED_CONFIG_READ_FAILED");
            continue;
        }
        if (selected == command_index)
        {
            process_command_queue();
            continue;
        }
        break;
    }
    if (wait_result != WAIT_OBJECT_0)
    {
        write_status("DISABLED", "SHUTDOWN_EVENT_WAIT_FAILED");
        return dtmgr.uninstall_all_detours() ? 1 : 0;
    }
    if (!dtmgr.uninstall_all_detours())
    {
        write_status("DISABLED", "LOADER_UNINSTALL_FAILED");
        return 0;
    }

    write_status("UNINSTALLED", "LOADER_UNLOAD_READY");
    return 1;
}

static DWORD WINAPI initialize_tpf2(LPVOID self)
{
    paths(static_cast<HMODULE>(self));
    initialize_ipc();
    if (!initialize_command_ipc())
        write_status("ACTIVE", "COMMAND_IPC_V2_UNAVAILABLE");
    path_vehicle_tls = TlsAlloc();
    if (path_vehicle_tls == TLS_OUT_OF_INDEXES)
    {
        write_status("DISABLED", "PATH_TLS_ALLOC_FAILED");
        InterlockedExchange(&controller_safe_to_unload, 1);
        close_ipc();
        return 0;
    }

    if (!load_shared_config())
        load_config();
    if (!install_hooks())
    {
        TlsFree(path_vehicle_tls);
        path_vehicle_tls = TLS_OUT_OF_INDEXES;
        close_ipc();
        return 0;
    }

    const int safe_to_unload = wait_for_shutdown();
    if (safe_to_unload && path_vehicle_tls != TLS_OUT_OF_INDEXES)
    {
        TlsFree(path_vehicle_tls);
        path_vehicle_tls = TLS_OUT_OF_INDEXES;
    }
    close_ipc();
    InterlockedExchange(&controller_safe_to_unload, safe_to_unload ? 1 : 0);
    return 0;
}

VOID start_tpf2(HMODULE self)
{
    AcquireSRWLockExclusive(&lifecycle_lock);
    if (controller_thread != nullptr)
    {
        ReleaseSRWLockExclusive(&lifecycle_lock);
        return;
    }
    shutdown_event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (shutdown_event == nullptr)
    {
        ReleaseSRWLockExclusive(&lifecycle_lock);
        paths(self);
        write_status("DISABLED", "SHUTDOWN_EVENT_CREATE_FAILED");
        return;
    }
    InterlockedExchange(&controller_safe_to_unload, 0);
    HANDLE thread = CreateThread(nullptr, 0, initialize_tpf2, self, 0, nullptr);
    if (thread == nullptr)
    {
        CloseHandle(shutdown_event);
        shutdown_event = nullptr;
        ReleaseSRWLockExclusive(&lifecycle_lock);
        paths(self);
        write_status("DISABLED", "INITIALIZE_THREAD_CREATE_FAILED");
        return;
    }
    controller_thread = thread;
    ReleaseSRWLockExclusive(&lifecycle_lock);
}

extern "C" __declspec(dllexport) BOOL tpf2_controller_prepare_unload(DWORD timeout_ms)
{
    // Restore game-owned paths before removing the update hook that performs it.
    if (!prepare_train_motion_unload(timeout_ms ? timeout_ms : 15000))
        return FALSE;
    AcquireSRWLockShared(&lifecycle_lock);
    HANDLE event = shutdown_event;
    HANDLE thread = controller_thread;
    if (event == nullptr || thread == nullptr)
    {
        ReleaseSRWLockShared(&lifecycle_lock);
        return FALSE;
    }
    if (!SetEvent(event))
    {
        ReleaseSRWLockShared(&lifecycle_lock);
        return FALSE;
    }
    ReleaseSRWLockShared(&lifecycle_lock);

    const DWORD wait_result = WaitForSingleObject(thread, timeout_ms ? timeout_ms : 15000);
    if (wait_result != WAIT_OBJECT_0)
        return FALSE;

    AcquireSRWLockExclusive(&lifecycle_lock);
    if (controller_thread == thread)
    {
        CloseHandle(controller_thread);
        controller_thread = nullptr;
    }
    if (shutdown_event == event)
    {
        CloseHandle(shutdown_event);
        shutdown_event = nullptr;
    }
    ReleaseSRWLockExclusive(&lifecycle_lock);
    return InterlockedCompareExchange(&controller_safe_to_unload, 0, 0) != 0;
}
