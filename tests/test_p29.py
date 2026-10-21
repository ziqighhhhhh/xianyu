"""Long-poll event wait tests."""

from __future__ import annotations

import time
import unittest

from test_core import BaseCase


class WaitEventTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.account = self.client.get("/api/accounts").json["accounts"][0]
        self.cursor = self.client.get("/api/events/poll").json["cursor"]

    def test_wait_returns_existing_events(self):
        self.client.post("/api/sim/message", json={
            "account_id": self.account["id"], "buyer": "wait_buyer", "text": "hello wait",
        })
        start = time.monotonic()
        r = self.client.get("/api/events/wait", query_string={
            "after_message": self.cursor["message"], "after_order": self.cursor["order"],
            "after_job": self.cursor["job"], "timeout": 5,
        })
        elapsed = time.monotonic() - start
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.json["timed_out"])
        self.assertTrue(any(m["buyer"] == "wait_buyer" for m in r.json["messages"]))
        self.assertLess(elapsed, 3)

    def test_wait_times_out(self):
        r = self.client.get("/api/events/wait", query_string={
            "after_message": self.cursor["message"], "after_order": self.cursor["order"],
            "after_job": self.cursor["job"], "timeout": 1,
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json["timed_out"])
        self.assertEqual(r.json["messages"], [])

    def test_operator_scope_in_wait(self):
        self.client.post("/api/sim/message", json={
            "account_id": self.account["id"], "buyer": "admin_wait", "text": "admin only",
        })
        self.client.post("/api/users", json={"username": "op16", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op16", "password": "op123456"})
        r = op.get("/api/events/wait", query_string={"timeout": 1})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([m for m in r.json["messages"] if m["buyer"] == "admin_wait"], [])


if __name__ == "__main__":
    unittest.main()
