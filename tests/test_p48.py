"""Experimental LWP send endpoint tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from test_core import BaseCase
from fap.platform import goofish


class LWPSendTests(BaseCase):
    def _account(self):
        return self.client.post("/api/accounts", json={"name": "LWP账号", "cookie": "real-lwp"}).json["id"]

    def test_disabled_by_default(self):
        aid = self._account()
        r = self.client.post(f"/api/accounts/{aid}/lwp/send", json={
            "conversation_id": "c1", "receiver_id": "u1", "text": "hi"})
        self.assertEqual(r.status_code, 403)

    def test_enabled_with_mock(self):
        aid = self._account()
        with patch.dict("os.environ", {"FAP_ENABLE_LWP_SEND": "1"}), \
             patch.object(goofish.GoofishAdapter, "send_lwp_text",
                          return_value={"connected": True, "responses": []}) as send:
            r = self.client.post(f"/api/accounts/{aid}/lwp/send", json={
                "conversation_id": "c1", "receiver_id": "u1", "text": "hi"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.json["result"]["connected"])
        send.assert_called_once_with("c1", "u1", "hi")

    def test_validation(self):
        aid = self._account()
        with patch.dict("os.environ", {"FAP_ENABLE_LWP_SEND": "1"}):
            self.assertEqual(self.client.post(f"/api/accounts/{aid}/lwp/send", json={}).status_code, 400)
            demo = next(a for a in self.client.get("/api/accounts").json["accounts"]
                        if a["name"] == "演示账号")["id"]
            self.assertEqual(self.client.post(f"/api/accounts/{demo}/lwp/send", json={
                "conversation_id": "c", "receiver_id": "u", "text": "hi"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
