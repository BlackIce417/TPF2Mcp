#include "pch.h"
#include "scheduler.h"

#include <atomic>

namespace {
constexpr wchar_t kNetworkRefreshEvent[] = L"Local\\tpf2mcp_network_refresh_v1";
constexpr DWORD kPeriodicNetworkRefreshMs = 60000;
SRWLOCK g_start_lock = SRWLOCK_INIT;
std::atomic_bool g_network_due{true};
std::atomic_bool g_started{false};
HANDLE g_refresh_event = nullptr;

DWORD WINAPI scheduler_thread(void*) noexcept
{
    for (;;) {
        const DWORD result = WaitForSingleObject(g_refresh_event, kPeriodicNetworkRefreshMs);
        if (result != WAIT_OBJECT_0 && result != WAIT_TIMEOUT) return 0;
        g_network_due.store(true, std::memory_order_release);
    }
}
}

namespace tpf2::loader::scheduler {

bool initialize() noexcept
{
    if (g_started.load(std::memory_order_acquire)) return true;
    AcquireSRWLockExclusive(&g_start_lock);
    if (g_started.load(std::memory_order_acquire)) { ReleaseSRWLockExclusive(&g_start_lock); return true; }
    g_refresh_event = CreateEventW(nullptr, FALSE, FALSE, kNetworkRefreshEvent);
    if (g_refresh_event == nullptr) { ReleaseSRWLockExclusive(&g_start_lock); return false; }
    HANDLE thread = CreateThread(nullptr, 0, scheduler_thread, nullptr, 0, nullptr);
    if (thread == nullptr) { CloseHandle(g_refresh_event); g_refresh_event = nullptr; ReleaseSRWLockExclusive(&g_start_lock); return false; }
    CloseHandle(thread);
    g_started.store(true, std::memory_order_release);
    ReleaseSRWLockExclusive(&g_start_lock);
    return true;
}

bool consume_network_refresh() noexcept
{
    initialize();
    return g_network_due.exchange(false, std::memory_order_acq_rel);
}

bool request_network_refresh() noexcept
{
    if (!initialize()) return false;
    return SetEvent(g_refresh_event) != FALSE;
}

}
