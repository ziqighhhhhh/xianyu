"""Goods offline tests: local/mtop, batch and item_id persistence."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from test_core import BaseCase
from fap.platform import goofish, mtop


class OfflineTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.demo = self.client.get("/api/accounts").json["accounts"][0]
        self.goods = self.client.get("/api/goods").json["goods"]

    def _real_goods(self, item_id="123456"):
        acc = self.client.post("/api/accounts", json={"name": "下架账号", "cookie": "real-cookie"}).json
        return self.client.post("/api/goods", json={
            "account_id": acc["id"], "title": "待下架商品", "price": 1, "stock": 1, "item_id": item_id,
        }).json["id"]

    def test_mock_goods_local_offline(self):
        gid = self.goods[0]["id"]
        r = self.client.post(f"/api/goods/{gid}/offline")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.json["result"]["local"])
        row = next(g for g in self.client.get("/api/goods").json["goods"] if g["id"] == gid)
        self.assertEqual(row["status"], "off_shelf")

    def test_real_goods_mtop_offline(self):
        gid = self._real_goods("888")
        with patch.object(goofish.GoofishAdapter, "offline_items", return_value={"ret": ["SUCCESS"]}) as call:
            r = self.client.post(f"/api/goods/{gid}/offline")
        self.assertEqual(r.status_code, 200, r.data)
        call.assert_called_once_with(["888"])
        row = next(g for g in self.client.get("/api/goods").json["goods"] if g["id"] == gid)
        self.assertEqual(row["status"], "off_shelf")

    def test_offline_failure_keeps_status(self):
        gid = self._real_goods("999")
        err = mtop.MtopError("session", "FAIL_SYS_SESSION_EXPIRED", ["FAIL_SYS_SESSION_EXPIRED"])
        with patch.object(goofish.GoofishAdapter, "offline_items", side_effect=err):
            r = self.client.post(f"/api/goods/{gid}/offline")
        self.assertEqual(r.status_code, 400)
        row = next(g for g in self.client.get("/api/goods").json["goods"] if g["id"] == gid)
        self.assertEqual(row["status"], "on_sale")

    def test_batch_offline(self):
        gid = self._real_goods("777")
        ids = [g["id"] for g in self.client.get("/api/goods").json["goods"]
               if g["account_id"] == self.demo["id"]]
        ids.append(gid)
        with patch.object(goofish.GoofishAdapter, "offline_items", return_value={"ok": True}):
            r = self.client.post("/api/goods/offline", json={"ids": ids})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.json["failed"], 0)
        self.assertTrue(all(g["status"] == "off_shelf" for g in self.client.get("/api/goods").json["goods"]
                            if g["id"] in ids))

    def test_publish_stores_item_id(self):
        mat = self.client.post("/api/materials", json={
            "account_id": self.demo["id"], "title": "带 itemId 的发布", "price": 2, "stock": 1,
        }).json
        r = self.client.post("/api/product-publish/publish", json={"material_id": mat["id"]})
        self.assertEqual(r.status_code, 200, r.data)
        gid = r.json["result"]["results"][0]["goods_id"]
        row = next(g for g in self.client.get("/api/goods").json["goods"] if g["id"] == gid)
        self.assertTrue(row["item_id"].startswith("mock-"))


if __name__ == "__main__":
    unittest.main()
