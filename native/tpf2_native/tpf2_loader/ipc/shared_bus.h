#pragma once

#include <cstddef>
#include <cstdint>

namespace tpf2::loader::shared_bus {
bool initialize() noexcept;
bool publish(const char* key, std::size_t key_size, const char* json, std::size_t json_size) noexcept;
// Returns required bytes; copies only a changed, complete value under the bus lock.
std::size_t copy(const char* key, char* output, std::size_t capacity, std::uint64_t* revision) noexcept;
}
