from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LuaResourceRepositoryCallTests(unittest.TestCase):
    def test_vehicle_model_repository_accepts_callable_table(self):
        source = (ROOT / "tpf2_mod/res/scripts/tpf2_mcp/collectors/vehicle.lua").read_text(encoding="utf-8")
        self.assertIn('local get = common.field(repository, "get")', source)
        self.assertNotIn('type(repository.get) == "function"', source)

    def test_track_repository_accepts_callable_table_in_both_states(self):
        collector = (ROOT / "tpf2_mod/res/scripts/tpf2_mcp/collectors/rail_network.lua").read_text(encoding="utf-8")
        game_script = (ROOT / "tpf2_mod/res/config/game_script/tpf2_mcp.lua").read_text(encoding="utf-8")
        self.assertNotIn('type(get_all) == "function"', collector)
        self.assertNotIn('type(get_all) ~= "function"', collector)
        self.assertNotIn('type(get_all) == "function"', game_script)
        self.assertIn('pcall(function() return get(index) end)', collector)
        self.assertIn('pcall(function() return get(index) end)', game_script)


if __name__ == "__main__":
    unittest.main()
