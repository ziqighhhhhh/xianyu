"""Order delete and local refund tracking tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class OrderAdminTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.account = self.client.get("/api/accounts").json["accounts"][0]
        self.goods = self.client.get("/api/goods").json["goods"][0]

    def _order(self):
        r = self.client.post("/api/sim/order", json={"goods_id": self.goods["id"], "quantity": 1})
        return r.json["order"]["id"]

    def test_delete_order_and_logs(self):
        oid = self._order()
        self.assertTrue(self.client.get(f"/api/orders/{oid}/logs").json["logs"])
        r = self.client.delete(f"/api/orders/{oid}")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.client.get(f"/api/orders/{oid}").status_code, 404)
        self.assertEqual(self.client.get("/api/orders").json["orders"], [])

    def test_refund_success_marks_order(self):
        oid = self._order()
        r = self.client.post(f"/api/orders/{oid}/refund", json={
            "status": "success", "amount": 9.9, "reason": "买家协商退款",
        })
        self.assertEqual(r.status_code, 200, r.data)
        order = self.client.get(f"/api/orders/{oid}").json["order"]
        self.assertEqual(order["refund_status"], "success")
        self.assertEqual(order["status"], "refunded")
        self.assertAlmostEqual(order["refund_amount"], 9.9)
        self.assertEqual(order["refund_reason"], "买家协商退款")
        self.assertTrue(order["refunded_at"])

    def test_refund_invalid_status(self):
        oid = self._order()
        self.assertEqual(self.client.post(f"/api/orders/{oid}/refund", json={
            "status": "nope",
        }).status_code, 400)

    def test_operator_cannot_delete_or_refund_admin_order(self):
        oid = self._order()
        self.client.post("/api/users", json={"username": "op10", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op10", "password": "op123456"})
        self.assertEqual(op.delete(f"/api/orders/{oid}").status_code, 404)
        self.assertEqual(op.post(f"/api/orders/{oid}/refund", json={"status": "success"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
