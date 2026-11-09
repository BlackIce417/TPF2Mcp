#pragma once

#include <cstddef>

namespace tpf2::loader::shared_bus {
bool initialize() noexcept;
bool publish(const char* key, std::size_t key_size, const char* json, std::size_t json_size) noexcept;
}
