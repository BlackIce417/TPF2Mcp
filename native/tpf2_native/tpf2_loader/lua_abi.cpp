#include "pch.h"
#include "lua_abi.h"

#include <cstdint>

namespace {
// Transport Fever 2 embeds 64-bit Lua 5.2.  The game does not export lua_*;
// package.loadlib still calls our C functions with the ordinary Lua ABI.
struct TValue {
    union { void* gc; double number; int boolean; } value;
    int type;
    int padding;
};

struct CallInfoPrefix { TValue* function; TValue* top; };
struct LuaStatePrefix {
    void* next;
    std::uint8_t type;
    std::uint8_t marked;
    std::uint8_t status;
    std::uint8_t padding[5];
    TValue* top;
    void* global;
    CallInfoPrefix* call_info;
};

constexpr int kLuaTypeBoolean = 1;
constexpr int kLuaTypeNumber = 3;
constexpr int kLuaTypeString = 4;

bool readable(const void* pointer, std::size_t bytes) noexcept
{
    if (pointer == nullptr || bytes == 0) return false;
    MEMORY_BASIC_INFORMATION information{};
    if (VirtualQuery(pointer, &information, sizeof(information)) != sizeof(information)) return false;
    if (information.State != MEM_COMMIT || (information.Protect & (PAGE_NOACCESS | PAGE_GUARD)) != 0) return false;
    const auto begin = reinterpret_cast<std::uintptr_t>(pointer);
    const auto end = begin + bytes;
    const auto region_end = reinterpret_cast<std::uintptr_t>(information.BaseAddress) + information.RegionSize;
    return end >= begin && end <= region_end;
}

TValue* argument(lua_State* state, int index) noexcept
{
    if (state == nullptr || index < 1) return nullptr;
    auto* raw = reinterpret_cast<LuaStatePrefix*>(state);
    if (!readable(raw, sizeof(*raw)) || !readable(raw->call_info, sizeof(CallInfoPrefix))) return nullptr;
    TValue* value = raw->call_info->function + index;
    if (value >= raw->top || !readable(value, sizeof(*value))) return nullptr;
    return value;
}
}

namespace tpf2::loader::lua_abi {

bool string_argument(lua_State* state, int index, const char*& data, std::size_t& size) noexcept
{
    data = nullptr;
    size = 0;
    TValue* value = argument(state, index);
    if (value == nullptr || (value->type & 0x0f) != kLuaTypeString || !readable(value->value.gc, 24)) return false;
    auto* bytes = static_cast<const std::uint8_t*>(value->value.gc);
    const auto length = *reinterpret_cast<const std::size_t*>(bytes + 16);
    const char* characters = reinterpret_cast<const char*>(bytes + 24);
    if (length > 16u * 1024u * 1024u || !readable(characters, length + 1)) return false;
    data = characters;
    size = length;
    return true;
}

bool number_argument(lua_State* state, int index, double& result) noexcept
{
    TValue* value = argument(state, index);
    if (value == nullptr || (value->type & 0x0f) != kLuaTypeNumber) return false;
    result = value->value.number;
    return result == result;
}

int return_numbers(lua_State* state, const double* values, std::size_t count) noexcept
{
    if (!state || !values || !count || count > 8) return 0;
    auto* raw = reinterpret_cast<LuaStatePrefix*>(state);
    if (!readable(raw, sizeof(*raw)) || !readable(raw->call_info, sizeof(CallInfoPrefix)) ||
        raw->top > raw->call_info->top || static_cast<std::size_t>(raw->call_info->top - raw->top) < count ||
        !readable(raw->top, sizeof(TValue) * count)) return 0;
    for (std::size_t i = 0; i < count; ++i) {
        raw->top->value.number = values[i]; raw->top->type = kLuaTypeNumber; raw->top->padding = 0;
        ++raw->top;
    }
    return static_cast<int>(count);
}

int return_boolean(lua_State* state, bool result) noexcept
{
    if (state == nullptr) return 0;
    auto* raw = reinterpret_cast<LuaStatePrefix*>(state);
    if (!readable(raw, sizeof(*raw)) || !readable(raw->call_info, sizeof(CallInfoPrefix)) ||
        raw->top >= raw->call_info->top || !readable(raw->top, sizeof(TValue))) return 0;
    raw->top->value.boolean = result ? 1 : 0;
    raw->top->type = kLuaTypeBoolean;
    raw->top->padding = 0;
    ++raw->top;
    return 1;
}

}
