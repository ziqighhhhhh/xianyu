"""Order sync, audit scoping and quick-phrase ownership tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase
from fap import sync


class SyncHelperTests(unittest.TestCase):
    def test_field_mapping(self):
        raw = {"data": {"order": {"bizOrderId": "123", "buyerNick": "张三",
                                  "itemTitle": "商品", "totalAmount": "¥1,299.00",
                                  "quantity": 2, "orderStatusName": "已发货"}}}
        self.assertEqual(sync._deep(raw, ("bizOrderId",)), "123")
        self.assertEqual(sync._amount(sync._deep(raw, ("totalAmount",))), 1299.0)
        self.assertEqual(sync._status("已发货"), "delivered")
        self.assertEqual(sync._status("待发货"), "paid")
        self.assertEqual(sync._status("退款成功"), "refunded")


class OrderSyncTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.account = self.client.get("/api/accounts").json["accounts"][0]

    def test_mock_account_sync_creates_order(self):
        resp = self.client.post("/api/orders/sync", json={
            "account_id": self.account["id"], "order_id": "SYNC-1001",
        })
        self.assertEqual(resp.status_code, 200, resp.data)
        order = resp.json["result"]["order"]
        self.assertEqual(order["order_no"], "SYNC-1001")
        self.assertEqual(order["buyer"], "同步买家")
        self.assertEqual(order["status"], "paid")
        self.assertAlmostEqual(order["amount"], 9.9)
        orders = self.client.get("/api/orders").json["orders"]
        self.assertEqual(len(orders), 1)

    def test_sync_is_idempotent(self):
        payload = {"account_id": self.account["id"], "order_id": "SYNC-1002"}
        first = self.client.post("/api/orders/sync", json=payload)
        second = self.client.post("/api/orders/sync", json=payload)
        self.assertEqual(first.json["result"]["order"]["id"], second.json["result"]["order"]["id"])
        self.assertEqual(len(self.client.get("/api/orders").json["orders"]), 1)

    def test_sync_requires_owned_account(self):
        # create an operator and try to use the admin's account
        self.client.post("/api/users", json={"username": "op2", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op2", "password": "op123456"})
        resp = op.post("/api/orders/sync", json={"account_id": self.account["id"], "order_id": "X"})
        self.assertEqual(resp.status_code, 404)


class AuditScopingTests(BaseCase):
    def test_operator_sees_only_own_audit(self):
        self.client.post("/api/users", json={"username": "op3", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op3", "password": "op123456"})
        op.post("/api/accounts", json={"name": "op3-acc", "cookie": "demo-op3"})

        op_logs = op.get("/api/audit-logs").json["logs"]
        actions = [l["action"] for l in op_logs]
        self.assertIn("account.create", actions)
        self.assertTrue(all(l["user_id"] is not None for l in op_logs if l["action"] == "account.create"))
        admin_logs = self.client.get("/api/audit-logs").json["logs"]
        self.assertGreaterEqual(len(admin_logs), len(op_logs))


class QuickPhraseScopingTests(BaseCase):
    def test_operator_phrases_are_isolated(self):
        seeded = self.client.get("/api/quick-phrases").json["phrases"]
        self.assertEqual(len(seeded), 3)
        self.client.post("/api/users", json={"username": "op4", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op4", "password": "op123456"})
        self.assertEqual(op.get("/api/quick-phrases").json["phrases"], [])
        op.post("/api/quick-phrases", json={"content": "运营专属话术"})
        phrases = op.get("/api/quick-phrases").json["phrases"]
        self.assertEqual([p["content"] for p in phrases], ["运营专属话术"])
        # operator cannot delete the admin's seeded phrase
        seeded_id = seeded[0]["id"]
        self.assertEqual(op.delete(f"/api/quick-phrases/{seeded_id}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
