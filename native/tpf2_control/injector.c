#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <wchar.h>

int wmain(int argc, wchar_t **argv)
{
    if (argc != 3)
    {
        fwprintf(stderr, L"usage: injector.exe <pid> <absolute-dll-path>\n");
        return 2;
    }
    DWORD pid = wcstoul(argv[1], NULL, 10);
    wchar_t full[MAX_PATH];
    if (!GetFullPathNameW(argv[2], MAX_PATH, full, NULL) || GetFileAttributesW(full) == INVALID_FILE_ATTRIBUTES)
        return 3;
    HANDLE process = OpenProcess(PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION | PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ, FALSE, pid);
    if (!process)
    {
        fwprintf(stderr, L"OpenProcess failed: %lu\n", GetLastError());
        return 4;
    }
    SIZE_T bytes = (wcslen(full) + 1) * sizeof(wchar_t);
    void *remote = VirtualAllocEx(process, NULL, bytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!remote || !WriteProcessMemory(process, remote, full, bytes, NULL))
    {
        CloseHandle(process);
        return 5;
    }
    LPTHREAD_START_ROUTINE load = (LPTHREAD_START_ROUTINE)GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "LoadLibraryW");
    HANDLE thread = CreateRemoteThread(process, NULL, 0, load, remote, 0, NULL);
    if (!thread)
    {
        VirtualFreeEx(process, remote, 0, MEM_RELEASE);
        CloseHandle(process);
        return 6;
    }
    WaitForSingleObject(thread, 10000);
    DWORD result = 0;
    GetExitCodeThread(thread, &result);
    CloseHandle(thread);
    VirtualFreeEx(process, remote, 0, MEM_RELEASE);
    CloseHandle(process);
    if (!result)
    {
        fwprintf(stderr, L"LoadLibraryW failed in target\n");
        return 7;
    }
    wprintf(L"injected %ls into pid %lu\n", full, pid);
    return 0;
}
