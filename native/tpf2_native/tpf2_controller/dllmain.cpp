// dllmain.cpp : 定义 DLL 应用程序的入口点。
#include "pch.h"
#include "control/tpf2.h"

BOOL is_in_game() {
    return GetModuleHandleW(L"TransportFever2.exe") != nullptr;
}

BOOL APIENTRY DllMain( HMODULE hModule,
                       DWORD  ul_reason_for_call,
                       LPVOID lpReserved
                     )
{
    switch (ul_reason_for_call)
    {
    case DLL_PROCESS_ATTACH:
		DisableThreadLibraryCalls(hModule);
        if (is_in_game()) {
            OutputDebugStringA("in game.");
			start_tpf2(hModule);
        }
		break;
    case DLL_THREAD_ATTACH:
    case DLL_THREAD_DETACH:
    case DLL_PROCESS_DETACH:
        break;
    }
    return TRUE;
}

