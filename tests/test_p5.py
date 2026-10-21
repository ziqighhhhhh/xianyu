"""Multi-user isolation tests: operator must not see or mutate admin data."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class MultiUserTests(BaseCase):
    def setUp(self):
        super().setUp()
        r = self.client.post("/api/users", json={
            "username": "op1", "password": "op123456", "role": "operator",
        })
        self.assertEqual(r.status_code, 200, r.data)
        self.op_id = r.json["id"]
        self.op = self.app.test_client()
        login = self.op.post("/api/auth/login", json={"username": "op1", "password": "op123456"})
        self.assertEqual(login.status_code, 200, login.data)

    def test_operator_sees_empty_core_data(self):
        self.assertEqual(self.op.get("/api/accounts").json["accounts"], [])
        self.assertEqual(self.op.get("/api/goods").json["goods"], [])
        self.assertEqual(self.op.get("/api/orders").json["orders"], [])
        self.assertEqual(self.op.get("/api/conversations").json["conversations"], [])
        self.assertEqual(self.op.get("/api/autoreply/rules").json["rules"], [])
        stats = self.op.get("/api/dashboard").json["stats"]
        self.assertEqual(stats["accounts"], 0)
        self.assertEqual(stats["orders_today"], 0)

    def test_admin_only_endpoints(self):
        self.assertEqual(self.op.get("/api/settings").status_code, 403)
        self.assertEqual(self.op.get("/api/users").status_code, 403)
        self.assertEqual(self.op.get("/api/backups").status_code, 403)
        # operators may read their own audit trail
        self.assertEqual(self.op.get("/api/audit-logs").status_code, 200)
        self.assertEqual(self.op.post("/api/backups").status_code, 403)

    def test_operator_cannot_read_or_mutate_admin_rows(self):
        goods = self.client.get("/api/goods").json["goods"]
        gid = goods[0]["id"]
        account = self.client.get("/api/accounts").json["accounts"][0]
        # admin creates an order from the seeded goods
        order = self.client.post("/api/sim/order", json={"goods_id": gid, "quantity": 1}).json["order"]
        self.assertEqual(self.op.get(f"/api/orders/{order['id']}").status_code, 404)
        self.assertEqual(self.op.post(f"/api/orders/{order['id']}/deliver", json={}).status_code, 404)
        self.assertEqual(self.op.patch(f"/api/goods/{gid}", json={"title": "hacked"}).status_code, 404)
        self.assertEqual(self.op.delete(f"/api/goods/{gid}").status_code, 404)
        self.assertEqual(self.op.patch(f"/api/accounts/{account['id']}", json={"name": "hacked"}).status_code, 404)
        self.assertEqual(self.op.post(f"/api/accounts/{account['id']}/connect").status_code, 404)

    def test_operator_own_data_and_admin_visibility(self):
        acc = self.op.post("/api/accounts", json={"name": "op-account", "cookie": "demo-op"}).json
        goods = self.op.post("/api/goods", json={
            "title": "op-goods", "price": 3.5, "stock": 2, "account_id": acc["id"],
        }).json
        self.assertTrue(acc["id"])
        self.assertTrue(goods["id"])
        self.assertEqual(len(self.op.get("/api/accounts").json["accounts"]), 1)
        self.assertEqual(len(self.op.get("/api/goods").json["goods"]), 1)
        # admin sees both admin and operator rows
        self.assertGreaterEqual(len(self.client.get("/api/accounts").json["accounts"]), 2)
        self.assertGreaterEqual(len(self.client.get("/api/goods").json["goods"]), 4)
        # operator's order works against its own goods
        order = self.op.post("/api/sim/order", json={"goods_id": goods["id"], "quantity": 1}).json
        self.assertEqual(order["order"]["status"], "failed")  # no delivery rule, but visible
        own = self.op.get("/api/orders").json["orders"]
        self.assertEqual(len(own), 1)
        self.assertEqual(self.op.get(f"/api/orders/{order['order']['id']}").status_code, 200)

    def test_operator_rules_are_isolated(self):
        rule = self.op.post("/api/autoreply/rules", json={
            "name": "op-rule", "match_type": "keyword", "pattern": "在吗",
            "reply_type": "text", "content": "在的",
        }).json
        self.assertTrue(rule["id"])
        self.assertEqual(len(self.op.get("/api/autoreply/rules").json["rules"]), 1)
        admin_rules = self.client.get("/api/autoreply/rules").json["rules"]
        self.assertTrue(any(r["name"] == "op-rule" for r in admin_rules))
        # operator cannot touch the admin's seeded rule
        seeded = next(r for r in admin_rules if r["id"] != rule["id"])
        self.assertEqual(self.op.delete(f"/api/autoreply/rules/{seeded['id']}").status_code, 404)

    def test_inactive_user_cannot_login_or_reuse_session(self):
        self.client.patch(f"/api/users/{self.op_id}", json={"is_active": False})
        self.assertEqual(self.op.get("/api/accounts").status_code, 401)
        fresh = self.app.test_client()
        self.assertEqual(fresh.post("/api/auth/login", json={
            "username": "op1", "password": "op123456",
        }).status_code, 401)

    def test_admin_guards(self):
        me = self.client.get("/api/auth/me").json["user"]
        self.assertEqual(self.client.patch(f"/api/users/{me['id']}", json={"role": "operator"}).status_code, 400)
        self.assertEqual(self.client.delete(f"/api/users/{me['id']}").status_code, 400)
        # operator with data cannot be deleted yet
        acc = self.op.post("/api/accounts", json={"name": "op-acc", "cookie": "demo-op"}).json
        self.assertTrue(acc["id"])
        self.assertEqual(self.client.delete(f"/api/users/{self.op_id}").status_code, 400)


if __name__ == "__main__":
    unittest.main()
