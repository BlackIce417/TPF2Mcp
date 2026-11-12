#pragma once
#include "native_command_ipc.h"

// Uses the existing DetourManager and Controller command ring. No game calls are
// made by the IPC thread; commands are applied during TrainMoveSystem::Update2.
bool install_train_motion_hooks(DWORD path_vehicle_tls);
uint32_t train_motion_command(const Tpf2CommandSlot*, char* detail, size_t detail_size);
float train_motion_speed_limit(void* move_path, float native_limit);
bool train_motion_blocks_station_path(void* context, uint32_t vehicle);
// Restoration must finish on the game update thread before detours can drain.
bool prepare_train_motion_unload(DWORD timeout_ms);
