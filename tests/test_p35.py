"""Batch account operation tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class BatchAccountTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.a1 = self.client.post("/api/accounts", json={"name": "批量A", "cookie": "demo-a"}).json["id"]
        self.a2 = self.client.post("/api/accounts", json={"name": "批量B", "cookie": "demo-b"}).json["id"]

    def _acct(self, aid):
        return next(a for a in self.client.get("/api/accounts").json["accounts"] if a["id"] == aid)

    def test_enable_disable(self):
        r = self.client.post("/api/accounts/batch", json={"action": "disable", "ids": [self.a1, self.a2]})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.json["success"], 2)
        self.assertEqual(self._acct(self.a1)["enabled"], 0)
        self.client.post("/api/accounts/batch", json={"action": "enable", "ids": [self.a1, self.a2]})
        self.assertEqual(self._acct(self.a2)["enabled"], 1)

    def test_connect_disconnect(self):
        r = self.client.post("/api/accounts/batch", json={"action": "connect", "ids": [self.a1, self.a2]})
        self.assertEqual(r.json["success"], 2)
        self.assertEqual(self._acct(self.a1)["status"], "online")
        self.client.post("/api/accounts/batch", json={"action": "disconnect", "ids": [self.a1]})
        self.assertEqual(self._acct(self.a1)["status"], "offline")
        self.assertEqual(self._acct(self.a2)["status"], "online")

    def test_invalid_requests(self):
        self.assertEqual(self.client.post("/api/accounts/batch", json={"action": "nope", "ids": [1]}).status_code, 400)
        self.assertEqual(self.client.post("/api/accounts/batch", json={"action": "enable", "ids": []}).status_code, 400)

    def test_operator_cannot_touch_admin_accounts(self):
        self.client.post("/api/users", json={"username": "op21", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op21", "password": "op123456"})
        r = op.post("/api/accounts/batch", json={"action": "connect", "ids": [self.a1]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["success"], 0)
        self.assertEqual(r.json["failed"], 1)


if __name__ == "__main__":
    unittest.main()
