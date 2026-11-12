#pragma once
#include <Windows.h>
#include "../lua/loader_api.h"

namespace tpf2::loader {
void set_module(HMODULE module) noexcept;
bool pin_module() noexcept;
bool start_lifecycle_listener() noexcept;
Tpf2LoaderResult start_controller() noexcept;
Tpf2LoaderResult reload_controller() noexcept;
Tpf2LoaderState state() noexcept;
DWORD last_error() noexcept;
}
