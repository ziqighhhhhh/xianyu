"""HTTP API for the clone (Flask blueprint)."""

from __future__ import annotations

import base64
import io
import json
import os
import random
import secrets
import string
import time
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import httpx
from flask import Blueprint, g, jsonify, request, make_response, send_file, current_app

from . import auth, backup, db, exports, jobs, knowledge, maintenance, notify, publish, ratelimit, sync
from . import account_export
from .engines import ai, delivery, replies
from .engines import workflows as wf_engine
from .engines.common import render as render_template
from .engines.workflows import WorkflowError
from .platform import goofish, lwp, lwp_frames, mtop
from .platform.goofish import GoofishAdapter, PlatformUnavailable
from .platform.mock import MockAdapter

api = Blueprint("api", __name__, url_prefix="/api")


# --------------------------------------------------------------------------- helpers

def conn():
    if "conn" not in g:
        g.conn = db.connect()
        g.conn.row_factory = __import__("sqlite3").Row
    return g.conn


def body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def ok(payload=None, **kwargs):
    data = {"ok": True}
    if payload is not None:
        data.update(payload if isinstance(payload, dict) else {"data": payload})
    data.update(kwargs)
    return jsonify(data)


def fail(message: str, status: int = 400, **kwargs):
    data = {"ok": False, "error": message}
    data.update(kwargs)
    return jsonify(data), status


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _now() -> str:
    return db.now_iso()


def _new_order_no() -> str:
    return "FAP" + time.strftime("%Y%m%d%H%M%S") + "".join(random.choices(string.digits, k=4))


def _adapter_for(account: dict | None):
    from .platform.factory import adapter_for

    return adapter_for(account)


def _account(account_id):
    row = conn().execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not row:
        return None
    if not is_admin() and row["owner_id"] != owner_id():
        return None
    return dict(row)


def _goods(goods_id):
    row = conn().execute("SELECT * FROM goods WHERE id=?", (goods_id,)).fetchone()
    if not row:
        return None
    if not is_admin() and row["owner_id"] != owner_id():
        return None
    return dict(row)


def _conversation(conversation_id):
    row = conn().execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    if not row:
        return None
    if not is_admin() and row["owner_id"] != owner_id():
        return None
    return dict(row)


def _sell_rule(rule_id):
    row = conn().execute("SELECT * FROM autosell_rules WHERE id=?", (rule_id,)).fetchone()
    if not row:
        return None
    if not is_admin() and row["owner_id"] != owner_id():
        return None
    return dict(row)


def _kb(kb_id):
    row = conn().execute(
        "SELECT b.* FROM knowledge_bases b WHERE b.id=? AND (?=1 OR b.owner_id=?)",
        (kb_id, 1 if is_admin() else 0, owner_id()),
    ).fetchone()
    return dict(row) if row else None


def _doc(doc_id):
    row = conn().execute(
        "SELECT d.* FROM knowledge_documents d JOIN knowledge_bases b ON b.id=d.kb_id "
        "WHERE d.id=? AND (?=1 OR b.owner_id=?)",
        (doc_id, 1 if is_admin() else 0, owner_id()),
    ).fetchone()
    return dict(row) if row else None


def is_admin() -> bool:
    return (g.user or {}).get("role") == "admin"


def owner_id() -> int:
    return int((g.user or {}).get("id") or 0)


def scope(alias: str = "") -> tuple[str, list]:
    """SQL fragment + args restricting a query to the current user's rows."""
    if is_admin():
        return "", []
    prefix = (alias + ".") if alias else ""
    return f" AND {prefix}owner_id=?", [owner_id()]


def can_access(table: str, row_id: int) -> bool:
    row = conn().execute(f"SELECT owner_id FROM {table} WHERE id=?", (row_id,)).fetchone()
    return bool(row) and (is_admin() or row["owner_id"] == owner_id())


def require_admin():
    if not is_admin():
        return fail("需要管理员权限", 403)
    return None


INTEGRATION_TOKEN_KEY = "ingest_token"


def _setting(key: str) -> str:
    row = conn().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else ""


def _set_setting(key: str, value: str) -> None:
    conn().execute(
        "INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def integration_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("X-FAP-Token", "")
        auth_header = request.headers.get("Authorization", "")
        if not header and auth_header.lower().startswith("bearer "):
            header = auth_header[7:].strip()
        expected = _setting(INTEGRATION_TOKEN_KEY)
        if not expected:
            return fail("尚未配置消息接入令牌", 503)
        if not header or not secrets.compare_digest(header, expected):
            return fail("接入令牌无效", 401)
        return fn(*args, **kwargs)
    return wrapper


# --------------------------------------------------------------------------- setup / auth

@api.get("/setup/status")
def setup_status():
    return jsonify({"needs_setup": auth.setup_required()})


@api.post("/setup")
def setup():
    if not auth.setup_required():
        return fail("系统已初始化", 409)
    ip_key = f"setup:{request.remote_addr}"
    allowed, retry = ratelimit.check(ip_key, limit=3, window=600)
    if not allowed:
        return fail(f"初始化尝试过多，请 {retry} 秒后再试", 429, retry_after=retry)
    data = body()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if len(username) < 3:
        ratelimit.failure(ip_key)
        return fail("用户名至少 3 个字符")
    if len(password) < 6:
        ratelimit.failure(ip_key)
        return fail("密码至少 6 个字符")
    user_id = auth.create_user(username, password)
    if data.get("seed_demo", True):
        try:
            db.seed_demo(conn())
        except Exception:
            pass
    db.audit(conn(), "setup", f"user={username}", user_id)
    conn().commit()
    resp = make_response(jsonify({"ok": True, "user": {"id": user_id, "username": username, "role": "admin"}}))
    token = auth.issue_session(user_id, 0, request.headers.get("User-Agent", ""),
                               request.remote_addr or "")
    resp.set_cookie(auth.COOKIE_NAME, token, httponly=True, secure=auth.cookie_secure(),
                    samesite="Lax", max_age=auth.SESSION_TTL)
    return resp


@api.post("/auth/login")
def login():
    data = body()
    username = (data.get("username") or "").strip()
    key = f"login:{request.remote_addr}:{username.casefold()}"
    allowed, retry = ratelimit.check(key, limit=5, window=300)
    if not allowed:
        db.audit(conn(), "login.locked", f"user={username} ip={request.remote_addr}")
        notify.notify_async_safe(conn(), "auth.lockout", "登录被限流",
                                 f"账号 {username} 在 5 分钟内失败次数过多，来源 {request.remote_addr}")
        conn().commit()
        resp, status = fail(f"尝试次数过多，请 {retry} 秒后再试", 429, retry_after=retry)
        resp.headers["Retry-After"] = str(retry)
        return resp, status
    user = auth.authenticate(username, data.get("password") or "")
    if not user:
        ratelimit.failure(key)
        db.audit(conn(), "login.failed", f"user={username} ip={request.remote_addr}")
        conn().commit()
        return fail("用户名或密码错误", 401)
    ratelimit.reset(key)
    db.audit(conn(), "login", f"user={user['username']}", user["id"])
    conn().commit()
    resp = make_response(jsonify({"ok": True, "user": user}))
    token = auth.issue_session(user["id"], user.get("session_version", 0),
                               request.headers.get("User-Agent", ""), request.remote_addr or "")
    resp.set_cookie(auth.COOKIE_NAME, token, httponly=True, secure=auth.cookie_secure(),
                    samesite="Lax", max_age=auth.SESSION_TTL)
    return resp


@api.post("/auth/logout")
def logout():
    payload = auth.parse_session(request.cookies.get(auth.COOKIE_NAME))
    if payload:
        auth.revoke_session(payload.get("jti", ""))
    resp = make_response(jsonify({"ok": True}))
    resp.delete_cookie(auth.COOKIE_NAME)
    return resp


@api.get("/auth/sessions")
@auth.login_required
def list_sessions():
    payload = auth.parse_session(request.cookies.get(auth.COOKIE_NAME)) or {}
    current_jti = payload.get("jti", "")
    rows = conn().execute(
        "SELECT id, jti, user_agent, ip, created_at, last_seen_at FROM user_sessions "
        "WHERE user_id=? AND revoked_at='' ORDER BY id DESC", (g.user["id"],)
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["current"] = item.pop("jti") == current_jti
        out.append(item)
    return jsonify({"sessions": out})


@api.delete("/auth/sessions/<int:session_id>")
@auth.login_required
def revoke_own_session(session_id):
    row = conn().execute("SELECT * FROM user_sessions WHERE id=? AND user_id=?",
                         (session_id, g.user["id"])).fetchone()
    if not row:
        return fail("会话不存在", 404)
    conn().execute("UPDATE user_sessions SET revoked_at=? WHERE id=?", (_now(), session_id))
    conn().commit()
    payload = auth.parse_session(request.cookies.get(auth.COOKIE_NAME)) or {}
    return ok({"current": row["jti"] == payload.get("jti", "")})


@api.get("/auth/me")
@auth.login_required
def me():
    return jsonify({"user": g.user})


@api.post("/auth/password")
@auth.login_required
def change_password():
    data = body()
    old = data.get("old_password") or ""
    new = data.get("new_password") or ""
    if len(new) < 6:
        return fail("新密码至少 6 个字符")
    if old == new:
        return fail("新密码不能与旧密码相同")
    row = conn().execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
    if not row or not auth.verify_password(old, row["password_hash"]):
        return fail("旧密码不正确", 400)
    version = int(row["session_version"]) + 1
    conn().execute(
        "UPDATE users SET password_hash=?, session_version=? WHERE id=?",
        (auth.hash_password(new), version, row["id"]),
    )
    db.audit(conn(), "auth.password", f"user={row['username']}", row["id"])
    conn().commit()
    auth.revoke_user_sessions(row["id"])
    token = auth.issue_session(row["id"], version, request.headers.get("User-Agent", ""),
                               request.remote_addr or "")
    resp = make_response(jsonify({"ok": True}))
    resp.set_cookie(auth.COOKIE_NAME, token, httponly=True, secure=auth.cookie_secure(),
                    samesite="Lax", max_age=auth.SESSION_TTL)
    return resp


# --------------------------------------------------------------------------- users

@api.get("/users")
@auth.login_required
def list_users():
    guard = require_admin()
    if guard:
        return guard
    rows = conn().execute(
        "SELECT u.id, u.username, u.role, u.is_active, u.created_at, "
        "(SELECT COUNT(*) FROM accounts a WHERE a.owner_id=u.id) AS account_count "
        "FROM users u ORDER BY u.id"
    ).fetchall()
    return jsonify({"users": db.rows_to_dicts(rows)})


@api.post("/users")
@auth.login_required
def create_user_api():
    guard = require_admin()
    if guard:
        return guard
    data = body()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = data.get("role") or "operator"
    if len(username) < 3:
        return fail("用户名至少 3 个字符")
    if len(password) < 6:
        return fail("密码至少 6 个字符")
    if role not in ("admin", "operator"):
        return fail("角色只能是 admin 或 operator")
    try:
        user_id = auth.create_user(username, password, role)
    except Exception:
        return fail("用户名已存在")
    db.audit(conn(), "user.create", f"user={username} role={role}", g.user["id"])
    conn().commit()
    return ok({"id": user_id})


@api.patch("/users/<int:user_id>")
@auth.login_required
def update_user_api(user_id):
    guard = require_admin()
    if guard:
        return guard
    row = conn().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        return fail("用户不存在", 404)
    data = body()
    fields, values = [], []
    if "role" in data:
        if data["role"] not in ("admin", "operator"):
            return fail("角色只能是 admin 或 operator")
        if row["role"] == "admin" and data["role"] != "admin":
            admins = conn().execute(
                "SELECT COUNT(*) AS n FROM users WHERE role='admin' AND is_active=1 AND id!=?", (user_id,)
            ).fetchone()["n"]
            if admins == 0:
                return fail("至少保留一个启用的管理员")
        fields.append("role=?")
        values.append(data["role"])
    if "is_active" in data:
        active = 1 if data["is_active"] else 0
        if not active and row["role"] == "admin":
            admins = conn().execute(
                "SELECT COUNT(*) AS n FROM users WHERE role='admin' AND is_active=1 AND id!=?", (user_id,)
            ).fetchone()["n"]
            if admins == 0:
                return fail("至少保留一个启用的管理员")
        fields.append("is_active=?")
        values.append(active)
    if "password" in data and data["password"]:
        if len(data["password"]) < 6:
            return fail("密码至少 6 个字符")
        fields.append("password_hash=?")
        values.append(auth.hash_password(data["password"]))
        fields.append("session_version=session_version+1")
    if not fields:
        return fail("没有可更新的字段")
    values.append(user_id)
    conn().execute(f"UPDATE users SET {', '.join(fields)} WHERE id=?", values)
    db.audit(conn(), "user.update", f"user={row['username']}", g.user["id"])
    conn().commit()
    if ("password" in data and data.get("password")) or data.get("is_active") is False:
        auth.revoke_user_sessions(user_id)
    return ok()


@api.delete("/users/<int:user_id>")
@auth.login_required
def delete_user_api(user_id):
    guard = require_admin()
    if guard:
        return guard
    if user_id == g.user["id"]:
        return fail("不能删除当前登录用户")
    row = conn().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        return fail("用户不存在", 404)
    if row["role"] == "admin":
        admins = conn().execute(
            "SELECT COUNT(*) AS n FROM users WHERE role='admin' AND is_active=1 AND id!=?", (user_id,)
        ).fetchone()["n"]
        if admins == 0:
            return fail("至少保留一个启用的管理员")
    owned = 0
    for table in db.OWNER_TABLES:
        owned += conn().execute(f"SELECT COUNT(*) AS n FROM {table} WHERE owner_id=?", (user_id,)).fetchone()["n"]
    if owned:
        return fail("该用户仍有账号/商品/订单/规则等数据，请先删除或转移", 400)
    conn().execute("DELETE FROM users WHERE id=?", (user_id,))
    conn().execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
    db.audit(conn(), "user.delete", f"user={row['username']}", g.user["id"])
    conn().commit()
    return ok()


# --------------------------------------------------------------------------- dashboard

@api.get("/dashboard")
@auth.login_required
def dashboard():
    c = conn()
    today = time.strftime("%Y-%m-%d")
    days_count = max(1, min(_int(request.args.get("days"), 7) or 7, 90))
    start_day = time.strftime("%Y-%m-%d", time.localtime(time.time() - (days_count - 1) * 86400))

    def count(sql: str, args=()):
        return c.execute(sql, args).fetchone()["n"]

    s, sa = scope()
    stats = {
        "accounts": count(f"SELECT COUNT(*) AS n FROM accounts WHERE 1=1 {s}", sa),
        "accounts_online": count(f"SELECT COUNT(*) AS n FROM accounts WHERE status='online' {s}", sa),
        "goods": count(f"SELECT COUNT(*) AS n FROM goods WHERE status='on_sale' {s}", sa),
        "orders_today": count(f"SELECT COUNT(*) AS n FROM orders WHERE substr(created_at,1,10)=? {s}", [today, *sa]),
        "orders_pending": count(f"SELECT COUNT(*) AS n FROM orders WHERE status='paid' {s}", sa),
        "orders_failed": count(f"SELECT COUNT(*) AS n FROM orders WHERE status='failed' {s}", sa),
        "orders_range": count(f"SELECT COUNT(*) AS n FROM orders WHERE substr(created_at,1,10)>=? {s}", [start_day, *sa]),
        "refunds_range": count(f"SELECT COUNT(*) AS n FROM orders WHERE status='refunded' AND substr(created_at,1,10)>=? {s}",
                               [start_day, *sa]),
        "revenue_today": c.execute(
            f"SELECT COALESCE(SUM(amount),0) AS v FROM orders WHERE substr(created_at,1,10)=? "
            f"AND status!='refunded' {s}", [today, *sa],
        ).fetchone()["v"],
        "revenue_range": c.execute(
            f"SELECT COALESCE(SUM(amount),0) AS v FROM orders WHERE substr(created_at,1,10)>=? "
            f"AND status!='refunded' {s}", [start_day, *sa],
        ).fetchone()["v"],
        "refund_amount_range": c.execute(
            f"SELECT COALESCE(SUM(refund_amount),0) AS v FROM orders WHERE refund_status='success' "
            f"AND substr(refunded_at,1,10)>=? {s}", [start_day, *sa],
        ).fetchone()["v"],
        "delivered_total": count(f"SELECT COUNT(*) AS n FROM orders WHERE status='delivered' {s}", sa),
        "stock_available": count(
            "SELECT COUNT(*) AS n FROM autosell_stock st JOIN autosell_rules r ON r.id=st.rule_id "
            f"WHERE st.status='available' {scope('r')[0]}", scope("r")[1],
        ),
        "unread": c.execute(f"SELECT COALESCE(SUM(unread),0) AS n FROM conversations WHERE 1=1 {s}", sa).fetchone()["n"],
    }
    so, soa = scope("o")
    recent_orders = db.rows_to_dicts(c.execute(
        "SELECT o.*, g.title AS goods_title FROM orders o LEFT JOIN goods g ON g.id=o.goods_id "
        f"WHERE 1=1 {so} ORDER BY o.id DESC LIMIT 6", soa
    ).fetchall())
    sc, sca = scope("cv")
    recent_messages = db.rows_to_dicts(c.execute(
        "SELECT m.*, cv.buyer FROM messages m JOIN conversations cv ON cv.id=m.conversation_id "
        f"WHERE 1=1 {sc} ORDER BY m.id DESC LIMIT 6", sca
    ).fetchall())
    days = []
    for offset in range(days_count - 1, -1, -1):
        day = time.strftime("%Y-%m-%d", time.localtime(time.time() - offset * 86400))
        row = c.execute(
            "SELECT COUNT(*) AS orders, COALESCE(SUM(CASE WHEN status='delivered' THEN 1 ELSE 0 END),0) AS delivered, "
            f"COALESCE(SUM(amount),0) AS amount FROM orders WHERE substr(created_at,1,10)=? {s}",
            [day, *sa],
        ).fetchone()
        days.append({"date": day, "orders": row["orders"], "delivered": row["delivered"], "amount": row["amount"]})
    return jsonify({"stats": stats, "recent_orders": recent_orders, "recent_messages": recent_messages,
                    "days": days, "range_days": days_count})


def _events_since(after_message: int, after_order: int, after_job: int) -> dict:
    sc, sca = scope("c")
    messages = db.rows_to_dicts(conn().execute(
        "SELECT m.id, m.content, m.direction, m.created_at, c.buyer, c.id AS conversation_id "
        "FROM messages m JOIN conversations c ON c.id=m.conversation_id "
        f"WHERE m.id>? {sc} ORDER BY m.id LIMIT 20", [after_message, *sca]
    ).fetchall())
    so, soa = scope("o")
    orders = db.rows_to_dicts(conn().execute(
        "SELECT o.id, o.order_no, o.buyer, o.amount, o.status, o.created_at "
        f"FROM orders o WHERE o.id>? {so} ORDER BY o.id LIMIT 20", [after_order, *soa]
    ).fetchall())
    sj, sja = scope("t")
    jobs = db.rows_to_dicts(conn().execute(
        "SELECT r.id, r.status, r.message, r.started_at, t.name AS task_name "
        "FROM job_runs r JOIN job_tasks t ON t.id=r.task_id "
        f"WHERE r.id>? {sj} ORDER BY r.id LIMIT 20", [after_job, *sja]
    ).fetchall())
    cursor = {
        "message": max([after_message] + [m["id"] for m in messages]),
        "order": max([after_order] + [o["id"] for o in orders]),
        "job": max([after_job] + [j["id"] for j in jobs]),
    }
    return {"messages": messages, "orders": orders, "jobs": jobs, "cursor": cursor}


def _event_args():
    return (_int(request.args.get("after_message"), 0) or 0,
            _int(request.args.get("after_order"), 0) or 0,
            _int(request.args.get("after_job"), 0) or 0)


@api.get("/events/wait")
@auth.login_required
def wait_events():
    after_message, after_order, after_job = _event_args()
    timeout = max(1, min(_int(request.args.get("timeout"), 20) or 20, 25))
    deadline = time.time() + timeout
    while True:
        data = _events_since(after_message, after_order, after_job)
        if data["messages"] or data["orders"] or data["jobs"]:
            data["timed_out"] = False
            return jsonify(data)
        if time.time() >= deadline:
            data["timed_out"] = True
            return jsonify(data)
        time.sleep(0.8)


@api.get("/events/poll")
@auth.login_required
def poll_events():
    after_message = _int(request.args.get("after_message"), 0) or 0
    after_order = _int(request.args.get("after_order"), 0) or 0
    after_job = _int(request.args.get("after_job"), 0) or 0
    sc, sca = scope("c")
    messages = db.rows_to_dicts(conn().execute(
        "SELECT m.id, m.content, m.direction, m.created_at, c.buyer, c.id AS conversation_id "
        "FROM messages m JOIN conversations c ON c.id=m.conversation_id "
        f"WHERE m.id>? {sc} ORDER BY m.id LIMIT 20", [after_message, *sca]
    ).fetchall())
    so, soa = scope("o")
    orders = db.rows_to_dicts(conn().execute(
        "SELECT o.id, o.order_no, o.buyer, o.amount, o.status, o.created_at "
        f"FROM orders o WHERE o.id>? {so} ORDER BY o.id LIMIT 20", [after_order, *soa]
    ).fetchall())
    sj, sja = scope("t")
    jobs = db.rows_to_dicts(conn().execute(
        "SELECT r.id, r.status, r.message, r.started_at, t.name AS task_name "
        "FROM job_runs r JOIN job_tasks t ON t.id=r.task_id "
        f"WHERE r.id>? {sj} ORDER BY r.id LIMIT 20", [after_job, *sja]
    ).fetchall())
    cursor = {
        "message": max([after_message] + [m["id"] for m in messages]),
        "order": max([after_order] + [o["id"] for o in orders]),
        "job": max([after_job] + [j["id"] for j in jobs]),
    }
    return jsonify({"messages": messages, "orders": orders, "jobs": jobs, "cursor": cursor})


# --------------------------------------------------------------------------- buyer tags

@api.get("/buyer-tags")
@auth.login_required
def list_buyer_tags():
    s, sa = scope()
    sql = f"SELECT * FROM buyer_tags WHERE 1=1 {s}"
    args = list(sa)
    q = (request.args.get("q") or "").strip()
    if q:
        sql += " AND (buyer LIKE ? OR tag LIKE ? OR note LIKE ?)"
        args += [f"%{q}%"] * 3
    sql += " ORDER BY id DESC LIMIT 500"
    return jsonify({"tags": db.rows_to_dicts(conn().execute(sql, args).fetchall())})


@api.get("/buyers/summary")
@auth.login_required
def buyer_summary():
    buyer = (request.args.get("buyer") or "").strip()
    if not buyer:
        return fail("请提供买家")
    so, soa = scope("o")
    orders = conn().execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN o.status!='refunded' THEN o.amount ELSE 0 END),0) AS amount, "
        "MAX(o.created_at) AS last_at "
        f"FROM orders o WHERE o.buyer=? {so}", [buyer, *soa]
    ).fetchone()
    sc, sca = scope("c")
    convs = conn().execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(c.unread),0) AS unread "
        f"FROM conversations c WHERE c.buyer=? {sc}", [buyer, *sca]
    ).fetchone()
    st, sta = scope("t")
    tags = db.rows_to_dicts(conn().execute(
        f"SELECT t.* FROM buyer_tags t WHERE t.buyer=? {st} ORDER BY t.id DESC", [buyer, *sta]
    ).fetchall())
    recent = db.rows_to_dicts(conn().execute(
        "SELECT o.id, o.order_no, (SELECT g.title FROM goods g WHERE g.id=o.goods_id) AS goods_title, "
        "o.amount, o.status, o.created_at "
        f"FROM orders o WHERE o.buyer=? {so} ORDER BY o.id DESC LIMIT 5", [buyer, *soa]
    ).fetchall())
    messages = db.rows_to_dicts(conn().execute(
        "SELECT m.direction, m.content, m.created_at FROM messages m "
        "JOIN conversations c ON c.id=m.conversation_id "
        f"WHERE c.buyer=? {sc} ORDER BY m.id DESC LIMIT 10", [buyer, *sca]
    ).fetchall())
    return jsonify({
        "buyer": buyer,
        "orders": orders["n"],
        "spend": orders["amount"],
        "last_order_at": orders["last_at"] or "",
        "conversations": convs["n"],
        "unread": convs["unread"],
        "tags": tags,
        "recent_orders": recent,
        "recent_messages": messages,
    })


@api.get("/buyers/messages")
@auth.login_required
def buyer_messages():
    buyer = (request.args.get("buyer") or "").strip()
    if not buyer:
        return fail("请提供买家")
    before_id = _int(request.args.get("before_id"), 0) or 0
    limit = max(1, min(_int(request.args.get("limit"), 20) or 20, 50))
    sc, sca = scope("c")
    sql = ("SELECT m.id, m.direction, m.content, m.created_at, c.id AS conversation_id "
           "FROM messages m JOIN conversations c ON c.id=m.conversation_id "
           f"WHERE c.buyer=? {sc}")
    args = [buyer, *sca]
    if before_id:
        sql += " AND m.id<?"
        args.append(before_id)
    sql += " ORDER BY m.id DESC LIMIT ?"
    args.append(limit + 1)
    rows = db.rows_to_dicts(conn().execute(sql, args).fetchall())
    has_more = len(rows) > limit
    rows = rows[:limit]
    return jsonify({"messages": rows, "has_more": has_more,
                    "before_id": rows[-1]["id"] if rows else 0})


@api.get("/buyers/messages.xlsx")
@auth.login_required
def export_buyer_messages():
    buyer = (request.args.get("buyer") or "").strip()
    if not buyer:
        return fail("请提供买家")
    data = exports.messages_xlsx(conn(), None if is_admin() else owner_id(), buyer)
    return send_file(io.BytesIO(data), as_attachment=True,
                     download_name=exports.filename("buyer-messages"),
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@api.get("/buyer-blacklist")
@auth.login_required
def list_buyer_blacklist():
    s, sa = scope()
    sql = f"SELECT * FROM buyer_blacklist WHERE 1=1 {s}"
    args = list(sa)
    q = (request.args.get("q") or "").strip()
    if q:
        sql += " AND (buyer LIKE ? OR reason LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY id DESC LIMIT 500"
    return jsonify({"blacklist": db.rows_to_dicts(conn().execute(sql, args).fetchall())})


@api.post("/buyer-blacklist")
@auth.login_required
def upsert_buyer_blacklist():
    data = body()
    buyer = (data.get("buyer") or "").strip()
    if not buyer:
        return fail("买家不能为空")
    now = _now()
    conn().execute(
        "INSERT INTO buyer_blacklist(owner_id, buyer, reason, created_at) VALUES(?,?,?,?) "
        "ON CONFLICT(owner_id, buyer) DO UPDATE SET reason=excluded.reason",
        (owner_id(), buyer, data.get("reason", ""), now),
    )
    conn().commit()
    row = dict(conn().execute(
        "SELECT * FROM buyer_blacklist WHERE owner_id=? AND buyer=?", (owner_id(), buyer)).fetchone())
    db.audit(conn(), "buyer_blacklist.upsert", f"buyer={buyer}", g.user["id"])
    conn().commit()
    return ok({"entry": row})


@api.delete("/buyer-blacklist/<int:entry_id>")
@auth.login_required
def delete_buyer_blacklist(entry_id):
    if not can_access("buyer_blacklist", entry_id):
        return fail("黑名单项不存在", 404)
    row = conn().execute("SELECT buyer FROM buyer_blacklist WHERE id=?", (entry_id,)).fetchone()
    conn().execute("DELETE FROM buyer_blacklist WHERE id=?", (entry_id,))
    conn().commit()
    db.audit(conn(), "buyer_blacklist.delete", f"buyer={row['buyer']}", g.user["id"])
    conn().commit()
    return ok()


@api.post("/buyer-tags")
@auth.login_required
def upsert_buyer_tag():
    data = body()
    buyer = (data.get("buyer") or "").strip()
    tag = (data.get("tag") or "").strip()
    if not buyer or not tag:
        return fail("买家与标签都不能为空")
    now = _now()
    conn().execute(
        "INSERT INTO buyer_tags(owner_id, buyer, tag, note, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT(owner_id, buyer, tag) DO UPDATE SET "
        "note=excluded.note, updated_at=excluded.updated_at",
        (owner_id(), buyer, tag, data.get("note", ""), now, now),
    )
    conn().commit()
    row = dict(conn().execute(
        "SELECT * FROM buyer_tags WHERE owner_id=? AND buyer=? AND tag=?",
        (owner_id(), buyer, tag)).fetchone())
    db.audit(conn(), "buyer_tag.upsert", f"buyer={buyer} tag={tag}", g.user["id"])
    conn().commit()
    return ok({"tag": row})


@api.delete("/buyer-tags/<int:tag_id>")
@auth.login_required
def delete_buyer_tag(tag_id):
    if not can_access("buyer_tags", tag_id):
        return fail("标签不存在", 404)
    row = conn().execute("SELECT buyer, tag FROM buyer_tags WHERE id=?", (tag_id,)).fetchone()
    conn().execute("DELETE FROM buyer_tags WHERE id=?", (tag_id,))
    conn().commit()
    db.audit(conn(), "buyer_tag.delete", f"buyer={row['buyer']} tag={row['tag']}", g.user["id"])
    conn().commit()
    return ok()


# --------------------------------------------------------------------------- movie tickets

MOVIE_STATUSES = {"pending", "paid", "used", "refunded", "cancelled"}


@api.get("/movie-tickets")
@auth.login_required
def list_movie_tickets():
    s, sa = scope()
    sql = f"SELECT * FROM movie_ticket_orders WHERE 1=1 {s}"
    args = list(sa)
    q = (request.args.get("q") or "").strip()
    if q:
        sql += " AND (order_no LIKE ? OR movie_name LIKE ? OR buyer LIKE ?)"
        args += [f"%{q}%"] * 3
    status = (request.args.get("status") or "").strip()
    if status in MOVIE_STATUSES:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY id DESC LIMIT 300"
    return jsonify({"tickets": db.rows_to_dicts(conn().execute(sql, args).fetchall())})


@api.post("/movie-tickets")
@auth.login_required
def create_movie_ticket():
    data = body()
    movie_name = (data.get("movie_name") or "").strip()
    if not movie_name:
        return fail("请填写影片名称")
    status = data.get("status") or "pending"
    if status not in MOVIE_STATUSES:
        return fail("无效的票务状态")
    order_no = "MT" + datetime.now().strftime("%Y%m%d%H%M%S") + str(random.randint(100, 999))
    code = secrets.token_hex(10).upper()
    cur = conn().execute(
        "INSERT INTO movie_ticket_orders(owner_id, order_no, movie_name, cinema, show_time, seats, "
        "quantity, amount, buyer, phone, status, code, note, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (owner_id(), order_no, movie_name, data.get("cinema", ""), data.get("show_time", ""),
         data.get("seats", ""), max(1, _int(data.get("quantity"), 1) or 1),
         float(data.get("amount") or 0), data.get("buyer", ""), data.get("phone", ""),
         status, code, data.get("note", ""), _now(), _now()),
    )
    conn().commit()
    row = dict(conn().execute("SELECT * FROM movie_ticket_orders WHERE id=?", (cur.lastrowid,)).fetchone())
    db.audit(conn(), "movie.create", f"order={order_no}", g.user["id"])
    conn().commit()
    return ok({"ticket": row})


@api.patch("/movie-tickets/<int:ticket_id>")
@auth.login_required
def update_movie_ticket(ticket_id):
    if not can_access("movie_ticket_orders", ticket_id):
        return fail("电影票订单不存在", 404)
    data = body()
    fields = ("movie_name", "cinema", "show_time", "seats", "quantity", "amount", "buyer", "phone", "note")
    sets, args = [], []
    for field in fields:
        if field in data:
            sets.append(f"{field}=?")
            args.append(data[field])
    if "status" in data:
        if data["status"] not in MOVIE_STATUSES:
            return fail("无效的票务状态")
        sets.append("status=?")
        args.append(data["status"])
    if not sets:
        return fail("没有需要更新的字段")
    sets.append("updated_at=?")
    args += [_now(), ticket_id]
    conn().execute(f"UPDATE movie_ticket_orders SET {', '.join(sets)} WHERE id=?", args)
    conn().commit()
    row = dict(conn().execute("SELECT * FROM movie_ticket_orders WHERE id=?", (ticket_id,)).fetchone())
    db.audit(conn(), "movie.update", f"order={row['order_no']}", g.user["id"])
    conn().commit()
    return ok({"ticket": row})


@api.delete("/movie-tickets/<int:ticket_id>")
@auth.login_required
def delete_movie_ticket(ticket_id):
    if not can_access("movie_ticket_orders", ticket_id):
        return fail("电影票订单不存在", 404)
    row = conn().execute("SELECT order_no FROM movie_ticket_orders WHERE id=?", (ticket_id,)).fetchone()
    conn().execute("DELETE FROM movie_ticket_orders WHERE id=?", (ticket_id,))
    conn().commit()
    db.audit(conn(), "movie.delete", f"order={row['order_no']}", g.user["id"])
    conn().commit()
    return ok()


@api.post("/movie-tickets/<int:ticket_id>/verify")
@auth.login_required
def verify_movie_ticket(ticket_id):
    if not can_access("movie_ticket_orders", ticket_id):
        return fail("电影票订单不存在", 404)
    row = conn().execute("SELECT * FROM movie_ticket_orders WHERE id=?", (ticket_id,)).fetchone()
    if row["status"] == "used":
        return ok({"ticket": dict(row), "already": True})
    if row["status"] != "paid":
        return fail("只有已支付订单可以核销", 400)
    now = _now()
    conn().execute(
        "UPDATE movie_ticket_orders SET status='used', used_at=?, verified_by=?, updated_at=? WHERE id=?",
        (now, g.user["username"], now, ticket_id),
    )
    conn().commit()
    db.audit(conn(), "movie.verify", f"order={row['order_no']}", g.user["id"])
    conn().commit()
    return ok({"ticket": dict(conn().execute(
        "SELECT * FROM movie_ticket_orders WHERE id=?", (ticket_id,)).fetchone()), "already": False})


@api.post("/movie-tickets/verify")
@auth.login_required
def verify_movie_ticket_code():
    data = body()
    code = (data.get("code") or "").strip().upper()
    if not code:
        return fail("请提供取票码")
    row = conn().execute(
        "SELECT * FROM movie_ticket_orders WHERE upper(code)=? AND owner_id=?",
        (code, owner_id()),
    ).fetchone()
    if not row:
        return fail("取票码不存在", 404)
    return verify_movie_ticket(row["id"])


@api.get("/movie-tickets.xlsx")
@auth.login_required
def export_movie_tickets():
    status = (request.args.get("status") or "").strip()
    if status not in MOVIE_STATUSES:
        status = ""
    q = (request.args.get("q") or "").strip()
    data = exports.movie_tickets_xlsx(conn(), None if is_admin() else owner_id(), status or None, q or None)
    return send_file(io.BytesIO(data), as_attachment=True, download_name=exports.filename("movie-tickets"),
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@api.get("/movie-tickets/<int:ticket_id>/qr")
@auth.login_required
def movie_ticket_qr(ticket_id):
    if not can_access("movie_ticket_orders", ticket_id):
        return fail("电影票订单不存在", 404)
    row = conn().execute("SELECT order_no, code FROM movie_ticket_orders WHERE id=?", (ticket_id,)).fetchone()
    import qrcode
    img = qrcode.make(row["code"] or row["order_no"])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = base64.b64encode(buf.getvalue()).decode()
    return ok({"code": row["code"], "data_url": "data:image/png;base64," + data})


# --------------------------------------------------------------------------- accounts

@api.get("/accounts")
@auth.login_required
def list_accounts():
    s, sa = scope("a")
    rows = conn().execute(
        "SELECT a.*, "
        "(SELECT COUNT(*) FROM goods g WHERE g.account_id=a.id) AS goods_count, "
        "(SELECT COUNT(*) FROM orders o WHERE o.account_id=a.id) AS order_count "
        f"FROM accounts a WHERE 1=1 {s} ORDER BY a.id DESC", sa
    ).fetchall()
    return jsonify({"accounts": db.rows_to_dicts(rows)})


@api.post("/accounts")
@auth.login_required
def create_account():
    data = body()
    name = (data.get("name") or "").strip()
    if not name:
        return fail("账号名称不能为空")
    cur = conn().execute(
        "INSERT INTO accounts(owner_id, name, cookie, status, enabled, proxy, note, ai_enabled, "
        "auto_comment, comment_template, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (owner_id(), name, data.get("cookie", ""), "offline", 1 if data.get("enabled", True) else 0,
         data.get("proxy", ""), data.get("note", ""), 1 if data.get("ai_enabled") else 0,
         1 if data.get("auto_comment") else 0, data.get("comment_template", ""), _now()),
    )
    conn().commit()
    db.audit(conn(), "account.create", f"account={cur.lastrowid}", g.user["id"])
    conn().commit()
    return ok({"id": cur.lastrowid})


@api.patch("/accounts/<int:account_id>")
@auth.login_required
def update_account(account_id):
    if not can_access("accounts", account_id):
        return fail("账号不存在", 404)
    data = body()
    fields, values = [], []
    for key in ("name", "cookie", "proxy", "note", "comment_template"):
        if key in data:
            fields.append(f"{key}=?")
            values.append(data[key])
    for key in ("enabled", "ai_enabled", "auto_comment"):
        if key in data:
            fields.append(f"{key}=?")
            values.append(1 if data[key] else 0)
    if not fields:
        return fail("没有可更新的字段")
    values.append(account_id)
    conn().execute(f"UPDATE accounts SET {', '.join(fields)} WHERE id=?", values)
    conn().commit()
    return ok()


@api.delete("/accounts/<int:account_id>")
@auth.login_required
def delete_account(account_id):
    if not can_access("accounts", account_id):
        return fail("账号不存在", 404)
    conn().execute("DELETE FROM accounts WHERE id=?", (account_id,))
    conn().commit()
    return ok()


@api.get("/accounts/export")
@auth.login_required
def export_accounts():
    s, sa = scope()
    rows = conn().execute(
        "SELECT name, cookie, proxy, note, ai_enabled, auto_comment, comment_template "
        f"FROM accounts WHERE 1=1 {s} ORDER BY id", sa
    ).fetchall()
    return jsonify({
        "version": 1,
        "exported_at": _now(),
        "accounts": db.rows_to_dicts(rows),
    })


@api.post("/accounts/export/encrypted")
@auth.login_required
def export_accounts_encrypted():
    data = body()
    password = data.get("password") or ""
    if len(password) < 6:
        return fail("加密密码至少 6 个字符")
    s, sa = scope()
    rows = conn().execute(
        "SELECT name, cookie, proxy, note, ai_enabled, auto_comment, comment_template "
        f"FROM accounts WHERE 1=1 {s} ORDER BY id", sa
    ).fetchall()
    blob = account_export.encrypt(db.rows_to_dicts(rows), password)
    db.audit(conn(), "account.export_encrypted", f"count={len(rows)}", g.user["id"])
    conn().commit()
    return ok({"blob": blob})


@api.post("/accounts/import")
@auth.login_required
def import_accounts():
    data = body()
    if data.get("format") == account_export.FORMAT or data.get("encrypted") or data.get("blob"):
        password = data.get("password") or ""
        if not password:
            return fail("加密文件需要密码")
        blob = data.get("blob") or data
        try:
            items = account_export.decrypt(blob, password)
        except account_export.DecryptError as exc:
            return fail(str(exc), 400)
        db.audit(conn(), "account.import_encrypted", f"count={len(items)}", g.user["id"])
    else:
        items = data.get("accounts")
    if not isinstance(items, list) or not items:
        return fail("accounts 必须是非空数组")
    imported = skipped = 0
    for item in items[:100]:
        if not isinstance(item, dict):
            skipped += 1
            continue
        name = (item.get("name") or "").strip()
        if not name:
            skipped += 1
            continue
        exists = conn().execute(
            "SELECT 1 FROM accounts WHERE owner_id=? AND name=?", (owner_id(), name)
        ).fetchone()
        if exists:
            skipped += 1
            continue
        conn().execute(
            "INSERT INTO accounts(owner_id, name, cookie, proxy, note, ai_enabled, "
            "auto_comment, comment_template, status, enabled, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (owner_id(), name, item.get("cookie", ""), item.get("proxy", ""), item.get("note", ""),
             1 if item.get("ai_enabled") else 0, 1 if item.get("auto_comment") else 0,
             item.get("comment_template", ""), "offline", 1, _now()),
        )
        imported += 1
    conn().commit()
    db.audit(conn(), "account.import", f"imported={imported} skipped={skipped}", g.user["id"])
    conn().commit()
    return ok({"imported": imported, "skipped": skipped})


@api.post("/accounts/batch")
@auth.login_required
def batch_accounts():
    data = body()
    action = data.get("action")
    if action not in ("enable", "disable", "connect", "disconnect"):
        return fail("不支持的操作")
    ids = data.get("ids")
    if not isinstance(ids, list) or not ids:
        return fail("请选择账号")
    results = []
    for raw in ids[:100]:
        try:
            account_id = int(raw)
        except (TypeError, ValueError):
            continue
        account = _account(account_id)
        if not account:
            results.append({"id": account_id, "ok": False, "error": "账号不存在"})
            continue
        try:
            if action in ("enable", "disable"):
                conn().execute("UPDATE accounts SET enabled=? WHERE id=?",
                               (1 if action == "enable" else 0, account_id))
                conn().commit()
                results.append({"id": account_id, "ok": True})
            elif action == "disconnect":
                conn().execute("UPDATE accounts SET status='offline' WHERE id=?", (account_id,))
                conn().commit()
                results.append({"id": account_id, "ok": True})
            else:
                _adapter_for(account).connect()
                conn().execute("UPDATE accounts SET status='online', last_seen_at=? WHERE id=?",
                               (_now(), account_id))
                conn().commit()
                results.append({"id": account_id, "ok": True})
        except PlatformUnavailable as exc:
            results.append({"id": account_id, "ok": False, "error": str(exc)})
        except Exception as exc:
            results.append({"id": account_id, "ok": False, "error": str(exc)})
    success = sum(1 for r in results if r.get("ok"))
    db.audit(conn(), "account.batch", f"action={action} success={success}/{len(results)}", g.user["id"])
    conn().commit()
    return ok({"results": results, "success": success, "failed": len(results) - success})


@api.post("/accounts/<int:account_id>/connect")
@auth.login_required
def connect_account(account_id):
    account = _account(account_id)
    if not account:
        return fail("账号不存在", 404)
    try:
        result = _adapter_for(account).connect()
    except PlatformUnavailable as exc:
        return fail(str(exc), 400)
    conn().execute("UPDATE accounts SET status='online', last_seen_at=? WHERE id=?", (_now(), account_id))
    db.audit(conn(), "account.connect", json.dumps(result, ensure_ascii=False), g.user["id"])
    conn().commit()
    return ok({"result": result})


@api.get("/accounts/<int:account_id>/summary")
@auth.login_required
def account_summary(account_id):
    account = _account(account_id)
    if not account:
        return fail("账号不存在", 404)
    counts = {}
    for key, sql in (
        ("goods", "SELECT COUNT(*) AS n FROM goods WHERE account_id=?"),
        ("orders", "SELECT COUNT(*) AS n FROM orders WHERE account_id=?"),
        ("conversations", "SELECT COUNT(*) AS n FROM conversations WHERE account_id=?"),
        ("reply_rules", "SELECT COUNT(*) AS n FROM autoreply_rules WHERE account_id=?"),
        ("sell_rules", "SELECT COUNT(*) AS n FROM autosell_rules WHERE goods_id IN "
                       "(SELECT id FROM goods WHERE account_id=?)"),
    ):
        counts[key] = conn().execute(sql, (account_id,)).fetchone()["n"]
    revenue = conn().execute(
        "SELECT COALESCE(SUM(amount),0) AS v FROM orders WHERE account_id=? AND status!='refunded'",
        (account_id,),
    ).fetchone()["v"]
    recent_orders = db.rows_to_dicts(conn().execute(
        "SELECT id, order_no, buyer, amount, status, created_at FROM orders "
        "WHERE account_id=? ORDER BY id DESC LIMIT 5", (account_id,)
    ).fetchall())
    recent_goods = db.rows_to_dicts(conn().execute(
        "SELECT id, title, price, stock, status FROM goods "
        "WHERE account_id=? ORDER BY id DESC LIMIT 5", (account_id,)
    ).fetchall())
    safe = {k: v for k, v in account.items() if k != "cookie"}
    safe["has_cookie"] = bool(account.get("cookie"))
    safe["is_demo"] = (account.get("cookie") or "").startswith("demo")
    return jsonify({"account": safe, "counts": counts, "revenue": revenue,
                    "recent_orders": recent_orders, "recent_goods": recent_goods})


@api.post("/accounts/<int:account_id>/proxy-test")
@auth.login_required
def proxy_test(account_id):
    account = _account(account_id)
    if not account:
        return fail("账号不存在", 404)
    proxy = (account.get("proxy") or "").strip()
    if proxy and not proxy.startswith(("http://", "https://")):
        return fail("代理地址需以 http:// 或 https:// 开头", 400)
    started = time.time()
    try:
        with httpx.Client(timeout=12, proxy=proxy or None) as client:
            resp = client.get("https://api.ipify.org", params={"format": "json"})
            resp.raise_for_status()
            ip = resp.json().get("ip", "")
    except Exception as exc:
        return fail(f"代理检测失败: {exc}", 400)
    elapsed = int((time.time() - started) * 1000)
    db.audit(conn(), "account.proxy_test", f"account={account_id} ok ip={ip}", g.user["id"])
    conn().commit()
    return ok({"ip": ip, "elapsed_ms": elapsed, "proxy_used": bool(proxy)})


@api.post("/accounts/<int:account_id>/ws-test")
@auth.login_required
def ws_test(account_id):
    account = _account(account_id)
    if not account:
        return fail("账号不存在", 404)
    if (account.get("cookie") or "").startswith("demo"):
        return fail("Mock 演示账号没有 LWP 令牌", 400)
    try:
        info = goofish.GoofishAdapter(account).fetch_ws_token()
    except mtop.MtopError as exc:
        return fail(str(exc), 400, mtop_code=exc.code, ret=exc.ret, stage="token")
    except PlatformUnavailable as exc:
        return fail(str(exc), 400, stage="token")
    result = lwp.exchange(info["token"], [lwp_frames.build_register_frame()], timeout=6.0)
    result["token_ok"] = True
    result["frame"] = "/reg"
    db.audit(conn(), "account.ws_test", f"account={account_id} connected={result.get('connected')}",
             g.user["id"])
    conn().commit()
    return ok({"result": result})


@api.post("/accounts/<int:account_id>/lwp/send")
@auth.login_required
def lwp_send(account_id):
    if os.environ.get("FAP_ENABLE_LWP_SEND") != "1":
        return fail("LWP 发送未启用（设置 FAP_ENABLE_LWP_SEND=1 仅供真实账号校准）", 403)
    account = _account(account_id)
    if not account:
        return fail("账号不存在", 404)
    if (account.get("cookie") or "").startswith("demo"):
        return fail("Mock 账号不支持 LWP 发送", 400)
    data = body()
    conversation_id = str(data.get("conversation_id") or "").strip()
    receiver_id = str(data.get("receiver_id") or "").strip()
    text = (data.get("text") or "").strip()
    if not conversation_id or not receiver_id or not text:
        return fail("conversation_id / receiver_id / text 都不能为空")
    try:
        result = goofish.GoofishAdapter(account).send_lwp_text(conversation_id, receiver_id, text)
    except mtop.MtopError as exc:
        return fail(str(exc), 400, mtop_code=exc.code, ret=exc.ret)
    except PlatformUnavailable as exc:
        return fail(str(exc), 400)
    db.audit(conn(), "account.lwp_send", f"account={account_id} connected={result.get('connected')}",
             g.user["id"])
    conn().commit()
    return ok({"result": result})


@api.post("/accounts/<int:account_id>/refresh-info")
@auth.login_required
def refresh_account_info(account_id):
    account = _account(account_id)
    if not account:
        return fail("账号不存在", 404)
    if (account.get("cookie") or "").startswith("demo"):
        return fail("Mock 演示账号没有可刷新的平台资料", 400)
    try:
        profile = goofish.GoofishAdapter(account).fetch_profile()
    except mtop.MtopError as exc:
        return fail(str(exc), 400, mtop_code=exc.code, ret=exc.ret)
    except PlatformUnavailable as exc:
        return fail(str(exc), 400)
    conn().execute(
        "UPDATE accounts SET nickname=?, avatar_url=?, platform_user_id=? WHERE id=?",
        (profile.get("nickname", ""), profile.get("avatar_url", ""),
         profile.get("platform_user_id", ""), account_id),
    )
    db.audit(conn(), "account.refresh_info", f"account={account_id}", g.user["id"])
    conn().commit()
    return ok({"profile": {k: v for k, v in profile.items() if k != "raw"}})


@api.post("/accounts/<int:account_id>/mtop/test")
@auth.login_required
def mtop_test(account_id):
    account = _account(account_id)
    if not account:
        return fail("账号不存在", 404)
    if (account.get("cookie") or "").startswith("demo"):
        return fail("Mock 演示账号没有真实 Cookie", 400)
    item_id = str(body().get("item_id") or "1")
    try:
        data = goofish.GoofishAdapter(account).fetch_item(item_id)
    except mtop.MtopError as exc:
        return fail(str(exc), 400, mtop_code=exc.code, ret=exc.ret)
    except PlatformUnavailable as exc:
        return fail(str(exc), 400)
    return ok({"item_id": item_id, "data": data})


@api.post("/accounts/<int:account_id>/mtop/search")
@auth.login_required
def mtop_search(account_id):
    account = _account(account_id)
    if not account:
        return fail("账号不存在", 404)
    if (account.get("cookie") or "").startswith("demo"):
        return fail("Mock 演示账号没有真实 Cookie", 400)
    keyword = (body().get("keyword") or "").strip()
    if not keyword:
        return fail("请输入搜索关键词")
    try:
        items = goofish.GoofishAdapter(account).search_items(keyword, None, None)
    except mtop.MtopError as exc:
        return fail(str(exc), 400, mtop_code=exc.code, ret=exc.ret)
    except PlatformUnavailable as exc:
        return fail(str(exc), 400)
    return ok({"items": [item.__dict__ for item in items], "count": len(items)})


@api.get("/accounts/<int:account_id>/items")
@auth.login_required
def account_items(account_id):
    account = _account(account_id)
    if not account:
        return fail("账号不存在", 404)
    if (account.get("cookie") or "").startswith("demo"):
        return fail("Mock 演示账号没有真实在售商品", 400)
    page = max(1, _int(request.args.get("page"), 1) or 1)
    try:
        items = goofish.GoofishAdapter(account).list_my_items(page)
    except mtop.MtopError as exc:
        return fail(str(exc), 400, mtop_code=exc.code, ret=exc.ret)
    except PlatformUnavailable as exc:
        return fail(str(exc), 400)
    return ok({"items": items, "count": len(items)})


@api.post("/accounts/<int:account_id>/polish")
@auth.login_required
def polish_items(account_id):
    account = _account(account_id)
    if not account:
        return fail("账号不存在", 404)
    if (account.get("cookie") or "").startswith("demo"):
        return fail("Mock 演示账号不支持擦亮", 400)
    raw = body().get("item_ids") or ""
    if isinstance(raw, str):
        ids = [x.strip() for x in raw.replace(",", "\n").splitlines() if x.strip()]
    elif isinstance(raw, list):
        ids = [str(x).strip() for x in raw if str(x).strip()]
    else:
        ids = []
    ids = list(dict.fromkeys(ids))[:50]
    if not ids:
        return fail("请输入要擦亮的商品 ID")
    adapter = goofish.GoofishAdapter(account)
    results, success = [], 0
    for item_id in ids:
        try:
            adapter.polish_item(item_id)
            results.append({"item_id": item_id, "ok": True})
            success += 1
        except mtop.MtopError as exc:
            results.append({"item_id": item_id, "ok": False, "error": str(exc), "code": exc.code})
        except Exception as exc:
            results.append({"item_id": item_id, "ok": False, "error": str(exc)})
    db.audit(conn(), "account.polish", f"account={account_id} success={success}/{len(ids)}", g.user["id"])
    conn().commit()
    return ok({"results": results, "success": success, "failed": len(ids) - success})


@api.post("/accounts/<int:account_id>/qr/start")
@auth.login_required
def start_account_qr(account_id):
    account = _account(account_id)
    if not account:
        return fail("账号不存在", 404)
    if (account.get("cookie") or "").startswith("demo"):
        return fail("Mock 演示账号无需扫码登录", 400)
    try:
        result = goofish.start_qr_login(account)
    except goofish.QRLoginError as exc:
        return fail(str(exc), 400)
    except Exception as exc:
        return fail(f"获取二维码失败: {exc}", 400)
    db.audit(conn(), "account.qr_start", f"account={account_id}", g.user["id"])
    conn().commit()
    return ok({"result": result})


@api.get("/accounts/<int:account_id>/qr/status/<session_id>")
@auth.login_required
def poll_account_qr(account_id, session_id):
    account = _account(account_id)
    if not account:
        return fail("账号不存在", 404)
    try:
        result = goofish.poll_qr_login(session_id)
    except goofish.QRLoginError as exc:
        return fail(str(exc), 400)
    if result.get("status") == "confirmed":
        cookie = result.pop("cookie", "")
        check = goofish.check_login(cookie, proxy=account.get("proxy") or None)
        if not check.get("ok"):
            return fail("扫码完成但登录态校验失败：" + check.get("message", ""), 400, qr_status="failed")
        conn().execute(
            "UPDATE accounts SET cookie=?, status='online', last_seen_at=? WHERE id=?",
            (cookie, _now(), account_id),
        )
        db.audit(conn(), "account.qr_success", f"account={account_id}", g.user["id"])
        conn().commit()
        result["cookie_saved"] = True
        result["message"] = check.get("message") or "登录成功"
    return ok({"result": result})


@api.post("/accounts/<int:account_id>/disconnect")
@auth.login_required
def disconnect_account(account_id):
    conn().execute("UPDATE accounts SET status='offline' WHERE id=?", (account_id,))
    conn().commit()
    return ok()


# --------------------------------------------------------------------------- goods

@api.get("/goods")
@auth.login_required
def list_goods():
    account_id = _int(request.args.get("account_id"))
    status = request.args.get("status")
    q = request.args.get("q", "").strip()
    sql = ("SELECT g.*, a.name AS account_name FROM goods g LEFT JOIN accounts a ON a.id=g.account_id WHERE 1=1")
    args = []
    if account_id:
        sql += " AND g.account_id=?"
        args.append(account_id)
    if status:
        sql += " AND g.status=?"
        args.append(status)
    if q:
        sql += " AND g.title LIKE ?"
        args.append(f"%{q}%")
    s, sa = scope("g")
    sql += s
    args += sa
    sql += " ORDER BY g.id DESC"
    rows = conn().execute(sql, args).fetchall()
    return jsonify({"goods": db.rows_to_dicts(rows)})


@api.post("/goods")
@auth.login_required
def create_goods():
    data = body()
    title = (data.get("title") or "").strip()
    if not title:
        return fail("商品标题不能为空")
    account_id = _int(data.get("account_id"))
    if account_id and not _account(account_id):
        return fail("账号不存在", 404)
    cur = conn().execute(
        "INSERT INTO goods(owner_id, account_id, title, price, stock, status, description, image_url, item_id, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (owner_id(), account_id, title, _float(data.get("price"), 0) or 0,
         _int(data.get("stock"), 0) or 0, data.get("status", "on_sale"),
         data.get("description", ""), data.get("image_url", ""), data.get("item_id", ""), _now()),
    )
    conn().commit()
    return ok({"id": cur.lastrowid})


@api.patch("/goods/<int:goods_id>")
@auth.login_required
def update_goods(goods_id):
    if not can_access("goods", goods_id):
        return fail("商品不存在", 404)
    data = body()
    fields, values = [], []
    for key in ("title", "description", "image_url", "status", "item_id"):
        if key in data:
            fields.append(f"{key}=?")
            values.append(data[key])
    if "price" in data:
        fields.append("price=?")
        values.append(_float(data["price"], 0) or 0)
    if "stock" in data:
        fields.append("stock=?")
        values.append(_int(data["stock"], 0) or 0)
    if "account_id" in data:
        fields.append("account_id=?")
        values.append(_int(data["account_id"]))
    if not fields:
        return fail("没有可更新的字段")
    values.append(goods_id)
    conn().execute(f"UPDATE goods SET {', '.join(fields)} WHERE id=?", values)
    conn().commit()
    return ok()


@api.delete("/goods/<int:goods_id>")
@auth.login_required
def delete_goods(goods_id):
    if not can_access("goods", goods_id):
        return fail("商品不存在", 404)
    conn().execute("DELETE FROM goods WHERE id=?", (goods_id,))
    conn().commit()
    return ok()


def _offline_one(goods: dict, account: dict | None) -> dict:
    c = conn()
    item_id = (goods.get("item_id") or "").strip()
    if not item_id or not account or (account.get("cookie") or "").startswith("demo"):
        c.execute("UPDATE goods SET status='off_shelf' WHERE id=?", (goods["id"],))
        c.commit()
        return {"goods_id": goods["id"], "ok": True, "local": True,
                "message": "已在本地下架" + ("（无平台 item_id）" if not item_id else "")}
    try:
        _adapter_for(account).offline_items([item_id])
    except mtop.MtopError as exc:
        return {"goods_id": goods["id"], "ok": False, "error": str(exc), "code": exc.code}
    except Exception as exc:
        return {"goods_id": goods["id"], "ok": False, "error": str(exc)}
    c.execute("UPDATE goods SET status='off_shelf' WHERE id=?", (goods["id"],))
    c.commit()
    return {"goods_id": goods["id"], "ok": True, "local": False, "message": "已下架"}


@api.post("/goods/<int:goods_id>/offline")
@auth.login_required
def offline_goods(goods_id):
    if not can_access("goods", goods_id):
        return fail("商品不存在", 404)
    goods = dict(conn().execute("SELECT * FROM goods WHERE id=?", (goods_id,)).fetchone())
    account = _account(goods.get("account_id")) if goods.get("account_id") else None
    result = _offline_one(goods, account)
    if not result.get("ok"):
        return fail(result.get("error", "下架失败"), 400, result=result)
    db.audit(conn(), "goods.offline", f"goods={goods_id} local={result.get('local')}", g.user["id"])
    conn().commit()
    return ok({"result": result})


@api.post("/goods/offline")
@auth.login_required
def offline_goods_batch():
    data = body()
    ids = data.get("ids")
    if not isinstance(ids, list) or not ids:
        return fail("请选择要下架的商品")
    results = []
    for raw_id in ids[:200]:
        try:
            goods_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if not can_access("goods", goods_id):
            continue
        goods = dict(conn().execute("SELECT * FROM goods WHERE id=?", (goods_id,)).fetchone())
        account = _account(goods.get("account_id")) if goods.get("account_id") else None
        results.append(_offline_one(goods, account))
    success = sum(1 for r in results if r.get("ok"))
    db.audit(conn(), "goods.offline_batch", f"success={success}/{len(results)}", g.user["id"])
    conn().commit()
    return ok({"results": results, "success": success, "failed": len(results) - success})


# --------------------------------------------------------------------------- orders

@api.get("/orders")
@auth.login_required
def list_orders():
    status = request.args.get("status")
    q = request.args.get("q", "").strip()
    limit = min(_int(request.args.get("limit"), 100) or 100, 500)
    sql = ("SELECT o.*, g.title AS goods_title, a.name AS account_name FROM orders o "
           "LEFT JOIN goods g ON g.id=o.goods_id LEFT JOIN accounts a ON a.id=o.account_id WHERE 1=1")
    args = []
    if status:
        sql += " AND o.status=?"
        args.append(status)
    if q:
        sql += " AND (o.order_no LIKE ? OR o.buyer LIKE ? OR g.title LIKE ? OR o.note LIKE ?)"
        args += [f"%{q}%"] * 4
    s, sa = scope("o")
    sql += s
    args += sa
    sql += " ORDER BY o.id DESC LIMIT ?"
    args.append(limit)
    rows = conn().execute(sql, args).fetchall()
    return jsonify({"orders": db.rows_to_dicts(rows)})


@api.get("/orders/<int:order_id>")
@auth.login_required
def order_detail(order_id):
    if not can_access("orders", order_id):
        return fail("订单不存在", 404)
    row = conn().execute(
        "SELECT o.*, g.title AS goods_title, a.name AS account_name FROM orders o "
        "LEFT JOIN goods g ON g.id=o.goods_id LEFT JOIN accounts a ON a.id=o.account_id WHERE o.id=?",
        (order_id,),
    ).fetchone()
    if not row:
        return fail("订单不存在", 404)
    logs = db.rows_to_dicts(conn().execute(
        "SELECT * FROM delivery_logs WHERE order_id=? ORDER BY id DESC", (order_id,)
    ).fetchall())
    return jsonify({"order": dict(row), "logs": logs})


@api.post("/orders/<int:order_id>/deliver")
@auth.login_required
def deliver_order(order_id):
    if not can_access("orders", order_id):
        return fail("订单不存在", 404)
    result = delivery.deliver_order(conn(), order_id, force=bool(body().get("force")))
    if not result.get("ok"):
        return fail(result.get("error", "发货失败"), 400, result=result)
    return ok({"result": result})


@api.post("/orders/<int:order_id>/rate")
@auth.login_required
def rate_order(order_id):
    if not can_access("orders", order_id):
        return fail("订单不存在", 404)
    order = dict(conn().execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())
    if order["status"] != "delivered":
        return fail("只有已发货订单才能好评", 400)
    if order.get("rated_at"):
        return fail("该订单已评价", 400)
    account = _account(order.get("account_id")) if order.get("account_id") else None
    if not account:
        return fail("订单缺少账号", 400)
    content = (body().get("content") or "宝贝很好，下次还会再来～").strip()[:500]
    try:
        _adapter_for(account).rate_order(order["order_no"], content)
    except PlatformUnavailable as exc:
        return fail(str(exc), 400)
    except Exception as exc:
        conn().execute("UPDATE orders SET rate_status='failed', rate_content=? WHERE id=?",
                       (f"{content}（失败：{exc}）", order_id))
        conn().commit()
        return fail(f"好评失败: {exc}", 400)
    conn().execute(
        "UPDATE orders SET rated_at=?, rate_status='success', rate_content=? WHERE id=?",
        (_now(), content, order_id),
    )
    db.audit(conn(), "order.rate", f"order={order['order_no']}", g.user["id"], "order", order["id"])
    conn().commit()
    return ok({"content": content})


@api.get("/orders/<int:order_id>/history")
@auth.login_required
def order_history(order_id):
    if not can_access("orders", order_id):
        return fail("订单不存在", 404)
    order = conn().execute("SELECT order_no FROM orders WHERE id=?", (order_id,)).fetchone()
    pattern = f"%order={order['order_no']}%"
    sql = "SELECT * FROM audit_logs WHERE ((entity_type='order' AND entity_id=?) OR detail LIKE ?)"
    args = [order_id, pattern]
    if not is_admin():
        sql += " AND user_id=?"
        args.append(owner_id())
    sql += " ORDER BY id DESC LIMIT 100"
    return jsonify({"logs": db.rows_to_dicts(conn().execute(sql, args).fetchall())})


@api.patch("/orders/<int:order_id>")
@auth.login_required
def update_order_api(order_id):
    if not can_access("orders", order_id):
        return fail("订单不存在", 404)
    data = body()
    if "note" not in data:
        return fail("只支持修改订单备注")
    conn().execute("UPDATE orders SET note=? WHERE id=?", (str(data.get("note") or ""), order_id))
    conn().commit()
    row = conn().execute("SELECT order_no FROM orders WHERE id=?", (order_id,)).fetchone()
    db.audit(conn(), "order.note", f"order={row['order_no']}", g.user["id"], "order", order_id)
    conn().commit()
    return ok({"note": str(data.get("note") or "")})


@api.get("/orders/stats")
@auth.login_required
def order_stats():
    s, sa = scope("o")
    args = list(sa)
    days = max(0, min(_int(request.args.get("days"), 0) or 0, 3650))
    if days:
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - days * 86400))
        s += " AND o.created_at>=?"
        args.append(cutoff)
    rows = conn().execute(
        f"SELECT o.status, COUNT(*) AS n, COALESCE(SUM(o.amount),0) AS amount "
        f"FROM orders o WHERE 1=1 {s} GROUP BY o.status", args
    ).fetchall()
    by_status = {r["status"]: {"count": r["n"], "amount": r["amount"]} for r in rows}
    total = sum(x["count"] for x in by_status.values())
    revenue = sum(x["amount"] for st, x in by_status.items() if st != "refunded")
    return jsonify({"total": total, "by_status": by_status, "revenue": revenue})


@api.post("/orders/<int:order_id>/ship")
@auth.login_required
def ship_order_api(order_id):
    if not can_access("orders", order_id):
        return fail("订单不存在", 404)
    order = dict(conn().execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())
    if order["status"] != "delivered":
        return fail("只有已发货订单才能同步平台物流", 400)
    if order.get("ship_status") == "success":
        return fail("该订单已同步过平台发货", 400)
    account = _account(order.get("account_id")) if order.get("account_id") else None
    if not account:
        return fail("订单缺少账号", 400)
    try:
        _adapter_for(account).ship_order(order["order_no"])
    except PlatformUnavailable as exc:
        return fail(str(exc), 400)
    except Exception as exc:
        conn().execute("UPDATE orders SET ship_status='failed' WHERE id=?", (order_id,))
        conn().commit()
        return fail(f"平台发货同步失败: {exc}", 400)
    conn().execute(
        "UPDATE orders SET ship_status='success', platform_shipped_at=? WHERE id=?",
        (_now(), order_id),
    )
    db.audit(conn(), "order.ship", f"order={order['order_no']}", g.user["id"], "order", order_id)
    conn().commit()
    return ok({"shipped_at": _now()})


@api.delete("/orders/<int:order_id>")
@auth.login_required
def delete_order(order_id):
    if not can_access("orders", order_id):
        return fail("订单不存在", 404)
    order = conn().execute("SELECT order_no FROM orders WHERE id=?", (order_id,)).fetchone()
    conn().execute("DELETE FROM delivery_logs WHERE order_id=?", (order_id,))
    conn().execute("DELETE FROM orders WHERE id=?", (order_id,))
    db.audit(conn(), "order.delete", f"order={order['order_no'] if order else order_id}", g.user["id"], "order", order_id)
    conn().commit()
    return ok()


@api.post("/orders/<int:order_id>/refund")
@auth.login_required
def refund_order(order_id):
    if not can_access("orders", order_id):
        return fail("订单不存在", 404)
    order = dict(conn().execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())
    data = body()
    status = data.get("status") or "requested"
    if status not in ("requested", "refunding", "success", "failed"):
        return fail("退款状态不合法")
    amount = _float(data.get("amount"), order.get("amount") or 0)
    reason = (data.get("reason") or "").strip()[:500]
    refunded_at = _now() if status == "success" else ""
    conn().execute(
        "UPDATE orders SET refund_status=?, refund_amount=?, refund_reason=?, refunded_at=? WHERE id=?",
        (status, amount, reason, refunded_at, order_id),
    )
    if status == "success":
        conn().execute("UPDATE orders SET status='refunded' WHERE id=?", (order_id,))
    db.audit(conn(), "order.refund", f"order={order['order_no']} status={status} amount={amount}", g.user["id"], "order", order_id)
    conn().commit()
    return ok({"refund_status": status, "amount": amount})


@api.get("/orders/<int:order_id>/logs")
@auth.login_required
def order_logs(order_id):
    if not can_access("orders", order_id):
        return fail("订单不存在", 404)
    rows = conn().execute("SELECT * FROM delivery_logs WHERE order_id=? ORDER BY id DESC", (order_id,)).fetchall()
    return jsonify({"logs": db.rows_to_dicts(rows)})


@api.post("/orders/sync")
@auth.login_required
def sync_order_api():
    data = body()
    account = _account(_int(data.get("account_id")))
    if not account:
        return fail("账号不存在", 404)
    order_no = str(data.get("order_id") or "").strip()
    if not order_no:
        return fail("请输入订单号")
    try:
        result = sync.sync_order(conn(), account, order_no, bool(data.get("auto_deliver")))
    except sync.SyncError as exc:
        return fail(str(exc), 400)
    db.audit(conn(), "order.sync", f"account={account['id']} order={order_no}", g.user["id"], "order", (result.get("order") or {}).get("id", 0))
    conn().commit()
    return ok({"result": {k: v for k, v in result.items() if k != "raw"}, "raw": result.get("raw")})


@api.post("/orders/sync-list")
@auth.login_required
def sync_order_list_api():
    data = body()
    account = _account(_int(data.get("account_id")))
    if not account:
        return fail("账号不存在", 404)
    limit = max(1, min(_int(data.get("limit"), 50) or 50, 200))
    pages = max(1, min(_int(data.get("pages"), 1) or 1, 10))
    try:
        result = sync.sync_orders(conn(), account, bool(data.get("auto_deliver")), limit, pages)
    except sync.SyncError as exc:
        return fail(str(exc), 400)
    db.audit(conn(), "order.sync_list",
             f"account={account['id']} fetched={result['fetched']} created={result['created']}", g.user["id"])
    conn().commit()
    return ok({"result": result})


# --------------------------------------------------------------------------- scheduled jobs

def _validate_job_target(job_type: str, config: dict) -> str | None:
    if job_type == "order_sync":
        if not _account(config["account_id"]):
            return "账号不存在"
    elif job_type == "monitor":
        if not can_access("monitor_tasks", config["task_id"]):
            return "监控任务不存在"
    elif job_type == "relist":
        if not can_access("auto_relist_rules", config["rule_id"]):
            return "补货规则不存在"
    elif job_type == "polish":
        if not _account(config["account_id"]):
            return "账号不存在"
    return None


@api.get("/jobs")
@auth.login_required
def list_jobs():
    s, sa = scope("t")
    rows = conn().execute(
        "SELECT t.*, (SELECT COUNT(*) FROM job_runs r WHERE r.task_id=t.id) AS run_count "
        f"FROM job_tasks t WHERE 1=1 {s} ORDER BY t.id DESC", sa
    ).fetchall()
    return jsonify({"jobs": db.rows_to_dicts(rows), "types": jobs.JOB_TYPES})


@api.post("/jobs")
@auth.login_required
def create_job():
    data = body()
    job_type = data.get("type")
    if job_type not in jobs.JOB_TYPES:
        return fail("不支持的任务类型")
    if job_type in ("backup", "prune") and not is_admin():
        return fail("只有管理员可以创建该任务", 403)
    try:
        config = jobs.normalize_config(job_type, data.get("config"))
    except jobs.JobError as exc:
        return fail(str(exc))
    error = _validate_job_target(job_type, config)
    if error:
        return fail(error, 404)
    interval = max(60, min(_int(data.get("interval_seconds"), 600) or 600, jobs.MAX_INTERVAL))
    enabled = 1 if data.get("enabled", True) else 0
    name = (data.get("name") or jobs.JOB_TYPES[job_type]).strip()
    cur = conn().execute(
        "INSERT INTO job_tasks(owner_id, name, type, config_json, interval_seconds, enabled, next_run_at, created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (owner_id(), name, job_type, json.dumps(config, ensure_ascii=False), interval, enabled,
         jobs.next_at(interval) if enabled else None, _now()),
    )
    db.audit(conn(), "job.create", f"job={cur.lastrowid} type={job_type}", g.user["id"])
    conn().commit()
    return ok({"id": cur.lastrowid})


@api.patch("/jobs/<int:job_id>")
@auth.login_required
def update_job(job_id):
    if not can_access("job_tasks", job_id):
        return fail("任务不存在", 404)
    row = conn().execute("SELECT * FROM job_tasks WHERE id=?", (job_id,)).fetchone()
    data = body()
    fields, values = [], []
    if "name" in data:
        fields.append("name=?")
        values.append((data["name"] or "").strip() or row["name"])
    if "type" in data and data["type"] != row["type"]:
        return fail("任务类型不能修改，请新建任务")
    if "config" in data or "interval_seconds" in data or "enabled" in data:
        job_type = row["type"]
        config = jobs.normalize_config(job_type, data.get("config", json.loads(row["config_json"] or "{}")))
        error = _validate_job_target(job_type, config)
        if error:
            return fail(error, 404)
        fields.append("config_json=?")
        values.append(json.dumps(config, ensure_ascii=False))
        interval = row["interval_seconds"]
        if "interval_seconds" in data:
            interval = max(60, min(_int(data.get("interval_seconds"), 600) or 600, jobs.MAX_INTERVAL))
            fields.append("interval_seconds=?")
            values.append(interval)
        enabled = row["enabled"]
        if "enabled" in data:
            enabled = 1 if data["enabled"] else 0
            fields.append("enabled=?")
            values.append(enabled)
        fields.append("next_run_at=?")
        values.append(jobs.next_at(interval) if enabled else None)
    if not fields:
        return fail("没有可更新的字段")
    values.append(job_id)
    conn().execute(f"UPDATE job_tasks SET {', '.join(fields)} WHERE id=?", values)
    conn().commit()
    return ok()


@api.delete("/jobs/<int:job_id>")
@auth.login_required
def delete_job(job_id):
    if not can_access("job_tasks", job_id):
        return fail("任务不存在", 404)
    conn().execute("DELETE FROM job_tasks WHERE id=?", (job_id,))
    conn().execute("DELETE FROM job_runs WHERE task_id=?", (job_id,))
    conn().commit()
    return ok()


@api.post("/jobs/<int:job_id>/run")
@auth.login_required
def run_job(job_id):
    if not can_access("job_tasks", job_id):
        return fail("任务不存在", 404)
    try:
        result = jobs.run_task(conn(), job_id)
    except jobs.JobError as exc:
        return fail(str(exc), 400)
    if not result.get("ok"):
        return fail(result.get("message", "任务失败"), 400, result=result)
    return ok({"result": result})


@api.get("/jobs/<int:job_id>/runs")
@auth.login_required
def job_runs(job_id):
    if not can_access("job_tasks", job_id):
        return fail("任务不存在", 404)
    rows = conn().execute(
        "SELECT * FROM job_runs WHERE task_id=? ORDER BY id DESC LIMIT 50", (job_id,)
    ).fetchall()
    return jsonify({"runs": db.rows_to_dicts(rows)})


# --------------------------------------------------------------------------- conversations

@api.get("/conversations")
@auth.login_required
def list_conversations():
    s, sa = scope("c")
    q = (request.args.get("q") or "").strip()
    unread = request.args.get("unread") in ("1", "true")
    sql = ("SELECT c.*, a.name AS account_name, g.title AS goods_title, "
           "(SELECT GROUP_CONCAT(bt.tag, ',') FROM buyer_tags bt "
           " WHERE bt.owner_id=c.owner_id AND bt.buyer=c.buyer) AS tags "
           "FROM conversations c "
           "LEFT JOIN accounts a ON a.id=c.account_id LEFT JOIN goods g ON g.id=c.goods_id WHERE 1=1")
    args = list(sa)
    sql += s
    tag = (request.args.get("tag") or "").strip()
    if tag:
        sql += (" AND EXISTS(SELECT 1 FROM buyer_tags bt WHERE bt.owner_id=c.owner_id "
                "AND bt.buyer=c.buyer AND bt.tag=?)")
        args.append(tag)
    if q:
        sql += (" AND (c.buyer LIKE ? OR c.last_message LIKE ? OR EXISTS("
                "SELECT 1 FROM messages m WHERE m.conversation_id=c.id AND m.content LIKE ?))")
        args += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if unread:
        sql += " AND c.unread>0"
    sql += " ORDER BY c.updated_at DESC"
    rows = conn().execute(sql, args).fetchall()
    return jsonify({"conversations": db.rows_to_dicts(rows)})


@api.post("/conversations/read-all")
@auth.login_required
def read_all_conversations():
    cur = conn().execute("UPDATE conversations SET unread=0 WHERE unread>0 AND owner_id=?", (owner_id(),))
    conn().commit()
    return ok({"updated": cur.rowcount or 0})


@api.get("/conversations/<int:conversation_id>/messages")
@auth.login_required
def conversation_messages(conversation_id):
    conv = _conversation(conversation_id)
    if not conv:
        return fail("会话不存在", 404)
    limit = max(1, min(_int(request.args.get("limit"), 200) or 200, 500))
    before = _int(request.args.get("before_id"))
    sql = "SELECT * FROM messages WHERE conversation_id=?"
    args: list = [conversation_id]
    if before:
        sql += " AND id<?"
        args.append(before)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit + 1)
    rows = conn().execute(sql, args).fetchall()
    has_more = len(rows) > limit
    rows = list(reversed(rows[:limit]))
    conn().execute("UPDATE conversations SET unread=0 WHERE id=?", (conversation_id,))
    conn().commit()
    return jsonify({"conversation": conv, "messages": db.rows_to_dicts(rows),
                    "has_more": has_more, "before_id": rows[0]["id"] if rows else 0})


@api.post("/conversations/<int:conversation_id>/messages")
@auth.login_required
def send_message(conversation_id):
    conv = _conversation(conversation_id)
    if not conv:
        return fail("会话不存在", 404)
    content = (body().get("content") or "").strip()
    if not content:
        return fail("消息内容不能为空")
    cur = conn().execute(
        "INSERT INTO messages(conversation_id, direction, content, delivery_status, created_at) "
        "VALUES(?,?,?,?,?)",
        (conversation_id, "out", content, "pending", _now()),
    )
    message_id = int(cur.lastrowid)
    conn().execute(
        "UPDATE conversations SET last_message=?, updated_at=? WHERE id=?",
        (content, _now(), conversation_id),
    )
    conn().commit()
    account = _account(conv["account_id"])
    sent = True
    error = ""
    try:
        _adapter_for(account).send_message(conv["buyer"], content)
    except PlatformUnavailable as exc:
        sent = False
        error = str(exc)
    conn().execute("UPDATE messages SET delivery_status=? WHERE id=?", ("sent" if sent else "pending", message_id))
    conn().commit()
    return ok({"sent": sent, "error": error, "message_id": message_id})


@api.post("/conversations/<int:conversation_id>/ai")
@auth.login_required
def toggle_ai(conversation_id):
    if not _conversation(conversation_id):
        return fail("会话不存在", 404)
    enabled = bool(body().get("enabled", True))
    conn().execute("UPDATE conversations SET ai_enabled=? WHERE id=?", (1 if enabled else 0, conversation_id))
    conn().commit()
    return ok({"enabled": enabled})


@api.post("/conversations/<int:conversation_id>/autoreply")
@auth.login_required
def toggle_autoreply(conversation_id):
    conv = _conversation(conversation_id)
    if not conv:
        return fail("会话不存在", 404)
    paused = bool(body().get("paused", True))
    minutes = max(0, min(_int(body().get("minutes"), 0) or 0, 7 * 24 * 60))
    until = ""
    if paused and minutes:
        until = (datetime.now(timezone.utc).astimezone() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    conn().execute(
        "UPDATE conversations SET autoreply_paused=?, autoreply_paused_until=? WHERE id=?",
        (1 if paused else 0, until, conversation_id),
    )
    conn().commit()
    return ok({"paused": paused, "until": until})


# --------------------------------------------------------------------------- auto reply

@api.get("/autoreply/rules")
@auth.login_required
def list_reply_rules():
    s, sa = scope("r")
    rows = conn().execute(
        "SELECT r.*, a.name AS account_name, g.title AS goods_title FROM autoreply_rules r "
        "LEFT JOIN accounts a ON a.id=r.account_id LEFT JOIN goods g ON g.id=r.goods_id "
        f"WHERE 1=1 {s} ORDER BY r.priority DESC, r.id DESC", sa
    ).fetchall()
    return jsonify({"rules": db.rows_to_dicts(rows)})


@api.post("/autoreply/rules")
@auth.login_required
def create_reply_rule():
    data = body()
    if not (data.get("name") or "").strip():
        return fail("规则名称不能为空")
    if not (data.get("pattern") or "").strip():
        return fail("匹配内容不能为空")
    account_id = _int(data.get("account_id"))
    goods_id = _int(data.get("goods_id"))
    if account_id and not _account(account_id):
        return fail("账号不存在", 404)
    if goods_id and not _goods(goods_id):
        return fail("商品不存在", 404)
    cur = conn().execute(
        "INSERT INTO autoreply_rules(owner_id, name, account_id, scope, goods_id, match_type, pattern, reply_type, "
        "content, image_url, priority, enabled, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (owner_id(), data["name"].strip(), account_id, data.get("scope", "all"),
         goods_id, data.get("match_type", "keyword"), data["pattern"],
         data.get("reply_type", "text"), data.get("content", ""), data.get("image_url", ""),
         _int(data.get("priority"), 0) or 0, 1 if data.get("enabled", True) else 0, _now()),
    )
    conn().commit()
    return ok({"id": cur.lastrowid})


@api.patch("/autoreply/rules/<int:rule_id>")
@auth.login_required
def update_reply_rule(rule_id):
    if not can_access("autoreply_rules", rule_id):
        return fail("规则不存在", 404)
    data = body()
    allowed = ("name", "scope", "match_type", "pattern", "reply_type", "content", "image_url")
    fields, values = [], []
    for key in allowed:
        if key in data:
            fields.append(f"{key}=?")
            values.append(data[key])
    for key in ("account_id", "goods_id", "priority"):
        if key in data:
            fields.append(f"{key}=?")
            values.append(_int(data[key]))
    if "enabled" in data:
        fields.append("enabled=?")
        values.append(1 if data["enabled"] else 0)
    if not fields:
        return fail("没有可更新的字段")
    values.append(rule_id)
    conn().execute(f"UPDATE autoreply_rules SET {', '.join(fields)} WHERE id=?", values)
    conn().commit()
    return ok()


@api.delete("/autoreply/rules/<int:rule_id>")
@auth.login_required
def delete_reply_rule(rule_id):
    if not can_access("autoreply_rules", rule_id):
        return fail("规则不存在", 404)
    conn().execute("DELETE FROM autoreply_rules WHERE id=?", (rule_id,))
    conn().commit()
    return ok()


@api.post("/autoreply/test")
@auth.login_required
def test_reply_rule():
    data = body()
    text = (data.get("text") or "").strip()
    if not text:
        return fail("请输入测试消息")
    account = _account(_int(data.get("account_id"))) if data.get("account_id") else None
    if not account:
        row = conn().execute(
            "SELECT * FROM accounts WHERE 1=1 " + scope()[0] + " ORDER BY id LIMIT 1", scope()[1]
        ).fetchone()
        account = dict(row) if row else None
    goods = _goods(_int(data.get("goods_id"))) if data.get("goods_id") else None
    rule = replies.find_matching_rule(conn(), text, account["id"] if account else None,
                                      goods["id"] if goods else None)
    if not rule:
        cfg = ai.config(conn())
        if cfg["enabled"]:
            try:
                content = ai.reply(conn(), text, goods=goods)
                return ok({"matched": False, "ai": True, "reply": {"type": "text", "content": content}})
            except ai.AIError as exc:
                return ok({"matched": False, "ai": False, "error": str(exc)})
        return ok({"matched": False, "ai": False})
    context = {"buyer": "测试买家", "goods_title": (goods or {}).get("title", ""),
               "account_name": (account or {}).get("name", "")}
    return ok({"matched": True, "rule": dict(rule), "reply": replies.build_reply(rule, context)})


# --------------------------------------------------------------------------- auto delivery

@api.get("/autosell/rules")
@auth.login_required
def list_sell_rules():
    s, sa = scope("r")
    rows = conn().execute(
        "SELECT r.*, g.title AS goods_title, "
        "(SELECT COUNT(*) FROM autosell_stock s WHERE s.rule_id=r.id AND s.status='available') AS stock_available "
        f"FROM autosell_rules r LEFT JOIN goods g ON g.id=r.goods_id WHERE 1=1 {s} ORDER BY r.id DESC", sa
    ).fetchall()
    return jsonify({"rules": db.rows_to_dicts(rows)})


@api.post("/autosell/rules")
@auth.login_required
def create_sell_rule():
    data = body()
    if not (data.get("name") or "").strip():
        return fail("规则名称不能为空")
    goods_id = _int(data.get("goods_id"))
    workflow_id = _int(data.get("workflow_id"))
    if goods_id and not _goods(goods_id):
        return fail("商品不存在", 404)
    if workflow_id and not can_access("workflows", workflow_id):
        return fail("流程不存在", 404)
    cur = conn().execute(
        "INSERT INTO autosell_rules(owner_id, name, goods_id, delivery_type, content, api_url, api_method, api_headers, "
        "api_body, api_response_path, multi_quantity, workflow_id, enabled, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (owner_id(), data["name"].strip(), goods_id, data.get("delivery_type", "fixed"),
         data.get("content", ""), data.get("api_url", ""), data.get("api_method", "POST"),
         json.dumps(data.get("api_headers") or {}, ensure_ascii=False),
         data.get("api_body", "") if isinstance(data.get("api_body"), str) else json.dumps(data.get("api_body"), ensure_ascii=False),
         data.get("api_response_path", ""), 1 if data.get("multi_quantity") else 0,
         workflow_id, 1 if data.get("enabled", True) else 0, _now()),
    )
    conn().commit()
    return ok({"id": cur.lastrowid})


@api.patch("/autosell/rules/<int:rule_id>")
@auth.login_required
def update_sell_rule(rule_id):
    if not _sell_rule(rule_id):
        return fail("规则不存在", 404)
    data = body()
    allowed = ("name", "delivery_type", "content", "api_url", "api_method", "api_response_path")
    fields, values = [], []
    for key in allowed:
        if key in data:
            fields.append(f"{key}=?")
            values.append(data[key])
    if "goods_id" in data:
        fields.append("goods_id=?")
        values.append(_int(data["goods_id"]))
    if "workflow_id" in data:
        fields.append("workflow_id=?")
        values.append(_int(data["workflow_id"]))
    if "multi_quantity" in data:
        fields.append("multi_quantity=?")
        values.append(1 if data["multi_quantity"] else 0)
    if "enabled" in data:
        fields.append("enabled=?")
        values.append(1 if data["enabled"] else 0)
    if "api_headers" in data:
        fields.append("api_headers=?")
        values.append(json.dumps(data["api_headers"], ensure_ascii=False))
    if "api_body" in data:
        fields.append("api_body=?")
        values.append(data["api_body"] if isinstance(data["api_body"], str) else json.dumps(data["api_body"], ensure_ascii=False))
    if not fields:
        return fail("没有可更新的字段")
    values.append(rule_id)
    conn().execute(f"UPDATE autosell_rules SET {', '.join(fields)} WHERE id=?", values)
    conn().commit()
    return ok()


@api.delete("/autosell/rules/<int:rule_id>")
@auth.login_required
def delete_sell_rule(rule_id):
    if not _sell_rule(rule_id):
        return fail("规则不存在", 404)
    conn().execute("DELETE FROM autosell_rules WHERE id=?", (rule_id,))
    conn().commit()
    return ok()


@api.get("/autosell/rules/<int:rule_id>/stock")
@auth.login_required
def list_stock(rule_id):
    if not _sell_rule(rule_id):
        return fail("规则不存在", 404)
    rows = conn().execute(
        "SELECT * FROM autosell_stock WHERE rule_id=? ORDER BY status='used', id LIMIT 500", (rule_id,)
    ).fetchall()
    counts = conn().execute(
        "SELECT status, COUNT(*) AS n FROM autosell_stock WHERE rule_id=? GROUP BY status", (rule_id,)
    ).fetchall()
    return jsonify({"stock": db.rows_to_dicts(rows), "counts": {r["status"]: r["n"] for r in counts}})


@api.post("/autosell/rules/<int:rule_id>/stock")
@auth.login_required
def add_stock(rule_id):
    if not _sell_rule(rule_id):
        return fail("规则不存在", 404)
    data = body()
    items = data.get("items")
    if isinstance(items, str):
        items = [line.strip() for line in items.splitlines() if line.strip()]
    if not isinstance(items, list) or not items:
        return fail("请提供卡密内容")
    count = 0
    for item in items:
        item = str(item).strip()
        if not item:
            continue
        conn().execute(
            "INSERT INTO autosell_stock(rule_id, content, status, created_at) VALUES(?,?,?,?)",
            (rule_id, item, "available", _now()),
        )
        count += 1
    conn().commit()
    return ok({"added": count})


@api.delete("/autosell/stock/<int:stock_id>")
@auth.login_required
def delete_stock(stock_id):
    row = conn().execute("SELECT rule_id FROM autosell_stock WHERE id=?", (stock_id,)).fetchone()
    if not row or not _sell_rule(row["rule_id"]):
        return fail("库存不存在", 404)
    conn().execute("DELETE FROM autosell_stock WHERE id=?", (stock_id,))
    conn().commit()
    return ok()


@api.get("/autosell/logs")
@auth.login_required
def sell_logs():
    s, sa = scope("o")
    rows = conn().execute(
        "SELECT l.*, o.order_no, o.buyer FROM delivery_logs l LEFT JOIN orders o ON o.id=l.order_id "
        f"WHERE 1=1 {s} ORDER BY l.id DESC LIMIT 200", sa
    ).fetchall()
    return jsonify({"logs": db.rows_to_dicts(rows)})


@api.post("/autosell/rules/<int:rule_id>/preview")
@auth.login_required
def preview_sell_rule(rule_id):
    rule = _sell_rule(rule_id)
    if not rule:
        return fail("规则不存在", 404)
    data = body()
    qty = max(1, _int(data.get("quantity"), 1) or 1)
    ctx = {"order_no": "PREVIEW0001", "buyer": data.get("buyer", "测试买家"), "quantity": qty,
           "amount": 0, "goods_title": "", "rule_name": rule["name"]}
    if rule["delivery_type"] == "fixed":
        return ok({"preview": render_template(rule["content"], ctx)})
    if rule["delivery_type"] == "stock":
        rows = conn().execute(
            "SELECT content FROM autosell_stock WHERE rule_id=? AND status='available' ORDER BY id LIMIT ?",
            (rule_id, qty if rule["multi_quantity"] else 1),
        ).fetchall()
        return ok({"preview": "\n".join(r["content"] for r in rows),
                   "available": len(rows), "needed": qty if rule["multi_quantity"] else 1})
    if rule["delivery_type"] == "workflow":
        return ok({"preview": "流程发货需在运行订单时执行", "workflow_id": rule["workflow_id"]})
    return ok({"preview": "API 发货需在运行订单时执行"})


# --------------------------------------------------------------------------- workflows

@api.get("/workflows")
@auth.login_required
def list_workflows():
    s, sa = scope()
    rows = conn().execute(f"SELECT * FROM workflows WHERE 1=1 {s} ORDER BY id DESC", sa).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["nodes"] = json.loads(item.pop("nodes_json") or "[]")
        item["edges"] = json.loads(item.pop("edges_json") or "[]")
        out.append(item)
    return jsonify({"workflows": out})


@api.post("/workflows")
@auth.login_required
def create_workflow():
    data = body()
    nodes = data.get("nodes") or []
    edges = data.get("edges") or []
    errors = wf_engine.validate(nodes, edges)
    if errors:
        return fail("; ".join(errors))
    cur = conn().execute(
        "INSERT INTO workflows(owner_id, name, nodes_json, edges_json, enabled, created_at) VALUES(?,?,?,?,?,?)",
        (owner_id(), (data.get("name") or "未命名流程").strip(), json.dumps(nodes, ensure_ascii=False),
         json.dumps(edges, ensure_ascii=False), 1 if data.get("enabled", True) else 0, _now()),
    )
    conn().commit()
    return ok({"id": cur.lastrowid})


@api.patch("/workflows/<int:workflow_id>")
@auth.login_required
def update_workflow(workflow_id):
    if not can_access("workflows", workflow_id):
        return fail("流程不存在", 404)
    data = body()
    nodes = data.get("nodes")
    edges = data.get("edges")
    if nodes is not None or edges is not None:
        current = conn().execute("SELECT * FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        if not current:
            return fail("流程不存在", 404)
        nodes = nodes if nodes is not None else json.loads(current["nodes_json"] or "[]")
        edges = edges if edges is not None else json.loads(current["edges_json"] or "[]")
        errors = wf_engine.validate(nodes, edges)
        if errors:
            return fail("; ".join(errors))
    fields, values = [], []
    if nodes is not None:
        fields.append("nodes_json=?")
        values.append(json.dumps(nodes, ensure_ascii=False))
    if edges is not None:
        fields.append("edges_json=?")
        values.append(json.dumps(edges, ensure_ascii=False))
    if "name" in data:
        fields.append("name=?")
        values.append(data["name"])
    if "enabled" in data:
        fields.append("enabled=?")
        values.append(1 if data["enabled"] else 0)
    if not fields:
        return fail("没有可更新的字段")
    values.append(workflow_id)
    conn().execute(f"UPDATE workflows SET {', '.join(fields)} WHERE id=?", values)
    conn().commit()
    return ok()


@api.delete("/workflows/<int:workflow_id>")
@auth.login_required
def delete_workflow(workflow_id):
    if not can_access("workflows", workflow_id):
        return fail("流程不存在", 404)
    conn().execute("DELETE FROM workflows WHERE id=?", (workflow_id,))
    conn().commit()
    return ok()


@api.post("/workflows/<int:workflow_id>/run")
@auth.login_required
def run_workflow(workflow_id):
    row = conn().execute("SELECT * FROM workflows WHERE id=?", (workflow_id,)).fetchone()
    if not row or (not is_admin() and row["owner_id"] != owner_id()):
        return fail("流程不存在", 404)
    context = body().get("context") or {}
    if not isinstance(context, dict):
        return fail("context 必须是对象")
    try:
        result = wf_engine.run_workflow(conn(), dict(row), context)
    except WorkflowError as exc:
        return fail(str(exc))
    return ok({"result": result})


@api.get("/workflows/<int:workflow_id>/runs")
@auth.login_required
def workflow_runs(workflow_id):
    if not can_access("workflows", workflow_id):
        return fail("流程不存在", 404)
    rows = conn().execute(
        "SELECT * FROM workflow_runs WHERE workflow_id=? ORDER BY id DESC LIMIT 50", (workflow_id,)
    ).fetchall()
    return jsonify({"runs": db.rows_to_dicts(rows)})


@api.get("/workflow-runs/<int:run_id>")
@auth.login_required
def workflow_run_detail(run_id):
    run = conn().execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,)).fetchone()
    if not run:
        return fail("运行记录不存在", 404)
    if not can_access("workflows", run["workflow_id"]):
        return fail("运行记录不存在", 404)
    steps = conn().execute("SELECT * FROM workflow_steps WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
    return jsonify({"run": dict(run), "steps": db.rows_to_dicts(steps)})


# --------------------------------------------------------------------------- monitor

@api.get("/monitor/tasks")
@auth.login_required
def list_monitor_tasks():
    s, sa = scope("t")
    rows = conn().execute(
        "SELECT t.*, a.name AS account_name, "
        "(SELECT COUNT(*) FROM monitor_items i WHERE i.task_id=t.id) AS item_count "
        f"FROM monitor_tasks t LEFT JOIN accounts a ON a.id=t.account_id WHERE 1=1 {s} ORDER BY t.id DESC", sa
    ).fetchall()
    return jsonify({"tasks": db.rows_to_dicts(rows)})


@api.post("/monitor/tasks")
@auth.login_required
def create_monitor_task():
    data = body()
    if not (data.get("keyword") or "").strip():
        return fail("监控关键词不能为空")
    account_id = _int(data.get("account_id"))
    if account_id and not _account(account_id):
        return fail("账号不存在", 404)
    cur = conn().execute(
        "INSERT INTO monitor_tasks(owner_id, name, keyword, min_price, max_price, account_id, interval_seconds, "
        "action, enabled, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (owner_id(), (data.get("name") or data["keyword"]).strip(), data["keyword"].strip(),
         _float(data.get("min_price")), _float(data.get("max_price")), account_id,
         max(10, _int(data.get("interval_seconds"), 60) or 60), data.get("action", "notify"),
         1 if data.get("enabled", True) else 0, _now()),
    )
    conn().commit()
    return ok({"id": cur.lastrowid})


@api.patch("/monitor/tasks/<int:task_id>")
@auth.login_required
def update_monitor_task(task_id):
    if not can_access("monitor_tasks", task_id):
        return fail("监控任务不存在", 404)
    data = body()
    fields, values = [], []
    for key in ("name", "keyword", "action"):
        if key in data:
            fields.append(f"{key}=?")
            values.append(data[key])
    for key in ("min_price", "max_price"):
        if key in data:
            fields.append(f"{key}=?")
            values.append(_float(data[key]))
    for key in ("account_id", "interval_seconds"):
        if key in data:
            fields.append(f"{key}=?")
            values.append(_int(data[key]))
    if "enabled" in data:
        fields.append("enabled=?")
        values.append(1 if data["enabled"] else 0)
    if not fields:
        return fail("没有可更新的字段")
    values.append(task_id)
    conn().execute(f"UPDATE monitor_tasks SET {', '.join(fields)} WHERE id=?", values)
    conn().commit()
    return ok()


@api.delete("/monitor/tasks/<int:task_id>")
@auth.login_required
def delete_monitor_task(task_id):
    if not can_access("monitor_tasks", task_id):
        return fail("监控任务不存在", 404)
    conn().execute("DELETE FROM monitor_tasks WHERE id=?", (task_id,))
    conn().commit()
    return ok()


@api.post("/monitor/tasks/<int:task_id>/run")
@auth.login_required
def run_monitor_task(task_id):
    if not can_access("monitor_tasks", task_id):
        return fail("监控任务不存在", 404)
    from .engines.monitor import run_task

    result = run_task(conn(), task_id)
    if not result.get("ok"):
        return fail(result.get("error", "监控失败"), 400, result=result)
    return ok({"result": result})


@api.get("/monitor/items")
@auth.login_required
def list_monitor_items():
    task_id = _int(request.args.get("task_id"))
    sql = ("SELECT i.*, t.keyword FROM monitor_items i JOIN monitor_tasks t ON t.id=i.task_id WHERE 1=1")
    args = []
    if task_id:
        sql += " AND i.task_id=?"
        args.append(task_id)
    s, sa = scope("t")
    sql += s
    args += sa
    sql += " ORDER BY i.id DESC LIMIT 300"
    rows = conn().execute(sql, args).fetchall()
    return jsonify({"items": db.rows_to_dicts(rows)})


@api.post("/monitor/mock-items")
@auth.login_required
def add_mock_item():
    data = body()
    if not (data.get("title") or "").strip():
        return fail("标题不能为空")
    cur = conn().execute(
        "INSERT INTO mock_items(title, price, url, created_at) VALUES(?,?,?,?)",
        (data["title"].strip(), _float(data.get("price"), 0) or 0, data.get("url", ""), _now()),
    )
    conn().commit()
    return ok({"id": cur.lastrowid})


# --------------------------------------------------------------------------- settings / AI

ALLOWED_SETTINGS = {
    "ai_enabled", "ai_base_url", "ai_api_key", "ai_model", "ai_system_prompt", "ai_kb_id",
    "app_name",
}


@api.get("/system/status")
@auth.login_required
def system_status():
    guard = require_admin()
    if guard:
        return guard
    return jsonify({"status": maintenance.status(conn(), current_app.config.get("VERSION", ""))})


@api.post("/system/prune")
@auth.login_required
def system_prune():
    guard = require_admin()
    if guard:
        return guard
    data = body()
    targets = data.get("targets")
    if targets is not None and not isinstance(targets, list):
        return fail("targets 必须是数组")
    result = maintenance.prune(conn(), _int(data.get("days"), 30) or 30, targets,
                               bool(data.get("vacuum")))
    db.audit(conn(), "system.prune", f"days={result['days']} total={result['total']}", g.user["id"])
    conn().commit()
    return ok({"result": result})


@api.get("/settings")
@auth.login_required
def get_settings():
    guard = require_admin()
    if guard:
        return guard
    c = conn()
    values = {row["key"]: row["value"] for row in c.execute("SELECT * FROM settings").fetchall()}
    values.pop("ai_api_key", None)  # never expose secrets back to the client
    values.pop(INTEGRATION_TOKEN_KEY, None)
    cfg = ai.config(c)
    return jsonify({
        "settings": values,
        "ai": {
            "enabled": cfg["enabled"], "base_url": cfg["base_url"], "model": cfg["model"],
            "system_prompt": cfg["system_prompt"], "has_key": bool(cfg["api_key"]),
            "kb_id": cfg["kb_id"],
        },
    })


@api.put("/settings")
@auth.login_required
def put_settings():
    guard = require_admin()
    if guard:
        return guard
    data = body()
    if not isinstance(data, dict):
        return fail("无效的设置")
    c = conn()
    for key, value in data.items():
        if key not in ALLOWED_SETTINGS:
            continue
        if isinstance(value, bool):
            value = "1" if value else "0"
        db.set_setting(c, key, "" if value is None else str(value))
    db.audit(c, "settings.update", ",".join(data.keys()), g.user["id"])
    c.commit()
    return ok()


@api.post("/ai/test")
@auth.login_required
def ai_test():
    try:
        result = ai.test(conn())
    except ai.AIError as exc:
        return fail(str(exc), 400)
    return ok({"result": result})


@api.post("/ai/reply")
@auth.login_required
def ai_reply():
    data = body()
    text = (data.get("text") or "").strip()
    if not text:
        return fail("请输入消息")
    goods = _goods(_int(data.get("goods_id"))) if data.get("goods_id") else None
    if data.get("goods_id") and not goods:
        return fail("商品不存在", 404)
    history = []
    conv_id = _int(data.get("conversation_id"))
    if conv_id:
        if not _conversation(conv_id):
            return fail("会话不存在", 404)
        history = db.rows_to_dicts(conn().execute(
            "SELECT direction, content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT 10",
            (conv_id,),
        ).fetchall())[::-1]
    try:
        answer = ai.reply(conn(), text, history=history, goods=goods)
    except ai.AIError as exc:
        return fail(str(exc), 400)
    return ok({"reply": answer})


# --------------------------------------------------------------------------- simulator

def _auto_reply(conv: dict, text: str, goods: dict | None, account: dict | None = None,
                send: bool = True) -> dict:
    c = conn()
    if conv.get("autoreply_paused"):
        until = conv.get("autoreply_paused_until") or ""
        if until and until <= db.now_iso():
            c.execute("UPDATE conversations SET autoreply_paused=0, autoreply_paused_until='' WHERE id=?",
                      (conv["id"],))
            c.commit()
            conv = dict(conv)
            conv["autoreply_paused"] = 0
            conv["autoreply_paused_until"] = ""
        else:
            return {"replied": False, "paused": True, "error": "", "ai_used": False}
    account = account or _account(conv["account_id"])
    if c.execute("SELECT 1 FROM buyer_blacklist WHERE owner_id=? AND buyer=?",
                 (conv.get("owner_id", 1), conv["buyer"])).fetchone():
        return {"replied": False, "blacklisted": True, "error": "", "ai_used": False}
    rule = replies.find_matching_rule(c, text, conv["account_id"], conv["goods_id"])
    reply = None
    ai_used = False
    error = ""
    if rule:
        context = {"buyer": conv["buyer"], "goods_title": (goods or {}).get("title", ""),
                   "account_name": (account or {}).get("name", "")}
        reply = replies.build_reply(rule, context)
    elif conv.get("ai_enabled") and account and account.get("ai_enabled") and ai.config(c)["enabled"]:
        try:
            content = ai.reply(c, text, goods=goods)
            reply = {"type": "text", "content": content, "rule_id": None, "rule_name": "AI"}
            ai_used = True
        except ai.AIError as exc:
            error = str(exc)
    if not reply:
        return {"replied": False, "error": error, "ai_used": False}
    cur = c.execute(
        "INSERT INTO messages(conversation_id, direction, content, delivery_status, created_at) "
        "VALUES(?,?,?,?,?)",
        (conv["id"], "out", reply["content"], "pending", _now()),
    )
    message_id = int(cur.lastrowid)
    c.execute(
        "UPDATE conversations SET last_message=?, unread=0, updated_at=? WHERE id=?",
        (reply["content"], _now(), conv["id"]),
    )
    c.commit()
    sent = False
    send_error = ""
    if send:
        try:
            _adapter_for(account).send_message(conv["buyer"], reply["content"])
            sent = True
            c.execute("UPDATE messages SET delivery_status='sent' WHERE id=?", (message_id,))
            c.commit()
        except PlatformUnavailable as exc:
            send_error = str(exc)
        except Exception as exc:
            send_error = str(exc)
    reply.update({"sent": sent, "send_error": send_error, "message_id": message_id,
                  "delivery_status": "sent" if sent else "pending"})
    return {"replied": True, "reply": reply, "ai_used": ai_used, "error": error}


@api.post("/sim/message")
@auth.login_required
def sim_message():
    data = body()
    text = (data.get("text") or "").strip()
    if not text:
        return fail("消息内容不能为空")
    account_id = _int(data.get("account_id"))
    if account_id:
        if not _account(account_id):
            return fail("账号不存在", 404)
    else:
        s, sa = scope()
        row = conn().execute(f"SELECT id FROM accounts WHERE 1=1 {s} ORDER BY id LIMIT 1", sa).fetchone()
        account_id = row["id"] if row else None
    if not account_id:
        return fail("请先创建账号")
    buyer = (data.get("buyer") or "demo_buyer").strip()
    goods_id = _int(data.get("goods_id"))
    if goods_id and not _goods(goods_id):
        return fail("商品不存在", 404)
    c = conn()
    conv = c.execute(
        "SELECT * FROM conversations WHERE account_id=? AND buyer=?", (account_id, buyer)
    ).fetchone()
    if conv:
        conversation = dict(conv)
        c.execute("UPDATE conversations SET goods_id=COALESCE(?, goods_id) WHERE id=?",
                  (goods_id, conversation["id"]))
    else:
        cur = c.execute(
            "INSERT INTO conversations(owner_id, account_id, goods_id, buyer, last_message, unread, ai_enabled, "
            "updated_at, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (owner_id(), account_id, goods_id, buyer, text, 0, 1, _now(), _now()),
        )
        conversation = dict(c.execute("SELECT * FROM conversations WHERE id=?", (cur.lastrowid,)).fetchone())
    c.execute(
        "INSERT INTO messages(conversation_id, direction, content, created_at) VALUES(?,?,?,?)",
        (conversation["id"], "in", text, _now()),
    )
    c.execute(
        "UPDATE conversations SET last_message=?, unread=unread+1, updated_at=? WHERE id=?",
        (text, _now(), conversation["id"]),
    )
    c.commit()
    goods = _goods(conversation["goods_id"]) if conversation["goods_id"] else None
    result = _auto_reply(conversation, text, goods)
    return ok({"conversation_id": conversation["id"], **result})


@api.post("/sim/order")
@auth.login_required
def sim_order():
    data = body()
    goods = _goods(_int(data.get("goods_id"))) if data.get("goods_id") else None
    if not goods:
        s, sa = scope()
        row = conn().execute(f"SELECT * FROM goods WHERE 1=1 {s} ORDER BY id LIMIT 1", sa).fetchone()
        goods = dict(row) if row else None
    if not goods:
        return fail("请先创建商品")
    account_id = _int(data.get("account_id")) or goods.get("account_id")
    if account_id and not _account(account_id):
        return fail("账号不存在", 404)
    quantity = max(1, _int(data.get("quantity"), 1) or 1)
    buyer = (data.get("buyer") or "demo_buyer").strip()
    amount = round(float(goods["price"]) * quantity, 2)
    order_no = _new_order_no()
    c = conn()
    cur = c.execute(
        "INSERT INTO orders(owner_id, order_no, account_id, goods_id, buyer, quantity, amount, status, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (owner_id(), order_no, account_id, goods["id"], buyer, quantity, amount, "paid", _now()),
    )
    order_id = int(cur.lastrowid)
    c.commit()
    result = delivery.deliver_order(c, order_id)
    order = dict(c.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())
    return ok({"order": order, "delivery": result})


@api.post("/sim/item")
@auth.login_required
def sim_item():
    return add_mock_item()


@api.post("/sim/seed-demo")
@auth.login_required
def seed_demo_endpoint():
    guard = require_admin()
    if guard:
        return guard
    result = db.seed_demo(conn())
    return ok({"result": result})


# --------------------------------------------------------------------------- notifications

def _channel_payload(data: dict) -> tuple[str, str, str, int]:
    name = (data.get("name") or "").strip()
    ctype = (data.get("type") or "").strip()
    if not name:
        raise ValueError("渠道名称不能为空")
    if ctype not in notify.CHANNEL_TYPES:
        raise ValueError("不支持的通知类型")
    cfg = data.get("config")
    if cfg is None:
        raw = data.get("config_json") or "{}"
        try:
            cfg = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as exc:
            raise ValueError("配置不是合法 JSON") from exc
    if not isinstance(cfg, dict):
        raise ValueError("配置必须是 JSON 对象")
    return name, ctype, json.dumps(cfg, ensure_ascii=False), 1 if data.get("enabled", True) else 0


def _set_bindings(channel_id: int, account_ids) -> None:
    conn().execute("DELETE FROM account_notification_bindings WHERE channel_id=?", (channel_id,))
    for account_id in account_ids or []:
        try:
            account_id = int(account_id)
        except (TypeError, ValueError):
            continue
        if not _account(account_id):
            continue
        conn().execute(
            "INSERT OR IGNORE INTO account_notification_bindings(account_id, channel_id) VALUES(?,?)",
            (account_id, channel_id),
        )


@api.get("/notifications/meta")
@auth.login_required
def notification_meta():
    return jsonify({"types": notify.CHANNEL_TYPES})


@api.get("/notifications/channels")
@auth.login_required
def list_channels():
    s, sa = scope()
    rows = conn().execute(f"SELECT * FROM notification_channels WHERE 1=1 {s} ORDER BY id DESC", sa).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["config"] = json.loads(item.pop("config_json") or "{}")
        item["account_ids"] = [r["account_id"] for r in conn().execute(
            "SELECT account_id FROM account_notification_bindings WHERE channel_id=?", (row["id"],)
        ).fetchall()]
        out.append(item)
    return jsonify({"channels": out})


@api.post("/notifications/channels")
@auth.login_required
def create_channel():
    data = body()
    try:
        name, ctype, cfg_json, enabled = _channel_payload(data)
    except ValueError as exc:
        return fail(str(exc))
    cur = conn().execute(
        "INSERT INTO notification_channels(owner_id, name, type, config_json, enabled, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (owner_id(), name, ctype, cfg_json, enabled, _now()),
    )
    _set_bindings(int(cur.lastrowid), data.get("account_ids"))
    conn().commit()
    return ok({"id": cur.lastrowid})


@api.patch("/notifications/channels/<int:channel_id>")
@auth.login_required
def update_channel(channel_id):
    row = conn().execute("SELECT * FROM notification_channels WHERE id=?", (channel_id,)).fetchone()
    if not row or (not is_admin() and row["owner_id"] != owner_id()):
        return fail("通知渠道不存在", 404)
    data = body()
    fields, values = [], []
    if "name" in data:
        fields.append("name=?")
        values.append((data["name"] or "").strip())
    if "type" in data:
        if data["type"] not in notify.CHANNEL_TYPES:
            return fail("不支持的通知类型")
        fields.append("type=?")
        values.append(data["type"])
    if "config" in data or "config_json" in data:
        cfg = data.get("config", data.get("config_json"))
        try:
            cfg = json.loads(cfg) if isinstance(cfg, str) else cfg
        except json.JSONDecodeError as exc:
            return fail("配置不是合法 JSON: " + str(exc))
        if not isinstance(cfg, dict):
            return fail("配置必须是 JSON 对象")
        fields.append("config_json=?")
        values.append(json.dumps(cfg, ensure_ascii=False))
    if "enabled" in data:
        fields.append("enabled=?")
        values.append(1 if data["enabled"] else 0)
    if fields:
        values.append(channel_id)
        conn().execute(f"UPDATE notification_channels SET {', '.join(fields)} WHERE id=?", values)
    if "account_ids" in data:
        _set_bindings(channel_id, data.get("account_ids"))
    conn().commit()
    return ok()


@api.delete("/notifications/channels/<int:channel_id>")
@auth.login_required
def delete_channel(channel_id):
    if not can_access("notification_channels", channel_id):
        return fail("通知渠道不存在", 404)
    conn().execute("DELETE FROM notification_channels WHERE id=?", (channel_id,))
    conn().commit()
    return ok()


@api.post("/notifications/channels/<int:channel_id>/test")
@auth.login_required
def test_channel(channel_id):
    row = conn().execute("SELECT * FROM notification_channels WHERE id=?", (channel_id,)).fetchone()
    if not row or (not is_admin() and row["owner_id"] != owner_id()):
        return fail("通知渠道不存在", 404)
    channel = dict(row)
    try:
        cfg = json.loads(channel["config_json"] or "{}")
        detail = notify.send(channel["type"], cfg, "test", "测试通知", "这是一条来自 FishAutoPro Clone 的测试消息")
    except Exception as exc:
        notify.log(conn(), channel_id, "test", "测试通知", "测试消息", "failed", str(exc))
        conn().commit()
        return fail(str(exc), 400)
    notify.log(conn(), channel_id, "test", "测试通知", "测试消息", "sent", "")
    conn().commit()
    return ok({"detail": detail})


@api.get("/notifications/logs")
@auth.login_required
def notification_logs():
    s, sa = scope("c")
    rows = conn().execute(
        "SELECT l.*, c.name AS channel_name, c.type AS channel_type FROM notification_logs l "
        "LEFT JOIN notification_channels c ON c.id=l.channel_id "
        f"WHERE 1=1 {s} ORDER BY l.id DESC LIMIT 200", sa
    ).fetchall()
    return jsonify({"logs": db.rows_to_dicts(rows)})


# --------------------------------------------------------------------------- backup / restore

@api.get("/backups")
@auth.login_required
def list_backups_api():
    guard = require_admin()
    if guard:
        return guard
    return jsonify({"backups": backup.list_backups(),
                    "pending_restore": (db.data_dir() / "restore-pending.db").exists()})


@api.post("/backups")
@auth.login_required
def create_backup_api():
    guard = require_admin()
    if guard:
        return guard
    try:
        info = backup.create_backup(conn())
    except Exception as exc:
        return fail(f"备份失败: {exc}", 500)
    db.audit(conn(), "backup.create", info["name"], g.user["id"])
    conn().commit()
    return ok({"backup": info})


@api.get("/backups/<path:name>/download")
@auth.login_required
def download_backup(name):
    guard = require_admin()
    if guard:
        return guard
    try:
        path = backup.backup_path(name)
    except backup.BackupError as exc:
        return fail(str(exc), 404)
    return send_file(path, as_attachment=True, download_name=path.name)


@api.delete("/backups/<path:name>")
@auth.login_required
def delete_backup_api(name):
    guard = require_admin()
    if guard:
        return guard
    try:
        backup.delete_backup(name)
    except backup.BackupError as exc:
        return fail(str(exc), 404)
    db.audit(conn(), "backup.delete", name, g.user["id"])
    conn().commit()
    return ok()


@api.post("/backups/restore")
@auth.login_required
def restore_backup_api():
    guard = require_admin()
    if guard:
        return guard
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return fail("请上传备份文件（.zip 或 .db）")
    data = upload.read(backup.MAX_RESTORE_BYTES + 1)
    try:
        info = backup.stage_restore(data, upload.filename)
    except backup.BackupError as exc:
        return fail(str(exc))
    db.audit(conn(), "backup.restore_staged", upload.filename, g.user["id"])
    conn().commit()
    return ok({"result": info})


# --------------------------------------------------------------------------- media

MEDIA_MAX_BYTES = 5 * 1024 * 1024
IMAGE_FORMATS = {"PNG": "png", "JPEG": "jpg", "GIF": "gif", "WEBP": "webp"}


def media_dir() -> Path:
    p = db.data_dir() / "media"
    p.mkdir(parents=True, exist_ok=True)
    return p


@api.post("/media/upload")
@auth.login_required
def upload_media():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return fail("请选择图片文件")
    data = upload.read(MEDIA_MAX_BYTES + 1)
    if len(data) > MEDIA_MAX_BYTES:
        return fail("图片不能超过 5MB")
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
            img.verify()
    except Exception:
        return fail("无法识别的图片格式")
    ext = IMAGE_FORMATS.get(fmt or "")
    if not ext:
        return fail("仅支持 PNG / JPEG / GIF / WEBP")
    filename = uuid.uuid4().hex + "." + ext
    (media_dir() / filename).write_bytes(data)
    conn().execute(
        "INSERT INTO media_files(owner_id, filename, original_name, mime, size, created_at) VALUES(?,?,?,?,?,?)",
        (owner_id(), filename, upload.filename, f"image/{ext}", len(data), _now()),
    )
    conn().commit()
    return ok({"url": f"/media/{filename}", "filename": filename, "size": len(data)})


@api.get("/media")
@auth.login_required
def list_media():
    s, sa = scope()
    rows = conn().execute(f"SELECT * FROM media_files WHERE 1=1 {s} ORDER BY id DESC LIMIT 200", sa).fetchall()
    return jsonify({"media": db.rows_to_dicts(rows)})


@api.delete("/media/<int:media_id>")
@auth.login_required
def delete_media(media_id):
    row = conn().execute("SELECT * FROM media_files WHERE id=?", (media_id,)).fetchone()
    if row and not is_admin() and row["owner_id"] != owner_id():
        return fail("图片不存在", 404)
    if row:
        try:
            (media_dir() / row["filename"]).unlink()
        except FileNotFoundError:
            pass
        except PermissionError:
            return fail("图片正在被使用，请稍后重试", 409)
        conn().execute("DELETE FROM media_files WHERE id=?", (media_id,))
        conn().commit()
    return ok()


# --------------------------------------------------------------------------- materials / publish

@api.get("/materials")
@auth.login_required
def list_materials():
    s, sa = scope("m")
    rows = conn().execute(
        "SELECT m.*, a.name AS account_name FROM product_materials m "
        f"LEFT JOIN accounts a ON a.id=m.account_id WHERE 1=1 {s} ORDER BY m.id DESC", sa
    ).fetchall()
    return jsonify({"materials": db.rows_to_dicts(rows)})


@api.post("/materials")
@auth.login_required
def create_material():
    data = body()
    title = (data.get("title") or "").strip()
    if not title:
        return fail("素材标题不能为空")
    account_id = _int(data.get("account_id"))
    if account_id and not _account(account_id):
        return fail("账号不存在", 404)
    cur = conn().execute(
        "INSERT INTO product_materials(owner_id, account_id, name, title, description, price, stock, image_url, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (owner_id(), account_id, (data.get("name") or title).strip(), title,
         data.get("description", ""), _float(data.get("price"), 0) or 0,
         _int(data.get("stock"), 0) or 0, data.get("image_url", ""), _now()),
    )
    conn().commit()
    return ok({"id": cur.lastrowid})


@api.patch("/materials/<int:material_id>")
@auth.login_required
def update_material(material_id):
    if not can_access("product_materials", material_id):
        return fail("素材不存在", 404)
    data = body()
    fields, values = [], []
    for key in ("name", "title", "description", "image_url"):
        if key in data:
            fields.append(f"{key}=?")
            values.append(data[key])
    for key, caster in (("price", _float), ("stock", _int), ("account_id", _int)):
        if key in data:
            fields.append(f"{key}=?")
            values.append(caster(data[key]))
    if not fields:
        return fail("没有可更新的字段")
    values.append(material_id)
    conn().execute(f"UPDATE product_materials SET {', '.join(fields)} WHERE id=?", values)
    conn().commit()
    return ok()


@api.delete("/materials/<int:material_id>")
@auth.login_required
def delete_material(material_id):
    if not can_access("product_materials", material_id):
        return fail("素材不存在", 404)
    conn().execute("DELETE FROM product_materials WHERE id=?", (material_id,))
    conn().commit()
    return ok()


@api.post("/product-publish/publish")
@auth.login_required
def product_publish():
    data = body()
    ids = data.get("material_ids") or ([data["material_id"]] if data.get("material_id") else [])
    if not isinstance(ids, list) or not ids:
        return fail("请选择要发布的素材")
    if not is_admin():
        ids = [int(i) for i in ids if can_access("product_materials", int(i))]
        if not ids:
            return fail("素材不存在", 404)
    account_id = _int(data.get("account_id"))
    if account_id and not _account(account_id):
        return fail("账号不存在", 404)
    result = publish.batch_publish(conn(), ids, account_id)
    if not result["ok"] and result["success"] == 0:
        return fail("发布失败", 400, result=result)
    return ok({"result": result})


@api.get("/product-publish/logs")
@auth.login_required
def product_publish_logs():
    s, sa = scope("m")
    rows = conn().execute(
        "SELECT l.*, m.name AS material_name, a.name AS account_name, g.title AS goods_title "
        "FROM publish_logs l LEFT JOIN product_materials m ON m.id=l.material_id "
        "LEFT JOIN accounts a ON a.id=l.account_id LEFT JOIN goods g ON g.id=l.goods_id "
        f"WHERE 1=1 {s} ORDER BY l.id DESC LIMIT 200", sa
    ).fetchall()
    return jsonify({"logs": db.rows_to_dicts(rows)})


# --------------------------------------------------------------------------- auto relist

@api.get("/auto-relist/rules")
@auth.login_required
def list_relist_rules():
    s, sa = scope("r")
    rows = conn().execute(
        "SELECT r.*, g.title AS goods_title, g.status AS goods_status, g.stock AS goods_stock, "
        "m.name AS material_name FROM auto_relist_rules r "
        "LEFT JOIN goods g ON g.id=r.goods_id LEFT JOIN product_materials m ON m.id=r.material_id "
        f"WHERE 1=1 {s} ORDER BY r.id DESC", sa
    ).fetchall()
    return jsonify({"rules": db.rows_to_dicts(rows)})


@api.post("/auto-relist/rules")
@auth.login_required
def create_relist_rule():
    data = body()
    goods_id = _int(data.get("goods_id"))
    if not goods_id:
        return fail("请选择需要补货的商品")
    if not _goods(goods_id):
        return fail("商品不存在", 404)
    material_id = _int(data.get("material_id"))
    if material_id and not can_access("product_materials", material_id):
        return fail("素材不存在", 404)
    cur = conn().execute(
        "INSERT INTO auto_relist_rules(owner_id, goods_id, material_id, interval_seconds, enabled, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (owner_id(), goods_id, material_id,
         max(30, _int(data.get("interval_seconds"), 600) or 600),
         1 if data.get("enabled", True) else 0, _now()),
    )
    conn().commit()
    return ok({"id": cur.lastrowid})


@api.patch("/auto-relist/rules/<int:rule_id>")
@auth.login_required
def update_relist_rule(rule_id):
    if not can_access("auto_relist_rules", rule_id):
        return fail("补货规则不存在", 404)
    data = body()
    fields, values = [], []
    if "material_id" in data:
        fields.append("material_id=?")
        values.append(_int(data["material_id"]))
    if "interval_seconds" in data:
        fields.append("interval_seconds=?")
        values.append(max(30, _int(data["interval_seconds"], 600) or 600))
    if "enabled" in data:
        fields.append("enabled=?")
        values.append(1 if data["enabled"] else 0)
    if not fields:
        return fail("没有可更新的字段")
    values.append(rule_id)
    conn().execute(f"UPDATE auto_relist_rules SET {', '.join(fields)} WHERE id=?", values)
    conn().commit()
    return ok()


@api.delete("/auto-relist/rules/<int:rule_id>")
@auth.login_required
def delete_relist_rule(rule_id):
    if not can_access("auto_relist_rules", rule_id):
        return fail("补货规则不存在", 404)
    conn().execute("DELETE FROM auto_relist_rules WHERE id=?", (rule_id,))
    conn().commit()
    return ok()


@api.post("/auto-relist/rules/<int:rule_id>/run")
@auth.login_required
def run_relist(rule_id):
    if not can_access("auto_relist_rules", rule_id):
        return fail("补货规则不存在", 404)
    result = publish.run_relist_rule(conn(), rule_id)
    if not result.get("ok"):
        return fail(result.get("error", "补货失败"), 400, result=result)
    return ok({"result": result})


@api.get("/auto-relist/logs")
@auth.login_required
def relist_logs():
    s, sa = scope("r")
    rows = conn().execute(
        "SELECT l.*, r.goods_id AS rule_goods_id, g.title AS goods_title FROM auto_relist_logs l "
        "LEFT JOIN auto_relist_rules r ON r.id=l.rule_id LEFT JOIN goods g ON g.id=l.goods_id "
        f"WHERE 1=1 {s} ORDER BY l.id DESC LIMIT 200", sa
    ).fetchall()
    return jsonify({"logs": db.rows_to_dicts(rows)})


# --------------------------------------------------------------------------- quick phrases

@api.get("/quick-phrases")
@auth.login_required
def list_quick_phrases():
    s, sa = scope()
    rows = conn().execute(f"SELECT * FROM quick_phrases WHERE 1=1 {s} ORDER BY sort_order, id", sa).fetchall()
    return jsonify({"phrases": db.rows_to_dicts(rows)})


@api.post("/quick-phrases")
@auth.login_required
def create_quick_phrase():
    content = (body().get("content") or "").strip()
    if not content:
        return fail("话术内容不能为空")
    max_order = conn().execute(f"SELECT COALESCE(MAX(sort_order),0) AS m FROM quick_phrases WHERE 1=1 {scope()[0]}",
                               scope()[1]).fetchone()["m"]
    cur = conn().execute(
        "INSERT INTO quick_phrases(owner_id, content, sort_order, created_at) VALUES(?,?,?,?)",
        (owner_id(), content, int(max_order) + 10, _now()),
    )
    conn().commit()
    return ok({"id": cur.lastrowid})


@api.patch("/quick-phrases/<int:phrase_id>")
@auth.login_required
def update_quick_phrase(phrase_id):
    if not can_access("quick_phrases", phrase_id):
        return fail("话术不存在", 404)
    data = body()
    fields, values = [], []
    if "content" in data:
        fields.append("content=?")
        values.append(data["content"])
    if "sort_order" in data:
        fields.append("sort_order=?")
        values.append(_int(data["sort_order"], 0) or 0)
    if not fields:
        return fail("没有可更新的字段")
    values.append(phrase_id)
    conn().execute(f"UPDATE quick_phrases SET {', '.join(fields)} WHERE id=?", values)
    conn().commit()
    return ok()


@api.delete("/quick-phrases/<int:phrase_id>")
@auth.login_required
def delete_quick_phrase(phrase_id):
    if not can_access("quick_phrases", phrase_id):
        return fail("话术不存在", 404)
    conn().execute("DELETE FROM quick_phrases WHERE id=?", (phrase_id,))
    conn().commit()
    return ok()


# --------------------------------------------------------------------------- knowledge base

@api.get("/knowledge/stats")
@auth.login_required
def knowledge_stats():
    return jsonify({"stats": knowledge.stats(conn(), None if is_admin() else owner_id())})


@api.get("/knowledge/bases")
@auth.login_required
def list_knowledge_bases():
    s, sa = scope("b")
    rows = conn().execute(
        "SELECT b.*, "
        "(SELECT COUNT(*) FROM knowledge_documents d WHERE d.kb_id=b.id) AS doc_count, "
        "(SELECT COUNT(*) FROM knowledge_chunks c WHERE c.kb_id=b.id) AS chunk_count "
        f"FROM knowledge_bases b WHERE 1=1 {s} ORDER BY b.id DESC", sa
    ).fetchall()
    return jsonify({"bases": db.rows_to_dicts(rows)})


@api.post("/knowledge/bases")
@auth.login_required
def create_knowledge_base():
    data = body()
    name = (data.get("name") or "").strip()
    if not name:
        return fail("知识库名称不能为空")
    cur = conn().execute(
        "INSERT INTO knowledge_bases(owner_id, name, description, enabled, created_at) VALUES(?,?,?,?,?)",
        (owner_id(), name, data.get("description", ""), 1 if data.get("enabled", True) else 0, _now()),
    )
    conn().commit()
    return ok({"id": cur.lastrowid})


@api.patch("/knowledge/bases/<int:kb_id>")
@auth.login_required
def update_knowledge_base(kb_id):
    if not _kb(kb_id):
        return fail("知识库不存在", 404)
    data = body()
    fields, values = [], []
    for key in ("name", "description"):
        if key in data:
            fields.append(f"{key}=?")
            values.append(data[key])
    if "enabled" in data:
        fields.append("enabled=?")
        values.append(1 if data["enabled"] else 0)
    if not fields:
        return fail("没有可更新的字段")
    values.append(kb_id)
    conn().execute(f"UPDATE knowledge_bases SET {', '.join(fields)} WHERE id=?", values)
    conn().commit()
    return ok()


@api.delete("/knowledge/bases/<int:kb_id>")
@auth.login_required
def delete_knowledge_base(kb_id):
    if not _kb(kb_id):
        return fail("知识库不存在", 404)
    conn().execute("DELETE FROM knowledge_bases WHERE id=?", (kb_id,))
    conn().commit()
    return ok()


@api.get("/knowledge/bases/<int:kb_id>/documents")
@auth.login_required
def list_knowledge_docs(kb_id):
    if not _kb(kb_id):
        return fail("知识库不存在", 404)
    rows = conn().execute(
        "SELECT d.*, (SELECT COUNT(*) FROM knowledge_chunks c WHERE c.doc_id=d.id) AS chunk_count "
        "FROM knowledge_documents d WHERE d.kb_id=? ORDER BY d.id DESC", (kb_id,)
    ).fetchall()
    return jsonify({"documents": db.rows_to_dicts(rows)})


@api.get("/knowledge/documents/<int:doc_id>")
@auth.login_required
def get_knowledge_doc(doc_id):
    row = _doc(doc_id)
    if not row:
        return fail("文档不存在", 404)
    return jsonify({"document": row})


@api.post("/knowledge/documents")
@auth.login_required
def create_knowledge_doc():
    data = body()
    kb_id = _int(data.get("kb_id"))
    title = (data.get("title") or "").strip()
    content = data.get("content") or ""
    if not kb_id or not _kb(kb_id):
        return fail("知识库不存在")
    if not title:
        return fail("文档标题不能为空")
    if not content.strip():
        return fail("文档内容不能为空")
    ts = _now()
    cur = conn().execute(
        "INSERT INTO knowledge_documents(kb_id, title, content, created_at, updated_at) VALUES(?,?,?,?,?)",
        (kb_id, title, content, ts, ts),
    )
    conn().commit()
    chunks = knowledge.reindex_document(conn(), int(cur.lastrowid))
    return ok({"id": cur.lastrowid, "chunks": chunks})


@api.patch("/knowledge/documents/<int:doc_id>")
@auth.login_required
def update_knowledge_doc(doc_id):
    row = _doc(doc_id)
    if not row:
        return fail("文档不存在", 404)
    data = body()
    fields, values = [], []
    for key in ("title", "content"):
        if key in data:
            fields.append(f"{key}=?")
            values.append(data[key])
    if not fields:
        return fail("没有可更新的字段")
    fields.append("updated_at=?")
    values.append(_now())
    values.append(doc_id)
    conn().execute(f"UPDATE knowledge_documents SET {', '.join(fields)} WHERE id=?", values)
    conn().commit()
    chunks = knowledge.reindex_document(conn(), doc_id)
    return ok({"chunks": chunks})


@api.delete("/knowledge/documents/<int:doc_id>")
@auth.login_required
def delete_knowledge_doc(doc_id):
    if not _doc(doc_id):
        return fail("文档不存在", 404)
    conn().execute("DELETE FROM knowledge_documents WHERE id=?", (doc_id,))
    conn().commit()
    return ok()


@api.post("/knowledge/search")
@auth.login_required
def knowledge_search():
    data = body()
    query = (data.get("query") or "").strip()
    if not query:
        return fail("请输入检索内容")
    limit = max(1, min(_int(data.get("limit"), 3) or 3, 20))
    kb_id = _int(data.get("kb_id"))
    if kb_id and not _kb(kb_id):
        return fail("知识库不存在", 404)
    hits = knowledge.search(conn(), query, kb_id, limit, None if is_admin() else owner_id())
    return ok({"hits": hits, "count": len(hits)})


# --------------------------------------------------------------------------- exports

@api.get("/exports/orders.xlsx")
@auth.login_required
def export_orders():
    data = exports.orders_xlsx(conn(), None if is_admin() else owner_id())
    return send_file(io.BytesIO(data), as_attachment=True, download_name=exports.filename("orders"),
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@api.get("/exports/goods.xlsx")
@auth.login_required
def export_goods():
    data = exports.goods_xlsx(conn(), None if is_admin() else owner_id())
    return send_file(io.BytesIO(data), as_attachment=True, download_name=exports.filename("goods"),
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@api.get("/exports/messages.xlsx")
@auth.login_required
def export_messages():
    data = exports.messages_xlsx(conn(), None if is_admin() else owner_id())
    return send_file(io.BytesIO(data), as_attachment=True, download_name=exports.filename("messages"),
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# --------------------------------------------------------------------------- audit

def _audit_query(limit: int = 200, before_id: int = 0):
    q = (request.args.get("q") or "").strip()
    action = (request.args.get("action") or "").strip()
    days = max(0, min(_int(request.args.get("days"), 0) or 0, 3650))
    sql = "SELECT * FROM audit_logs WHERE 1=1"
    args: list = []
    if not is_admin():
        sql += " AND user_id=?"
        args.append(owner_id())
    if q:
        sql += " AND (action LIKE ? OR detail LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if action:
        sql += " AND action LIKE ?"
        args.append(f"{action}%")
    if days:
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - days * 86400))
        sql += " AND created_at>=?"
        args.append(cutoff)
    if before_id:
        sql += " AND id<?"
        args.append(before_id)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit + 1)
    return db.rows_to_dicts(conn().execute(sql, args).fetchall())


@api.get("/audit-logs")
@auth.login_required
def audit_logs():
    limit = max(1, min(_int(request.args.get("limit"), 100) or 100, 500))
    before_id = _int(request.args.get("before_id"), 0) or 0
    rows = _audit_query(limit, before_id)
    has_more = len(rows) > limit
    rows = rows[:limit]
    return jsonify({"logs": rows, "has_more": has_more,
                    "before_id": rows[-1]["id"] if rows else 0})


@api.get("/audit-logs.xlsx")
@auth.login_required
def export_audit_logs():
    data = exports.audit_xlsx(_audit_query(500))
    return send_file(io.BytesIO(data), as_attachment=True, download_name=exports.filename("audit"),
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# --------------------------------------------------------------------------- integrations
#
# A small token-authenticated bridge for real chat sources (browser extension,
# Android notification listener, ...).  The bridge posts inbound messages, then
# polls the outbox to deliver replies through the real client and ACK them.

@api.get("/integrations/token")
@auth.login_required
def get_integration_token():
    guard = require_admin()
    if guard:
        return guard
    token = _setting(INTEGRATION_TOKEN_KEY)
    return ok({"token": token, "configured": bool(token)})


@api.post("/integrations/token/rotate")
@auth.login_required
def rotate_integration_token():
    guard = require_admin()
    if guard:
        return guard
    token = secrets.token_urlsafe(32)
    _set_setting(INTEGRATION_TOKEN_KEY, token)
    db.audit(conn(), "integration.token_rotate", "", g.user["id"])
    conn().commit()
    return ok({"token": token})


def _integration_account(account_id: int) -> dict | None:
    row = conn().execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    return dict(row) if row else None


def _conversation_for(account: dict, buyer: str, goods_id: int | None) -> dict:
    row = conn().execute(
        "SELECT * FROM conversations WHERE account_id=? AND buyer=?", (account["id"], buyer)
    ).fetchone()
    if row:
        return dict(row)
    cur = conn().execute(
        "INSERT INTO conversations(owner_id, account_id, goods_id, buyer, last_message, unread, ai_enabled, "
        "updated_at, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (account.get("owner_id") or 1, account["id"], goods_id, buyer, "", 0, 1, _now(), _now()),
    )
    return dict(conn().execute("SELECT * FROM conversations WHERE id=?", (cur.lastrowid,)).fetchone())


@api.post("/integrations/messages")
@integration_required
def integration_ingest_message():
    data = body()
    account = _integration_account(_int(data.get("account_id")))
    if not account:
        return fail("账号不存在", 404)
    text = (data.get("text") or "").strip()
    buyer = (data.get("buyer") or "").strip()
    if not text or not buyer:
        return fail("buyer 和 text 不能为空")
    external_id = str(data.get("external_id") or "").strip()[:200]
    goods_id = _int(data.get("goods_id"))
    conv = _conversation_for(account, buyer, goods_id)
    if external_id:
        existing = conn().execute(
            "SELECT id FROM messages WHERE conversation_id=? AND external_id=?", (conv["id"], external_id)
        ).fetchone()
        if existing:
            return ok({"duplicate": True, "conversation_id": conv["id"], "message_id": existing["id"]})
    cur = conn().execute(
        "INSERT INTO messages(conversation_id, direction, content, external_id, created_at) VALUES(?,?,?,?,?)",
        (conv["id"], "in", text, external_id, _now()),
    )
    message_id = int(cur.lastrowid)
    conn().execute(
        "UPDATE conversations SET last_message=?, unread=unread+1, updated_at=? WHERE id=?",
        (text, _now(), conv["id"]),
    )
    conn().commit()
    result = {"replied": False}
    if data.get("auto_reply", True):
        goods = None
        if conv.get("goods_id"):
            row = conn().execute("SELECT * FROM goods WHERE id=?", (conv["goods_id"],)).fetchone()
            goods = dict(row) if row else None
        result = _auto_reply(conv, text, goods, account=account, send=False)
    reply = result.get("reply") or {}
    return ok({
        "duplicate": False, "conversation_id": conv["id"], "message_id": message_id,
        "replied": result.get("replied", False), "reply": reply.get("content", ""),
        "reply_message_id": reply.get("message_id"), "ai_used": result.get("ai_used", False),
        "error": result.get("error", ""),
    })


@api.post("/integrations/send")
@integration_required
def integration_queue_message():
    data = body()
    account = _integration_account(_int(data.get("account_id")))
    if not account:
        return fail("账号不存在", 404)
    buyer = (data.get("buyer") or "").strip()
    content = (data.get("content") or "").strip()
    if not buyer or not content:
        return fail("buyer 和 content 不能为空")
    conv = _conversation_for(account, buyer, _int(data.get("goods_id")))
    cur = conn().execute(
        "INSERT INTO messages(conversation_id, direction, content, delivery_status, created_at) "
        "VALUES(?,?,?,?,?)",
        (conv["id"], "out", content, "pending", _now()),
    )
    conn().execute(
        "UPDATE conversations SET last_message=?, updated_at=? WHERE id=?",
        (content, _now(), conv["id"]),
    )
    conn().commit()
    return ok({"message_id": cur.lastrowid, "conversation_id": conv["id"]})


@api.get("/integrations/outbox")
@integration_required
def integration_outbox():
    account_id = _int(request.args.get("account_id"))
    limit = max(1, min(_int(request.args.get("limit"), 50) or 50, 200))
    sql = (
        "SELECT m.id, m.conversation_id, m.content, m.created_at, c.buyer, c.account_id, a.name AS account_name "
        "FROM messages m JOIN conversations c ON c.id=m.conversation_id "
        "LEFT JOIN accounts a ON a.id=c.account_id "
        "WHERE m.direction='out' AND m.delivery_status='pending'"
    )
    args: list = []
    if account_id:
        sql += " AND c.account_id=?"
        args.append(account_id)
    sql += " ORDER BY m.id LIMIT ?"
    args.append(limit)
    rows = conn().execute(sql, args).fetchall()
    return ok({"messages": db.rows_to_dicts(rows), "count": len(rows)})


@api.post("/integrations/outbox/<int:message_id>/ack")
@integration_required
def integration_ack(message_id):
    data = body()
    status = data.get("status") or "sent"
    if status not in ("sent", "failed"):
        return fail("status 只能是 sent 或 failed")
    row = conn().execute("SELECT * FROM messages WHERE id=? AND direction='out'", (message_id,)).fetchone()
    if not row:
        return fail("消息不存在", 404)
    conn().execute(
        "UPDATE messages SET delivery_status=?, delivery_error=? WHERE id=?",
        (status, str(data.get("error") or "")[:500], message_id),
    )
    conn().commit()
    return ok({"message_id": message_id, "status": status})
