"""Sold-list sync tests: extraction, endpoint idempotency and job mode."""

from __future__ import annotations

import unittest

from test_core import BaseCase
from fap.platform import mtop


class OrderExtractTests(unittest.TestCase):
    def test_extract_orders(self):
        payload = {"data": {"list": [
            {"bizOrderId": "111", "buyerNick": "张三", "itemTitle": "商品A",
             "totalAmount": "9.90", "quantity": 1, "orderStatusName": "待发货"},
            {"bizOrderId": "222", "buyerNick": "李四", "itemTitle": "商品B",
             "totalAmount": "20", "quantity": 2, "orderStatusName": "已发货"},
        ]}}
        rows = mtop.extract_orders(payload)
        self.assertEqual([r["bizOrderId"] for r in rows], ["111", "222"])
        self.assertEqual(rows[0]["buyerNick"], "张三")


class OrderListSyncTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.account = self.client.get("/api/accounts").json["accounts"][0]

    def test_sync_list_creates_and_updates(self):
        r = self.client.post("/api/orders/sync-list", json={"account_id": self.account["id"]})
        self.assertEqual(r.status_code, 200, r.data)
        res = r.json["result"]
        self.assertEqual(res["fetched"], 2)
        self.assertEqual(res["created"], 2)
        self.assertEqual(len(self.client.get("/api/orders").json["orders"]), 2)

        again = self.client.post("/api/orders/sync-list", json={"account_id": self.account["id"]})
        res2 = again.json["result"]
        self.assertEqual(res2["created"], 0)
        self.assertEqual(res2["updated"], 2)
        self.assertEqual(len(self.client.get("/api/orders").json["orders"]), 2)

    def test_job_list_mode(self):
        created = self.client.post("/api/jobs", json={
            "name": "列表同步任务", "type": "order_sync", "interval_seconds": 600,
            "config": {"account_id": self.account["id"]},
        })
        self.assertEqual(created.status_code, 200, created.data)
        run = self.client.post(f"/api/jobs/{created.json['id']}/run")
        self.assertEqual(run.status_code, 200, run.data)
        self.assertIn("拉取 2", run.json["result"]["message"])
        self.assertEqual(len(self.client.get("/api/orders").json["orders"]), 2)

    def test_single_order_still_works(self):
        r = self.client.post("/api/orders/sync", json={
            "account_id": self.account["id"], "order_id": "SINGLE-1",
        })
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.json["result"]["order"]["order_no"], "SINGLE-1")


if __name__ == "__main__":
    unittest.main()
