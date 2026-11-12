#pragma once
#include<Windows.h>
#include "../hooks/detour.h"

VOID start_tpf2(HMODULE self);
extern "C" __declspec(dllexport) BOOL tpf2_controller_prepare_unload(DWORD timeout_ms);
