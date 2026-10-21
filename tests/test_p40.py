"""LWP WebSocket diagnostic tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from test_core import BaseCase
from fap.platform import goofish, mtop


class WsTestTests(BaseCase):
    def test_token_and_handshake(self):
        aid = self.client.post("/api/accounts", json={"name": "WS账号", "cookie": "real-ws"}).json["id"]
        with patch.object(goofish.GoofishAdapter, "fetch_ws_token", return_value={"token": "tok-1"}), \
             patch("fap.api.lwp.exchange", return_value={"connected": True, "responses": []}) as exchange:
            r = self.client.post(f"/api/accounts/{aid}/ws-test")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.json["result"]["token_ok"])
        self.assertTrue(r.json["result"]["connected"])
        self.assertEqual(exchange.call_args.args[0], "tok-1")
        self.assertEqual(exchange.call_args.args[1][0]["lwp"], "/reg")

    def test_token_failure(self):
        aid = self.client.post("/api/accounts", json={"name": "WS失败", "cookie": "real"}).json["id"]
        err = mtop.MtopError("session", "FAIL_SYS_SESSION_EXPIRED", ["FAIL_SYS_SESSION_EXPIRED"])
        with patch.object(goofish.GoofishAdapter, "fetch_ws_token", side_effect=err):
            r = self.client.post(f"/api/accounts/{aid}/ws-test")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json["stage"], "token")
        self.assertEqual(r.json["mtop_code"], "FAIL_SYS_SESSION_EXPIRED")

    def test_mock_account_rejected(self):
        demo = self.client.get("/api/accounts").json["accounts"][0]
        self.assertEqual(self.client.post(f"/api/accounts/{demo['id']}/ws-test").status_code, 400)

    def test_operator_isolation(self):
        aid = self.client.post("/api/accounts", json={"name": "管理员WS", "cookie": "real"}).json["id"]
        self.client.post("/api/users", json={"username": "op25", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op25", "password": "op123456"})
        self.assertEqual(op.post(f"/api/accounts/{aid}/ws-test").status_code, 404)


if __name__ == "__main__":
    unittest.main()
