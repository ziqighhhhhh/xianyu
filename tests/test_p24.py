"""Per-conversation auto-reply pause tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class PauseTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.account = self.client.get("/api/accounts").json["accounts"][0]

    def _send(self, buyer, text):
        r = self.client.post("/api/sim/message", json={
            "account_id": self.account["id"], "buyer": buyer, "text": text,
        })
        self.assertEqual(r.status_code, 200, r.data)
        return r.json["conversation_id"]

    def _out(self, cid):
        msgs = self.client.get(f"/api/conversations/{cid}/messages").json["messages"]
        return [m for m in msgs if m["direction"] == "out"]

    def test_pause_and_resume(self):
        cid = self._send("paused_buyer", "能便宜点吗")
        self.assertTrue(self._out(cid))
        paused = self.client.post(f"/api/conversations/{cid}/autoreply", json={"paused": True})
        self.assertEqual(paused.status_code, 200, paused.data)
        self.assertTrue(paused.json["paused"])
        self._send("paused_buyer", "还能便宜吗")
        self.assertEqual(len(self._out(cid)), 1)
        self.client.post(f"/api/conversations/{cid}/autoreply", json={"paused": False})
        self._send("paused_buyer", "再便宜点")
        self.assertEqual(len(self._out(cid)), 2)

    def test_operator_cannot_pause_admin_conversation(self):
        cid = self._send("admin_conv", "能便宜点吗")
        self.client.post("/api/users", json={"username": "op14", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op14", "password": "op123456"})
        self.assertEqual(op.post(f"/api/conversations/{cid}/autoreply", json={"paused": True}).status_code, 404)

    def test_bridge_respects_pause(self):
        cid = self._send("bridge_pause", "能便宜点吗")
        self.client.post(f"/api/conversations/{cid}/autoreply", json={"paused": True})
        token = self.client.post("/api/integrations/token/rotate").json["token"]
        r = self.client.post("/api/integrations/messages", headers={"X-FAP-Token": token}, json={
            "account_id": self.account["id"], "buyer": "bridge_pause", "text": "能便宜点吗",
        })
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.json["replied"])
        self.assertEqual(len(self._out(cid)), 1)


if __name__ == "__main__":
    unittest.main()
