"""Buyer tag tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class BuyerTagTests(BaseCase):
    def test_upsert_and_list(self):
        r = self.client.post("/api/buyer-tags", json={"buyer": "老买家", "tag": "老客", "note": "复购 3 次"})
        self.assertEqual(r.status_code, 200, r.data)
        first = r.json["tag"]
        again = self.client.post("/api/buyer-tags", json={"buyer": "老买家", "tag": "老客", "note": "复购 5 次"})
        self.assertEqual(again.json["tag"]["id"], first["id"])
        self.assertEqual(again.json["tag"]["note"], "复购 5 次")
        tags = self.client.get("/api/buyer-tags").json["tags"]
        self.assertEqual(len([t for t in tags if t["buyer"] == "老买家"]), 1)
        found = self.client.get("/api/buyer-tags", query_string={"q": "复购 5"}).json["tags"]
        self.assertEqual(found[0]["buyer"], "老买家")

    def test_validation_and_delete(self):
        self.assertEqual(self.client.post("/api/buyer-tags", json={"buyer": "", "tag": "x"}).status_code, 400)
        t = self.client.post("/api/buyer-tags", json={"buyer": "待删", "tag": "临时"}).json["tag"]
        self.assertEqual(self.client.delete(f"/api/buyer-tags/{t['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/buyer-tags/{t['id']}").status_code, 404)

    def test_operator_isolation(self):
        admin_tag = self.client.post("/api/buyer-tags", json={"buyer": "管理员买家", "tag": "VIP"}).json["tag"]
        self.client.post("/api/users", json={"username": "op26", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op26", "password": "op123456"})
        self.assertEqual(op.get("/api/buyer-tags").json["tags"], [])
        self.assertEqual(op.delete(f"/api/buyer-tags/{admin_tag['id']}").status_code, 404)
        op.post("/api/buyer-tags", json={"buyer": "运营买家", "tag": "新客"})
        self.assertEqual([t["buyer"] for t in op.get("/api/buyer-tags").json["tags"]], ["运营买家"])


if __name__ == "__main__":
    unittest.main()
