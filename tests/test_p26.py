"""Background pause-expiry scan tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase
from fap import db, pauses


class PauseScanTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.account = self.client.get("/api/accounts").json["accounts"][0]
        r = self.client.post("/api/sim/message", json={
            "account_id": self.account["id"], "buyer": "scan_buyer", "text": "能便宜点吗",
        })
        self.cid = r.json["conversation_id"]

    def test_tick_clears_expired_pause(self):
        self.client.post(f"/api/conversations/{self.cid}/autoreply",
                         json={"paused": True, "minutes": 30})
        conn = db.connect()
        conn.execute("UPDATE conversations SET autoreply_paused_until='2000-01-01T00:00:00+08:00' WHERE id=?",
                     (self.cid,))
        conn.commit()
        cleared = pauses.tick(conn)
        conn.close()
        self.assertGreaterEqual(cleared, 1)
        conv = self.client.get(f"/api/conversations/{self.cid}/messages").json["conversation"]
        self.assertEqual(conv["autoreply_paused"], 0)
        self.assertEqual(conv["autoreply_paused_until"], "")

    def test_tick_keeps_active_pause(self):
        self.client.post(f"/api/conversations/{self.cid}/autoreply",
                         json={"paused": True, "minutes": 30})
        conn = db.connect()
        pauses.tick(conn)
        conn.close()
        conv = self.client.get(f"/api/conversations/{self.cid}/messages").json["conversation"]
        self.assertEqual(conv["autoreply_paused"], 1)


if __name__ == "__main__":
    unittest.main()
