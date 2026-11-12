#pragma once
#include <Windows.h>
#include <cstdint>
#include <cstring>
#include <string>

// Read-only consumer of Loader bus ABI v1. The Engine/System objects are COW
// snapshots and their addresses are NOT save identifiers. Read the simulation
// collector's session, not heartbeat.json: GUI load callbacks can publish their
// own LOADING heartbeats repeatedly and do not identify the simulation world.
namespace train_motion
{
inline uint64_t session_hash(const std::string& json)
{
    int depth = 0;
    for (size_t i = 0; i < json.size(); ++i)
    {
        char c = json[i];
        if (c == '{' || c == '[') ++depth;
        else if (c == '}' || c == ']') --depth;
        else if (c == '"')
        {
            size_t begin = ++i;
            for (; i < json.size() && json[i] != '"'; ++i)
                if (json[i] == '\\') ++i;
            if (i >= json.size()) return 0;
            if (depth != 1 || json.compare(begin, i - begin, "session_id")) continue;
            size_t value = json.find_first_not_of(" \t\r\n", i + 1);
            if (value == std::string::npos || json[value] != ':') continue;
            value = json.find_first_not_of(" \t\r\n", value + 1);
            if (value == std::string::npos || json[value++] != '"') return 0;
            uint64_t hash = 14695981039346656037ULL;
            size_t count = 0;
            for (; value < json.size() && json[value] != '"'; ++value)
            {
                // Runtime session identifiers are ASCII timestamps/table IDs.
                if (json[value] == '\\' || ++count > 160) return 0;
                hash = (hash ^ static_cast<unsigned char>(json[value])) * 1099511628211ULL;
            }
            return count && value < json.size() ? hash : 0;
        }
    }
    return 0;
}

class LoaderSession
{
    struct Entry { char key[96]; wchar_t name[128]; uint32_t capacity, generation; uint64_t publishes; };
    struct Control { uint32_t magic, version, pid, count; volatile LONG64 sequence; Entry entries[64]; };
    struct Header { uint32_t magic, version, capacity; volatile LONG active; volatile LONG64 sequence[2];
                    uint32_t length[2], reserved[2]; uint64_t timestamps[2]; };
    static_assert(sizeof(Entry) == 368 && sizeof(Control) == 23576 && sizeof(Header) == 64);
    HANDLE control_handle_{}, value_handle_{};
    const Control* control_{};
    const Header* value_{};
    Entry descriptor_{};
    uint64_t session_{};
    LONG64 sequence_ = -1;
    LONG buffer_ = -1;

    void close_value()
    {
        if (value_) UnmapViewOfFile(value_);
        if (value_handle_) CloseHandle(value_handle_);
        value_ = nullptr; value_handle_ = nullptr;
        sequence_ = -1; buffer_ = -1;
    }
public:
    ~LoaderSession()
    {
        close_value();
        if (control_) UnmapViewOfFile(control_);
        if (control_handle_) CloseHandle(control_handle_);
    }
    uint64_t read()
    {
        if (!control_)
        {
            control_handle_ = OpenFileMappingW(FILE_MAP_READ, FALSE, L"Local\\tpf2mcp_lua_bus_control_v1");
            if (!control_handle_) return 0;
            control_ = static_cast<const Control*>(MapViewOfFile(control_handle_, FILE_MAP_READ, 0, 0, sizeof(Control)));
            if (!control_) { CloseHandle(control_handle_); control_handle_ = nullptr; return 0; }
        }
        if (control_->magic != 0x42504654 || control_->version != 1 || control_->pid != GetCurrentProcessId()) return 0;
        Entry descriptor{};
        bool found = false;
        for (int attempt = 0; attempt < 8 && !found; ++attempt)
        {
            LONG64 sequence = control_->sequence;
            if (sequence & 1) continue;
            MemoryBarrier();
            uint32_t count = control_->count;
            if (count > 64) return 0;
            for (uint32_t i = 0; i < count; ++i)
            {
                constexpr char key[] = "operational-telemetry-train_footprints.json";
                if (!memcmp(control_->entries[i].key, key, sizeof(key)))
                { memcpy(&descriptor, &control_->entries[i], sizeof(Entry)); found = true; break; }
            }
            MemoryBarrier();
            if (control_->sequence != sequence) found = false;
        }
        if (!found) return session_; // Brief contention with an unrelated channel.
        if (descriptor.capacity < 4096 || descriptor.capacity > 16 * 1024 * 1024 || descriptor.name[127]) return 0;
        if (!value_ || descriptor.generation != descriptor_.generation || wcscmp(descriptor.name, descriptor_.name))
        {
            close_value(); descriptor_ = descriptor;
            value_handle_ = OpenFileMappingW(FILE_MAP_READ, FALSE, descriptor.name);
            if (!value_handle_) return 0;
            value_ = static_cast<const Header*>(MapViewOfFile(value_handle_, FILE_MAP_READ, 0, 0,
                sizeof(Header) + 2ULL * descriptor.capacity));
            if (!value_) { close_value(); return 0; }
        }
        for (int attempt = 0; attempt < 8; ++attempt)
        {
            if (value_->magic != 0x56504654 || value_->version != 1 || value_->capacity != descriptor.capacity) return 0;
            LONG active = value_->active;
            if (active < 0 || active > 1) continue;
            LONG64 sequence = value_->sequence[active];
            if (sequence & 1) continue;
            MemoryBarrier();
            if (sequence == sequence_ && active == buffer_) return session_;
            uint32_t length = value_->length[active];
            if (!length || length > descriptor.capacity) return 0;
            auto data = reinterpret_cast<const char*>(value_ + 1) + static_cast<size_t>(active) * descriptor.capacity;
            std::string json(data, length);
            MemoryBarrier();
            if (value_->active == active && value_->sequence[active] == sequence)
            {
                uint64_t session = session_hash(json);
                if (!session) return 0;
                session_ = session; sequence_ = sequence; buffer_ = active;
                return session_;
            }
        }
        return session_;
    }
};
}
