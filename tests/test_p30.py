"""Audit filtering and XLSX export tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase
from fap import db


class AuditFilterTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.conn.execute("INSERT INTO audit_logs(action, detail, user_id, created_at) VALUES(?,?,?,?)",
                          ("order.sync", "order=OLD-1", 1, "2020-01-01T00:00:00+08:00"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def test_filter_by_action_and_query(self):
        self.client.post("/api/accounts", json={"name": "审计账号", "cookie": "demo-audit"})
        rows = self.client.get("/api/audit-logs", query_string={"action": "account."}).json["logs"]
        self.assertTrue(rows)
        self.assertTrue(all(r["action"].startswith("account.") for r in rows))
        rows = self.client.get("/api/audit-logs", query_string={"q": "account="}).json["logs"]
        self.assertTrue(any("account=" in (r["detail"] or "") for r in rows))

    def test_days_filter(self):
        rows = self.client.get("/api/audit-logs", query_string={"days": 7}).json["logs"]
        self.assertNotIn("order.sync", [r["action"] for r in rows])
        rows = self.client.get("/api/audit-logs", query_string={"days": 3650}).json["logs"]
        self.assertIn("order.sync", [r["action"] for r in rows])

    def test_operator_scope(self):
        self.client.post("/api/users", json={"username": "op17", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op17", "password": "op123456"})
        op.post("/api/accounts", json={"name": "op17-acc", "cookie": "demo-op17"})
        rows = op.get("/api/audit-logs").json["logs"]
        self.assertTrue(rows)
        self.assertTrue(all(r["user_id"] == 2 for r in rows))

    def test_export_xlsx(self):
        r = self.client.get("/api/audit-logs.xlsx")
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r.headers["Content-Type"])
        self.assertTrue(r.data.startswith(b"PK"))
        r.close()


if __name__ == "__main__":
    unittest.main()
