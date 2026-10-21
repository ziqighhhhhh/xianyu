"""Operational status and log retention helpers."""

from __future__ import annotations

import os
import time
from pathlib import Path

from . import backup, db

STARTED_AT = time.time()

TABLES = {
    "audit_logs": "created_at",
    "notification_logs": "created_at",
    "job_runs": "started_at",
    "delivery_logs": "created_at",
    "publish_logs": "created_at",
    "auto_relist_logs": "created_at",
}


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def status(conn, version: str) -> dict:
    counts = {}
    for table in ("accounts", "goods", "orders", "conversations", "messages",
                  "autoreply_rules", "autosell_rules", "monitor_tasks", "job_tasks",
                  "knowledge_bases", "user_sessions"):
        try:
            counts[table] = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        except Exception:
            counts[table] = 0
    db_file = db.db_path()
    data_dir = db.data_dir()
    return {
        "version": version,
        "uptime_seconds": int(time.time() - STARTED_AT),
        "db_path": str(db_file),
        "db_size": _size(db_file),
        "wal_size": _size(Path(str(db_file) + "-wal")),
        "data_dir": str(data_dir),
        "python": os.sys.version.split()[0],
        "counts": counts,
        "backups": len(backup.list_backups()),
        "scheduler": os.environ.get("FAP_DISABLE_SCHEDULER") != "1",
    }


def prune(conn, days: int = 30, targets: list[str] | None = None, vacuum: bool = False) -> dict:
    days = max(1, min(int(days or 30), 3650))
    selected = [t for t in (targets or list(TABLES)) if t in TABLES]
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - days * 86400))
    deleted = {}
    for table in selected:
        column = TABLES[table]
        cur = conn.execute(f"DELETE FROM {table} WHERE {column} <> '' AND {column} < ?", (cutoff,))
        deleted[table] = cur.rowcount or 0
    conn.commit()
    if vacuum:
        conn.execute("VACUUM")
    return {"days": days, "cutoff": cutoff, "deleted": deleted,
            "total": sum(deleted.values()), "vacuum": bool(vacuum)}
