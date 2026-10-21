"""Automatic delivery engine.

Supported strategies (matching the original product's feature set):

* ``fixed``    - render a fixed template
* ``stock``    - consume one or more rows from the stock/card-key pool
* ``api``      - call an external HTTP API and map the response
* ``workflow`` - run a workflow and use its ``delivery`` value
"""

from __future__ import annotations

import json

import httpx

from .. import db, notify
from ..platform.factory import adapter_for
from .common import render
from .workflows import run_workflow

CONTENT_TYPES = {"content-type": "application/json"}


class DeliveryError(Exception):
    pass


def order_context(order: dict, account: dict | None, goods: dict | None) -> dict:
    return {
        "order_id": order.get("id"),
        "order_no": order.get("order_no", ""),
        "buyer": order.get("buyer", ""),
        "quantity": order.get("quantity", 1),
        "amount": order.get("amount", 0),
        "goods_id": order.get("goods_id"),
        "goods_title": (goods or {}).get("title", order.get("goods_title", "")),
        "account_id": order.get("account_id"),
        "account_name": (account or {}).get("name", ""),
    }


def find_rule(conn, goods_id: int | None) -> dict | None:
    row = conn.execute(
        "SELECT * FROM autosell_rules WHERE enabled=1 AND goods_id=? ORDER BY id LIMIT 1",
        (goods_id,),
    ).fetchone()
    if row:
        return dict(row)
    row = conn.execute(
        "SELECT * FROM autosell_rules WHERE enabled=1 AND goods_id IS NULL ORDER BY id LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def _write_log(conn, order_id: int, rule_id: int | None, status: str, content: str, error: str) -> int:
    cur = conn.execute(
        "INSERT INTO delivery_logs(order_id, rule_id, status, content, error, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (order_id, rule_id, status, content, error, db.now_iso()),
    )
    conn.commit()
    return int(cur.lastrowid)


def _take_stock(conn, rule_id: int, quantity: int, order_id: int) -> list[str]:
    qty = max(1, int(quantity or 1))
    conn.execute("BEGIN IMMEDIATE")
    try:
        rows = conn.execute(
            "SELECT id, content FROM autosell_stock WHERE rule_id=? AND status='available' "
            "ORDER BY id LIMIT ?",
            (rule_id, qty),
        ).fetchall()
        if len(rows) < qty:
            conn.rollback()
            raise DeliveryError(f"库存不足：需要 {qty} 份，仅剩 {len(rows)} 份")
        ids = [r["id"] for r in rows]
        marks = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE autosell_stock SET status='used', used_order_id=?, used_at=? WHERE id IN ({marks})",
            (order_id, db.now_iso(), *ids),
        )
        conn.commit()
        return [r["content"] for r in rows]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise


def _call_api(rule: dict, ctx: dict) -> str:
    url = render(rule.get("api_url", ""), ctx)
    if not url:
        raise DeliveryError("API 发货规则缺少 api_url")
    method = (rule.get("api_method") or "POST").upper()
    try:
        headers = json.loads(rule.get("api_headers") or "{}")
    except json.JSONDecodeError:
        headers = {}
    headers = {str(k): render(str(v), ctx) for k, v in headers.items()}
    body_raw = rule.get("api_body") or ""
    body_text = render(body_raw, ctx) if body_raw else ""
    json_body = None
    if body_text:
        try:
            parsed = json.loads(body_text)
            json_body = parsed
        except json.JSONDecodeError:
            json_body = None
    if not body_text:
        json_body = {k: ctx.get(k) for k in ("order_no", "buyer", "quantity", "goods_title")}
    with httpx.Client(timeout=10) as client:
        if method in ("GET", "DELETE"):
            resp = client.request(method, url, headers=headers, params=json_body or None)
        else:
            resp = client.request(
                method, url, headers=headers,
                json=json_body if json_body is not None else None,
                content=body_text.encode("utf-8") if json_body is None and body_text else None,
            )
    if resp.status_code >= 400:
        raise DeliveryError(f"API 发货失败: HTTP {resp.status_code} {resp.text[:200]}")
    path = (rule.get("api_response_path") or "").strip()
    if not path:
        return resp.text
    try:
        data = resp.json()
    except ValueError:
        return resp.text
    for part in path.split("."):
        if part == "":
            continue
        if isinstance(data, list):
            data = data[int(part)]
        else:
            data = data[part]
    if isinstance(data, (dict, list)):
        return json.dumps(data, ensure_ascii=False)
    return str(data)


def _stock_content(conn, rule: dict, ctx: dict) -> str:
    qty = int(ctx.get("quantity") or 1) if rule.get("multi_quantity") else 1
    keys = _take_stock(conn, rule["id"], qty, int(ctx["order_id"]))
    return "\n".join(keys)


def deliver_order(conn, order_id: int, force: bool = False) -> dict:
    order_row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order_row:
        raise DeliveryError("订单不存在")
    order = dict(order_row)
    if order["status"] == "delivered" and not force:
        return {"ok": True, "status": "already_delivered", "content": order["delivery_content"]}

    account = None
    goods = None
    if order.get("account_id"):
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (order["account_id"],)).fetchone()
        account = dict(row) if row else None
    if order.get("goods_id"):
        row = conn.execute("SELECT * FROM goods WHERE id=?", (order["goods_id"],)).fetchone()
        goods = dict(row) if row else None

    rule = find_rule(conn, order.get("goods_id"))
    ctx = order_context(order, account, goods)
    if not rule:
        error = "未配置自动发货规则"
        conn.execute(
            "UPDATE orders SET status='failed', delivery_error=? WHERE id=?",
            (error, order_id),
        )
        conn.commit()
        _write_log(conn, order_id, None, "failed", "", error)
        try:
            notify.dispatch(conn, "order.failed", "订单发货失败",
                            f"订单 {order['order_no']} 未配置自动发货规则", order.get("account_id"))
        except Exception:
            pass
        return {"ok": False, "status": "failed", "error": error}

    ctx["rule_name"] = rule["name"]
    try:
        kind = rule.get("delivery_type") or "fixed"
        if kind == "fixed":
            content = render(rule.get("content", ""), ctx)
        elif kind == "stock":
            content = _stock_content(conn, rule, ctx)
        elif kind == "api":
            content = _call_api(rule, ctx)
        elif kind == "workflow":
            wf_id = rule.get("workflow_id")
            if not wf_id:
                raise DeliveryError("流程发货规则缺少 workflow_id")
            wf = conn.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
            if not wf:
                raise DeliveryError("关联的流程不存在")
            result = run_workflow(conn, dict(wf), ctx, order_id=order_id)
            if result["status"] != "ok":
                raise DeliveryError(f"流程执行失败: {result.get('error', '')}")
            content = str(result["context"].get("delivery", ""))
        else:
            raise DeliveryError(f"未知发货类型: {kind}")

        if not content.strip():
            raise DeliveryError("发货内容为空")
        conn.execute(
            "UPDATE orders SET status='delivered', delivery_content=?, delivery_error='', delivered_at=? "
            "WHERE id=?",
            (content, db.now_iso(), order_id),
        )
        conn.commit()
        log_id = _write_log(conn, order_id, rule["id"], "success", content, "")
        rate_status = ""
        if account and account.get("auto_comment") and not order.get("rated_at"):
            comment = render(account.get("comment_template") or "宝贝很好，下次还会再来～", ctx)
            try:
                adapter_for(account).rate_order(order["order_no"], comment)
                conn.execute(
                    "UPDATE orders SET rated_at=?, rate_status='success', rate_content=? WHERE id=?",
                    (db.now_iso(), comment, order_id),
                )
                conn.commit()
                rate_status = "success"
            except Exception as exc:
                conn.execute(
                    "UPDATE orders SET rate_status='failed', rate_content=? WHERE id=?",
                    (f"{comment}（失败：{exc}）", order_id),
                )
                conn.commit()
                rate_status = "failed"
        try:
            notify.dispatch(
                conn, "order.delivered", "订单已自动发货",
                f"订单 {ctx['order_no']}｜{ctx['goods_title']}｜买家 {ctx['buyer']}｜数量 {ctx['quantity']}",
                order.get("account_id"),
            )
        except Exception:
            pass
        return {"ok": True, "status": "delivered", "content": content,
                "rule_id": rule["id"], "log_id": log_id, "rate_status": rate_status}
    except Exception as exc:
        conn.execute(
            "UPDATE orders SET status='failed', delivery_error=? WHERE id=?",
            (str(exc), order_id),
        )
        conn.commit()
        _write_log(conn, order_id, rule.get("id"), "failed", "", str(exc))
        try:
            notify.dispatch(conn, "order.failed", "订单发货失败",
                            f"订单 {ctx['order_no']} 发货失败：{exc}", order.get("account_id"))
        except Exception:
            pass
        return {"ok": False, "status": "failed", "error": str(exc)}
