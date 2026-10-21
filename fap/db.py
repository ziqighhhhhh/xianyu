"""SQLite storage for the FishAutoPro-compatible clone.

The schema mirrors the core entities we recovered from the original product:
users, accounts, goods, orders, conversations/messages, auto-reply rules,
auto-delivery rules + stock, delivery logs, product monitor, workflows and
settings.  It intentionally keeps the license/authorisation tables out: this
clone is self-hosted and has no licence gate.
"""

from __future__ import annotations

import json
import re
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 11

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    is_active INTEGER NOT NULL DEFAULT 1,
    session_version INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    cookie TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'offline',
    enabled INTEGER NOT NULL DEFAULT 1,
    proxy TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    ai_enabled INTEGER NOT NULL DEFAULT 0,
    auto_comment INTEGER NOT NULL DEFAULT 0,
    comment_template TEXT NOT NULL DEFAULT '',
    nickname TEXT NOT NULL DEFAULT '',
    avatar_url TEXT NOT NULL DEFAULT '',
    platform_user_id TEXT NOT NULL DEFAULT '',
    last_seen_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS goods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    price REAL NOT NULL DEFAULT 0,
    stock INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'on_sale',
    description TEXT NOT NULL DEFAULT '',
    image_url TEXT NOT NULL DEFAULT '',
    item_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT NOT NULL UNIQUE,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    goods_id INTEGER REFERENCES goods(id) ON DELETE SET NULL,
    buyer TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    amount REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'paid',
    delivery_content TEXT NOT NULL DEFAULT '',
    delivery_error TEXT NOT NULL DEFAULT '',
    rated_at TEXT NOT NULL DEFAULT '',
    rate_status TEXT NOT NULL DEFAULT '',
    rate_content TEXT NOT NULL DEFAULT '',
    refund_status TEXT NOT NULL DEFAULT '',
    refund_amount REAL NOT NULL DEFAULT 0,
    refund_reason TEXT NOT NULL DEFAULT '',
    refunded_at TEXT NOT NULL DEFAULT '',
    ship_status TEXT NOT NULL DEFAULT '',
    platform_shipped_at TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    delivered_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    goods_id INTEGER REFERENCES goods(id) ON DELETE SET NULL,
    buyer TEXT NOT NULL,
    last_message TEXT NOT NULL DEFAULT '',
    unread INTEGER NOT NULL DEFAULT 0,
    ai_enabled INTEGER NOT NULL DEFAULT 1,
    autoreply_paused INTEGER NOT NULL DEFAULT 0,
    autoreply_paused_until TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(account_id, buyer)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    direction TEXT NOT NULL CHECK(direction IN ('in','out')),
    content TEXT NOT NULL,
    external_id TEXT NOT NULL DEFAULT '',
    delivery_status TEXT NOT NULL DEFAULT '',
    delivery_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS autoreply_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
    scope TEXT NOT NULL DEFAULT 'all',
    goods_id INTEGER REFERENCES goods(id) ON DELETE CASCADE,
    match_type TEXT NOT NULL DEFAULT 'keyword',
    pattern TEXT NOT NULL,
    reply_type TEXT NOT NULL DEFAULT 'text',
    content TEXT NOT NULL DEFAULT '',
    image_url TEXT NOT NULL DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS autosell_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    goods_id INTEGER REFERENCES goods(id) ON DELETE CASCADE,
    delivery_type TEXT NOT NULL DEFAULT 'fixed',
    content TEXT NOT NULL DEFAULT '',
    api_url TEXT NOT NULL DEFAULT '',
    api_method TEXT NOT NULL DEFAULT 'POST',
    api_headers TEXT NOT NULL DEFAULT '{}',
    api_body TEXT NOT NULL DEFAULT '',
    api_response_path TEXT NOT NULL DEFAULT '',
    multi_quantity INTEGER NOT NULL DEFAULT 0,
    workflow_id INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS autosell_stock (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER NOT NULL REFERENCES autosell_rules(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'available',
    used_order_id INTEGER,
    used_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    rule_id INTEGER,
    status TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monitor_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    keyword TEXT NOT NULL,
    min_price REAL,
    max_price REAL,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    interval_seconds INTEGER NOT NULL DEFAULT 60,
    action TEXT NOT NULL DEFAULT 'notify',
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monitor_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES monitor_tasks(id) ON DELETE CASCADE,
    item_key TEXT NOT NULL,
    title TEXT NOT NULL,
    price REAL NOT NULL DEFAULT 0,
    url TEXT NOT NULL DEFAULT '',
    found_at TEXT NOT NULL,
    UNIQUE(task_id, item_key)
);

CREATE TABLE IF NOT EXISTS workflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    nodes_json TEXT NOT NULL DEFAULT '[]',
    edges_json TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id INTEGER NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    order_id INTEGER,
    status TEXT NOT NULL,
    context_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS workflow_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    node_id TEXT NOT NULL,
    node_type TEXT NOT NULL,
    status TEXT NOT NULL,
    output TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mock_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    price REAL NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_notification_bindings (
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    channel_id INTEGER NOT NULL REFERENCES notification_channels(id) ON DELETE CASCADE,
    PRIMARY KEY (account_id, channel_id)
);

CREATE TABLE IF NOT EXISTS notification_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER,
    event TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL UNIQUE,
    original_name TEXT NOT NULL DEFAULT '',
    mime TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_bases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kb_id INTEGER NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    kb_id INTEGER NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_kb ON knowledge_chunks(kb_id);
CREATE INDEX IF NOT EXISTS idx_docs_kb ON knowledge_documents(kb_id);

CREATE TABLE IF NOT EXISTS product_materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price REAL NOT NULL DEFAULT 0,
    stock INTEGER NOT NULL DEFAULT 0,
    image_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS publish_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER,
    account_id INTEGER,
    goods_id INTEGER,
    item_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auto_relist_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goods_id INTEGER NOT NULL REFERENCES goods(id) ON DELETE CASCADE,
    material_id INTEGER REFERENCES product_materials(id) ON DELETE SET NULL,
    interval_seconds INTEGER NOT NULL DEFAULT 600,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auto_relist_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER,
    goods_id INTEGER,
    status TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quick_phrases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    interval_seconds INTEGER NOT NULL DEFAULT 600,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run_at TEXT,
    next_run_at TEXT,
    last_status TEXT,
    last_message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    jti TEXT NOT NULL UNIQUE,
    user_agent TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL DEFAULT '',
    revoked_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id);

CREATE TABLE IF NOT EXISTS movie_ticket_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL DEFAULT 1,
    order_no TEXT NOT NULL UNIQUE,
    movie_name TEXT NOT NULL,
    cinema TEXT NOT NULL DEFAULT '',
    show_time TEXT NOT NULL DEFAULT '',
    seats TEXT NOT NULL DEFAULT '',
    quantity INTEGER NOT NULL DEFAULT 1,
    amount REAL NOT NULL DEFAULT 0,
    buyer TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    code TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    used_at TEXT NOT NULL DEFAULT '',
    verified_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS buyer_blacklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL DEFAULT 1,
    buyer TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(owner_id, buyer)
);

CREATE TABLE IF NOT EXISTS buyer_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL DEFAULT 1,
    buyer TEXT NOT NULL,
    tag TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(owner_id, buyer, tag)
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def data_dir() -> Path:
    p = Path(os.environ.get("FAP_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return Path(os.environ.get("FAP_DB", data_dir() / "app.db"))


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or db_path()), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    conn = conn or connect()
    try:
        conn.executescript(SCHEMA)
        _ensure_user_columns(conn)
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
        backfill_order_audit(conn)
        conn.commit()
    finally:
        if own:
            conn.close()


def backfill_order_audit(conn: sqlite3.Connection) -> int:
    """Attach legacy order audit rows to order ids parsed from their detail."""
    orders = {r["order_no"]: r["id"] for r in conn.execute("SELECT id, order_no FROM orders")}
    ids = set(orders.values())
    rows = conn.execute(
        "SELECT id, detail FROM audit_logs WHERE action LIKE 'order.%' AND entity_type=''"
    ).fetchall()
    updated = 0
    for row in rows:
        match = re.search(r"order=([^\s]+)", row["detail"] or "")
        if not match:
            continue
        value = match.group(1)
        order_id = orders.get(value)
        if not order_id and value.isdigit() and int(value) in ids:
            order_id = int(value)
        if order_id:
            conn.execute(
                "UPDATE audit_logs SET entity_type='order', entity_id=? WHERE id=?",
                (order_id, row["id"]),
            )
            updated += 1
    return updated


OWNER_TABLES = (
    "accounts", "goods", "orders", "conversations",
    "autoreply_rules", "autosell_rules", "monitor_tasks", "workflows",
    "product_materials", "auto_relist_rules", "knowledge_bases",
    "notification_channels", "media_files", "quick_phrases", "job_tasks",
    "movie_ticket_orders", "buyer_tags", "buyer_blacklist",
)


def _ensure_user_columns(conn: sqlite3.Connection) -> None:
    """Add owner_id/is_active columns to databases created before multi-user."""
    user_cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "is_active" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    for table in OWNER_TABLES:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "owner_id" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN owner_id INTEGER NOT NULL DEFAULT 1")
        conn.execute(f"UPDATE {table} SET owner_id=1 WHERE owner_id IS NULL OR owner_id=0")
    extra = (
        ("accounts", "auto_comment", "INTEGER NOT NULL DEFAULT 0"),
        ("accounts", "comment_template", "TEXT NOT NULL DEFAULT ''"),
        ("accounts", "nickname", "TEXT NOT NULL DEFAULT ''"),
        ("accounts", "avatar_url", "TEXT NOT NULL DEFAULT ''"),
        ("accounts", "platform_user_id", "TEXT NOT NULL DEFAULT ''"),
        ("movie_ticket_orders", "used_at", "TEXT NOT NULL DEFAULT ''"),
        ("movie_ticket_orders", "verified_by", "TEXT NOT NULL DEFAULT ''"),
        ("orders", "rated_at", "TEXT NOT NULL DEFAULT ''"),
        ("orders", "rate_status", "TEXT NOT NULL DEFAULT ''"),
        ("orders", "rate_content", "TEXT NOT NULL DEFAULT ''"),
        ("orders", "refund_status", "TEXT NOT NULL DEFAULT ''"),
        ("orders", "refund_amount", "REAL NOT NULL DEFAULT 0"),
        ("orders", "refund_reason", "TEXT NOT NULL DEFAULT ''"),
        ("orders", "refunded_at", "TEXT NOT NULL DEFAULT ''"),
        ("orders", "ship_status", "TEXT NOT NULL DEFAULT ''"),
        ("orders", "platform_shipped_at", "TEXT NOT NULL DEFAULT ''"),
        ("orders", "note", "TEXT NOT NULL DEFAULT ''"),
        ("audit_logs", "entity_type", "TEXT NOT NULL DEFAULT ''"),
        ("audit_logs", "entity_id", "INTEGER NOT NULL DEFAULT 0"),
        ("conversations", "autoreply_paused", "INTEGER NOT NULL DEFAULT 0"),
        ("conversations", "autoreply_paused_until", "TEXT NOT NULL DEFAULT ''"),
        ("messages", "external_id", "TEXT NOT NULL DEFAULT ''"),
        ("messages", "delivery_status", "TEXT NOT NULL DEFAULT ''"),
        ("messages", "delivery_error", "TEXT NOT NULL DEFAULT ''"),
        ("goods", "item_id", "TEXT NOT NULL DEFAULT ''"),
        ("users", "session_version", "INTEGER NOT NULL DEFAULT 0"),
    )
    for table, column, ddl in extra:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_external "
        "ON messages(conversation_id, external_id) WHERE external_id<>''"
    )


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def audit(conn: sqlite3.Connection, action: str, detail: str = "", user_id: int | None = None,
          entity_type: str = "", entity_id: int = 0) -> None:
    conn.execute(
        "INSERT INTO audit_logs(user_id, action, detail, entity_type, entity_id, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (user_id, action, detail, entity_type, int(entity_id or 0), now_iso()),
    )


DEMO_GOODS = [
    ("闲鱼自动发货测试商品", 9.9, 50, "on_sale", "这是一个用于演示自动发货的商品。拍下后自动发送卡密。"),
    ("AI 客服演示商品", 19.9, 20, "on_sale", "用于演示自动回复与 AI 客服。"),
    ("库存卡密演示商品", 5.0, 100, "on_sale", "演示多数量发货：拍几件发几份卡密。"),
]


def seed_demo(conn: sqlite3.Connection) -> dict:
    """Create demonstration data so the UI is usable immediately."""
    exists = conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"]
    if exists:
        return {"seeded": False, "reason": "accounts already exist"}

    ts = now_iso()
    cur = conn.execute(
        "INSERT INTO accounts(name, cookie, status, enabled, note, ai_enabled, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        ("演示账号", "demo-cookie", "online", 1, "模拟账号，用于本地演示", 1, ts),
    )
    account_id = cur.lastrowid

    goods_ids = []
    for title, price, stock, status, desc in DEMO_GOODS:
        c = conn.execute(
            "INSERT INTO goods(account_id, title, price, stock, status, description, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (account_id, title, price, stock, status, desc, ts),
        )
        goods_ids.append(c.lastrowid)

    conn.execute(
        "INSERT INTO autoreply_rules(name, account_id, scope, goods_id, match_type, pattern, reply_type, content, priority, enabled, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("价格咨询", account_id, "all", None, "keyword", "便宜,少点,优惠",
         "text", "亲，这款已经是活动价啦，拍下后会自动发货哦～", 10, 1, ts),
    )
    conn.execute(
        "INSERT INTO autoreply_rules(name, account_id, scope, goods_id, match_type, pattern, reply_type, content, priority, enabled, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("发货时间", account_id, "all", None, "keyword", "发货,多久,什么时候",
         "text", "付款后系统会自动发货，通常 1 分钟内到账，请留意闲鱼消息。", 9, 1, ts),
    )
    conn.execute(
        "INSERT INTO autoreply_rules(name, account_id, scope, goods_id, match_type, pattern, reply_type, content, priority, enabled, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("AI 兜底", account_id, "all", None, "regex", ".*", "ai", "", 0, 0, ts),
    )

    conn.execute(
        "INSERT INTO autosell_rules(name, goods_id, delivery_type, content, multi_quantity, enabled, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        ("固定内容发货", goods_ids[0], "fixed",
         "感谢购买！您的卡密是 DEMO-{{order_no}}，请妥善保存。", 0, 1, ts),
    )
    cur = conn.execute(
        "INSERT INTO autosell_rules(name, goods_id, delivery_type, content, multi_quantity, enabled, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        ("库存卡密发货（多数量）", goods_ids[2], "stock", "", 1, 1, ts),
    )
    stock_rule_id = cur.lastrowid
    for i in range(1, 21):
        conn.execute(
            "INSERT INTO autosell_stock(rule_id, content, status, created_at) VALUES(?,?,?,?)",
            (stock_rule_id, f"DEMO-KEY-{i:04d}", "available", ts),
        )

    conn.execute(
        "INSERT INTO monitor_tasks(name, keyword, min_price, max_price, account_id, interval_seconds, action, enabled, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        ("监控：显卡", "显卡", 100, 5000, account_id, 60, "notify", 1, ts),
    )
    conn.execute(
        "INSERT INTO mock_items(title, price, url, created_at) VALUES(?,?,?,?)",
        ("九成新 RTX 4070 显卡", 3200, "https://example.com/item/1001", ts),
    )

    wf_nodes = [
        {"id": "start", "type": "trigger", "label": "订单支付"},
        {"id": "set", "type": "set", "key": "shop", "value": "FishAutoPro Clone"},
        {"id": "cond", "type": "condition", "left": "{{quantity}}", "op": ">", "right": "1",
         "label": "多数量？"},
        {"id": "multi", "type": "deliver", "content": "多件订单：共 {{quantity}} 份\n{{delivery}}"},
        {"id": "single", "type": "deliver", "content": "单件订单：{{delivery}}"},
        {"id": "notify", "type": "notify", "message": "订单 {{order_no}} 已处理"},
    ]
    wf_edges = [
        {"from": "start", "to": "set"},
        {"from": "set", "to": "cond"},
        {"from": "cond", "to": "multi", "when": "true"},
        {"from": "cond", "to": "single", "when": "false"},
        {"from": "multi", "to": "notify"},
        {"from": "single", "to": "notify"},
    ]
    conn.execute(
        "INSERT INTO workflows(name, nodes_json, edges_json, enabled, created_at) VALUES(?,?,?,?,?)",
        ("多数量发货流程", json.dumps(wf_nodes, ensure_ascii=False),
         json.dumps(wf_edges, ensure_ascii=False), 1, ts),
    )

    conn.execute(
        "INSERT INTO conversations(account_id, goods_id, buyer, last_message, unread, ai_enabled, updated_at, created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (account_id, goods_ids[0], "demo_buyer", "这个还有货吗？", 1, 1, ts, ts),
    )
    conv_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.execute(
        "INSERT INTO messages(conversation_id, direction, content, created_at) VALUES(?,?,?,?)",
        (conv_id, "in", "这个还有货吗？", ts),
    )

    kb = conn.execute(
        "INSERT INTO knowledge_bases(name, description, enabled, created_at) VALUES(?,?,?,?)",
        ("店铺知识库", "发货说明、售后政策、常见问题", 1, ts),
    )
    kb_id = int(kb.lastrowid)
    docs = [
        ("发货说明", "付款后系统自动发货，卡密会发送到闲鱼聊天，通常 1 分钟内到账。若未收到，请先检查闲鱼消息和订单状态；超过 10 分钟仍未收到，请提供订单号联系客服。"),
        ("售后政策", "虚拟商品一经发出不支持无理由退款。如卡密无效、已被使用或与描述不符，请提供订单号和卡密截图，客服核实后补发或退款。"),
        ("常见问题", "可以便宜一点吗？本店价格已是最低活动价，暂不议价。支持多发吗？下单几件就发几份，库存不足会提示。"),
    ]
    from . import knowledge

    for title, content in docs:
        cur = conn.execute(
            "INSERT INTO knowledge_documents(kb_id, title, content, created_at, updated_at) VALUES(?,?,?,?,?)",
            (kb_id, title, content, ts, ts),
        )
        knowledge.reindex_document(conn, int(cur.lastrowid))
    conn.execute(
        "INSERT INTO settings(key, value) VALUES('ai_kb_id', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(kb_id),),
    )

    material_ids = []
    for idx, (title, price, stock, status, desc) in enumerate(DEMO_GOODS):
        cur = conn.execute(
            "INSERT INTO product_materials(account_id, name, title, description, price, stock, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (account_id, f"素材-{title}", title, desc, price, stock, ts),
        )
        material_ids.append(int(cur.lastrowid))
    conn.execute(
        "INSERT INTO auto_relist_rules(goods_id, material_id, interval_seconds, enabled, created_at) "
        "VALUES(?,?,?,?,?)",
        (goods_ids[0], material_ids[0], 600, 1, ts),
    )
    for i, phrase in enumerate([
        "亲，在的，有什么可以帮您？",
        "付款后会自动发货，请留意闲鱼消息～",
        "稍等，我帮您确认一下库存。",
    ]):
        conn.execute(
            "INSERT INTO quick_phrases(content, sort_order, created_at) VALUES(?,?,?)",
            (phrase, i, ts),
        )

    conn.execute(
        "INSERT INTO movie_ticket_orders(owner_id, order_no, movie_name, cinema, show_time, seats, "
        "quantity, amount, buyer, phone, status, code, note, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (1, "MT-DEMO-1", "流浪地球 3", "万达影城·人民广场店", "2026-11-01 19:30",
         "7排8座,7排9座", 2, 79.8, "观影买家", "13800000000", "paid",
         "MT-DEMO-CODE-1", "演示电影票订单", ts, ts),
    )

    conn.commit()
    return {"seeded": True, "account_id": account_id, "goods_ids": goods_ids}
