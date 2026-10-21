"""Order sync: pull one order or a sold-list page and upsert locally."""

from __future__ import annotations

import re

from . import db
from .platform.factory import adapter_for
from .platform.goofish import PlatformUnavailable


class SyncError(Exception):
    pass


def _deep(node, keys: tuple[str, ...]):
    if isinstance(node, dict):
        for key in keys:
            if key in node and node[key] not in (None, "", []):
                return node[key]
        for value in node.values():
            found = _deep(value, keys)
            if found not in (None, "", []):
                return found
    elif isinstance(node, list):
        for value in node:
            found = _deep(value, keys)
            if found not in (None, "", []):
                return found
    return None


def _amount(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"(\d+(?:\.\d+)?)", str(value or "").replace(",", ""))
    return float(m.group(1)) if m else 0.0


def _status(value) -> str:
    text = str(value or "").lower()
    if any(k in text for k in ("退款", "refund", "closed", "关闭")):
        return "refunded"
    if any(k in text for k in ("已发货", "shipped", "delivered", "已签收", "success")):
        return "delivered"
    if any(k in text for k in ("失败", "failed")):
        return "failed"
    return "paid"


def _upsert(conn, account: dict, raw: dict, fallback_no: str) -> tuple[int, bool]:
    order_no = str(_deep(raw, ("bizOrderId", "orderId", "biz_order_id", "order_no")) or fallback_no)
    if not order_no:
        raise SyncError("平台订单缺少订单号")
    buyer = str(_deep(raw, ("buyerNick", "buyerNickname", "buyerName", "buyer_name")) or "未知买家")
    title = str(_deep(raw, ("itemTitle", "item_title", "subject", "title")) or "")
    amount = _amount(_deep(raw, ("totalAmount", "payAmount", "amount", "price")))
    quantity = int(_deep(raw, ("quantity", "num", "buyAmount")) or 1)
    status = _status(_deep(raw, ("orderStatus", "orderStatusName", "status", "statusName")))

    existing = conn.execute(
        "SELECT * FROM orders WHERE order_no=? OR (account_id=? AND order_no=?)",
        (order_no, account["id"], str(fallback_no)),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE orders SET status=?, amount=?, quantity=?, buyer=? WHERE id=?",
            (status, amount, quantity, buyer, existing["id"]),
        )
        conn.commit()
        return int(existing["id"]), False
    goods = conn.execute(
        "SELECT * FROM goods WHERE title=? AND owner_id=? ORDER BY id LIMIT 1",
        (title, account.get("owner_id") or 1),
    ).fetchone()
    cur = conn.execute(
        "INSERT INTO orders(owner_id, order_no, account_id, goods_id, buyer, quantity, amount, status, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (account.get("owner_id") or 1, order_no, account["id"],
         goods["id"] if goods else None, buyer, quantity, amount, status, db.now_iso()),
    )
    conn.commit()
    return int(cur.lastrowid), True


def _deliver_if_needed(conn, order_id: int, auto_deliver: bool):
    if not auto_deliver:
        return None
    from .engines import delivery

    try:
        return delivery.deliver_order(conn, order_id)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def sync_order(conn, account: dict, order_id: str, auto_deliver: bool = False) -> dict:
    adapter = adapter_for(account)
    try:
        raw = adapter.fetch_order(str(order_id))
    except PlatformUnavailable as exc:
        raise SyncError(str(exc)) from exc
    except Exception as exc:
        raise SyncError(f"订单同步失败: {exc}") from exc
    if not raw:
        raise SyncError("平台未返回订单数据")
    order_id_local, created = _upsert(conn, account, raw, str(order_id))
    delivered = _deliver_if_needed(conn, order_id_local, auto_deliver)
    order = dict(conn.execute("SELECT * FROM orders WHERE id=?", (order_id_local,)).fetchone())
    return {"order": order, "raw": raw, "delivery": delivered, "created": created}


def sync_orders(conn, account: dict, auto_deliver: bool = False, limit: int = 50,
                pages: int = 1) -> dict:
    adapter = adapter_for(account)
    results = []
    created = updated = fetched = 0
    pages_done = 0
    max_pages = max(1, min(int(pages or 1), 10))
    limit = max(1, int(limit or 50))
    try:
        for page in range(1, max_pages + 1):
            rows = adapter.fetch_orders(page)
            pages_done = page
            if not rows:
                break
            fetched += len(rows)
            for raw in rows:
                if len(results) >= limit:
                    break
                try:
                    order_id, is_new = _upsert(conn, account, raw, "")
                except SyncError:
                    continue
                created += 1 if is_new else 0
                updated += 0 if is_new else 1
                if auto_deliver:
                    _deliver_if_needed(conn, order_id, True)
                results.append(order_id)
            if len(results) >= limit:
                break
    except PlatformUnavailable as exc:
        raise SyncError(str(exc)) from exc
    except SyncError:
        raise
    except Exception as exc:
        raise SyncError(f"订单列表同步失败: {exc}") from exc
    return {"fetched": fetched, "created": created, "updated": updated,
            "order_ids": results, "pages": pages_done}
