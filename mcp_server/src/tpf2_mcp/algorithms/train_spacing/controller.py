"""Reusable spacing controller. Reading frames and scheduling ticks belong to the host."""
from __future__ import annotations

import math
from copy import deepcopy
from typing import Callable, Any

from ...dispatch_runtime.geometry import RailGraph
from .engine import DEFAULT_POLICY, compile_train_spacing


class TrainSpacingController:
    """Compute a complete desired lease set; optionally submit through a host callback.

    One instance per save/network revision. No threads, polling or game writes are
    started by construction. The sink receives the entire spacing-owned batch,
    including an empty batch to remove previously owned limits.
    """

    def __init__(self, network: dict, policy: dict | None = None, *, lease_seconds: float = 5.0,
                 release_rate_kmh_per_second: float = 3.0):
        if not math.isfinite(lease_seconds) or lease_seconds <= 0:
            raise ValueError('lease_seconds must be positive')
        if not math.isfinite(release_rate_kmh_per_second) or release_rate_kmh_per_second < 0:
            raise ValueError('release rate must be nonnegative')
        self.network = deepcopy(network)
        self.graph = RailGraph(self.network)
        self.policy = {**DEFAULT_POLICY, **(policy or {})}
        self.lease_seconds = lease_seconds
        self.release_rate = release_rate_kmh_per_second
        self._previous: dict[int, dict] = {}
        self._last_time: float | None = None

    def step(self, live: dict, *, now: float,
             sink: Callable[[list[dict]], Any] | None = None) -> dict:
        """Evaluate normalized rail-live data and optionally replace owned commands.

        Reductions are immediate. Increases have a deadband and slew limit. A
        failed sink raises and leaves controller history unchanged for retry.
        Diagnostics requiring a native stop are returned, never converted into
        a higher positive speed. This module is not a collision safety system.
        """
        if not math.isfinite(now):
            raise ValueError('now must be finite')
        if self._last_time is not None and now < self._last_time:
            raise ValueError('time moved backwards; create a controller for the new session')
        decisions = compile_train_spacing(self.network, live, now + self.lease_seconds,
                                          self.policy, publishable=True, now=now, graph=self.graph)
        commands = []
        elapsed = 0 if self._last_time is None else now - self._last_time
        for decision in decisions:
            if decision['kind'] != 'speed':
                continue
            command = dict(decision)
            previous = self._previous.get(command['vehicle_id'])
            if previous and previous['expires_at'] > now:
                old, target = previous['speed_mps'], command['speed_mps']
                if target > old:
                    command['speed_mps'] = old if (target-old)*3.6 < self.policy['hysteresis_kmh'] else min(
                        target, old + self.release_rate * elapsed / 3.6)
                    command['speed_kmh'] = round(command['speed_mps'] * 3.6, 1)
            commands.append(command)
        receipt = sink(deepcopy(commands)) if sink is not None else None
        self._previous = {x['vehicle_id']: x for x in commands}
        self._last_time = now
        return {'sampled_at': live.get('sampled_at'), 'evaluated_at': now,
                'decisions': decisions, 'commands': deepcopy(commands),
                'submitted': sink is not None, 'receipt': receipt}


def native_batch_sink(writer, *, generation: int, other_leases: list[dict], now: float):
    """Adapt NativeLeaseWriter.write without losing the host's other lease kinds.

    Host must own/serialize the native publisher, supply its current complete
    non-spacing lease set and choose the generation. Do not run a second writer
    alongside ControlSystem. Construct a fresh sink each tick.
    """
    remaining = deepcopy([x for x in other_leases if not str(x.get('lease_id', '')).startswith('spacing:')])

    def submit(commands):
        return writer.write(generation, remaining + commands, now=now)

    return submit
