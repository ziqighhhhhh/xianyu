"""Order stats time-range tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class OrderStatsRangeTests(BaseCase):
    def setUp(self):
        super().setUp()
        account = self.client.get("/api/accounts").json["accounts"][0]
        self.client.post("/api/orders/sync", json={"account_id": account["id"], "order_id": "MOCK-SOLD-1"})

    def test_range_filters(self):
        all_stats = self.client.get("/api/orders/stats").json
        day = self.client.get("/api/orders/stats", query_string={"days": 1}).json
        self.assertEqual(day["total"], all_stats["total"])
        year = self.client.get("/api/orders/stats", query_string={"days": 3650}).json
        self.assertEqual(year["total"], all_stats["total"])

    def test_invalid_days_ignored(self):
        all_stats = self.client.get("/api/orders/stats").json
        invalid = self.client.get("/api/orders/stats", query_string={"days": "abc"}).json
        self.assertEqual(invalid["total"], all_stats["total"])

    def test_operator_scope_with_range(self):
        self.client.post("/api/users", json={"username": "op37", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op37", "password": "op123456"})
        self.assertEqual(op.get("/api/orders/stats", query_string={"days": 30}).json["total"], 0)


if __name__ == "__main__":
    unittest.main()
