"""Buyer message timeline tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class BuyerTimelineTests(BaseCase):
    def test_recent_messages(self):
        conv = self.client.get("/api/conversations").json["conversations"][0]
        r = self.client.get("/api/buyers/summary", query_string={"buyer": conv["buyer"]})
        self.assertEqual(r.status_code, 200, r.data)
        msgs = r.json["recent_messages"]
        self.assertTrue(msgs)
        self.assertTrue(all("content" in m and "direction" in m for m in msgs))
        self.assertLessEqual(len(msgs), 10)
        self.assertTrue(all(m["direction"] in ("in", "out") for m in msgs))

    def test_operator_messages_empty(self):
        conv = self.client.get("/api/conversations").json["conversations"][0]
        self.client.post("/api/users", json={"username": "op29", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op29", "password": "op123456"})
        r = op.get("/api/buyers/summary", query_string={"buyer": conv["buyer"]})
        self.assertEqual(r.json["recent_messages"], [])


if __name__ == "__main__":
    unittest.main()
