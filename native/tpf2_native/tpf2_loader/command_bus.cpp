#include "pch.h"
#include "command_bus.h"
#include <cstring>

namespace {
using namespace tpf2::loader::commands;
SRWLOCK g_start_lock = SRWLOCK_INIT;
Block* g_block = nullptr;
HANDLE g_mapping = nullptr, g_reply = nullptr, g_mutex = nullptr;
// Lua states on other threads must never overwrite an in-flight payload.
thread_local struct Snapshot {
    std::uint64_t sequence = 0;
    std::size_t length = 0;
    char payload[kPayloadCapacity]{};
} g_snapshot;

bool supported(std::uint32_t opcode) noexcept
{
    switch (static_cast<Opcode>(opcode)) {
    case Opcode::Ping: case Opcode::GetControlState: case Opcode::GetGameState:
    case Opcode::GetTelemetry: case Opcode::SetLineStopPolicy: case Opcode::HoldTrain:
    case Opcode::ReleaseTrain: case Opcode::StopTrain: case Opcode::ResumeTrain: return true;
    default: return false;
    }
}
std::uint64_t unix_ms() noexcept
{
    FILETIME time{}; GetSystemTimeAsFileTime(&time);
    ULARGE_INTEGER value{}; value.LowPart = time.dwLowDateTime; value.HighPart = time.dwHighDateTime;
    return (value.QuadPart - 116444736000000000ULL) / 10000;
}
}

namespace tpf2::loader::commands {
bool initialize() noexcept
{
    AcquireSRWLockExclusive(&g_start_lock);
    if (g_block) { ReleaseSRWLockExclusive(&g_start_lock); return true; }
    HANDLE mapping = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE, 0,
        sizeof(Block), L"Local\\tpf2mcp_loader_cmd_v1");
    auto* block = mapping ? static_cast<Block*>(MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(Block))) : nullptr;
    HANDLE reply = CreateEventW(nullptr, FALSE, FALSE, L"Local\\tpf2mcp_loader_cmd_reply_v1");
    HANDLE mutex = CreateMutexW(nullptr, FALSE, L"Local\\tpf2mcp_loader_cmd_mutex_v1");
    if (!block || !reply || !mutex) {
        if (block) UnmapViewOfFile(block);
        if (mapping) CloseHandle(mapping);
        if (reply) CloseHandle(reply);
        if (mutex) CloseHandle(mutex);
        ReleaseSRWLockExclusive(&g_start_lock); return false;
    }
    // A new host/session must never execute bytes left by a previous process.
    std::memset(block, 0, sizeof(*block));
    block->header.version = kVersion; block->header.header_size = sizeof(Header);
    block->header.capacity = kPayloadCapacity; block->header.process_id = GetCurrentProcessId();
    MemoryBarrier(); block->header.magic = kMagic;
    g_mapping = mapping; g_reply = reply; g_mutex = mutex; g_block = block;
    ReleaseSRWLockExclusive(&g_start_lock); return true;
}

std::size_t poll(double (&values)[3]) noexcept
{
    if (!initialize() || g_snapshot.sequence) return 0;
    auto& header = g_block->header;
    if (InterlockedCompareExchange(&header.state, static_cast<LONG>(State::Taken),
                                  static_cast<LONG>(State::Ready)) != static_cast<LONG>(State::Ready)) return 0;
    MemoryBarrier();
    if (header.magic != kMagic || header.version != kVersion || header.header_size != sizeof(Header) ||
        header.capacity != kPayloadCapacity || header.process_id != GetCurrentProcessId() ||
        !header.sequence || header.sequence > 9007199254740991ULL ||
        !supported(header.opcode) || !header.payload_length || header.payload_length > kPayloadCapacity ||
        header.deadline_unix_ms < unix_ms()) {
        header.completed_sequence = header.sequence;
        InterlockedExchange(&header.state, static_cast<LONG>(State::Rejected));
        SetEvent(g_reply); return 0;
    }
    g_snapshot.sequence = header.sequence; g_snapshot.length = header.payload_length;
    std::memcpy(g_snapshot.payload, g_block->payload, g_snapshot.length);
    values[0] = header.opcode; values[1] = static_cast<double>(g_snapshot.length);
    values[2] = static_cast<double>(g_snapshot.sequence);
    return 3;
}

std::size_t read_words(std::size_t offset, double (&values)[8]) noexcept
{
    if (!g_snapshot.sequence || offset >= g_snapshot.length) return 0;
    // Six bytes fit exactly in a Lua 5.2 double. No Lua string allocation or
    // GC internals are needed across the game's private Lua ABI.
    for (std::size_t word = 0; word < 8; ++word) {
        std::uint64_t value = 0;
        for (std::size_t byte = 0; byte < 6; ++byte) {
            const auto index = offset + word * 6 + byte;
            if (index < g_snapshot.length)
                value |= static_cast<std::uint64_t>(static_cast<unsigned char>(g_snapshot.payload[index])) << (byte * 8);
        }
        values[word] = static_cast<double>(value);
    }
    return 8;
}

bool finish(std::uint64_t sequence) noexcept
{
    if (!g_block || !sequence || sequence != g_snapshot.sequence) return false;
    auto& header = g_block->header;
    const bool matches = header.sequence == sequence && header.state == static_cast<LONG>(State::Taken);
    g_snapshot.sequence = 0; g_snapshot.length = 0;
    if (!matches) return false;
    header.completed_sequence = sequence;
    InterlockedExchange(&header.state, static_cast<LONG>(State::Complete));
    SetEvent(g_reply); return true;
}
}
