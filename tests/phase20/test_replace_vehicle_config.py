import unittest

from tpf2_mcp.operations import OperationController
from tpf2_mcp.snapshot import SnapshotIndex


class ReplaceVehicleConfigTests(unittest.TestCase):
    def setUp(self):
        self.state = {"sequence": 1, "lines": [], "stations": [], "vehicles": [
            {"entity_id": 10, "line_id": 3, "name": "target", "consist_signature": "1:2", "capacity_total": 30, "consist_parts": [{}, {}]},
            {"entity_id": 11, "line_id": 4, "name": "source", "consist_signature": "1:2:2", "capacity_total": 60, "consist_parts": [{}, {}, {}]},
        ]}

    def index(self, _refresh=False):
        return SnapshotIndex(self.state)

    def test_propose_execute_and_verify_preserves_target_identity(self):
        sent = []
        controller = OperationController(self.index, lambda command: sent.append(command) or {"accepted": True, "engine_command_sent": True, "code": "EXECUTED"}, allow_unverified_test=True)
        params = {"source_vehicle_id": 11, "confirmation": "REPLACE_VEHICLE_CONFIG:10:11"}
        proposal = controller.propose("REPLACE_VEHICLE_CONFIG", {"vehicle_id": 10}, params)
        self.assertEqual("1:2:2", proposal["operation"]["expected_effect"]["consist_signature_after"])
        self.assertTrue(controller.execute(proposal["operation_id"], dry_run=False)["command_sent"])
        self.assertEqual("REPLACE_VEHICLE_CONFIG", sent[0]["operation_type"])
        self.state["sequence"] = 2
        self.state["vehicles"][0].update(consist_signature="1:2:2", capacity_total=60, consist_parts=[{}, {}, {}])
        self.assertEqual("POSTCONDITION_VERIFIED", controller.verify(proposal["operation_id"])["status"])
