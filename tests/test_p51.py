"""Buyer blacklist tests (CRUD + auto-reply bypass)."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class BuyerBlacklistTests(BaseCase):
    def test_crud(self):
        r = self.client.post("/api/buyer-blacklist", json={"buyer": "捣乱买家", "reason": "恶意砍价"})
        self.assertEqual(r.status_code, 200, r.data)
        first = r.json["entry"]
        again = self.client.post("/api/buyer-blacklist", json={"buyer": "捣乱买家", "reason": "重复"})
        self.assertEqual(again.json["entry"]["id"], first["id"])
        self.assertEqual(again.json["entry"]["reason"], "重复")
        rows = self.client.get("/api/buyer-blacklist").json["blacklist"]
        self.assertEqual(len([x for x in rows if x["buyer"] == "捣乱买家"]), 1)
        self.assertEqual(self.client.delete(f"/api/buyer-blacklist/{first['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/buyer-blacklist/{first['id']}").status_code, 404)
        self.assertEqual(self.client.post("/api/buyer-blacklist", json={"buyer": ""}).status_code, 400)

    def test_auto_reply_skips_blacklisted(self):
        account = self.client.get("/api/accounts").json["accounts"][0]
        self.client.post("/api/buyer-blacklist", json={"buyer": "黑名单买家", "reason": "test"})
        self.client.post("/api/sim/message", json={
            "account_id": account["id"], "buyer": "黑名单买家", "text": "在吗？"})
        conv = next(c for c in self.client.get("/api/conversations").json["conversations"]
                    if c["buyer"] == "黑名单买家")
        msgs = self.client.get(f"/api/conversations/{conv['id']}/messages").json["messages"]
        self.assertFalse([m for m in msgs if m["direction"] == "out"])

    def test_unblock_restores_auto_reply(self):
        account = self.client.get("/api/accounts").json["accounts"][0]
        entry = self.client.post("/api/buyer-blacklist", json={"buyer": "恢复买家"}).json["entry"]
        self.client.post("/api/sim/message", json={
            "account_id": account["id"], "buyer": "恢复买家", "text": "在吗？"})
        self.client.delete(f"/api/buyer-blacklist/{entry['id']}")
        self.client.post("/api/sim/message", json={
            "account_id": account["id"], "buyer": "恢复买家", "text": "发货时间？"})
        conv = next(c for c in self.client.get("/api/conversations").json["conversations"]
                    if c["buyer"] == "恢复买家")
        msgs = self.client.get(f"/api/conversations/{conv['id']}/messages").json["messages"]
        self.assertTrue([m for m in msgs if m["direction"] == "out"])

    def test_operator_isolation(self):
        admin_entry = self.client.post("/api/buyer-blacklist", json={"buyer": "管理员黑名单"}).json["entry"]
        self.client.post("/api/users", json={"username": "op32", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op32", "password": "op123456"})
        self.assertEqual(op.get("/api/buyer-blacklist").json["blacklist"], [])
        self.assertEqual(op.delete(f"/api/buyer-blacklist/{admin_entry['id']}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
