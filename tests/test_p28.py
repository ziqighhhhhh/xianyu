"""Event polling cursor and scoping tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class EventPollTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.account = self.client.get("/api/accounts").json["accounts"][0]
        self.cursor = self.client.get("/api/events/poll").json["cursor"]

    def test_new_message_event(self):
        self.client.post("/api/sim/message", json={
            "account_id": self.account["id"], "buyer": "event_buyer", "text": "hello event",
        })
        data = self.client.get("/api/events/poll", query_string={
            "after_message": self.cursor["message"], "after_order": self.cursor["order"],
            "after_job": self.cursor["job"],
        }).json
        buyers = [m["buyer"] for m in data["messages"] if m["direction"] == "in"]
        self.assertIn("event_buyer", buyers)
        self.assertGreater(data["cursor"]["message"], self.cursor["message"])

    def test_new_order_event(self):
        goods = self.client.get("/api/goods").json["goods"][0]
        self.client.post("/api/sim/order", json={"goods_id": goods["id"], "quantity": 1})
        data = self.client.get("/api/events/poll", query_string={
            "after_order": self.cursor["order"],
        }).json
        self.assertTrue(data["orders"])
        self.assertGreater(data["cursor"]["order"], self.cursor["order"])

    def test_job_event(self):
        acc = self.account
        created = self.client.post("/api/jobs", json={
            "name": "事件任务", "type": "order_sync",
            "config": {"account_id": acc["id"], "order_id": "EVENT-1"},
        }).json
        self.client.post(f"/api/jobs/{created['id']}/run")
        data = self.client.get("/api/events/poll", query_string={
            "after_job": self.cursor["job"],
        }).json
        self.assertTrue(any(j["task_name"] == "事件任务" for j in data["jobs"]))

    def test_operator_only_sees_own_messages(self):
        self.client.post("/api/sim/message", json={
            "account_id": self.account["id"], "buyer": "admin_only", "text": "admin msg",
        })
        self.client.post("/api/users", json={"username": "op15", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op15", "password": "op123456"})
        data = op.get("/api/events/poll").json
        self.assertEqual([m for m in data["messages"] if m["buyer"] == "admin_only"], [])


if __name__ == "__main__":
    unittest.main()
