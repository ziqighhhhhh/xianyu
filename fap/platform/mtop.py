"""Minimal mtop (H5 API) client for goofish.

Implements the standard H5 signing scheme:

    token = cookie["_m_h5_tk"].split("_")[0]
    sign  = md5(f"{token}&{t}&{appKey}&{data}")

Requests are sent as form data to
``https://h5api.m.goofish.com/h5/{api}/{version}/`` with `jsv/appKey/t/sign/api/v/
type/dataType/timeout` in the query string.  A missing/expired token triggers one
automatic retry after the server sets a fresh ``_m_h5_tk`` cookie.

Platform risk control can still reject calls (e.g. RGV587); those errors are
mapped to :class:`MtopError` so callers can show a useful message.
"""

from __future__ import annotations

import hashlib
import json
import re
import time

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
APP_KEY = "34839810"
API_HOST = "https://h5api.m.goofish.com"
JSONP_RE = re.compile(r"^[^()]*\((.*)\)\s*;?\s*$", re.S)

SEARCH_API = "mtop.taobao.idlemtopsearch.pc.search"
DETAIL_API = "mtop.taobao.idle.pc.detail"
ORDER_DETAIL_API = "mtop.idle.web.trade.order.detail"
SOLD_ORDERS_API = "mtop.taobao.idle.trade.merchant.sold.get"
ITEM_LIST_API = "mtop.idle.web.xyh.item.list"
POLISH_API = "mtop.taobao.idle.item.polish"
RATE_API = "mtop.taobao.idle.merchant.rate.create"
PUBLISH_API = "mtop.idle.pc.idleitem.publish"
OFFLINE_API = "mtop.alibaba.idle.seller.pc.item.batch.offline"
CONSIGN_API = "mtop.taobao.idle.logistic.consign.dummy"
LOGINUSER_API = "mtop.taobao.idlemessage.pc.loginuser.get"
WS_TOKEN_API = "mtop.taobao.idlemessage.pc.login.token"


class MtopError(RuntimeError):
    def __init__(self, message: str, code: str = "", ret: list | None = None):
        super().__init__(message)
        self.code = code
        self.ret = ret or []


def parse_cookie_header(text: str) -> dict:
    cookies: dict[str, str] = {}
    for part in (text or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if key:
            cookies[key] = value.strip()
    return cookies


def sign(token: str, t: str, data: str, app_key: str = APP_KEY) -> str:
    return hashlib.md5(f"{token}&{t}&{app_key}&{data}".encode("utf-8")).hexdigest()


def _parse_body(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("{"):
        return json.loads(text)
    m = JSONP_RE.match(text)
    if m:
        return json.loads(m.group(1))
    raise MtopError("无法解析 mtop 响应（既不是 JSON 也不是 JSONP）")


def _ret_code(payload: dict) -> str:
    ret = payload.get("ret") or []
    if not ret:
        return ""
    return str(ret[0]).split("::")[0]


class MtopClient:
    def __init__(self, cookie: str = "", app_key: str = APP_KEY, client: httpx.Client | None = None,
                 timeout: float = 20.0, proxy: str | None = None):
        self.cookies = parse_cookie_header(cookie)
        self.app_key = app_key
        self._own = client is None
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True,
                                            proxy=proxy or None)

    def close(self) -> None:
        if self._own:
            try:
                self.client.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def _merge_cookies(self) -> None:
        for c in self.client.cookies.jar:
            self.cookies[c.name] = c.value

    def _token(self) -> str:
        return (self.cookies.get("_m_h5_tk") or "").split("_")[0]

    def call(self, api: str, data: dict | None = None, version: str = "1.0",
             retry: bool = True, timeout: int = 10000) -> dict:
        data_text = json.dumps(data or {}, separators=(",", ":"), ensure_ascii=False)
        last: dict | None = None
        for attempt in range(2 if retry else 1):
            self._merge_cookies()
            token = self._token()
            t = str(int(time.time() * 1000))
            params = {
                "jsv": "2.7.2",
                "appKey": self.app_key,
                "t": t,
                "sign": sign(token, t, data_text, self.app_key),
                "api": api,
                "v": version,
                "type": "originaljson",
                "dataType": "json",
                "timeout": str(timeout),
            }
            headers = {
                "User-Agent": UA,
                "Referer": "https://www.goofish.com/",
                "Origin": "https://www.goofish.com",
                "Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items()),
            }
            url = f"{API_HOST}/h5/{api}/{version}/"
            try:
                resp = self.client.post(url, params=params, data={"data": data_text}, headers=headers)
            except httpx.HTTPError as exc:
                raise MtopError(f"mtop 请求失败: {exc}") from exc
            self._merge_cookies()
            try:
                payload = _parse_body(resp.text)
            except (ValueError, MtopError) as exc:
                raise MtopError(f"mtop 响应解析失败: {exc}") from exc
            code = _ret_code(payload)
            if code in ("FAIL_SYS_TOKEN_EMPTY", "FAIL_SYS_TOKEN_EXOIRED", "FAIL_SYS_TOKEN_EXPIRED",
                        "FAIL_SYS_TOKEN_ILLEGAL") or "TOKEN" in code:
                last = payload
                if attempt == 0 and retry:
                    continue
                raise MtopError(f"mtop 令牌无效: {code}", code, payload.get("ret"))
            if code and not code.startswith("SUCCESS"):
                message = " | ".join(str(x) for x in (payload.get("ret") or [])) or code
                raise MtopError(f"mtop 调用失败: {message}", code, payload.get("ret"))
            return payload
        raise MtopError("mtop 调用失败", _ret_code(last or {}), (last or {}).get("ret"))


def search_data(keyword: str, page: int = 1, rows: int = 30) -> dict:
    return {
        "pageNumber": page,
        "keyword": keyword,
        "fromFilter": False,
        "rowsPerPage": rows,
        "sortValue": "",
        "sortField": "",
        "customDistance": "",
        "shipping": "",
        "price": "",
        "searchScope": "",
        "listTime": "",
        "personalized": "",
    }


def _first_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        for item in value:
            text = _first_text(item)
            if text:
                return text
    if isinstance(value, dict):
        for key in ("text", "title", "content", "value"):
            if key in value:
                text = _first_text(value[key])
                if text:
                    return text
    return ""


def _deep_first(node, keys: tuple[str, ...]) -> str:
    if isinstance(node, dict):
        for key in keys:
            if key in node:
                text = _first_text(node[key])
                if text:
                    return text
        for value in node.values():
            text = _deep_first(value, keys)
            if text:
                return text
    elif isinstance(node, list):
        for value in node:
            text = _deep_first(value, keys)
            if text:
                return text
    return ""


def extract_search_items(payload: dict) -> list[dict]:
    """Best-effort extraction across goofish search response shapes."""
    items: list[dict] = []
    seen: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            item_id = node.get("itemId") or node.get("item_id")
            if item_id and str(item_id) not in seen:
                title = _deep_first(node, ("title",))
                price = _deep_first(node, ("price", "priceText", "soldPrice"))
                if title:
                    seen.add(str(item_id))
                    items.append({
                        "item_id": str(item_id),
                        "title": title,
                        "price": price,
                        "url": f"https://www.goofish.com/item?id={item_id}",
                    })
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload.get("data") if isinstance(payload, dict) else payload)
    return items


def extract_orders(payload: dict) -> list[dict]:
    """Pull order dicts out of a sold-list response (shape is not stable)."""
    orders: list[dict] = []
    seen: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            oid = node.get("bizOrderId") or node.get("orderId") or node.get("biz_order_id")
            if oid and str(oid) not in seen:
                seen.add(str(oid))
                orders.append({
                    "bizOrderId": str(oid),
                    "buyerNick": _deep_first(node, ("buyerNick", "buyerNickname", "buyerName")) or "未知买家",
                    "itemTitle": _deep_first(node, ("itemTitle", "item_title", "subject", "title")),
                    "totalAmount": _deep_first(node, ("totalAmount", "payAmount", "amount", "price")),
                    "quantity": _deep_first(node, ("quantity", "num", "buyAmount")) or 1,
                    "orderStatus": _deep_first(node, ("orderStatusName", "orderStatus", "statusName", "status")),
                    "raw": node,
                })
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload.get("data") if isinstance(payload, dict) else payload)
    return orders
