"""Mock platform adapter used for local demos and tests.

It reads the ``mock_items`` table (seeded with a few listings) and can synthesise
additional listings when a monitor keyword has no seeded rows, so the whole
monitor -> notify -> order loop can be exercised without touching goofish.
"""

from __future__ import annotations

import hashlib
import uuid

from .. import db
from .base import PlatformAdapter, PlatformItem


class MockAdapter(PlatformAdapter):
    name = "mock"

    def __init__(self, account: dict | None = None):
        self.account = account or {}

    def connect(self) -> dict:
        return {"ok": True, "status": "online", "message": "模拟账号已连接"}

    def search_items(self, keyword: str, min_price, max_price) -> list[PlatformItem]:
        conn = db.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM mock_items ORDER BY id DESC"
            ).fetchall()
            items = []
            for row in rows:
                if keyword and keyword.casefold() not in row["title"].casefold():
                    continue
                if min_price is not None and row["price"] < float(min_price):
                    continue
                if max_price is not None and row["price"] > float(max_price):
                    continue
                items.append(PlatformItem(
                    key=f"mock-{row['id']}", title=row["title"], price=row["price"], url=row["url"],
                ))
            if items:
                return items
            # Deterministic synthetic listing so the monitor demo always has data.
            digest = hashlib.sha1((keyword or "demo").encode("utf-8")).hexdigest()[:8]
            base = 100 + int(digest[:3], 16) % 900
            return [
                PlatformItem(key=f"synthetic-{digest}", title=f"{keyword} 九成新 个人闲置", price=float(base),
                             url=f"https://example.com/item/{digest}"),
                PlatformItem(key=f"synthetic-{digest}-b", title=f"【捡漏】{keyword} 急出", price=float(base) * 0.8,
                             url=f"https://example.com/item/{digest}-b"),
            ]
        finally:
            conn.close()

    def send_message(self, buyer: str, content: str) -> dict:
        return {"ok": True, "channel": "mock", "buyer": buyer, "content": content}

    def fetch_orders(self, page: int = 1) -> list[dict]:
        pages = {
            1: [
                {"bizOrderId": "MOCK-SOLD-1", "buyerNick": "列表买家A", "itemTitle": "订单列表商品A",
                 "totalAmount": "12.50", "quantity": 1, "orderStatus": "待发货"},
                {"bizOrderId": "MOCK-SOLD-2", "buyerNick": "列表买家B", "itemTitle": "订单列表商品B",
                 "totalAmount": "20.00", "quantity": 2, "orderStatus": "已发货"},
            ],
            2: [
                {"bizOrderId": "MOCK-SOLD-3", "buyerNick": "列表买家C", "itemTitle": "订单列表商品C",
                 "totalAmount": "30.00", "quantity": 1, "orderStatus": "待发货"},
            ],
        }
        return pages.get(int(page), [])

    def fetch_order(self, order_id: str) -> dict:
        return {
            "bizOrderId": str(order_id),
            "orderId": str(order_id),
            "buyerNick": "同步买家",
            "itemTitle": "订单同步演示商品",
            "totalAmount": "9.90",
            "quantity": 1,
            "orderStatus": "待发货",
        }

    def publish_item(self, material: dict) -> dict:
        item_id = "mock-" + uuid.uuid4().hex[:12]
        return {
            "ok": True, "channel": "mock", "item_id": item_id,
            "url": f"https://example.com/item/{item_id}",
            "title": material.get("title", ""),
        }

    def rate_order(self, order_id: str, content: str = "") -> dict:
        return {"ok": True, "order_id": order_id, "content": content}

    def ship_order(self, order_id: str, trade_id: str = "") -> dict:
        return {"ok": True, "order_id": order_id, "channel": "mock"}
