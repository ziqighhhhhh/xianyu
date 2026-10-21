"""Audit log pagination tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class AuditPagingTests(BaseCase):
    def test_pagination(self):
        for i in range(3):
            self.client.post("/api/accounts", json={"name": f"分页账号{i}", "cookie": f"demo-p{i}"})
        first = self.client.get("/api/audit-logs", query_string={"limit": 2}).json
        self.assertEqual(len(first["logs"]), 2)
        self.assertTrue(first["has_more"])
        before = first["before_id"]
        second = self.client.get("/api/audit-logs", query_string={
            "limit": 2, "before_id": before}).json
        self.assertTrue(second["logs"])
        self.assertTrue(all(x["id"] < before for x in second["logs"]))

    def test_filtered_pagination(self):
        self.client.post("/api/accounts", json={"name": "分页审计", "cookie": "demo-page"})
        data = self.client.get("/api/audit-logs", query_string={"action": "account.", "limit": 1}).json
        self.assertEqual(len(data["logs"]), 1)
        self.assertTrue(data["logs"][0]["action"].startswith("account."))

    def test_operator_scope(self):
        self.client.post("/api/users", json={"username": "op33", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op33", "password": "op123456"})
        data = op.get("/api/audit-logs", query_string={"limit": 5}).json
        self.assertTrue(all(x["user_id"] == 2 for x in data["logs"]))


if __name__ == "__main__":
    unittest.main()
