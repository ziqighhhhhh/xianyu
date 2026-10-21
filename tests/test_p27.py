"""Dashboard range aggregation tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class DashboardRangeTests(BaseCase):
    def test_default_seven_days(self):
        data = self.client.get("/api/dashboard").json
        self.assertEqual(data["range_days"], 7)
        self.assertEqual(len(data["days"]), 7)
        self.assertIn("orders_range", data["stats"])
        self.assertIn("revenue_range", data["stats"])

    def test_thirty_days(self):
        data = self.client.get("/api/dashboard", query_string={"days": 30}).json
        self.assertEqual(data["range_days"], 30)
        self.assertEqual(len(data["days"]), 30)

    def test_range_counts_include_today(self):
        goods = self.client.get("/api/goods").json["goods"][0]
        self.client.post("/api/sim/order", json={"goods_id": goods["id"], "quantity": 1})
        data = self.client.get("/api/dashboard", query_string={"days": 7}).json
        self.assertGreaterEqual(data["stats"]["orders_range"], 1)
        self.assertGreaterEqual(data["stats"]["revenue_range"], 0)

    def test_days_clamped(self):
        data = self.client.get("/api/dashboard", query_string={"days": 1000}).json
        self.assertEqual(data["range_days"], 90)
        self.assertEqual(len(data["days"]), 90)


if __name__ == "__main__":
    unittest.main()
