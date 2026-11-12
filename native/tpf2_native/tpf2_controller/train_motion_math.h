#pragma once
#include <algorithm>
#include <cmath>

namespace train_motion
{
// Bound BOTH the old and new speed so the native trapezoidal integration cannot
// cross the target. Native traction, reservations and lower speed limits still win.
inline float speed_cap(float requested, double remaining, float dt, float deceleration)
{
    if (!std::isfinite(remaining) || remaining <= 0.0 ||
        !std::isfinite(dt) || dt <= 0.0f || !std::isfinite(requested) || requested <= 0.0f ||
        !std::isfinite(deceleration) || deceleration <= 0.0f)
        return 0.0f;
    // Discrete-time braking envelope: v*dt + v^2/(2*a) <= remaining.
    double a_dt = static_cast<double>(deceleration) * dt;
    double braking = std::sqrt(a_dt * a_dt + 2.0 * deceleration * remaining) - a_dt;
    return static_cast<float>((std::min)({static_cast<double>(requested), braking, remaining / dt}));
}
}
