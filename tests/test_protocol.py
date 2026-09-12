import unittest

from tpf2_mcp.protocol import request


class ProtocolTests(unittest.TestCase):
    def test_request_has_required_fields(self):
        payload = request("ping")
        self.assertEqual(1, payload["schema_version"])
        self.assertEqual("ping", payload["command"])
        self.assertTrue(payload["request_id"])

    def test_unknown_command_is_rejected(self):
        with self.assertRaises(ValueError):
            request("rename_line")
