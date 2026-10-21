"""Auto-polish tests: mtop calls, API validation and polish job."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from test_core import BaseCase
from fap import jobs
from fap.platform import goofish, mtop


class PolishHelperTests(unittest.TestCase):
    def test_normalize_item_ids(self):
        cfg = jobs.normalize_config("polish", {"account_id": 1, "item_ids": "1, 2\n3\n2"})
        self.assertEqual(cfg["item_ids"], ["1", "2", "3"])
        many = jobs.normalize_config("polish", {"account_id": 1, "item_ids": [str(i) for i in range(80)]})
        self.assertEqual(len(many["item_ids"]), 50)
        with self.assertRaises(jobs.JobError):
            jobs.normalize_config("polish", {"account_id": 1, "item_ids": []})


class PolishApiTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.demo = self.client.get("/api/accounts").json["accounts"][0]
        self.account_id = self.client.post("/api/accounts", json={
            "name": "擦亮账号", "cookie": "real-cookie",
        }).json["id"]

    def test_demo_account_rejected(self):
        self.assertEqual(self.client.post(f"/api/accounts/{self.demo['id']}/polish", json={
            "item_ids": "1",
        }).status_code, 400)
        self.assertEqual(self.client.get(f"/api/accounts/{self.demo['id']}/items").status_code, 400)

    def test_polish_all_success(self):
        with patch.object(goofish.GoofishAdapter, "polish_item", return_value={"ret": ["SUCCESS"]}):
            r = self.client.post(f"/api/accounts/{self.account_id}/polish", json={"item_ids": "11\n22"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.json["success"], 2)
        self.assertEqual(r.json["failed"], 0)

    def test_polish_partial_failure(self):
        err = mtop.MtopError("duplicate", "POLISH_DUPLICATE", ["POLISH_DUPLICATE"])
        with patch.object(goofish.GoofishAdapter, "polish_item", side_effect=[err, {"ok": True}]):
            r = self.client.post(f"/api/accounts/{self.account_id}/polish", json={"item_ids": ["11", "22"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["success"], 1)
        self.assertEqual(r.json["results"][0]["code"], "POLISH_DUPLICATE")

    def test_list_items(self):
        items = [{"item_id": "11", "title": "商品", "price": "9", "url": ""}]
        with patch.object(goofish.GoofishAdapter, "list_my_items", return_value=items):
            r = self.client.get(f"/api/accounts/{self.account_id}/items")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["items"][0]["item_id"], "11")

    def test_polish_job_runs(self):
        with patch.object(goofish.GoofishAdapter, "polish_item", return_value={"ok": True}):
            created = self.client.post("/api/jobs", json={
                "name": "自动擦亮", "type": "polish", "interval_seconds": 3600,
                "config": {"account_id": self.account_id, "item_ids": "11,22"},
            })
            self.assertEqual(created.status_code, 200, created.data)
            run = self.client.post(f"/api/jobs/{created.json['id']}/run")
        self.assertEqual(run.status_code, 200, run.data)
        self.assertIn("2/2", run.json["result"]["message"])
        self.assertEqual(run.json["result"]["status"], "success")


if __name__ == "__main__":
    unittest.main()
