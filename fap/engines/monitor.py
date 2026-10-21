"""Product monitor: search -> dedupe -> record -> optional action."""

from __future__ import annotations

import time

from .. import db, notify
from ..platform.factory import adapter_for


def run_task(conn, task_id: int) -> dict:
    task_row = conn.execute("SELECT * FROM monitor_tasks WHERE id=?", (task_id,)).fetchone()
    if not task_row:
        return {"ok": False, "error": "监控任务不存在"}
    task = dict(task_row)
    account = None
    if task.get("account_id"):
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (task["account_id"],)).fetchone()
        account = dict(row) if row else None
    adapter = adapter_for(account)
    try:
        items = adapter.search_items(task["keyword"], task.get("min_price"), task.get("max_price"))
    except Exception as exc:  # adapter errors surface to the caller
        return {"ok": False, "error": str(exc)}
    now = db.now_iso()
    new_items = []
    for item in items:
        existing = conn.execute(
            "SELECT id FROM monitor_items WHERE task_id=? AND item_key=?",
            (task_id, item.key),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO monitor_items(task_id, item_key, title, price, url, found_at) VALUES(?,?,?,?,?,?)",
            (task_id, item.key, item.title, item.price, item.url, now),
        )
        new_items.append({"key": item.key, "title": item.title, "price": item.price, "url": item.url})
    conn.execute("UPDATE monitor_tasks SET last_run_at=? WHERE id=?", (now, task_id))
    if new_items:
        detail = f"task={task['name']} new={len(new_items)} action={task['action']}"
        db.audit(conn, "monitor.hit", detail)
        if task["action"] in ("dm", "order"):
            db.audit(conn, f"monitor.{task['action']}", detail)
    conn.commit()
    if new_items:
        try:
            lines = "\n".join(f"{i['title']} ¥{i['price']}" for i in new_items[:5])
            notify.dispatch(conn, "monitor.hit", f"监控命中：{task['keyword']}",
                            f"任务 {task['name']} 新增 {len(new_items)} 条\n{lines}", task.get("account_id"))
        except Exception:
            pass
    return {"ok": True, "new": len(new_items), "items": new_items, "task": task["name"]}


def tick() -> int:
    """Run every enabled task whose interval has elapsed. Returns task count."""
    conn = db.connect()
    try:
        rows = conn.execute("SELECT * FROM monitor_tasks WHERE enabled=1").fetchall()
        ran = 0
        now = time.time()
        for row in rows:
            last = row["last_run_at"]
            if last:
                try:
                    from datetime import datetime

                    last_ts = datetime.fromisoformat(last).timestamp()
                except ValueError:
                    last_ts = 0
            else:
                last_ts = 0
            if now - last_ts < max(10, int(row["interval_seconds"] or 60)):
                continue
            run_task(conn, row["id"])
            ran += 1
        return ran
    finally:
        conn.close()
