import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tpf2_mcp.native_supervisor import NativeSupervisor


class NativeSupervisorTests(unittest.TestCase):
    def test_staged_native_update_is_applied_only_when_game_is_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); native = root / "native"; native.mkdir()
            (native / "tpf2_control.dll").write_bytes(b"old")
            (native / "tpf2_control.next.dll").write_bytes(b"new")
            with patch("tpf2_mcp.native_supervisor.find_game_process", return_value=None):
                result = NativeSupervisor(root).reconcile(False)
            self.assertEqual("GAME_NOT_RUNNING", result["supervisor_state"])
            self.assertTrue(result["native_update_applied"])
            self.assertEqual(b"new", (native / "tpf2_control.dll").read_bytes())
            self.assertFalse((native / "tpf2_control.next.dll").exists())

    def test_loaded_module_is_reported_without_injection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); native = root / "native"; native.mkdir()
            dll = native / "tpf2_control.dll"; dll.write_bytes(b"dll")
            with patch("tpf2_mcp.native_supervisor.find_game_process", return_value=(12, Path("game.exe"))), \
                    patch("tpf2_mcp.native_supervisor.loaded_modules", return_value=[dll]):
                result = NativeSupervisor(root).reconcile(False)
            self.assertEqual("LOADED", result["supervisor_state"])


if __name__ == "__main__":
    unittest.main()
