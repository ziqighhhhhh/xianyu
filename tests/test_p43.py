"""Buyer 360 summary tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class BuyerSummaryTests(BaseCase):
    def test_summary(self):
        goods = self.client.get("/api/goods").json["goods"][0]
        self.client.post("/api/sim/order", json={"goods_id": goods["id"], "quantity": 1})
        orders = self.client.get("/api/orders").json["orders"]
        buyer = orders[0]["buyer"]
        self.client.post("/api/buyer-tags", json={"buyer": buyer, "tag": "概览标签"})
        r = self.client.get("/api/buyers/summary", query_string={"buyer": buyer})
        self.assertEqual(r.status_code, 200, r.data)
        data = r.json
        self.assertEqual(data["buyer"], buyer)
        self.assertGreaterEqual(data["orders"], 1)
        self.assertGreaterEqual(data["spend"], 0)
        self.assertIn("概览标签", [t["tag"] for t in data["tags"]])
        self.assertTrue(data["recent_orders"])

    def test_missing_buyer(self):
        self.assertEqual(self.client.get("/api/buyers/summary").status_code, 400)

    def test_operator_scope(self):
        goods = self.client.get("/api/goods").json["goods"][0]
        self.client.post("/api/sim/order", json={"goods_id": goods["id"], "quantity": 1})
        buyer = self.client.get("/api/orders").json["orders"][0]["buyer"]
        self.client.post("/api/users", json={"username": "op28", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op28", "password": "op123456"})
        data = op.get("/api/buyers/summary", query_string={"buyer": buyer}).json
        self.assertEqual(data["orders"], 0)
        self.assertEqual(data["tags"], [])


if __name__ == "__main__":
    unittest.main()
