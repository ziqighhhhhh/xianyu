"""System status and log-retention tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase
from fap import db


class MaintenanceTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        old = "2000-01-01T00:00:00+08:00"
        now = db.now_iso()
        self.conn.execute("INSERT INTO audit_logs(action, detail, user_id, created_at) VALUES(?,?,?,?)",
                          ("old.action", "", None, old))
        self.conn.execute("INSERT INTO audit_logs(action, detail, user_id, created_at) VALUES(?,?,?,?)",
                          ("new.action", "", None, now))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def test_status_admin_only(self):
        r = self.client.get("/api/system/status")
        self.assertEqual(r.status_code, 200, r.data)
        status = r.json["status"]
        self.assertTrue(status["version"])
        self.assertIn("db_size", status)
        self.assertGreaterEqual(status["counts"]["accounts"], 1)
        self.client.post("/api/users", json={"username": "op11", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op11", "password": "op123456"})
        self.assertEqual(op.get("/api/system/status").status_code, 403)
        self.assertEqual(op.post("/api/system/prune", json={"days": 30}).status_code, 403)

    def test_prune_old_logs(self):
        r = self.client.post("/api/system/prune", json={"days": 30})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertGreaterEqual(r.json["result"]["deleted"].get("audit_logs", 0), 1)
        rows = self.conn.execute("SELECT action FROM audit_logs ORDER BY id").fetchall()
        actions = [x["action"] for x in rows]
        self.assertNotIn("old.action", actions)
        self.assertIn("new.action", actions)

    def test_prune_validation(self):
        self.assertEqual(self.client.post("/api/system/prune", json={"targets": "audit"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
