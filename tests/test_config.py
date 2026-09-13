import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tpf2_mcp.config import bridge_dir, mod_dir

ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_explicit_bridge_directory_has_highest_priority(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"TPF2_MCP_BRIDGE_DIR": directory}, clear=True,
        ):
            self.assertEqual(Path(directory), bridge_dir())

    def test_bridge_defaults_to_directory_beside_explicit_mod(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"TPF2_MCP_MOD_DIR": directory}, clear=True,
        ):
            self.assertEqual(Path(directory).resolve(), mod_dir())
            self.assertEqual(Path(directory).resolve() / "bridge", bridge_dir())

    def test_lua_bridge_path_is_derived_without_machine_specific_override(self):
        config = (ROOT / "tpf2_mod/res/scripts/tpf2_mcp/config.lua").read_text(encoding="utf-8")
        installer = (ROOT / "tools/install-mod.ps1").read_text(encoding="utf-8")
        runtime = (ROOT / "tpf2_mod/res/scripts/tpf2_mcp/runtime.lua").read_text(encoding="utf-8")
        self.assertIn('package.searchpath, "tpf2_mcp/config"', config)
        self.assertIn('debug.getinfo, 1, "S"', config)
        self.assertIn('M.mod_dir .. "/bridge"', config)
        self.assertNotIn("local_config.bridge_dir", config)
        self.assertNotIn('M.bridge_dir = "$luaBridgeDirectory"', installer)
        self.assertIn("bridge_dir = config.bridge_dir", runtime)
        self.assertIn("path_resolution = config.path_resolution", runtime)
        self.assertIn('config.path_resolution == "MODULE_SOURCE"', runtime)
        self.assertIn(
            "bridge_ready = probe.io_read and probe.io_write and probe.path_resolved",
            runtime,
        )

    def test_mod_description_documents_bundled_stdio_server(self):
        strings = (ROOT / "tpf2_mod/strings.lua").read_text(encoding="utf-8")
        installer = (ROOT / "tools/install-mod.ps1").read_text(encoding="utf-8")
        launcher = (ROOT / "mcp_server/start_server.py").read_text(encoding="utf-8")
        ui_launcher = (ROOT / "mcp_server/start_ui.py").read_text(encoding="utf-8")
        requirements = ROOT / "mcp_server/requirements.txt"

        self.assertIn("mcp_server", strings)
        self.assertIn("python -m pip install -r requirements.txt", strings)
        self.assertIn("python start_server.py", strings)
        self.assertIn("stdio MCP", strings)
        self.assertTrue(requirements.is_file())
        self.assertIn("MCP server directory", installer)
        self.assertIn("TPF2_MCP_MOD_DIR", launcher)
        self.assertIn('SERVER_DIRECTORY / "src"', launcher)
        self.assertIn("sys.dont_write_bytecode = True", launcher)
        self.assertIn("python start_ui.py", strings)
        self.assertIn("http://127.0.0.1:8765/?view=network", strings)
        self.assertIn('MOD_DIRECTORY / "tools" / "serve-rail-map.py"', ui_launcher)
        self.assertIn("TPF2_MCP_MOD_DIR", ui_launcher)

    def test_workshop_metadata_and_clean_package_contract(self):
        mod = (ROOT / "tpf2_mod/mod.lua").read_text(encoding="utf-8")
        strings = (ROOT / "tpf2_mod/strings.lua").read_text(encoding="utf-8")
        builder = (ROOT / "tools/build-workshop-package.ps1").read_text(encoding="utf-8")

        self.assertIn('name = "BlackIce"', mod)
        self.assertEqual(2, strings.count('TPF2_MCP_NAME = "tpf2mcp"'))
        self.assertIn('"tpf2mcp_1"', builder)
        self.assertNotIn('"blackice_tpf2mcp_1"', builder)
        self.assertIn("workshop_preview.jpg", builder)
        self.assertIn("image_00.tga", builder)
        self.assertIn("320x180", builder)
        self.assertIn("local_config.lua", builder)
        self.assertIn("M\\.allow_write_operations", builder)
        self.assertIn("serve-rail-map.py", builder)
        self.assertIn("export-rail-network-map.py", builder)
        self.assertIn("network-app.js", builder)


if __name__ == "__main__":
    unittest.main()
