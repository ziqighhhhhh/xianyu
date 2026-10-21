"""Conversation search, unread filter and message pagination tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class ConversationQueryTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.account = self.client.get("/api/accounts").json["accounts"][0]

    def _send(self, buyer, text):
        r = self.client.post("/api/sim/message", json={
            "account_id": self.account["id"], "buyer": buyer, "text": text,
        })
        self.assertEqual(r.status_code, 200, r.data)
        return r.json["conversation_id"]

    def test_search_by_buyer_and_message(self):
        self._send("alice", "hello there")
        self._send("bob", "another question")
        rows = self.client.get("/api/conversations", query_string={"q": "alice"}).json["conversations"]
        self.assertEqual([c["buyer"] for c in rows], ["alice"])
        rows = self.client.get("/api/conversations", query_string={"q": "question"}).json["conversations"]
        self.assertEqual([c["buyer"] for c in rows], ["bob"])

    def test_unread_filter(self):
        self._send("carol", "hi")
        self._send("dave", "hi")
        buyers = [c["buyer"] for c in self.client.get("/api/conversations", query_string={"unread": "1"}).json["conversations"]]
        self.assertIn("carol", buyers)
        self.assertIn("dave", buyers)
        conv = self.client.get("/api/conversations", query_string={"q": "carol"}).json["conversations"][0]
        self.client.get(f"/api/conversations/{conv['id']}/messages")
        buyers = [c["buyer"] for c in self.client.get("/api/conversations", query_string={"unread": "1"}).json["conversations"]]
        self.assertNotIn("carol", buyers)
        self.assertIn("dave", buyers)

    def test_message_pagination(self):
        cid = self._send("erin", "msg-0")
        for i in range(1, 6):
            self.client.post("/api/sim/message", json={
                "account_id": self.account["id"], "buyer": "erin", "text": f"msg-{i}",
            })
        first = self.client.get(f"/api/conversations/{cid}/messages", query_string={"limit": 2}).json
        self.assertEqual(len(first["messages"]), 2)
        self.assertTrue(first["has_more"])
        self.assertEqual([m["content"] for m in first["messages"]], ["msg-4", "msg-5"])
        older = self.client.get(f"/api/conversations/{cid}/messages",
                                query_string={"limit": 2, "before_id": first["before_id"]}).json
        self.assertEqual([m["content"] for m in older["messages"]], ["msg-2", "msg-3"])
        self.assertTrue(older["has_more"])


if __name__ == "__main__":
    unittest.main()
