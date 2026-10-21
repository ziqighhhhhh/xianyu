"""Paginated order-list sync tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class PaginationTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.account = self.client.get("/api/accounts").json["accounts"][0]

    def test_two_pages(self):
        r = self.client.post("/api/orders/sync-list", json={
            "account_id": self.account["id"], "pages": 2,
        })
        self.assertEqual(r.status_code, 200, r.data)
        res = r.json["result"]
        self.assertEqual(res["fetched"], 3)
        self.assertEqual(res["created"], 3)
        self.assertEqual(res["pages"], 2)
        orders = self.client.get("/api/orders").json["orders"]
        self.assertEqual(len(orders), 3)
        self.assertIn("MOCK-SOLD-3", [o["order_no"] for o in orders])

    def test_limit_caps_results(self):
        r = self.client.post("/api/orders/sync-list", json={
            "account_id": self.account["id"], "pages": 3, "limit": 2,
        })
        res = r.json["result"]
        self.assertEqual(len(res["order_ids"]), 2)
        self.assertEqual(len(self.client.get("/api/orders").json["orders"]), 2)

    def test_job_pages_config(self):
        created = self.client.post("/api/jobs", json={
            "name": "多页同步", "type": "order_sync", "interval_seconds": 600,
            "config": {"account_id": self.account["id"], "pages": 2},
        })
        self.assertEqual(created.status_code, 200, created.data)
        run = self.client.post(f"/api/jobs/{created.json['id']}/run")
        self.assertEqual(run.status_code, 200, run.data)
        self.assertIn("拉取 3", run.json["result"]["message"])
        self.assertEqual(len(self.client.get("/api/orders").json["orders"]), 3)


if __name__ == "__main__":
    unittest.main()
