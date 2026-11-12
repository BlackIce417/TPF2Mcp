#pragma once
#include <cstddef>
#include <cstdint>

namespace tpf2::loader::commands {
constexpr std::uint32_t kMagic = 0x434c4654; // TFLC
constexpr std::uint32_t kVersion = 1;
constexpr std::size_t kPayloadCapacity = 16384;
enum class State : LONG { Idle, Ready, Taken, Complete, Rejected, Cancelled };
enum class Opcode : std::uint32_t {
    Ping = 1, GetControlState = 2, GetGameState = 3, GetTelemetry = 4,
    SetLineStopPolicy = 0x101, HoldTrain = 0x102, ReleaseTrain = 0x103,
    StopTrain = 0x104, ResumeTrain = 0x105,
};
struct alignas(8) Header {
    std::uint32_t magic, version, header_size, capacity, process_id;
    volatile LONG state;
    std::uint32_t opcode, payload_length;
    std::uint64_t sequence, deadline_unix_ms, completed_sequence, reserved;
};
static_assert(sizeof(Header) == 64);
static_assert(offsetof(Header, state) == 20);
static_assert(offsetof(Header, sequence) == 32);
struct Block { Header header; char payload[kPayloadCapacity]; };
static_assert(sizeof(Block) == 64 + kPayloadCapacity);

bool initialize() noexcept;
// Called only from a game Lua callback; never calls Lua from a worker thread.
std::size_t poll(double (&values)[3]) noexcept;
std::size_t read_words(std::size_t offset, double (&values)[8]) noexcept;
bool finish(std::uint64_t sequence) noexcept;
}
