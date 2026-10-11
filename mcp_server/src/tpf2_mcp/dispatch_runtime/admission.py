"""Fail-closed regional admission checks over explicit evidence values."""
from __future__ import annotations
import math


def stopping_distance(speed_mps, deceleration_mps2, reaction_seconds=2., margin_m=50.):
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (speed_mps, deceleration_mps2)):
        return None
    if speed_mps < 0 or deceleration_mps2 <= 0: return None
    return speed_mps*reaction_seconds + speed_mps*speed_mps/(2*deceleration_mps2) + margin_m


def evaluate_admission(train, candidate, braking, receiving, sequence, now):
    blockers = []
    if candidate.get('legal_route_verified') is not True: blockers.append('LEGAL_ROUTE')
    if candidate.get('signal_protection_verified') is not True: blockers.append('SIGNAL_PROTECTION')
    if train.get('footprint_complete') is not True: blockers.append('FULL_TRAIN_FOOTPRINT')
    required = stopping_distance(train.get('speed_mps'), braking.get('service_deceleration_mps2'))
    braking_ok = (braking.get('verified') is True and required is not None
                  and candidate.get('distance_m', -1) >= required)
    if not braking_ok: blockers.append('BRAKING_ENVELOPE')
    train_length = train.get('train_length_m')
    receiving_ok = (receiving.get('verified') is True
                    and isinstance(train_length, (int, float))
                    and receiving.get('clear_length_m', -1) >= train_length+50
                    and not receiving.get('conflicting_vehicle_ids'))
    if not receiving_ok: blockers.append('RECEIVING_SPACE')
    return {**candidate, 'verified': not blockers, 'sequence': sequence, 'expires_at': now+2,
            'blockers': blockers, 'braking': {**braking, 'required_distance_m': required,
                                             'distance_available_m': candidate.get('distance_m')},
            'receiving': receiving}
