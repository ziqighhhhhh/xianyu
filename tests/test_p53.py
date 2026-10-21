"""Order note tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class OrderNoteTests(BaseCase):
    def setUp(self):
        super().setUp()
        account = self.client.get("/api/accounts").json["accounts"][0]
        self.client.post("/api/orders/sync", json={"account_id": account["id"], "order_id": "MOCK-SOLD-1"})
        self.order = self.client.get("/api/orders").json["orders"][0]

    def test_set_and_clear_note(self):
        r = self.client.patch(f"/api/orders/{self.order['id']}", json={"note": "客户要求周末发货"})
        self.assertEqual(r.status_code, 200, r.data)
        detail = self.client.get(f"/api/orders/{self.order['id']}").json["order"]
        self.assertEqual(detail["note"], "客户要求周末发货")
        self.client.patch(f"/api/orders/{self.order['id']}", json={"note": ""})
        self.assertEqual(self.client.get(f"/api/orders/{self.order['id']}").json["order"]["note"], "")

    def test_only_note_supported(self):
        r = self.client.patch(f"/api/orders/{self.order['id']}", json={"status": "refunded"})
        self.assertEqual(r.status_code, 400)

    def test_operator_isolation(self):
        self.client.post("/api/users", json={"username": "op34", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op34", "password": "op123456"})
        self.assertEqual(op.patch(f"/api/orders/{self.order['id']}", json={"note": "x"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
