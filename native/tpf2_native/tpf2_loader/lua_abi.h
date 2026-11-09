#pragma once

#include <cstddef>

struct lua_State;

namespace tpf2::loader::lua_abi {
bool string_argument(lua_State* state, int index, const char*& data, std::size_t& size) noexcept;
bool number_argument(lua_State* state, int index, double& value) noexcept;
int return_boolean(lua_State* state, bool value) noexcept;
}
