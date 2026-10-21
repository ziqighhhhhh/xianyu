"""Goofish (闲鱼) adapter: QR login + cookie validation + protocol seam.

Implemented against the live passport endpoints discovered in the original
client (qrcode/generate.do, qrcode/query.do, hasLogin.do):

* ``start_qr_login`` asks passport for a QR code, renders it to a PNG data URL
  and keeps the httpx client (with its passport cookies) in memory.
* ``poll_qr_login`` queries the QR status.  On confirmation the account cookie
  is captured; the API validates it with ``check_login`` before persisting.
* ``check_login`` calls ``hasLogin.do`` with the supplied cookie.

Message/order/product operations still need the mtop ``sign`` chain and the
WebSocket handshake, so those methods return an explicit "not enabled" error.
"""

from __future__ import annotations

import base64
import io
import threading
import time
import urllib.parse
import uuid

import httpx
import qrcode

from . import lwp, lwp_frames, mtop
from .base import PlatformAdapter, PlatformItem

HOSTS = {
    "web": "https://www.goofish.com",
    "h5": "https://h5api.m.goofish.com",
    "passport": "https://passport.goofish.com",
    "seller": "https://seller.goofish.com",
    "im": "https://www.goofish.com/im",
}

PASSPORT_PARAMS = {"appName": "xianyu", "fromSite": "77"}
QR_GENERATE = HOSTS["passport"] + "/newlogin/qrcode/generate.do"
QR_QUERY = HOSTS["passport"] + "/newlogin/qrcode/query.do"
HAS_LOGIN = HOSTS["passport"] + "/newlogin/hasLogin.do"

MTOP_ENDPOINTS = {
    "send_message": "mtop.taobao.idlemessage.pc.send",
    "conversations": "mtop.taobao.idlemessage.pc.conversation.list",
    "history": "mtop.taobao.idlemessage.pc.message.list",
    "item_detail": "mtop.taobao.idle.pc.detail",
    "item_polish": "mtop.taobao.idle.item.polish",
    "item_offline": "mtop.taobao.idle.item.offline",
}

QR_STATUS = {
    "NEW": ("waiting", "等待扫码"),
    "SCANNED": ("scanned", "已扫码，请在手机上确认"),
    "CONFIRMED": ("confirmed", "已确认，正在获取登录态"),
    "EXPIRED": ("expired", "二维码已过期"),
    "CANCELED": ("canceled", "已取消登录"),
}
SESSION_TTL = 300

_sessions: dict[str, dict] = {}
_lock = threading.Lock()


class PlatformUnavailable(RuntimeError):
    pass


class QRLoginError(RuntimeError):
    pass


def cookie_header(client: httpx.Client) -> str:
    return "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar)


def _json_data(payload: dict) -> dict:
    return ((payload or {}).get("content") or {}).get("data") or {}


def _lg_token(code_content: str) -> str:
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(code_content).query)
        return (q.get("lgToken") or [""])[0]
    except Exception:
        return ""


def _parse_price(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return None
    import re

    m = re.search(r"(\d+(?:\.\d+)?)", str(value).replace(",", ""))
    return float(m.group(1)) if m else None


def _deep_find(node, key: str):
    if isinstance(node, dict):
        if key in node and node[key] not in (None, "", []):
            return node[key]
        for value in node.values():
            found = _deep_find(value, key)
            if found not in (None, "", []):
                return found
    elif isinstance(node, list):
        for value in node:
            found = _deep_find(value, key)
            if found not in (None, "", []):
                return found
    return None


def _render_qr(code_content: str) -> str:
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(code_content)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _cleanup_sessions() -> None:
    now = time.time()
    stale = [sid for sid, s in _sessions.items() if now - s["created"] > SESSION_TTL]
    for sid in stale:
        session = _sessions.pop(sid, None)
        if session:
            try:
                session["client"].close()
            except Exception:
                pass


def start_qr_login(account: dict) -> dict:
    client = httpx.Client(timeout=15, follow_redirects=True,
                          proxy=(account or {}).get("proxy") or None)
    try:
        resp = client.get(QR_GENERATE, params=PASSPORT_PARAMS)
        payload = resp.json()
        data = _json_data(payload)
        code_content = data.get("codeContent")
        if not code_content:
            raise QRLoginError(data.get("titleMsg") or "获取二维码失败")
        sid = uuid.uuid4().hex
        with _lock:
            _cleanup_sessions()
            _sessions[sid] = {
                "client": client,
                "account_id": int((account or {}).get("id") or 0),
                "lg_token": _lg_token(code_content),
                "t": str(data.get("t", "")),
                "ck": data.get("ck", ""),
                "created": time.time(),
            }
        return {
            "session_id": sid,
            "qr_image": _render_qr(code_content),
            "code_content": code_content,
            "expires_in": SESSION_TTL,
        }
    except Exception:
        client.close()
        raise


def poll_qr_login(session_id: str) -> dict:
    with _lock:
        session = _sessions.get(session_id)
    if not session:
        raise QRLoginError("二维码会话不存在或已过期")
    if time.time() - session["created"] > SESSION_TTL:
        with _lock:
            _sessions.pop(session_id, None)
        try:
            session["client"].close()
        except Exception:
            pass
        raise QRLoginError("二维码已过期，请重新获取")

    params = {
        **PASSPORT_PARAMS,
        "lgToken": session["lg_token"],
        "t": session["t"],
        "ck": session["ck"],
    }
    try:
        resp = session["client"].post(QR_QUERY, data=params)
        payload = resp.json()
    except Exception as exc:
        raise QRLoginError(f"查询二维码状态失败: {exc}") from exc

    data = _json_data(payload)
    raw_status = data.get("qrCodeStatus")
    status_code = str(raw_status or "").upper()
    success = bool((payload.get("content") or {}).get("success"))
    if status_code == "CONFIRMED" or (not status_code and success):
        cookie = cookie_header(session["client"])
        with _lock:
            _sessions.pop(session_id, None)
        try:
            session["client"].close()
        except Exception:
            pass
        return {"status": "confirmed", "message": "扫码成功", "cookie": cookie}
    name, message = QR_STATUS.get(status_code, ("unknown", data.get("titleMsg") or "等待扫码"))
    if name in ("expired", "canceled"):
        with _lock:
            _sessions.pop(session_id, None)
        try:
            session["client"].close()
        except Exception:
            pass
    return {"status": name, "message": message, "raw_status": raw_status}


def check_login(cookie: str, proxy: str | None = None) -> dict:
    if not cookie:
        return {"ok": False, "message": "Cookie 为空"}
    try:
        with httpx.Client(timeout=15, follow_redirects=True, proxy=proxy or None) as client:
            resp = client.get(HAS_LOGIN, params=PASSPORT_PARAMS, headers={"Cookie": cookie})
            payload = resp.json()
    except Exception as exc:
        return {"ok": False, "message": f"登录检测失败: {exc}"}
    content = payload.get("content") or {}
    data = content.get("data") or {}
    ok = bool(content.get("success")) and data.get("errorCode") not in ("SystemError",)
    message = data.get("titleMsg") or ("登录有效" if ok else "Cookie 无效或已过期")
    return {"ok": ok, "message": message}


class GoofishAdapter(PlatformAdapter):
    name = "goofish"

    def __init__(self, account: dict):
        self.account = account
        self.cookie = (account or {}).get("cookie", "")
        self.proxy = (account or {}).get("proxy") or None

    def _mtop(self) -> mtop.MtopClient:
        return mtop.MtopClient(self.cookie, proxy=self.proxy)

    def _require_cookie(self) -> None:
        if not self.cookie:
            raise PlatformUnavailable("账号未配置 Cookie，无法连接真实闲鱼")

    def _request(self, endpoint: str, payload: dict) -> dict:
        self._require_cookie()
        raise PlatformUnavailable(
            "真实闲鱼消息接口尚未启用：需要实现 mtop 签名（sign/t/appKey/h5token）与 WebSocket 握手。"
            f"目标端点: {endpoint}"
        )

    def connect(self) -> dict:
        self._require_cookie()
        result = check_login(self.cookie, proxy=self.proxy)
        if not result["ok"]:
            raise PlatformUnavailable(result["message"])
        return {"ok": True, "message": result["message"], "channel": "goofish"}

    def search_items(self, keyword: str, min_price, max_price) -> list[PlatformItem]:
        self._require_cookie()
        with self._mtop() as client:
            payload = client.call(mtop.SEARCH_API, mtop.search_data(keyword))
        out: list[PlatformItem] = []
        for row in mtop.extract_search_items(payload):
            price = _parse_price(row.get("price"))
            if min_price is not None and price is not None and price < float(min_price):
                continue
            if max_price is not None and price is not None and price > float(max_price):
                continue
            out.append(PlatformItem(
                key=row["item_id"], title=row["title"],
                price=price if price is not None else 0.0, url=row.get("url", ""),
            ))
        return out

    def fetch_item(self, item_id: str) -> dict:
        self._require_cookie()
        with self._mtop() as client:
            payload = client.call(mtop.DETAIL_API, {"itemId": str(item_id)})
        return payload.get("data") or {}

    def list_my_items(self, page: int = 1) -> list[dict]:
        self._require_cookie()
        with self._mtop() as client:
            payload = client.call(mtop.ITEM_LIST_API, {"pageNumber": page, "pageSize": 20})
        return mtop.extract_search_items(payload)

    def polish_item(self, item_id: str) -> dict:
        self._require_cookie()
        with self._mtop() as client:
            return client.call(mtop.POLISH_API, {"itemId": str(item_id)})

    def rate_order(self, order_id: str, content: str = "") -> dict:
        self._require_cookie()
        comment = (content or "宝贝很好，下次还会再来～").strip()
        data = {"orderId": str(order_id), "feedback": comment, "content": comment, "rateType": 1}
        with self._mtop() as client:
            return client.call(mtop.RATE_API, data)

    def ship_order(self, order_id: str, trade_id: str = "") -> dict:
        self._require_cookie()
        data = {"orderId": str(order_id), "tradeId": str(trade_id or order_id)}
        with self._mtop() as client:
            return client.call(mtop.CONSIGN_API, data)

    def fetch_ws_token(self) -> dict:
        self._require_cookie()
        with self._mtop() as client:
            payload = client.call(mtop.WS_TOKEN_API, {})
        data = payload.get("data") or {}
        token = (_deep_find(data, "accessToken") or _deep_find(data, "token")
                 or _deep_find(data, "wsToken") or "")
        if not token:
            raise mtop.MtopError("no token", "LWP_TOKEN_MISSING", [str(payload)[:200]])
        return {"token": str(token), "raw": payload}

    def send_lwp_text(self, conversation_id: str, receiver_id: str, text: str) -> dict:
        """Experimental: register then send one text frame over LWP."""
        info = self.fetch_ws_token()
        frames = [lwp_frames.build_register_frame(),
                  lwp_frames.build_text_frame(conversation_id, receiver_id, text)]
        return lwp.exchange(info["token"], frames, timeout=8.0)

    def fetch_profile(self) -> dict:
        self._require_cookie()
        with self._mtop() as client:
            payload = client.call(mtop.LOGINUSER_API, {})
        data = payload.get("data") or {}
        return {
            "nickname": str(_deep_find(data, "nickName") or _deep_find(data, "nickname")
                            or _deep_find(data, "displayName") or ""),
            "avatar_url": str(_deep_find(data, "avatarUrl") or _deep_find(data, "avatar") or ""),
            "platform_user_id": str(_deep_find(data, "userId") or _deep_find(data, "user_id") or ""),
            "raw": payload,
        }

    def publish_item(self, material: dict) -> dict:
        self._require_cookie()
        image = (material.get("image_url") or "").strip()
        images = [image] if image.startswith("http") else []
        data = {
            "title": (material.get("title") or "").strip(),
            "desc": material.get("description", ""),
            "description": material.get("description", ""),
            "price": str(material.get("price") or 0),
            "quantity": max(1, int(material.get("stock") or 1)),
            "images": images,
            "imageUrls": images,
            "categoryId": material.get("category_id") or material.get("categoryId") or "",
            "itemType": "biz",
        }
        with self._mtop() as client:
            payload = client.call(mtop.PUBLISH_API, data)
        item_id = _deep_find(payload, "itemId")
        return {
            "ok": True,
            "item_id": str(item_id) if item_id else "",
            "url": f"https://www.goofish.com/item?id={item_id}" if item_id else "",
            "raw": payload,
        }

    def offline_items(self, item_ids: list[str]) -> dict:
        self._require_cookie()
        ids = [str(x) for x in item_ids if str(x).strip()]
        if not ids:
            raise PlatformUnavailable("商品缺少平台 item_id")
        with self._mtop() as client:
            return client.call(mtop.OFFLINE_API, {"itemIds": ids})

    def send_message(self, buyer: str, content: str) -> dict:
        return self._request(MTOP_ENDPOINTS["send_message"], {"buyer": buyer, "content": content})

    def fetch_orders(self, page: int = 1) -> list[dict]:
        self._require_cookie()
        with self._mtop() as client:
            payload = client.call(mtop.SOLD_ORDERS_API, {"page": max(1, int(page)), "pageSize": 20})
        return mtop.extract_orders(payload)

    def fetch_order(self, order_id: str) -> dict:
        self._require_cookie()
        data = {"orderId": str(order_id), "bizOrderId": str(order_id)}
        with self._mtop() as client:
            payload = client.call(mtop.ORDER_DETAIL_API, data)
        return payload.get("data") or {}
