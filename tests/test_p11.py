"""Integration bridge tests: token auth, inbound ingest, outbox and ACK."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class IntegrationTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.account = self.client.get("/api/accounts").json["accounts"][0]
        r = self.client.post("/api/integrations/token/rotate")
        self.assertEqual(r.status_code, 200, r.data)
        self.token = r.json["token"]
        self.headers = {"X-FAP-Token": self.token}

    def test_token_management_and_auth(self):
        self.assertEqual(self.client.get("/api/integrations/token").json["token"], self.token)
        self.assertEqual(self.client.post("/api/integrations/messages", json={
            "account_id": self.account["id"], "buyer": "b", "text": "hi",
        }).status_code, 401)
        self.assertEqual(self.client.post("/api/integrations/messages", headers={"X-FAP-Token": "bad"}, json={
            "account_id": self.account["id"], "buyer": "b", "text": "hi",
        }).status_code, 401)
        self.assertNotIn("ingest_token", self.client.get("/api/settings").json["settings"])

    def test_ingest_auto_reply_and_outbox(self):
        r = self.client.post("/api/integrations/messages", headers=self.headers, json={
            "account_id": self.account["id"], "buyer": "bridge_buyer",
            "text": "能便宜点吗", "external_id": "ext-1",
        })
        self.assertEqual(r.status_code, 200, r.data)
        body = r.json
        self.assertFalse(body["duplicate"])
        self.assertTrue(body["replied"], body)
        self.assertIn("活动价", body["reply"])
        self.assertIsNotNone(body["reply_message_id"])

        outbox = self.client.get("/api/integrations/outbox", headers=self.headers).json
        self.assertEqual(outbox["count"], 1)
        msg = outbox["messages"][0]
        self.assertEqual(msg["buyer"], "bridge_buyer")
        self.assertIn("活动价", msg["content"])

        ack = self.client.post(f"/api/integrations/outbox/{msg['id']}/ack", headers=self.headers,
                               json={"status": "sent"})
        self.assertEqual(ack.status_code, 200)
        self.assertEqual(self.client.get("/api/integrations/outbox", headers=self.headers).json["count"], 0)

    def test_ingest_is_idempotent(self):
        payload = {"account_id": self.account["id"], "buyer": "dup_buyer", "text": "在吗",
                   "external_id": "same-1"}
        first = self.client.post("/api/integrations/messages", headers=self.headers, json=payload).json
        second = self.client.post("/api/integrations/messages", headers=self.headers, json=payload).json
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["message_id"], second["message_id"])

    def test_disable_auto_reply_and_queue_outbound(self):
        r = self.client.post("/api/integrations/messages", headers=self.headers, json={
            "account_id": self.account["id"], "buyer": "quiet_buyer", "text": "在吗",
            "auto_reply": False,
        })
        self.assertFalse(r.json["replied"])
        sent = self.client.post("/api/integrations/send", headers=self.headers, json={
            "account_id": self.account["id"], "buyer": "quiet_buyer", "content": "人工回复",
        })
        self.assertEqual(sent.status_code, 200, sent.data)
        outbox = self.client.get("/api/integrations/outbox", headers=self.headers).json
        self.assertEqual(outbox["messages"][0]["content"], "人工回复")

    def test_operator_cannot_read_token(self):
        self.client.post("/api/users", json={"username": "op6", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op6", "password": "op123456"})
        self.assertEqual(op.get("/api/integrations/token").status_code, 403)


if __name__ == "__main__":
    unittest.main()
