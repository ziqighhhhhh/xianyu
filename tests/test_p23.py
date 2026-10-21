"""Message-content search, mark-all-read and goods filters."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class SearchTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.account = self.client.get("/api/accounts").json["accounts"][0]

    def _send(self, buyer, text):
        r = self.client.post("/api/sim/message", json={
            "account_id": self.account["id"], "buyer": buyer, "text": text,
        })
        self.assertEqual(r.status_code, 200, r.data)
        return r.json["conversation_id"]

    def test_search_matches_older_message_content(self):
        self._send("frank", "secret-code-123")
        self._send("frank", "last words")
        rows = self.client.get("/api/conversations", query_string={"q": "secret-code"}).json["conversations"]
        self.assertEqual([c["buyer"] for c in rows], ["frank"])

    def test_mark_all_read_is_scoped(self):
        self._send("grace", "hello")
        self.client.post("/api/users", json={"username": "op13", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op13", "password": "op123456"})
        acc = op.post("/api/accounts", json={"name": "op13-acc", "cookie": "demo-op13"}).json
        op.post("/api/sim/message", json={"account_id": acc["id"], "buyer": "opbuyer", "text": "hi"})
        self.client.post("/api/conversations/read-all")
        op_unread = op.get("/api/conversations", query_string={"unread": "1"}).json["conversations"]
        self.assertEqual([c["buyer"] for c in op_unread], ["opbuyer"])
        op.post("/api/conversations/read-all")
        self.assertEqual(op.get("/api/conversations", query_string={"unread": "1"}).json["conversations"], [])

    def test_goods_search_and_status(self):
        rows = self.client.get("/api/goods", query_string={"q": "库存"}).json["goods"]
        self.assertTrue(rows)
        self.assertTrue(all("库存" in g["title"] for g in rows))
        on_sale = self.client.get("/api/goods", query_string={"status": "on_sale"}).json["goods"]
        self.assertTrue(all(g["status"] == "on_sale" for g in on_sale))


if __name__ == "__main__":
    unittest.main()
