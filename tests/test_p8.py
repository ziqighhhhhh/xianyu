"""Scheduled job tests: order sync, backup, tick, validation and isolation."""

from __future__ import annotations

import unittest

from test_core import BaseCase
from fap import db, jobs


class JobTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.account = self.client.get("/api/accounts").json["accounts"][0]

    def _create(self, **over):
        payload = {
            "name": "订单同步任务",
            "type": "order_sync",
            "interval_seconds": 600,
            "config": {"account_id": self.account["id"], "order_id": "JOB-SYNC-1"},
        }
        payload.update(over)
        return self.client.post("/api/jobs", json=payload)

    def test_create_list_and_run_order_job(self):
        r = self._create()
        self.assertEqual(r.status_code, 200, r.data)
        job_id = r.json["id"]
        listed = self.client.get("/api/jobs").json
        self.assertEqual(len(listed["jobs"]), 1)
        self.assertEqual(listed["jobs"][0]["type"], "order_sync")
        run = self.client.post(f"/api/jobs/{job_id}/run")
        self.assertEqual(run.status_code, 200, run.data)
        self.assertIn("JOB-SYNC-1", run.json["result"]["message"])
        self.assertEqual(len(self.client.get("/api/orders").json["orders"]), 1)
        runs = self.client.get(f"/api/jobs/{job_id}/runs").json["runs"]
        self.assertEqual(runs[0]["status"], "success")
        self.assertEqual(self.client.get("/api/jobs").json["jobs"][0]["run_count"], 1)

    def test_scheduler_tick_runs_due_job(self):
        job_id = self._create().json["id"]
        conn = db.connect()
        conn.execute("UPDATE job_tasks SET next_run_at='2000-01-01T00:00:00+08:00' WHERE id=?", (job_id,))
        conn.commit()
        ran = jobs.tick(conn)
        conn.close()
        self.assertGreaterEqual(ran, 1)
        job = self.client.get("/api/jobs").json["jobs"][0]
        self.assertEqual(job["last_status"], "success")
        self.assertGreater(job["next_run_at"], "2020")

    def test_backup_job(self):
        r = self.client.post("/api/jobs", json={
            "name": "每日备份", "type": "backup", "interval_seconds": 86400, "config": {},
        })
        self.assertEqual(r.status_code, 200, r.data)
        run = self.client.post(f"/api/jobs/{r.json['id']}/run")
        self.assertEqual(run.status_code, 200, run.data)
        self.assertGreaterEqual(len(self.client.get("/api/backups").json["backups"]), 1)

    def test_validation(self):
        self.assertEqual(self.client.post("/api/jobs", json={
            "name": "x", "type": "order_sync", "config": {},
        }).status_code, 400)
        self.assertEqual(self.client.post("/api/jobs", json={
            "name": "x", "type": "nope", "config": {},
        }).status_code, 400)
        self.assertEqual(self.client.post("/api/jobs", json={
            "name": "x", "type": "monitor", "config": {"task_id": 9999},
        }).status_code, 404)

    def test_operator_isolation(self):
        job_id = self._create().json["id"]
        self.client.post("/api/users", json={"username": "op5", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op5", "password": "op123456"})
        self.assertEqual(op.get("/api/jobs").json["jobs"], [])
        self.assertEqual(op.post(f"/api/jobs/{job_id}/run").status_code, 404)
        self.assertEqual(op.post("/api/jobs", json={
            "name": "备份", "type": "backup", "config": {},
        }).status_code, 403)
        acc = op.post("/api/accounts", json={"name": "op5-acc", "cookie": "demo-op5"}).json
        own = op.post("/api/jobs", json={
            "name": "op订单", "type": "order_sync", "config": {"account_id": acc["id"], "order_id": "OP-JOB-1"},
        })
        self.assertEqual(own.status_code, 200, own.data)
        self.assertEqual(op.post(f"/api/jobs/{own.json['id']}/run").status_code, 200)
        self.assertEqual(len(self.client.get("/api/orders").json["orders"]), 1)


if __name__ == "__main__":
    unittest.main()
