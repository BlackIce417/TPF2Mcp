#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <wchar.h>

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
    LONG enabled;
    LONG consumed;
    uint32_t vehicle, station_group_id, station_index, terminal_index;
    int64_t expires_at;
} StationRule;

typedef struct
{
    LONG enabled;
    uint32_t source_line, target_line;
    int source_stop0, source_stop1, target_stop0, target_stop1, maximum;
    int entity_kind; /* 1 = person, 2 = cargo; cargo type still requires a verified reader. */
    volatile LONG successes;
    int64_t expires_at;
} RoutingRule;

typedef struct
{
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
extern float speed_hook_entry(void *, int, void *, int, int, float, void *, int, int);

static SpeedFn original_speed;
static StationFn original_station;
static CargoAssignFn original_cargo_assign;
static PersonAssignFn original_person_assign;
static PathCostFn original_path_cost;
static wchar_t config_path[MAX_PATH], status_path[MAX_PATH];
static volatile LONG loading;
static SRWLOCK rules_lock = SRWLOCK_INIT;
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
static ULONGLONG last_load;
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

static int readable(const void *p, SIZE_T size)
{
    MEMORY_BASIC_INFORMATION info;
    if (!p || !VirtualQuery(p, &info, sizeof(info)) || info.State != MEM_COMMIT || (info.Protect & (PAGE_NOACCESS | PAGE_GUARD)))
        return 0;
    return (const unsigned char *)p + size <= (const unsigned char *)info.BaseAddress + info.RegionSize;
}

static void write_status(const char *state, const char *detail)
{
    wchar_t tmp[MAX_PATH];
    _snwprintf(tmp, MAX_PATH, L"%ls.tmp", status_path);
    FILE *f = _wfopen(tmp, L"wb");
    if (!f)
        return;
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
}

static void paths(HMODULE self)
{
    wchar_t dll[MAX_PATH], *slash;
    GetModuleFileNameW(self, dll, MAX_PATH);
    slash = wcsrchr(dll, L'\\');
    if (slash)
        *slash = 0;
    _snwprintf(config_path, MAX_PATH, L"%ls\\..\\bridge\\native-control.ini", dll);
    _snwprintf(status_path, MAX_PATH, L"%ls\\..\\bridge\\native-control-status.json", dll);
}

static int64_t profile_i64(const wchar_t *section, const wchar_t *key)
{
    wchar_t value[64];
    GetPrivateProfileStringW(section, key, L"0", value, 64, config_path);
    return _wtoi64(value);
}

static float profile_float(const wchar_t *section, const wchar_t *key)
{
    wchar_t value[64];
    GetPrivateProfileStringW(section, key, L"0", value, 64, config_path);
    return (float)_wtof(value);
}

static void load_speed_rule(SpeedRule *rule, const wchar_t *section)
{
    wchar_t edges[32768];
    memset(rule, 0, sizeof(*rule));
    rule->vehicle = (uint32_t)GetPrivateProfileIntW(section, L"vehicle_id", 0, config_path);
    rule->speed_mps = profile_float(section, L"speed_mps");
    rule->hold = GetPrivateProfileIntW(section, L"hold", 0, config_path) != 0;
    rule->path_index_start = GetPrivateProfileIntW(section, L"path_index_start", -1, config_path);
    rule->path_index_end = GetPrivateProfileIntW(section, L"path_index_end", -1, config_path);
    rule->expires_at = profile_i64(section, L"expires_at");
    GetPrivateProfileStringW(section, L"edge_ids", L"", edges, 32768, config_path);
    wchar_t *context = NULL, *token = wcstok(edges, L",", &context);
    while (token && rule->edge_count < MAX_RULE_EDGES)
    {
        unsigned long value = wcstoul(token, NULL, 10);
        if (value)
            rule->edges[rule->edge_count++] = (uint32_t)value;
        token = wcstok(NULL, L",", &context);
    }
    rule->enabled = GetPrivateProfileIntW(section, L"enabled", 0, config_path) && rule->vehicle &&
                    (rule->speed_mps > 0 || rule->hold) && rule->speed_mps >= 0 && rule->edge_count > 0;
}

static void load_station_rule(StationRule *rule, const wchar_t *section)
{
    memset(rule, 0, sizeof(*rule));
    rule->vehicle = (uint32_t)GetPrivateProfileIntW(section, L"vehicle_id", 0, config_path);
    rule->station_group_id = (uint32_t)GetPrivateProfileIntW(section, L"station_group_id", 0, config_path);
    rule->station_index = (uint32_t)GetPrivateProfileIntW(section, L"station_index", -1, config_path);
    rule->terminal_index = (uint32_t)GetPrivateProfileIntW(section, L"terminal_index", -1, config_path);
    rule->expires_at = profile_i64(section, L"expires_at");
    rule->enabled = GetPrivateProfileIntW(section, L"enabled", 0, config_path) && rule->vehicle &&
                    rule->station_index != UINT32_MAX && rule->terminal_index != UINT32_MAX;
}

static void load_routing_rule(RoutingRule *rule, const wchar_t *section)
{
    memset(rule, 0, sizeof(*rule));
    rule->source_line = (uint32_t)GetPrivateProfileIntW(section, L"source_line", 0, config_path);
    rule->target_line = (uint32_t)GetPrivateProfileIntW(section, L"target_line", 0, config_path);
    rule->source_stop0 = GetPrivateProfileIntW(section, L"source_stop0", -1, config_path);
    rule->source_stop1 = GetPrivateProfileIntW(section, L"source_stop1", -1, config_path);
    rule->target_stop0 = GetPrivateProfileIntW(section, L"target_stop0", -1, config_path);
    rule->target_stop1 = GetPrivateProfileIntW(section, L"target_stop1", -1, config_path);
    rule->maximum = GetPrivateProfileIntW(section, L"max_assignments", 0, config_path);
    wchar_t entity_kind[16];
    GetPrivateProfileStringW(section, L"entity_kind", L"", entity_kind, 16, config_path);
    rule->entity_kind = _wcsicmp(entity_kind, L"PERSON") == 0 ? 1 : (_wcsicmp(entity_kind, L"CARGO") == 0 ? 2 : 0);
    rule->expires_at = profile_i64(section, L"expires_at");
    rule->enabled = GetPrivateProfileIntW(section, L"enabled", 0, config_path) && rule->source_line &&
                    rule->target_line && rule->entity_kind && rule->source_stop0 >= 0 && rule->source_stop1 >= 0 &&
                    rule->target_stop0 >= 0 && rule->target_stop1 >= 0 && rule->maximum > 0;
}

static void load_path_rule(PathRule *rule, const wchar_t *section)
{
    wchar_t edges[32768];
    memset(rule, 0, sizeof(*rule));
    rule->vehicle = (uint32_t)GetPrivateProfileIntW(section, L"vehicle_id", 0, config_path);
    rule->penalty_seconds = profile_float(section, L"penalty_seconds");
    rule->expires_at = profile_i64(section, L"expires_at");
    GetPrivateProfileStringW(section, L"edge_ids", L"", edges, 32768, config_path);
    wchar_t *context = NULL, *token = wcstok(edges, L",", &context);
    while (token && rule->edge_count < MAX_RULE_EDGES)
    {
        unsigned long value = wcstoul(token, NULL, 10);
        if (value)
            rule->edges[rule->edge_count++] = (uint32_t)value;
        token = wcstok(NULL, L",", &context);
    }
    rule->enabled = GetPrivateProfileIntW(section, L"enabled", 0, config_path) && rule->vehicle &&
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
    ULONGLONG now = GetTickCount64();
    if (now - last_load < 500 || InterlockedCompareExchange(&loading, 1, 0) != 0)
        return;
    last_load = now;
    LONG generation = GetPrivateProfileIntW(L"meta", L"generation", 0, config_path);
    if (generation && generation == config_generation)
    {
        InterlockedExchange(&loading, 0);
        return;
    }
    int speed_count = GetPrivateProfileIntW(L"meta", L"speed_count", -1, config_path);
    int station_count = GetPrivateProfileIntW(L"meta", L"station_count", -1, config_path);
    int routing_count = GetPrivateProfileIntW(L"meta", L"routing_count", -1, config_path);
    int path_count = GetPrivateProfileIntW(L"meta", L"path_count", -1, config_path);
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
            _snwprintf(section, 32, L"speed_%d", i);
            load_speed_rule(&pending_speed_rules[i], section);
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
            _snwprintf(section, 32, L"station_%d", i);
            load_station_rule(&pending_station_rules[i], section);
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
            _snwprintf(section, 32, L"routing_%d", i);
            load_routing_rule(&pending_routing_rules[i], section);
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
            _snwprintf(section, 32, L"path_%d", i);
            load_path_rule(&pending_path_rules[i], section);
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
    load_config();
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
    load_config();
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
    load_config();
    StationRule selected;
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
    float native_cost = original_path_cost(expander, path_vector, first, last);
    load_config();
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

static int install_detour(unsigned char *target, const unsigned char *expected, SIZE_T length,
                          void *hook, void **original, const char *failure)
{
    if (memcmp(target, expected, length) != 0)
    {
        write_status("DISABLED", failure);
        return 0;
    }
    unsigned char *trampoline = VirtualAlloc(NULL, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!trampoline)
    {
        write_status("DISABLED", "TRAMPOLINE_ALLOC_FAILED");
        return 0;
    }
    memcpy(trampoline, target, length);
    trampoline[length] = 0xFF;
    trampoline[length + 1] = 0x25;
    *(uint32_t *)(trampoline + length + 2) = 0;
    *(uint64_t *)(trampoline + length + 6) = (uint64_t)(target + length);
    *original = trampoline;
    DWORD old;
    if (!VirtualProtect(target, length, PAGE_EXECUTE_READWRITE, &old))
        return 0;
    target[0] = 0xFF;
    target[1] = 0x25;
    *(uint32_t *)(target + 2) = 0;
    *(uint64_t *)(target + 6) = (uint64_t)hook;
    for (SIZE_T i = 14; i < length; ++i)
        target[i] = 0x90;
    FlushInstructionCache(GetCurrentProcess(), target, length);
    VirtualProtect(target, length, old, &old);
    return 1;
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

float speed_hook_c(void *engine, int component, void *path_vector, int first, int last,
                   float factor, void *network, int filter0, int filter1, uint64_t vehicle_pointer)
{
    float native_limit = original_speed(engine, component, path_vector, first, last, factor, network, filter0, filter1);
    load_config();
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

static int install_hook(void)
{
    static const unsigned char expected[15] = {0x48, 0x8b, 0xc4, 0x55, 0x41, 0x54, 0x41, 0x55, 0x48, 0x81, 0xec, 0x80, 0x00, 0x00, 0x00};
    unsigned char *base = (unsigned char *)GetModuleHandleW(NULL);
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(base + dos->e_lfanew);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || nt->Signature != IMAGE_NT_SIGNATURE || nt->OptionalHeader.SizeOfImage <= PATH_COST_RVA)
    {
        write_status("DISABLED", "PE_IDENTITY_MISMATCH");
        return 0;
    }
    static const unsigned char station_expected[18] = {0x40, 0x55, 0x53, 0x56, 0x57, 0x41, 0x54, 0x41, 0x55, 0x41, 0x56, 0x41, 0x57, 0x48, 0x8d, 0x6c, 0x24, 0xe8};
    unsigned char *target = base + SPEED_RVA;
    if (!install_detour(target, expected, 15, (void *)&speed_hook_entry, (void **)&original_speed,
                        "SPEED_SIGNATURE_MISMATCH"))
        return 0;
    static const unsigned char path_cost_expected[16] = {0x41, 0x56, 0x41, 0x57, 0x48, 0x83, 0xec, 0x38, 0xf3, 0x0f, 0x10, 0x41, 0x74, 0x4c, 0x8b, 0xfa};
    if (!install_detour(base + PATH_COST_RVA, path_cost_expected, 16, (void *)&path_cost_hook,
                        (void **)&original_path_cost, "PATH_COST_SIGNATURE_MISMATCH"))
        return 0;
    if (!install_detour(base + STATION_RVA, station_expected, 18, (void *)&station_hook_c, (void **)&original_station,
                        "STATION_SIGNATURE_MISMATCH"))
        return 0;
    static const unsigned char cargo_expected[14] = {0x48, 0x89, 0x5c, 0x24, 0x10, 0x55, 0x56, 0x57, 0x41, 0x54, 0x41, 0x55, 0x41, 0x56};
    static const unsigned char person_expected[15] = {0x48, 0x8b, 0xc4, 0x55, 0x53, 0x56, 0x57, 0x41, 0x54, 0x41, 0x55, 0x41, 0x56, 0x41, 0x57};
    if (!install_detour(base + CARGO_ASSIGN_RVA, cargo_expected, 14, (void *)&cargo_assign_hook,
                        (void **)&original_cargo_assign, "CARGO_ASSIGN_SIGNATURE_MISMATCH"))
        return 0;
    if (!install_detour(base + PERSON_ASSIGN_RVA, person_expected, 15, (void *)&person_assign_hook,
                        (void **)&original_person_assign, "PERSON_ASSIGN_SIGNATURE_MISMATCH"))
        return 0;
    write_status("ACTIVE", "VERSION_LOCKED_STATION_AND_PATH_CONTROL_HOOKS");
    return 1;
}

static DWORD WINAPI initialize(LPVOID self)
{
    paths((HMODULE)self);
    path_vehicle_tls = TlsAlloc();
    if (path_vehicle_tls == TLS_OUT_OF_INDEXES)
    {
        write_status("DISABLED", "PATH_TLS_ALLOC_FAILED");
        return 0;
    }
    load_config();
    install_hook();
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH)
    {
        DisableThreadLibraryCalls(instance);
        CreateThread(NULL, 0, initialize, instance, 0, NULL);
    }
    else if (reason == DLL_PROCESS_DETACH && path_vehicle_tls != TLS_OUT_OF_INDEXES)
        TlsFree(path_vehicle_tls);
    return TRUE;
}
