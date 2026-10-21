"""QR login tests (passport calls mocked; no live account required)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from test_core import BaseCase
from fap.platform import goofish


class QRPureTests(unittest.TestCase):
    def test_lg_token_and_status_mapping(self):
        code = "https://passport.goofish.com/qrcodeCheck.htm?lgToken=abc123_0000000&_from=havana"
        self.assertEqual(goofish._lg_token(code), "abc123_0000000")
        self.assertEqual(goofish.QR_STATUS["NEW"][0], "waiting")
        self.assertEqual(goofish.QR_STATUS["CONFIRMED"][0], "confirmed")

    def test_check_login_empty_cookie(self):
        result = goofish.check_login("")
        self.assertFalse(result["ok"])


class QRApiTests(BaseCase):
    def _create_account(self, cookie="placeholder-cookie"):
        resp = self.client.post("/api/accounts", json={"name": "扫码账号", "cookie": cookie})
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.json["id"]

    def test_mock_account_cannot_qr(self):
        accounts = self.client.get("/api/accounts").json["accounts"]
        demo = accounts[0]
        resp = self.client.post(f"/api/accounts/{demo['id']}/qr/start")
        self.assertEqual(resp.status_code, 400)

    def test_qr_waiting_status(self):
        account_id = self._create_account()
        with patch.object(goofish, "start_qr_login", return_value={
            "session_id": "sess-1", "qr_image": "data:image/png;base64,AAAA",
            "code_content": "https://passport.goofish.com/qrcodeCheck.htm?lgToken=x", "expires_in": 300,
        }), patch.object(goofish, "poll_qr_login", return_value={
            "status": "waiting", "message": "等待扫码", "raw_status": "NEW",
        }):
            start = self.client.post(f"/api/accounts/{account_id}/qr/start")
            self.assertEqual(start.status_code, 200, start.data)
            self.assertTrue(start.json["result"]["qr_image"].startswith("data:image/png"))
            poll = self.client.get(f"/api/accounts/{account_id}/qr/status/sess-1")
            self.assertEqual(poll.status_code, 200)
            self.assertEqual(poll.json["result"]["status"], "waiting")

    def test_qr_confirmed_saves_cookie(self):
        account_id = self._create_account()
        cookie = "unb=123; cookie2=abc; _m_h5_tk=tk_1"
        with patch.object(goofish, "start_qr_login", return_value={
            "session_id": "sess-2", "qr_image": "data:image/png;base64,AAAA",
            "code_content": "x", "expires_in": 300,
        }), patch.object(goofish, "poll_qr_login", return_value={
            "status": "confirmed", "message": "扫码成功", "cookie": cookie,
        }), patch.object(goofish, "check_login", return_value={"ok": True, "message": "登录有效"}):
            self.client.post(f"/api/accounts/{account_id}/qr/start")
            poll = self.client.get(f"/api/accounts/{account_id}/qr/status/sess-2")
            self.assertEqual(poll.status_code, 200, poll.data)
            self.assertEqual(poll.json["result"]["status"], "confirmed")
            self.assertTrue(poll.json["result"]["cookie_saved"])
        accounts = self.client.get("/api/accounts").json["accounts"]
        row = next(a for a in accounts if a["id"] == account_id)
        self.assertEqual(row["cookie"], cookie)
        self.assertEqual(row["status"], "online")
        # the cookie must never be echoed back by the status endpoint
        self.assertNotIn("unb=123", poll.get_data(as_text=True))

    def test_qr_confirmed_but_invalid_login(self):
        account_id = self._create_account()
        with patch.object(goofish, "start_qr_login", return_value={
            "session_id": "sess-3", "qr_image": "data:image/png;base64,AAAA",
            "code_content": "x", "expires_in": 300,
        }), patch.object(goofish, "poll_qr_login", return_value={
            "status": "confirmed", "message": "扫码成功", "cookie": "bad=1",
        }), patch.object(goofish, "check_login", return_value={"ok": False, "message": "Cookie 无效"}):
            self.client.post(f"/api/accounts/{account_id}/qr/start")
            poll = self.client.get(f"/api/accounts/{account_id}/qr/status/sess-3")
            self.assertEqual(poll.status_code, 400)
        accounts = self.client.get("/api/accounts").json["accounts"]
        row = next(a for a in accounts if a["id"] == account_id)
        self.assertEqual(row["cookie"], "placeholder-cookie")
        self.assertNotEqual(row["status"], "online")


if __name__ == "__main__":
    unittest.main()
