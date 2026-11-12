#pragma once
namespace native_telemetry {
// Called only by the existing, guarded TransportVehicleSystem update hook.
void after_vehicle_update(void* system, void* engine, int count, float dt) noexcept;
}
