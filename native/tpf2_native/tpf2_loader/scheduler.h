#pragma once

namespace tpf2::loader::scheduler {
bool initialize() noexcept;
bool consume_network_refresh() noexcept;
bool request_network_refresh() noexcept;
}
