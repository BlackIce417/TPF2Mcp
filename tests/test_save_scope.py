import unittest

from tpf2_mcp.save_scope import snapshot_save_id


class SaveScopeTests(unittest.TestCase):
    def test_mutable_transport_state_does_not_change_world_scope(self):
        base = {"game": {"world_entity": "0", "player_entity": "9"},
                "towns": [{"entity_id": 3}, {"entity_id": 1}], "lines": [{"entity_id": 10}]}
        changed = {**base, "lines": [{"entity_id": 99}], "vehicles": [{"entity_id": 22}]}
        self.assertEqual(snapshot_save_id(base), snapshot_save_id(changed))

    def test_different_world_identity_changes_scope(self):
        left = {"game": {"world_entity": "0", "player_entity": "9"}, "towns": [{"entity_id": 1}]}
        right = {"game": {"world_entity": "0", "player_entity": "9"}, "towns": [{"entity_id": 2}]}
        self.assertNotEqual(snapshot_save_id(left), snapshot_save_id(right))


if __name__ == "__main__":
    unittest.main()
