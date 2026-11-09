#include "pch.h"
#include "loader_runtime.h"

#include <atomic>
#include <filesystem>
#include <string>

namespace {
constexpr wchar_t kGameModule[] = L"TransportFever2.exe";
constexpr wchar_t kReloadEventName[] = L"Local\\tpf2mcp_loader_hotreload_v1";
constexpr wchar_t kReloadCompleteEventName[] = L"Local\\tpf2mcp_loader_hotreload_complete_v1";
constexpr DWORD kControllerShutdownTimeoutMs = 15000;

using ControllerPrepareUnload = BOOL(WINAPI *)(DWORD);

HMODULE g_loader_module = nullptr;
HMODULE g_controller_module = nullptr;
std::filesystem::path g_controller_path;
bool g_owns_controller_reference = false;
HANDLE g_reload_event = nullptr;
HANDLE g_reload_complete_event = nullptr;
SRWLOCK g_lock = SRWLOCK_INIT;
std::atomic<Tpf2LoaderState> g_state{Tpf2LoaderState::Idle};
std::atomic<DWORD> g_last_error{ERROR_SUCCESS};
std::atomic_bool g_module_pinned{false};
std::atomic_bool g_listener_started{false};

void remember_error(DWORD value) noexcept
{
    g_last_error.store(value, std::memory_order_release);
}

std::filesystem::path module_path(HMODULE module)
{
    std::wstring buffer(32768, L'\0');
    const DWORD length = GetModuleFileNameW(module, buffer.data(), static_cast<DWORD>(buffer.size()));
    if (length == 0 || length >= buffer.size()) {
        remember_error(length == 0 ? GetLastError() : ERROR_INSUFFICIENT_BUFFER);
        return {};
    }
    buffer.resize(length);
    return std::filesystem::path(buffer);
}

std::filesystem::path module_directory(HMODULE module)
{
    const auto path = module_path(module);
    return path.empty() ? std::filesystem::path{} : path.parent_path();
}

HMODULE find_loaded_controller() noexcept
{
    for (const wchar_t* name : {L"tpf2_control.dll", L"tpf2_controller.dll"}) {
        if (HMODULE module = GetModuleHandleW(name); module != nullptr) return module;
    }
    return nullptr;
}

std::filesystem::path find_controller_file()
{
    const std::filesystem::path directory = module_directory(g_loader_module);
    if (directory.empty()) return {};
    for (const wchar_t* name : {L"tpf2_control.dll", L"tpf2_controller.dll"}) {
        std::error_code error;
        const auto candidate = directory / name;
        if (std::filesystem::is_regular_file(candidate, error) && !error) return candidate;
    }
    remember_error(ERROR_FILE_NOT_FOUND);
    return {};
}

std::filesystem::path staged_controller_file(const std::filesystem::path& controller)
{
    return controller.parent_path() /
        (controller.stem().wstring() + L".next" + controller.extension().wstring());
}

Tpf2LoaderResult load_controller_locked(const std::filesystem::path& controller) noexcept
{
    HMODULE loaded = LoadLibraryExW(controller.c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (loaded == nullptr) {
        remember_error(GetLastError());
        g_state.store(Tpf2LoaderState::Error, std::memory_order_release);
        return Tpf2LoaderResult::LoadFailed;
    }
    g_controller_module = loaded;
    g_controller_path = controller;
    g_owns_controller_reference = true;
    remember_error(ERROR_SUCCESS);
    g_state.store(Tpf2LoaderState::ControllerOwned, std::memory_order_release);
    return Tpf2LoaderResult::Ok;
}

DWORD WINAPI lifecycle_listener(LPVOID)
{
    for (;;) {
        const DWORD wait = WaitForSingleObject(g_reload_event, INFINITE);
        if (wait != WAIT_OBJECT_0) {
            remember_error(GetLastError());
            g_state.store(Tpf2LoaderState::Error, std::memory_order_release);
            return 0;
        }
        tpf2::loader::reload_controller();
        if (g_reload_complete_event) SetEvent(g_reload_complete_event);
    }
}
} // namespace

namespace tpf2::loader {

void set_module(HMODULE module) noexcept
{
    g_loader_module = module;
}

bool pin_module() noexcept
{
    if (g_module_pinned.load(std::memory_order_acquire)) return true;

    HMODULE pinned = nullptr;
    if (!GetModuleHandleExW(
            GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
            reinterpret_cast<LPCWSTR>(&pin_module),
            &pinned)) {
        remember_error(GetLastError());
        return false;
    }

    g_module_pinned.store(true, std::memory_order_release);
    return true;
}

bool start_lifecycle_listener() noexcept
{
    bool expected = false;
    if (!g_listener_started.compare_exchange_strong(expected, true, std::memory_order_acq_rel))
        return true;

    g_reload_event = CreateEventW(nullptr, FALSE, FALSE, kReloadEventName);
    g_reload_complete_event = CreateEventW(nullptr, FALSE, FALSE, kReloadCompleteEventName);
    if (g_reload_event == nullptr || g_reload_complete_event == nullptr) {
        remember_error(GetLastError());
        if (g_reload_event) CloseHandle(g_reload_event);
        if (g_reload_complete_event) CloseHandle(g_reload_complete_event);
        g_reload_event = nullptr;
        g_reload_complete_event = nullptr;
        g_listener_started.store(false, std::memory_order_release);
        g_state.store(Tpf2LoaderState::Error, std::memory_order_release);
        return false;
    }
    HANDLE thread = CreateThread(nullptr, 0, lifecycle_listener, nullptr, 0, nullptr);
    if (thread == nullptr) {
        remember_error(GetLastError());
        CloseHandle(g_reload_event);
        CloseHandle(g_reload_complete_event);
        g_reload_event = nullptr;
        g_reload_complete_event = nullptr;
        g_listener_started.store(false, std::memory_order_release);
        g_state.store(Tpf2LoaderState::Error, std::memory_order_release);
        return false;
    }
    CloseHandle(thread);
    return true;
}

Tpf2LoaderResult start_controller() noexcept
{
    AcquireSRWLockExclusive(&g_lock);
    if (GetModuleHandleW(kGameModule) == nullptr) {
        remember_error(ERROR_BAD_ENVIRONMENT);
        g_state.store(Tpf2LoaderState::Error, std::memory_order_release);
        ReleaseSRWLockExclusive(&g_lock);
        return Tpf2LoaderResult::InvalidHostProcess;
    }
    if (g_controller_module != nullptr) {
        ReleaseSRWLockExclusive(&g_lock);
        return Tpf2LoaderResult::AlreadyLoaded;
    }
    if (HMODULE existing = find_loaded_controller(); existing != nullptr) {
        g_controller_module = existing;
        g_controller_path = module_path(existing);
        g_owns_controller_reference = false;
        remember_error(ERROR_SUCCESS);
        g_state.store(Tpf2LoaderState::ControllerBorrowed, std::memory_order_release);
        ReleaseSRWLockExclusive(&g_lock);
        return Tpf2LoaderResult::AlreadyLoaded;
    }
    const std::filesystem::path controller = find_controller_file();
    if (controller.empty()) {
        g_state.store(Tpf2LoaderState::Error, std::memory_order_release);
        ReleaseSRWLockExclusive(&g_lock);
        return Tpf2LoaderResult::ControllerNotFound;
    }
    const Tpf2LoaderResult result = load_controller_locked(controller);
    ReleaseSRWLockExclusive(&g_lock);
    return result;
}

Tpf2LoaderResult reload_controller() noexcept
{
    AcquireSRWLockExclusive(&g_lock);
    if (g_controller_module == nullptr) {
        ReleaseSRWLockExclusive(&g_lock);
        return start_controller();
    }
    if (!g_owns_controller_reference) {
        remember_error(ERROR_INVALID_HANDLE);
        g_state.store(Tpf2LoaderState::ControllerBorrowed, std::memory_order_release);
        ReleaseSRWLockExclusive(&g_lock);
        return Tpf2LoaderResult::ControllerNotOwned;
    }

    g_state.store(Tpf2LoaderState::Reloading, std::memory_order_release);
    const auto prepare = reinterpret_cast<ControllerPrepareUnload>(
        GetProcAddress(g_controller_module, "tpf2_controller_prepare_unload"));
    if (prepare == nullptr || !prepare(kControllerShutdownTimeoutMs)) {
        remember_error(prepare == nullptr ? ERROR_PROC_NOT_FOUND : ERROR_TIMEOUT);
        g_state.store(Tpf2LoaderState::Error, std::memory_order_release);
        ReleaseSRWLockExclusive(&g_lock);
        return Tpf2LoaderResult::PrepareUnloadFailed;
    }

    const std::filesystem::path controller = g_controller_path;
    if (!FreeLibrary(g_controller_module)) {
        remember_error(GetLastError());
        g_state.store(Tpf2LoaderState::Error, std::memory_order_release);
        ReleaseSRWLockExclusive(&g_lock);
        return Tpf2LoaderResult::UnloadFailed;
    }
    g_controller_module = nullptr;
    g_controller_path.clear();
    g_owns_controller_reference = false;

    const std::filesystem::path staged = staged_controller_file(controller);
    std::error_code file_error;
    if (std::filesystem::is_regular_file(staged, file_error) && !file_error) {
        if (!MoveFileExW(staged.c_str(), controller.c_str(),
                         MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
            const DWORD replace_error = GetLastError();
            load_controller_locked(controller);
            remember_error(replace_error);
            ReleaseSRWLockExclusive(&g_lock);
            return Tpf2LoaderResult::ReplaceFailed;
        }
    }

    const Tpf2LoaderResult result = load_controller_locked(controller);
    ReleaseSRWLockExclusive(&g_lock);
    return result;
}

Tpf2LoaderState state() noexcept { return g_state.load(std::memory_order_acquire); }
DWORD last_error() noexcept { return g_last_error.load(std::memory_order_acquire); }

} // namespace tpf2::loader
