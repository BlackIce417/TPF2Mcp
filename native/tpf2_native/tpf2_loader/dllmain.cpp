// dllmain.cpp : 定义 DLL 应用程序的入口点。
#include "pch.h"
#include "lifecycle/loader_runtime.h"

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(module);
        tpf2::loader::set_module(module);
    }
    return TRUE;
}

