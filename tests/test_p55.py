"""Order audit history tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class OrderHistoryTests(BaseCase):
    def setUp(self):
        super().setUp()
        account = self.client.get("/api/accounts").json["accounts"][0]
        goods = self.client.get("/api/goods").json["goods"][0]
        self.client.post("/api/autosell/rules", json={
            "name": "历史发货", "goods_id": goods["id"], "delivery_type": "fixed", "content": "H-KEY"})
        self.client.post("/api/sim/order", json={"goods_id": goods["id"], "quantity": 1})
        self.order = self.client.get("/api/orders").json["orders"][0]

    def test_history_contains_actions(self):
        self.client.patch(f"/api/orders/{self.order['id']}", json={"note": "历史备注"})
        self.client.post(f"/api/orders/{self.order['id']}/ship")
        r = self.client.get(f"/api/orders/{self.order['id']}/history")
        self.assertEqual(r.status_code, 200, r.data)
        actions = [x["action"] for x in r.json["logs"]]
        self.assertIn("order.note", actions)
        self.assertIn("order.ship", actions)

    def test_entity_linkage(self):
        self.client.patch(f"/api/orders/{self.order['id']}", json={"note": "实体关联"})
        logs = self.client.get("/api/audit-logs", query_string={"action": "order.note"}).json["logs"]
        row = logs[0]
        self.assertEqual(row["entity_type"], "order")
        self.assertEqual(row["entity_id"], self.order["id"])

    def test_missing_and_scope(self):
        self.assertEqual(self.client.get("/api/orders/99999/history").status_code, 404)
        self.client.post("/api/users", json={"username": "op35", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op35", "password": "op123456"})
        self.assertEqual(op.get(f"/api/orders/{self.order['id']}/history").status_code, 404)


if __name__ == "__main__":
    unittest.main()
