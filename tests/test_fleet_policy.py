import unittest

from tpf2_mcp.fleet_policy import evaluate_fleet_adjustment


class FleetPolicyTests(unittest.TestCase):
    plan = {"line_id": 7, "service_class": "PASSENGER", "vehicle_count": 2, "headway_seconds": 300}

    @staticmethod
    def sample(onboard, waiting, wait=0):
        return {"passengers": {"truncated": False, "total_for_line": onboard + waiting, "onboard": onboard,
                                "waiting": waiting, "average_waiting_seconds": wait}}

    def test_add_needs_three_sustained_samples(self):
        values = [self.sample(190, 60, 400)] * 3
        self.assertEqual(evaluate_fleet_adjustment(self.plan, values, 200)["decision"], "ADD_ONE_PROPOSAL")

    def test_remove_needs_six_sustained_samples_and_keeps_one(self):
        values = [self.sample(40, 5)] * 6
        self.assertEqual(evaluate_fleet_adjustment(self.plan, values, 200)["decision"], "REMOVE_ONE_PROPOSAL")
        one = {**self.plan, "vehicle_count": 1}
        self.assertEqual(evaluate_fleet_adjustment(one, values, 200)["decision"], "HOLD_FLEET")

    def test_truncated_samples_are_not_actionable(self):
        value = self.sample(200, 200, 1000)
        value["passengers"]["truncated"] = True
        self.assertEqual(evaluate_fleet_adjustment(self.plan, [value] * 6, 200)["decision"], "INSUFFICIENT_DATA")

    def test_falling_backlog_at_low_load_holds_fleet_while_service_recovers(self):
        values = [self.sample(100, waiting, 900) for waiting in (300, 220, 180)]

        result = evaluate_fleet_adjustment(self.plan, values, 200)

        self.assertEqual("HOLD_FLEET", result["decision"])
        self.assertEqual("WAITING_BACKLOG_RECOVERING", result["hold_reason"])

    def test_falling_backlog_does_not_hide_saturated_trains(self):
        values = [self.sample(190, waiting, 900) for waiting in (300, 220, 180)]

        self.assertEqual("ADD_ONE_PROPOSAL", evaluate_fleet_adjustment(self.plan, values, 200)["decision"])
