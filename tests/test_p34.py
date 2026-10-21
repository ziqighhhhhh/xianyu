"""Account summary endpoint tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class AccountSummaryTests(BaseCase):
    def test_summary_and_cookie_masking(self):
        acct = self.client.get("/api/accounts").json["accounts"][0]
        r = self.client.get(f"/api/accounts/{acct['id']}/summary")
        self.assertEqual(r.status_code, 200, r.data)
        data = r.json
        self.assertNotIn("cookie", data["account"])
        self.assertTrue(data["account"]["has_cookie"])
        self.assertTrue(data["account"]["is_demo"])
        self.assertIn("goods", data["counts"])
        self.assertGreaterEqual(data["counts"]["goods"], 1)
        self.assertTrue(data["recent_goods"])
        self.assertGreaterEqual(data["revenue"], 0)

    def test_missing_account(self):
        self.assertEqual(self.client.get("/api/accounts/99999/summary").status_code, 404)

    def test_operator_isolation(self):
        acct = self.client.get("/api/accounts").json["accounts"][0]
        self.client.post("/api/users", json={"username": "op20", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op20", "password": "op123456"})
        self.assertEqual(op.get(f"/api/accounts/{acct['id']}/summary").status_code, 404)


if __name__ == "__main__":
    unittest.main()
