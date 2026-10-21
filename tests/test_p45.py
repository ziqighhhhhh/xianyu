"""Buyer message pagination/export tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class BuyerMessagePagingTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.buyer = "demo_buyer"

    def test_pagination(self):
        account = self.client.get("/api/accounts").json["accounts"][0]
        for i in range(3):
            self.client.post("/api/sim/message", json={
                "account_id": account["id"], "buyer": self.buyer, "text": f"分页消息 {i}",
            })
        first = self.client.get("/api/buyers/messages", query_string={
            "buyer": self.buyer, "limit": 2}).json
        self.assertEqual(len(first["messages"]), 2)
        self.assertTrue(first["has_more"])
        before = first["before_id"]
        second = self.client.get("/api/buyers/messages", query_string={
            "buyer": self.buyer, "limit": 2, "before_id": before}).json
        self.assertTrue(second["messages"])
        self.assertTrue(all(m["id"] < before for m in second["messages"]))

    def test_export(self):
        r = self.client.get("/api/buyers/messages.xlsx", query_string={"buyer": self.buyer})
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r.headers["Content-Type"])
        self.assertTrue(r.data.startswith(b"PK"))
        r.close()

    def test_validation_and_scope(self):
        self.assertEqual(self.client.get("/api/buyers/messages").status_code, 400)
        self.client.post("/api/users", json={"username": "op30", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op30", "password": "op123456"})
        data = op.get("/api/buyers/messages", query_string={"buyer": self.buyer}).json
        self.assertEqual(data["messages"], [])


if __name__ == "__main__":
    unittest.main()
