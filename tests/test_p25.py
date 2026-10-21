"""Timed auto-reply pause/resume tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase
from fap import db


class TimedPauseTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.account = self.client.get("/api/accounts").json["accounts"][0]

    def _send(self, buyer, text):
        r = self.client.post("/api/sim/message", json={
            "account_id": self.account["id"], "buyer": buyer, "text": text,
        })
        self.assertEqual(r.status_code, 200, r.data)
        return r.json["conversation_id"]

    def _out_count(self, cid):
        msgs = self.client.get(f"/api/conversations/{cid}/messages").json["messages"]
        return len([m for m in msgs if m["direction"] == "out"])

    def test_timed_pause_and_auto_resume(self):
        cid = self._send("timed_buyer", "能便宜点吗")
        self.assertEqual(self._out_count(cid), 1)
        r = self.client.post(f"/api/conversations/{cid}/autoreply",
                             json={"paused": True, "minutes": 30})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.json["until"])
        self._send("timed_buyer", "能便宜吗")
        self.assertEqual(self._out_count(cid), 1)

        conn = db.connect()
        conn.execute("UPDATE conversations SET autoreply_paused_until='2000-01-01T00:00:00+08:00' WHERE id=?",
                     (cid,))
        conn.commit()
        conn.close()
        self._send("timed_buyer", "再便宜点")
        self.assertEqual(self._out_count(cid), 2)
        conv = self.client.get(f"/api/conversations/{cid}/messages").json["conversation"]
        self.assertEqual(conv["autoreply_paused"], 0)

    def test_resume_clears_until(self):
        cid = self._send("resume_buyer", "能便宜点吗")
        self.client.post(f"/api/conversations/{cid}/autoreply", json={"paused": True, "minutes": 60})
        self.client.post(f"/api/conversations/{cid}/autoreply", json={"paused": False})
        conv = self.client.get(f"/api/conversations/{cid}/messages").json["conversation"]
        self.assertEqual(conv["autoreply_paused"], 0)
        self.assertEqual(conv["autoreply_paused_until"], "")


if __name__ == "__main__":
    unittest.main()
