"""Stable local database scope for one TPF2 world/save lineage."""
from __future__ import annotations

import hashlib
import json
from typing import Any


LEGACY_SAVE_ID = "legacy-unscoped"


def snapshot_save_id(snapshot: dict[str, Any]) -> str:
    """Derive a stable world fingerprint without mutable line/vehicle state.

    TPF2's verified snapshot API does not expose the save filename or a UUID.
    Player and town entity identities are persistent for a world and provide a
    conservative scope boundary. Copies/branches of the same world intentionally
    share history until an engine-native save UUID becomes available.
    """
    game = snapshot.get("game") or {}
    town_ids = sorted(int(item["entity_id"]) for item in snapshot.get("towns", [])
                      if isinstance(item, dict) and isinstance(item.get("entity_id"), int))
    identity = {
        "version": 1,
        "world_entity": str(game.get("world_entity") or "UNKNOWN"),
        "player_entity": str(game.get("player_entity") or (snapshot.get("company") or {}).get("entity_id") or "UNKNOWN"),
        "town_entity_ids": town_ids,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "world-v1-" + hashlib.sha256(encoded).hexdigest()[:24]
