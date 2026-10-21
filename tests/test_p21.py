"""Scheduled log-prune job tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase
from fap import db, jobs


class PruneJobTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.conn.execute("INSERT INTO audit_logs(action, detail, user_id, created_at) VALUES(?,?,?,?)",
                          ("old.job", "", None, "2000-01-01T00:00:00+08:00"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def test_prune_job_runs(self):
        r = self.client.post("/api/jobs", json={
            "name": "自动清理", "type": "prune", "interval_seconds": 86400,
            "config": {"days": 30},
        })
        self.assertEqual(r.status_code, 200, r.data)
        run = self.client.post(f"/api/jobs/{r.json['id']}/run")
        self.assertEqual(run.status_code, 200, run.data)
        self.assertIn("清理", run.json["result"]["message"])
        actions = [x["action"] for x in self.conn.execute("SELECT action FROM audit_logs").fetchall()]
        self.assertNotIn("old.job", actions)

    def test_operator_cannot_create_prune_job(self):
        self.client.post("/api/users", json={"username": "op12", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op12", "password": "op123456"})
        self.assertEqual(op.post("/api/jobs", json={
            "name": "清理", "type": "prune", "config": {"days": 30},
        }).status_code, 403)

    def test_job_type_registered(self):
        self.assertIn("prune", jobs.JOB_TYPES)


if __name__ == "__main__":
    unittest.main()
