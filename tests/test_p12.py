"""Real publish payload, ownership and failure tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from test_core import BaseCase
from fap.platform import goofish, mtop


class PublishPayloadTests(unittest.TestCase):
    def test_publish_payload_and_item_id(self):
        captured = {}

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def call(self, api, data, **kw):
                captured["api"] = api
                captured["data"] = data
                return {"data": {"itemId": "999"}}

        with patch.object(goofish.mtop, "MtopClient", FakeClient):
            adapter = goofish.GoofishAdapter({"cookie": "real-cookie"})
            result = adapter.publish_item({
                "title": "测试商品", "description": "描述", "price": 12.5,
                "stock": 3, "image_url": "https://img.example.com/a.jpg",
            })
        self.assertEqual(captured["api"], mtop.PUBLISH_API)
        self.assertEqual(captured["data"]["title"], "测试商品")
        self.assertEqual(captured["data"]["price"], "12.5")
        self.assertEqual(captured["data"]["quantity"], 3)
        self.assertEqual(captured["data"]["images"], ["https://img.example.com/a.jpg"])
        self.assertEqual(result["item_id"], "999")


class PublishApiTests(BaseCase):
    def test_operator_publish_creates_owned_goods(self):
        self.client.post("/api/users", json={"username": "op7", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op7", "password": "op123456"})
        acc = op.post("/api/accounts", json={"name": "op7-acc", "cookie": "real-cookie"}).json
        mat = op.post("/api/materials", json={
            "account_id": acc["id"], "title": "运营发布商品", "price": 8.8, "stock": 2,
        }).json
        with patch.object(goofish.GoofishAdapter, "publish_item", return_value={
            "ok": True, "item_id": "777", "url": "https://www.goofish.com/item?id=777",
        }):
            r = op.post("/api/product-publish/publish", json={"material_id": mat["id"]})
        self.assertEqual(r.status_code, 200, r.data)
        op_id = op.get("/api/auth/me").json["user"]["id"]
        goods = self.client.get("/api/goods").json["goods"]
        row = next(g for g in goods if g["id"] == r.json["result"]["results"][0]["goods_id"])
        self.assertEqual(row["owner_id"], op_id)

    def test_publish_failure_is_logged(self):
        acc = self.client.post("/api/accounts", json={"name": "发布账号", "cookie": "real-cookie"}).json
        mat = self.client.post("/api/materials", json={
            "account_id": acc["id"], "title": "失败商品", "price": 1, "stock": 1,
        }).json
        err = mtop.MtopError("session", "FAIL_SYS_SESSION_EXPIRED", ["FAIL_SYS_SESSION_EXPIRED"])
        with patch.object(goofish.GoofishAdapter, "publish_item", side_effect=err):
            r = self.client.post("/api/product-publish/publish", json={"material_id": mat["id"]})
        self.assertEqual(r.status_code, 400)
        logs = self.client.get("/api/product-publish/logs").json["logs"]
        self.assertEqual(logs[0]["status"], "failed")
        self.assertIn("SESSION_EXPIRED", logs[0]["message"])


if __name__ == "__main__":
    unittest.main()
