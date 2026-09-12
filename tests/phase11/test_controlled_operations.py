import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from tpf2_mcp.operations import OperationController, capabilities
from tpf2_mcp.snapshot import SnapshotIndex


class ControlledOperationsTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parents[1] / "fixtures" / "world_snapshot_001.json"
        self.state = json.loads(fixture.read_text(encoding="utf-8"))
        self.writes = 0

        def provider(_force_refresh):
            return SnapshotIndex(deepcopy(self.state))

        self.controller = OperationController(provider)

    def proposal(self):
        return self.controller.propose("RENAME_LINE", {"line_id": 40}, {"name": "Renamed Line"})

    def test_capability_records_live_rename_evidence(self):
        registry = capabilities()
        self.assertEqual(len(registry), len({item["operation_type"] for item in registry}))
        self.assertTrue(next(item for item in registry if item["operation_type"] == "RENAME_LINE")["verified"])
        self.assertFalse(next(item for item in registry if item["operation_type"] == "RENAME_STATION")["verified"])

    def test_proposal_and_validation_never_write(self):
        proposal = self.proposal()
        result = self.controller.validate(proposal["operation_id"])
        self.assertEqual("PROPOSED", proposal["status"])
        self.assertEqual("VALIDATED", result["validation"]["status"])
        self.assertEqual(0, self.writes)

    def test_stale_proposal_is_rejected_before_capability(self):
        proposal = self.proposal()
        self.state["sequence"] = 2
        result = self.controller.validate(proposal["operation_id"])
        self.assertEqual("STALE_PROPOSAL", result["validation"]["status"])

    def test_changed_entity_is_rejected(self):
        proposal = self.proposal()
        self.state["lines"][0]["name"] = "Changed elsewhere"
        result = self.controller.validate(proposal["operation_id"])
        self.assertEqual("ENTITY_STATE_CHANGED", result["validation"]["status"])

    def test_execute_is_fail_closed_and_rollback_is_a_proposal(self):
        proposal = self.proposal()
        execution = self.controller.execute(proposal["operation_id"], dry_run=False)
        rollback = self.controller.rollback(proposal["operation_id"])
        self.assertEqual("OPERATION_NOT_VERIFIED", execution["execution_status"])
        self.assertFalse(execution["command_sent"])
        self.assertEqual("PROPOSED", rollback["status"])
        self.assertEqual(self.state["lines"][0]["name"], rollback["operation"]["parameters"]["name"])

    def test_verified_vehicle_purchase_has_a_fresh_entity_postcondition(self):
        def executor(command):
            self.assertEqual("BUY_VEHICLE", command["operation_type"])
            self.assertEqual(50, command["target"]["source_vehicle_id"])
            self.state["vehicles"].append({"entity_id": 99, "entity_type": "vehicle", "name": "Purchased bus", "line_id": None})
            self.state["sequence"] += 1
            return {"accepted": True, "engine_command_sent": True, "code": "EXECUTED"}
        controller = OperationController(lambda _: SnapshotIndex(deepcopy(self.state)), executor)
        proposal = controller.propose("BUY_VEHICLE", {"depot_id": 60}, {"source_vehicle_id": 50})
        execution = controller.execute(proposal["operation_id"], dry_run=False)
        verification = controller.verify(proposal["operation_id"])
        self.assertTrue(execution["command_sent"])
        self.assertEqual("POSTCONDITION_VERIFIED", verification["status"])
        self.assertEqual(99, verification["verification"]["new_entities"][0]["entity_id"])

    def test_operation_journal_recovers_without_resending(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "operations.jsonl"
            first = OperationController(lambda _: SnapshotIndex(deepcopy(self.state)), journal_path=path)
            proposal = first.propose("RENAME_LINE", {"line_id": 40}, {"name": "Persisted"})
            recovered = OperationController(lambda _: SnapshotIndex(deepcopy(self.state)), journal_path=path)
            self.assertEqual("PROPOSED", recovered.get(proposal["operation_id"])["status"])
            self.assertEqual(0, self.writes)
