"""Platform dummy-consign shipping tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from test_core import BaseCase
from fap.platform import goofish, mtop


class ShipTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.account = self.client.get("/api/accounts").json["accounts"][0]
        self.goods = self.client.get("/api/goods").json["goods"][0]

    def _delivered(self):
        r = self.client.post("/api/sim/order", json={"goods_id": self.goods["id"], "quantity": 1})
        return r.json["order"]["id"]

    def test_mock_ship(self):
        oid = self._delivered()
        r = self.client.post(f"/api/orders/{oid}/ship")
        self.assertEqual(r.status_code, 200, r.data)
        order = self.client.get(f"/api/orders/{oid}").json["order"]
        self.assertEqual(order["ship_status"], "success")
        self.assertTrue(order["platform_shipped_at"])
        self.assertEqual(self.client.post(f"/api/orders/{oid}/ship").status_code, 400)

    def test_real_ship_calls_adapter(self):
        acc = self.client.post("/api/accounts", json={"name": "发货账号", "cookie": "real-cookie"}).json
        goods = self.client.post("/api/goods", json={
            "account_id": acc["id"], "title": "发货商品", "price": 1, "stock": 5,
        }).json
        self.client.post("/api/autosell/rules", json={
            "name": "发货规则", "goods_id": goods["id"], "delivery_type": "fixed", "content": "KEY",
        })
        oid = self.client.post("/api/sim/order", json={"goods_id": goods["id"], "quantity": 1}).json["order"]["id"]
        with patch.object(goofish.GoofishAdapter, "ship_order", return_value={"ret": ["SUCCESS"]}) as call:
            r = self.client.post(f"/api/orders/{oid}/ship")
        self.assertEqual(r.status_code, 200, r.data)
        call.assert_called_once()

    def test_ship_failure(self):
        oid = self._delivered()
        err = mtop.MtopError("session", "FAIL_SYS_SESSION_EXPIRED", ["FAIL_SYS_SESSION_EXPIRED"])
        with patch("fap.platform.mock.MockAdapter.ship_order", side_effect=err):
            r = self.client.post(f"/api/orders/{oid}/ship")
        self.assertEqual(r.status_code, 400)
        order = self.client.get(f"/api/orders/{oid}").json["order"]
        self.assertEqual(order["ship_status"], "failed")

    def test_only_delivered_can_ship(self):
        r = self.client.post("/api/orders/sync", json={
            "account_id": self.account["id"], "order_id": "SHIP-PAID-1",
        })
        oid = r.json["result"]["order"]["id"]
        self.assertEqual(self.client.post(f"/api/orders/{oid}/ship").status_code, 400)


if __name__ == "__main__":
    unittest.main()
