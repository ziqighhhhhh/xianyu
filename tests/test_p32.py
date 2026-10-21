"""Scheduled business report tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from test_core import BaseCase


class ReportJobTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.channel = self.client.post("/api/notifications/channels", json={
            "name": "报表渠道", "type": "webhook", "config": {"url": "http://example.com/hook"},
        }).json

    def test_report_job_sends_to_channel(self):
        with patch("fap.notify.send", return_value="ok") as send:
            job = self.client.post("/api/jobs", json={
                "name": "每日报表", "type": "report", "interval_seconds": 86400,
                "config": {"days": 1},
            })
            self.assertEqual(job.status_code, 200, job.data)
            run = self.client.post(f"/api/jobs/{job.json['id']}/run")
        self.assertEqual(run.status_code, 200, run.data)
        self.assertEqual(send.call_count, 1)
        self.assertIn("已发送 1/1", run.json["result"]["message"])
        log = self.client.get("/api/notifications/logs").json["logs"][0]
        self.assertEqual(log["event"], "report")
        self.assertEqual(log["status"], "sent")

    def test_operator_report_uses_own_channels(self):
        self.client.post("/api/users", json={"username": "op18", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op18", "password": "op123456"})
        op.post("/api/notifications/channels", json={
            "name": "运营渠道", "type": "webhook", "config": {"url": "http://example.com/op"},
        })
        with patch("fap.notify.send", return_value="ok") as send:
            job = op.post("/api/jobs", json={
                "name": "运营报表", "type": "report", "interval_seconds": 86400,
                "config": {"days": 7},
            }).json
            run = op.post(f"/api/jobs/{job['id']}/run")
        self.assertEqual(run.status_code, 200, run.data)
        # only the operator's own channel is used, not the admin channel
        self.assertEqual(send.call_count, 1)


if __name__ == "__main__":
    unittest.main()
