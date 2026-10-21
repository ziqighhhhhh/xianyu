"""Product materials, publishing and auto-relist.

Publishing uses the platform adapter's ``publish_item``.  The mock adapter
creates a local listing identity and the engine records a goods row plus a
publish log, so the full flow (material -> publish -> goods -> relist) can be
exercised locally.  The goofish adapter now calls the signed mtop publish endpoint.
"""

from __future__ import annotations

import time
from datetime import datetime

from . import db
from .platform.factory import adapter_for
from .platform.goofish import PlatformUnavailable


class PublishError(Exception):
    pass


def _log(conn, material_id, account_id, goods_id, item_id, status, message) -> int:
    cur = conn.execute(
        "INSERT INTO publish_logs(material_id, account_id, goods_id, item_id, status, message, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (material_id, account_id, goods_id, item_id or "", status, message, db.now_iso()),
    )
    conn.commit()
    return int(cur.lastrowid)


def publish_material(conn, material_id: int, account_id: int | None = None) -> dict:
    material_row = conn.execute("SELECT * FROM product_materials WHERE id=?", (material_id,)).fetchone()
    if not material_row:
        return {"ok": False, "error": "素材不存在", "material_id": material_id}
    material = dict(material_row)
    target_account = account_id or material.get("account_id")
    account = None
    if target_account:
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (target_account,)).fetchone()
        account = dict(row) if row else None
    if not account:
        _log(conn, material_id, target_account, None, "", "failed", "未绑定账号")
        return {"ok": False, "error": "素材未绑定账号", "material_id": material_id}

    try:
        result = adapter_for(account).publish_item(material)
    except PlatformUnavailable as exc:
        _log(conn, material_id, account["id"], None, "", "failed", str(exc))
        return {"ok": False, "error": str(exc), "material_id": material_id}
    except Exception as exc:
        code = getattr(exc, "code", "")
        message = f"{code}: {exc}" if code else str(exc)
        _log(conn, material_id, account["id"], None, "", "failed", message)
        return {"ok": False, "error": message, "material_id": material_id}

    cur = conn.execute(
        "INSERT INTO goods(owner_id, account_id, title, price, stock, status, description, image_url, item_id, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (account.get("owner_id") or 1, account["id"], material["title"], material["price"], material["stock"],
         "on_sale", material.get("description", ""), material.get("image_url", ""),
         result.get("item_id", ""), db.now_iso()),
    )
    goods_id = int(cur.lastrowid)
    conn.commit()
    log_id = _log(conn, material_id, account["id"], goods_id, result.get("item_id", ""),
                  "success", f"已发布：{material['title']}")
    return {"ok": True, "material_id": material_id, "goods_id": goods_id,
            "item_id": result.get("item_id", ""), "url": result.get("url", ""), "log_id": log_id}


def batch_publish(conn, material_ids: list[int], account_id: int | None = None) -> dict:
    results = []
    for material_id in material_ids:
        try:
            material_id = int(material_id)
        except (TypeError, ValueError):
            continue
        results.append(publish_material(conn, material_id, account_id))
    success = sum(1 for r in results if r.get("ok"))
    return {"ok": success == len(results) and bool(results), "total": len(results),
            "success": success, "failed": len(results) - success, "results": results}


def _log_relist(conn, rule_id, goods_id, status, message) -> None:
    conn.execute(
        "INSERT INTO auto_relist_logs(rule_id, goods_id, status, message, created_at) VALUES(?,?,?,?,?)",
        (rule_id, goods_id, status, message, db.now_iso()),
    )
    conn.commit()


def run_relist_rule(conn, rule_id: int) -> dict:
    rule_row = conn.execute("SELECT * FROM auto_relist_rules WHERE id=?", (rule_id,)).fetchone()
    if not rule_row:
        return {"ok": False, "error": "补货规则不存在"}
    rule = dict(rule_row)
    goods_row = conn.execute("SELECT * FROM goods WHERE id=?", (rule["goods_id"],)).fetchone()
    if not goods_row:
        _log_relist(conn, rule_id, rule["goods_id"], "failed", "商品不存在")
        return {"ok": False, "error": "商品不存在"}
    goods = dict(goods_row)
    material = None
    if rule.get("material_id"):
        row = conn.execute("SELECT * FROM product_materials WHERE id=?", (rule["material_id"],)).fetchone()
        material = dict(row) if row else None

    now = db.now_iso()
    if goods["status"] == "on_sale" and int(goods["stock"] or 0) > 0:
        conn.execute("UPDATE auto_relist_rules SET last_run_at=? WHERE id=?", (now, rule_id))
        conn.commit()
        _log_relist(conn, rule_id, goods["id"], "skipped", "在售且有库存，无需补货")
        return {"ok": True, "status": "skipped", "message": "在售且有库存，无需补货"}

    stock = int((material or {}).get("stock") or goods["stock"] or 0)
    price = float((material or {}).get("price") or goods["price"] or 0)
    conn.execute(
        "UPDATE goods SET status='on_sale', stock=?, price=?, created_at=? WHERE id=?",
        (stock if stock > 0 else 1, price, now, goods["id"]),
    )
    conn.execute("UPDATE auto_relist_rules SET last_run_at=? WHERE id=?", (now, rule_id))
    conn.commit()
    _log_relist(conn, rule_id, goods["id"], "success", f"已重新上架，库存 {stock if stock > 0 else 1}")
    return {"ok": True, "status": "relisted", "goods_id": goods["id"], "stock": stock or 1}


def relist_tick() -> int:
    conn = db.connect()
    try:
        rows = conn.execute("SELECT * FROM auto_relist_rules WHERE enabled=1").fetchall()
        now = time.time()
        ran = 0
        for row in rows:
            last = row["last_run_at"]
            if last:
                try:
                    last_ts = datetime.fromisoformat(last).timestamp()
                except ValueError:
                    last_ts = 0
            else:
                last_ts = 0
            if now - last_ts < max(30, int(row["interval_seconds"] or 600)):
                continue
            run_relist_rule(conn, row["id"])
            ran += 1
        return ran
    finally:
        conn.close()

