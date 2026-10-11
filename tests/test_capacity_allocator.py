import unittest

from tpf2_mcp.capacity_allocator import allocate_to_available_capacity


class CapacityAllocatorTests(unittest.TestCase):
    def test_full_line_gets_nothing_while_spare_line_absorbs_demand(self):
        result = allocate_to_available_capacity(100, [
            {"line_id": 1, "residual_capacity": 5, "departure_in_seconds": 20},
            {"line_id": 2, "residual_capacity": 160, "departure_in_seconds": 50},
        ])
        by_line = {item["line_id"]: item["assigned"] for item in result["allocations"]}
        self.assertEqual({1: 0, 2: 100}, by_line)
        self.assertFalse(result["equal_split"])

    def test_consumes_capacity_and_reports_unassigned_overflow(self):
        result = allocate_to_available_capacity(200, [
            {"line_id": 1, "residual_capacity": 30},
            {"line_id": 2, "residual_capacity": 100},
        ])
        self.assertEqual(130, result["assigned"])
        self.assertEqual(70, result["unassigned"])
