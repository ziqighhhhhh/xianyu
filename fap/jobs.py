"""Persistent scheduled jobs: order sync, monitor, relist and backup."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import backup, db, maintenance, notify
from .engines import monitor as monitor_engine
from . import publish, sync
from .platform.factory import adapter_for

JOB_TYPES = {
    "order_sync": "订单同步",
    "monitor": "商品监控",
    "relist": "自动补货",
    "polish": "自动擦亮",
    "backup": "自动备份",
    "prune": "日志清理",
    "report": "经营报表",
}
JOB_STATUS = {"success": "成功", "failed": "失败", "running": "运行中"}
MAX_INTERVAL = 30 * 24 * 3600


class JobError(Exception):
    pass


def normalize_config(job_type: str, config: dict | None) -> dict:
    config = config or {}
    if not isinstance(config, dict):
        raise JobError("config 必须是 JSON 对象")
    if job_type == "order_sync":
        account_id = int(config.get("account_id") or 0)
        order_id = str(config.get("order_id") or "").strip()
        if not account_id:
            raise JobError("订单同步任务需要账号")
        return {"account_id": account_id, "order_id": order_id,
                "auto_deliver": bool(config.get("auto_deliver")),
                "pages": max(1, min(int(config.get("pages") or 1), 10))}
    if job_type == "monitor":
        task_id = int(config.get("task_id") or 0)
        if not task_id:
            raise JobError("监控任务需要选择监控规则")
        return {"task_id": task_id}
    if job_type == "relist":
        rule_id = int(config.get("rule_id") or 0)
        if not rule_id:
            raise JobError("补货任务需要选择补货规则")
        return {"rule_id": rule_id}
    if job_type == "polish":
        account_id = int(config.get("account_id") or 0)
        raw = config.get("item_ids") or []
        if isinstance(raw, str):
            ids = [x.strip() for x in raw.replace(",", "\n").splitlines() if x.strip()]
        elif isinstance(raw, list):
            ids = [str(x).strip() for x in raw if str(x).strip()]
        else:
            ids = []
        ids = list(dict.fromkeys(ids))[:50]
        if not account_id or not ids:
            raise JobError("擦亮任务需要账号和商品 ID")
        return {"account_id": account_id, "item_ids": ids}
    if job_type == "backup":
        return {}
    if job_type == "prune":
        return {"days": max(1, min(int(config.get("days") or 30), 3650)),
                "vacuum": bool(config.get("vacuum"))}
    if job_type == "report":
        return {"days": max(1, min(int(config.get("days") or 1), 90))}
    raise JobError("不支持的任务类型")


def next_at(interval: int) -> str:
    return (datetime.now(timezone.utc).astimezone() + timedelta(seconds=interval)).isoformat(timespec="seconds")


def run_task(conn, task_id: int) -> dict:
    row = conn.execute("SELECT * FROM job_tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise JobError("任务不存在")
    task = dict(row)
    config = json.loads(task["config_json"] or "{}")
    started = db.now_iso()
    status, message, detail = "success", "", {}
    try:
        if task["type"] == "order_sync":
            account = conn.execute("SELECT * FROM accounts WHERE id=?", (config.get("account_id"),)).fetchone()
            if not account:
                raise JobError("账号不存在")
            if account["owner_id"] != task["owner_id"]:
                raise JobError("账号不属于任务所有者")
            if config.get("order_id"):
                result = sync.sync_order(conn, dict(account), config["order_id"],
                                         bool(config.get("auto_deliver")))
                order = result["order"]
                message = f"订单 {order['order_no']} 状态 {order['status']}"
                detail = {"order_id": order["id"], "status": order["status"]}
            else:
                result = sync.sync_orders(conn, dict(account), bool(config.get("auto_deliver")),
                                          pages=int(config.get("pages") or 1))
                message = f"列表同步：拉取 {result['fetched']}，新增 {result['created']}，更新 {result['updated']}"
                detail = result
        elif task["type"] == "monitor":
            target = conn.execute("SELECT * FROM monitor_tasks WHERE id=?", (config.get("task_id"),)).fetchone()
            if not target or target["owner_id"] != task["owner_id"]:
                raise JobError("监控任务不存在或不属于当前用户")
            result = monitor_engine.run_task(conn, int(target["id"]))
            status = "success" if result.get("ok") else "failed"
            message = f"新增 {result.get('new', 0)} 条，共 {result.get('items', 0)} 条"
            detail = result
        elif task["type"] == "relist":
            target = conn.execute("SELECT * FROM auto_relist_rules WHERE id=?", (config.get("rule_id"),)).fetchone()
            if not target or target["owner_id"] != task["owner_id"]:
                raise JobError("补货规则不存在或不属于当前用户")
            result = publish.run_relist_rule(conn, int(target["id"]))
            status = "success" if result.get("ok") else "failed"
            message = result.get("message") or result.get("error") or "已执行"
            detail = result
        elif task["type"] == "polish":
            account = conn.execute("SELECT * FROM accounts WHERE id=?", (config.get("account_id"),)).fetchone()
            if not account:
                raise JobError("账号不存在")
            if account["owner_id"] != task["owner_id"]:
                raise JobError("账号不属于任务所有者")
            if (account["cookie"] or "").startswith("demo"):
                raise JobError("Mock 演示账号不支持擦亮")
            adapter = adapter_for(dict(account))
            results, success = [], 0
            for item_id in config.get("item_ids") or []:
                try:
                    adapter.polish_item(str(item_id))
                    results.append({"item_id": item_id, "ok": True})
                    success += 1
                except Exception as exc:
                    results.append({"item_id": item_id, "ok": False, "error": str(exc)})
            message = f"擦亮成功 {success}/{len(results)}"
            status = "success" if success else "failed"
            detail = {"results": results, "success": success}
        elif task["type"] == "backup":
            if task["owner_id"] != 1:
                raise JobError("只有管理员可以创建自动备份任务")
            result = backup.create_backup(conn)
            message = f"已创建备份 {result.get('name', '')}"
            detail = result
        elif task["type"] == "prune":
            if task["owner_id"] != 1:
                raise JobError("只有管理员可以执行日志清理任务")
            result = maintenance.prune(conn, int(config.get("days") or 30), None,
                                       bool(config.get("vacuum")))
            message = f"清理 {result['total']} 条 {result['days']} 天前日志"
            detail = result
        elif task["type"] == "report":
            days = int(config.get("days") or 1)
            owner_id = int(task["owner_id"])
            since = (datetime.now(timezone.utc).astimezone() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
            orders = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS amount FROM orders "
                "WHERE owner_id=? AND substr(created_at,1,10)>=? AND status!='refunded'",
                (owner_id, since),
            ).fetchone()
            refunds = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(refund_amount),0) AS amount FROM orders "
                "WHERE owner_id=? AND refund_status='success' AND substr(refunded_at,1,10)>=?",
                (owner_id, since),
            ).fetchone()
            unread = conn.execute(
                "SELECT COALESCE(SUM(unread),0) AS n FROM conversations WHERE owner_id=?", (owner_id,)
            ).fetchone()["n"]
            on_sale = conn.execute(
                "SELECT COUNT(*) AS n FROM goods WHERE owner_id=? AND status='on_sale'", (owner_id,)
            ).fetchone()["n"]
            message = (
                f"近 {days} 天：订单 {orders['n']} 笔，收入 ¥{orders['amount']:.2f}，"
                f"退款 {refunds['n']} 笔 ¥{refunds['amount']:.2f}，未读 {unread}，在售 {on_sale}"
            )
            sent = notify.dispatch(conn, "report", "经营报表", message, owner_id=owner_id)
            ok = sum(1 for item in sent if item.get("ok"))
            status = "success"
            message = f"{message}｜已发送 {ok}/{len(sent)} 个渠道"
            detail = {"days": days, "channels": len(sent), "sent": ok}
        else:
            raise JobError("不支持的任务类型")
    except Exception as exc:  # job failures are recorded, never crash the scheduler
        status, message = "failed", str(exc)
        if not isinstance(exc, JobError):
            message = f"{type(exc).__name__}: {exc}"
    finished = db.now_iso()
    cur = conn.execute(
        "INSERT INTO job_runs(task_id, status, message, detail_json, started_at, finished_at) "
        "VALUES(?,?,?,?,?,?)",
        (task_id, status, message, json.dumps(detail, ensure_ascii=False, default=str), started, finished),
    )
    conn.execute(
        "UPDATE job_tasks SET last_run_at=?, next_run_at=?, last_status=?, last_message=? WHERE id=?",
        (started, next_at(int(task["interval_seconds"] or 600)), status, message, task_id),
    )
    conn.commit()
    return {"ok": status == "success", "status": status, "message": message,
            "detail": detail, "run_id": int(cur.lastrowid)}


def tick(conn=None) -> int:
    own = conn is None
    conn = conn or db.connect()
    ran = 0
    try:
        now = db.now_iso()
        rows = conn.execute(
            "SELECT id FROM job_tasks WHERE enabled=1 AND (next_run_at IS NULL OR next_run_at<=?) "
            "ORDER BY id LIMIT 20", (now,),
        ).fetchall()
        for row in rows:
            try:
                run_task(conn, int(row["id"]))
                ran += 1
            except Exception:
                continue
    finally:
        if own:
            conn.close()
    return ran
