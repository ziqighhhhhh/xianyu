"""Account profile refresh tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from test_core import BaseCase
from fap.platform import goofish, mtop


class ProfileRefreshTests(BaseCase):
    def test_refresh_updates_account(self):
        aid = self.client.post("/api/accounts", json={
            "name": "资料账号", "cookie": "real-cookie",
        }).json["id"]
        with patch.object(goofish.GoofishAdapter, "fetch_profile", return_value={
            "nickname": "小鱼", "avatar_url": "https://img.example.com/a.png", "platform_user_id": "12345",
        }):
            r = self.client.post(f"/api/accounts/{aid}/refresh-info")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.json["profile"]["nickname"], "小鱼")
        acct = next(a for a in self.client.get("/api/accounts").json["accounts"] if a["id"] == aid)
        self.assertEqual(acct["nickname"], "小鱼")
        self.assertEqual(acct["platform_user_id"], "12345")

    def test_demo_account_rejected(self):
        demo = self.client.get("/api/accounts").json["accounts"][0]
        self.assertEqual(self.client.post(f"/api/accounts/{demo['id']}/refresh-info").status_code, 400)

    def test_mtop_error(self):
        aid = self.client.post("/api/accounts", json={"name": "资料失败", "cookie": "real"}).json["id"]
        err = mtop.MtopError("session", "FAIL_SYS_SESSION_EXPIRED", ["FAIL_SYS_SESSION_EXPIRED"])
        with patch.object(goofish.GoofishAdapter, "fetch_profile", side_effect=err):
            r = self.client.post(f"/api/accounts/{aid}/refresh-info")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json["mtop_code"], "FAIL_SYS_SESSION_EXPIRED")

    def test_operator_isolation(self):
        self.client.post("/api/users", json={"username": "op19", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op19", "password": "op123456"})
        aid = self.client.post("/api/accounts", json={"name": "管理员资料", "cookie": "real"}).json["id"]
        self.assertEqual(op.post(f"/api/accounts/{aid}/refresh-info").status_code, 404)


if __name__ == "__main__":
    unittest.main()
