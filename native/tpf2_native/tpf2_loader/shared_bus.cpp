#include "pch.h"
#include "shared_bus.h"

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

namespace {
constexpr std::uint32_t kControlMagic = 0x42504654; // TFPB
constexpr std::uint32_t kValueMagic = 0x56504654;   // TFPV
constexpr std::uint32_t kAbiVersion = 1;
constexpr std::size_t kMaximumKeys = 64;
constexpr std::size_t kMaximumPayload = 16u * 1024u * 1024u;
constexpr wchar_t kControlName[] = L"Local\\tpf2mcp_lua_bus_control_v1";
constexpr wchar_t kDataEventName[] = L"Local\\tpf2mcp_lua_bus_data_event_v1";

struct ControlEntry {
    char key[96];
    wchar_t mapping_name[128];
    std::uint32_t capacity;
    std::uint32_t generation;
    std::uint64_t publish_count;
};

struct ControlBlock {
    std::uint32_t magic;
    std::uint32_t abi_version;
    std::uint32_t process_id;
    std::uint32_t entry_count;
    volatile LONG64 sequence;
    ControlEntry entries[kMaximumKeys];
};

struct ValueHeader {
    std::uint32_t magic;
    std::uint32_t abi_version;
    std::uint32_t capacity;
    volatile LONG active_buffer;
    volatile LONG64 sequence[2];
    std::uint32_t length[2];
    std::uint32_t reserved[2];
    std::uint64_t timestamp_qpc[2];
};

struct Channel {
    std::string key;
    std::uint32_t generation = 0;
    std::uint32_t capacity = 0;
    HANDLE mapping = nullptr;
    ValueHeader* view = nullptr;
    ~Channel() { if (view) UnmapViewOfFile(view); if (mapping) CloseHandle(mapping); }
};

SRWLOCK g_lock = SRWLOCK_INIT;
HANDLE g_control_mapping = nullptr;
ControlBlock* g_control = nullptr;
HANDLE g_data_event = nullptr;
std::vector<std::unique_ptr<Channel>> g_channels;

std::uint64_t hash_key(const char* data, std::size_t size) noexcept
{
    std::uint64_t value = 1469598103934665603ull;
    for (std::size_t index = 0; index < size; ++index) value = (value ^ static_cast<unsigned char>(data[index])) * 1099511628211ull;
    return value;
}

std::uint32_t capacity_for(std::size_t size) noexcept
{
    std::uint32_t capacity = 4096;
    while (capacity < size && capacity < kMaximumPayload) capacity <<= 1;
    return capacity;
}

void begin_control_write() noexcept { InterlockedIncrement64(&g_control->sequence); MemoryBarrier(); }
void finish_control_write() noexcept { MemoryBarrier(); InterlockedIncrement64(&g_control->sequence); }

bool replace_mapping(Channel& channel, std::uint32_t capacity, std::size_t entry_index) noexcept
{
    const auto generation = channel.generation + 1;
    wchar_t name[128]{};
    swprintf_s(name, L"Local\\tpf2mcp_lua_value_%lu_%016llx_%lu", GetCurrentProcessId(),
        static_cast<unsigned long long>(hash_key(channel.key.data(), channel.key.size())), generation);
    const std::uint64_t total = sizeof(ValueHeader) + static_cast<std::uint64_t>(capacity) * 2;
    HANDLE mapping = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE,
        static_cast<DWORD>(total >> 32), static_cast<DWORD>(total), name);
    if (mapping == nullptr) return false;
    auto* view = static_cast<ValueHeader*>(MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, static_cast<SIZE_T>(total)));
    if (view == nullptr) { CloseHandle(mapping); return false; }
    std::memset(view, 0, static_cast<std::size_t>(total));
    view->magic = kValueMagic;
    view->abi_version = kAbiVersion;
    view->capacity = capacity;

    if (channel.view) UnmapViewOfFile(channel.view);
    if (channel.mapping) CloseHandle(channel.mapping);
    channel.mapping = mapping;
    channel.view = view;
    channel.capacity = capacity;
    channel.generation = generation;

    begin_control_write();
    auto& descriptor = g_control->entries[entry_index];
    std::memset(&descriptor, 0, sizeof(descriptor));
    memcpy_s(descriptor.key, sizeof(descriptor.key), channel.key.data(), (std::min)(channel.key.size(), sizeof(descriptor.key) - 1));
    wcsncpy_s(descriptor.mapping_name, name, _TRUNCATE);
    descriptor.capacity = capacity;
    descriptor.generation = generation;
    finish_control_write();
    return true;
}
}

namespace tpf2::loader::shared_bus {

bool initialize() noexcept
{
    AcquireSRWLockExclusive(&g_lock);
    if (g_control != nullptr) { ReleaseSRWLockExclusive(&g_lock); return true; }
    g_control_mapping = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE, 0,
        static_cast<DWORD>(sizeof(ControlBlock)), kControlName);
    if (g_control_mapping != nullptr) {
        g_control = static_cast<ControlBlock*>(MapViewOfFile(g_control_mapping, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(ControlBlock)));
    }
    g_data_event = CreateEventW(nullptr, FALSE, FALSE, kDataEventName);
    if (g_control == nullptr || g_data_event == nullptr) {
        if (g_control) UnmapViewOfFile(g_control);
        if (g_control_mapping) CloseHandle(g_control_mapping);
        if (g_data_event) CloseHandle(g_data_event);
        g_control = nullptr; g_control_mapping = nullptr; g_data_event = nullptr;
        ReleaseSRWLockExclusive(&g_lock);
        return false;
    }
    std::memset(g_control, 0, sizeof(*g_control));
    g_control->magic = kControlMagic;
    g_control->abi_version = kAbiVersion;
    g_control->process_id = GetCurrentProcessId();
    ReleaseSRWLockExclusive(&g_lock);
    return true;
}

bool publish(const char* key, std::size_t key_size, const char* json, std::size_t json_size) noexcept
{
    if (key == nullptr || key_size == 0 || key_size >= 96 || json == nullptr ||
        json_size == 0 || json_size > kMaximumPayload || !initialize()) return false;
    AcquireSRWLockExclusive(&g_lock);
    Channel* channel = nullptr;
    std::size_t entry_index = 0;
    for (std::size_t index = 0; index < g_channels.size(); ++index) {
        if (g_channels[index]->key.size() == key_size && std::memcmp(g_channels[index]->key.data(), key, key_size) == 0) {
            channel = g_channels[index].get(); entry_index = index; break;
        }
    }
    if (channel == nullptr) {
        if (g_channels.size() >= kMaximumKeys) { ReleaseSRWLockExclusive(&g_lock); return false; }
        auto created = std::make_unique<Channel>();
        created->key.assign(key, key_size);
        channel = created.get();
        entry_index = g_channels.size();
        g_channels.push_back(std::move(created));
        begin_control_write();
        g_control->entry_count = static_cast<std::uint32_t>(g_channels.size());
        finish_control_write();
    }
    if (channel->capacity < json_size && !replace_mapping(*channel, capacity_for(json_size), entry_index)) {
        ReleaseSRWLockExclusive(&g_lock); return false;
    }
    const LONG target = 1 - InterlockedCompareExchange(&channel->view->active_buffer, 0, 0);
    InterlockedIncrement64(&channel->view->sequence[target]);
    MemoryBarrier();
    auto* data = reinterpret_cast<char*>(channel->view + 1) + static_cast<std::size_t>(target) * channel->capacity;
    std::memcpy(data, json, json_size);
    channel->view->length[target] = static_cast<std::uint32_t>(json_size);
    LARGE_INTEGER stamp{}; QueryPerformanceCounter(&stamp);
    channel->view->timestamp_qpc[target] = static_cast<std::uint64_t>(stamp.QuadPart);
    MemoryBarrier();
    InterlockedExchange(&channel->view->active_buffer, target);
    InterlockedIncrement64(&channel->view->sequence[target]);
    begin_control_write();
    ++g_control->entries[entry_index].publish_count;
    finish_control_write();
    SetEvent(g_data_event);
    ReleaseSRWLockExclusive(&g_lock);
    return true;
}

}
