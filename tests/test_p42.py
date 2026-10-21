"""Buyer tag integration in conversations tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class ConversationTagTests(BaseCase):
    def test_tags_in_conversation_list(self):
        conv = self.client.get("/api/conversations").json["conversations"][0]
        self.client.post("/api/buyer-tags", json={"buyer": conv["buyer"], "tag": "重点客户"})
        data = self.client.get("/api/conversations").json["conversations"]
        row = next(c for c in data if c["id"] == conv["id"])
        self.assertIn("重点客户", (row["tags"] or "").split(","))

    def test_filter_by_tag(self):
        data = self.client.get("/api/conversations").json["conversations"]
        buyer = data[0]["buyer"]
        self.client.post("/api/buyer-tags", json={"buyer": buyer, "tag": "筛选标签"})
        filtered = self.client.get("/api/conversations", query_string={"tag": "筛选标签"}).json["conversations"]
        self.assertTrue(filtered)
        self.assertTrue(all(c["buyer"] == buyer for c in filtered))
        self.assertEqual(self.client.get("/api/conversations", query_string={"tag": "不存在"}).json["conversations"], [])

    def test_operator_tag_scope(self):
        conv = self.client.get("/api/conversations").json["conversations"][0]
        self.client.post("/api/buyer-tags", json={"buyer": conv["buyer"], "tag": "管理员标签"})
        self.client.post("/api/users", json={"username": "op27", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op27", "password": "op123456"})
        self.assertEqual(op.get("/api/conversations", query_string={"tag": "管理员标签"}).json["conversations"], [])


if __name__ == "__main__":
    unittest.main()
