"""Proxy plumbing and proxy-test endpoint tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from test_core import BaseCase
from fap.platform import goofish, mtop


class ProxyPlumbingTests(unittest.TestCase):
    def test_mtop_client_passes_proxy(self):
        captured = {}

        class FakeClient:
            def __init__(self, **kw):
                captured.update(kw)

        with patch.object(mtop.httpx, "Client", FakeClient):
            mtop.MtopClient("c=1", proxy="http://127.0.0.1:7890")
        self.assertEqual(captured["proxy"], "http://127.0.0.1:7890")

    def test_adapter_uses_account_proxy(self):
        adapter = goofish.GoofishAdapter({"cookie": "c=1", "proxy": "http://127.0.0.1:7891"})
        self.assertEqual(adapter.proxy, "http://127.0.0.1:7891")
        captured = {}

        class FakeMtop:
            def __init__(self, cookie, proxy=None):
                captured["cookie"] = cookie
                captured["proxy"] = proxy

        with patch.object(goofish.mtop, "MtopClient", FakeMtop):
            adapter._mtop()
        self.assertEqual(captured["proxy"], "http://127.0.0.1:7891")


class ProxyEndpointTests(BaseCase):
    def _account(self, proxy=""):
        return self.client.post("/api/accounts", json={
            "name": "代理账号", "cookie": "real-cookie", "proxy": proxy,
        }).json["id"]

    def test_proxy_test_success(self):
        aid = self._account("http://127.0.0.1:7890")
        captured = {}

        class Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"ip": "203.0.113.9"}

        class FakeClient:
            def __init__(self, **kw):
                captured.update(kw)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def get(self, url, params=None):
                return Resp()

        with patch.object(httpx, "Client", FakeClient):
            r = self.client.post(f"/api/accounts/{aid}/proxy-test")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.json["ip"], "203.0.113.9")
        self.assertTrue(r.json["proxy_used"])
        self.assertEqual(captured["proxy"], "http://127.0.0.1:7890")

    def test_invalid_proxy_scheme(self):
        aid = self._account("socks5://127.0.0.1:1080")
        r = self.client.post(f"/api/accounts/{aid}/proxy-test")
        self.assertEqual(r.status_code, 400)

    def test_direct_connection(self):
        aid = self._account("")

        class Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"ip": "198.51.100.1"}

        class FakeClient:
            def __init__(self, **kw):
                self.kw = kw

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def get(self, url, params=None):
                return Resp()

        with patch.object(httpx, "Client", FakeClient):
            r = self.client.post(f"/api/accounts/{aid}/proxy-test")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json["proxy_used"])


import httpx  # noqa: E402  (imported for patching fap.api.httpx)

if __name__ == "__main__":
    unittest.main()
