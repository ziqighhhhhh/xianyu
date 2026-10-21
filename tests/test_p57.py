"""Order status statistics tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class OrderStatsTests(BaseCase):
    def test_stats_match_orders(self):
        account = self.client.get("/api/accounts").json["accounts"][0]
        for order_no in ("MOCK-SOLD-1", "MOCK-SOLD-2"):
            self.client.post("/api/orders/sync", json={"account_id": account["id"], "order_id": order_no})
        orders = self.client.get("/api/orders").json["orders"]
        stats = self.client.get("/api/orders/stats").json
        self.assertEqual(stats["total"], len(orders))
        self.assertEqual(sum(v["count"] for v in stats["by_status"].values()), len(orders))
        self.assertGreaterEqual(stats["revenue"], 0)

    def test_refund_excluded_revenue(self):
        account = self.client.get("/api/accounts").json["accounts"][0]
        self.client.post("/api/orders/sync", json={"account_id": account["id"], "order_id": "MOCK-SOLD-1"})
        order = self.client.get("/api/orders").json["orders"][0]
        before = self.client.get("/api/orders/stats").json["revenue"]
        self.client.post(f"/api/orders/{order['id']}/refund", json={
            "status": "success", "amount": order["amount"], "reason": "test"})
        after = self.client.get("/api/orders/stats").json["revenue"]
        self.assertAlmostEqual(before - after, order["amount"], places=2)

    def test_operator_scope(self):
        account = self.client.get("/api/accounts").json["accounts"][0]
        self.client.post("/api/orders/sync", json={"account_id": account["id"], "order_id": "MOCK-SOLD-1"})
        self.client.post("/api/users", json={"username": "op36", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op36", "password": "op123456"})
        self.assertEqual(op.get("/api/orders/stats").json["total"], 0)


if __name__ == "__main__":
    unittest.main()
