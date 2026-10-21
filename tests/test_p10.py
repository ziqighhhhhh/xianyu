"""Order rating tests: manual review, auto-comment, failures and validation."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from test_core import BaseCase
from fap.platform import mtop


class RatingTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.account = self.client.get("/api/accounts").json["accounts"][0]
        self.goods = self.client.get("/api/goods").json["goods"][0]

    def _delivered_order(self):
        r = self.client.post("/api/sim/order", json={"goods_id": self.goods["id"], "quantity": 1})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.json["order"]["status"], "delivered")
        return r.json["order"]["id"]

    def test_manual_rate(self):
        order_id = self._delivered_order()
        r = self.client.post(f"/api/orders/{order_id}/rate", json={"content": "发货很快"})
        self.assertEqual(r.status_code, 200, r.data)
        order = self.client.get(f"/api/orders/{order_id}").json["order"]
        self.assertEqual(order["rate_status"], "success")
        self.assertEqual(order["rate_content"], "发货很快")
        self.assertTrue(order["rated_at"])
        self.assertEqual(self.client.post(f"/api/orders/{order_id}/rate", json={}).status_code, 400)

    def test_auto_comment_on_delivery(self):
        self.client.patch(f"/api/accounts/{self.account['id']}", json={
            "auto_comment": True, "comment_template": "感谢购买，欢迎再来",
        })
        order_id = self._delivered_order()
        order = self.client.get(f"/api/orders/{order_id}").json["order"]
        self.assertEqual(order["rate_status"], "success")
        self.assertEqual(order["rate_content"], "感谢购买，欢迎再来")

    def test_rate_failure_recorded(self):
        order_id = self._delivered_order()
        err = mtop.MtopError("session", "FAIL_SYS_SESSION_EXPIRED", ["FAIL_SYS_SESSION_EXPIRED"])
        with patch("fap.platform.mock.MockAdapter.rate_order", side_effect=err):
            r = self.client.post(f"/api/orders/{order_id}/rate", json={"content": "好"})
        self.assertEqual(r.status_code, 400)
        order = self.client.get(f"/api/orders/{order_id}").json["order"]
        self.assertEqual(order["rate_status"], "failed")
        self.assertFalse(order["rated_at"])


if __name__ == "__main__":
    unittest.main()
