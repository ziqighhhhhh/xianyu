"""mtop signing, token retry, response parsing and diagnostic API tests."""

from __future__ import annotations

import json
import unittest
import urllib.parse
from unittest.mock import patch

import httpx

from test_core import BaseCase
from fap.platform import goofish, mtop


class MtopClientTests(unittest.TestCase):
    def test_token_retry_and_signature(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            params = dict(request.url.params)
            form = urllib.parse.parse_qs(request.content.decode())
            data = json.loads(form["data"][0])
            if len(calls) == 1:
                return httpx.Response(
                    200,
                    json={"ret": ["FAIL_SYS_TOKEN_EMPTY::令牌为空"]},
                    headers={"Set-Cookie": "_m_h5_tk=abc123_999; Path=/"},
                )
            token = (request.headers.get("cookie") or "").split("_m_h5_tk=")[-1].split("_")[0]
            expected = mtop.sign(token, params["t"], json.dumps(data, separators=(",", ":")))
            self.assertEqual(params["sign"], expected)
            self.assertEqual(params["appKey"], "34839810")
            return httpx.Response(200, json={"ret": ["SUCCESS::调用成功"], "data": {"ok": True}})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        m = mtop.MtopClient("", client=client)
        payload = m.call("mtop.test.api", {"a": 1})
        self.assertEqual(payload["data"], {"ok": True})
        self.assertEqual(len(calls), 2)

    def test_jsonp_and_error_mapping(self):
        def jsonp_handler(request):
            return httpx.Response(200, text='mtopjsonp1({"ret":["SUCCESS::ok"],"data":{"n":1}});')

        m = mtop.MtopClient("", client=httpx.Client(transport=httpx.MockTransport(jsonp_handler)))
        self.assertEqual(m.call("mtop.test.api", {})["data"], {"n": 1})

        def risk_handler(request):
            return httpx.Response(200, json={
                "ret": ["RGV587_ERROR::SM::哎哟喂,被挤爆啦"], "data": {},
            })

        m2 = mtop.MtopClient("", client=httpx.Client(transport=httpx.MockTransport(risk_handler)))
        with self.assertRaises(mtop.MtopError) as ctx:
            m2.call("mtop.test.api", {})
        self.assertEqual(ctx.exception.code, "RGV587_ERROR")

    def test_cookie_and_price_helpers(self):
        cookies = mtop.parse_cookie_header("unb=1; cookie2=abc; _m_h5_tk=tk_123")
        self.assertEqual(cookies["unb"], "1")
        self.assertEqual(cookies["_m_h5_tk"], "tk_123")
        self.assertEqual(goofish._parse_price("¥1,299.00"), 1299.0)
        self.assertEqual(goofish._parse_price([{"text": "88"}]), 88.0)
        self.assertIsNone(goofish._parse_price("面议"))

    def test_extract_search_items(self):
        payload = {"data": {"resultList": [
            {"data": {"item": {"itemId": "111", "main": {
                "exContent": {"title": "九成新显卡", "price": [{"text": "3200"}]},
            }}}},
            {"data": {"item": {"itemId": "222", "main": {
                "exContent": {"title": "显示器", "price": [{"text": "600"}]},
            }}}},
        ]}}
        rows = mtop.extract_search_items(payload)
        self.assertEqual([r["item_id"] for r in rows], ["111", "222"])
        self.assertEqual(rows[0]["price"], "3200")


class MtopApiTests(BaseCase):
    def _create_account(self):
        r = self.client.post("/api/accounts", json={"name": "mtop账号", "cookie": "real-cookie"})
        return r.json["id"]

    def test_demo_account_rejected(self):
        demo = self.client.get("/api/accounts").json["accounts"][0]
        self.assertEqual(self.client.post(f"/api/accounts/{demo['id']}/mtop/test", json={}).status_code, 400)

    def test_fetch_item_endpoint(self):
        account_id = self._create_account()
        with patch.object(goofish.GoofishAdapter, "fetch_item", return_value={"item": {"itemId": "1"}}):
            r = self.client.post(f"/api/accounts/{account_id}/mtop/test", json={"item_id": "1"})
            self.assertEqual(r.status_code, 200, r.data)
            self.assertEqual(r.json["data"]["item"]["itemId"], "1")

    def test_mtop_error_mapped(self):
        account_id = self._create_account()
        err = mtop.MtopError("risk", "RGV587_ERROR", ["RGV587_ERROR::SM"])
        with patch.object(goofish.GoofishAdapter, "fetch_item", side_effect=err):
            r = self.client.post(f"/api/accounts/{account_id}/mtop/test", json={"item_id": "1"})
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.json["mtop_code"], "RGV587_ERROR")


if __name__ == "__main__":
    unittest.main()
