"""Notification channels: Bark, Telegram, generic webhook and SMTP email."""

from __future__ import annotations

import json
import smtplib
import ssl
from email.message import EmailMessage

import httpx

from . import db

CHANNEL_TYPES = {
    "bark": {
        "label": "Bark (iOS)",
        "example": {"server": "https://api.day.app", "device_key": "your-key"},
    },
    "telegram": {
        "label": "Telegram Bot",
        "example": {"bot_token": "123:ABC", "chat_id": "123456"},
    },
    "webhook": {
        "label": "Webhook",
        "example": {"url": "https://example.com/hook", "headers": {"X-Token": "..."}},
    },
    "email": {
        "label": "SMTP 邮件",
        "example": {
            "host": "smtp.example.com", "port": 587, "username": "bot@example.com",
            "password": "***", "from": "bot@example.com", "to": "you@example.com",
            "tls": "starttls",
        },
    },
}


class NotifyError(Exception):
    pass


def _post_json(url: str, payload: dict, headers: dict | None = None) -> dict:
    with httpx.Client(timeout=10) as client:
        resp = client.post(url, json=payload, headers=headers or {})
    if resp.status_code >= 400:
        raise NotifyError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return {"status": resp.status_code, "body": resp.text[:200]}


def _send_bark(cfg: dict, title: str, message: str) -> dict:
    server = (cfg.get("server") or "https://api.day.app").rstrip("/")
    key = cfg.get("device_key") or cfg.get("key")
    if not key:
        raise NotifyError("Bark 缺少 device_key")
    payload = {"device_key": key, "title": title, "body": message}
    for extra in ("group", "sound", "icon"):
        if cfg.get(extra):
            payload[extra] = cfg[extra]
    return _post_json(server + "/push", payload)


def _send_telegram(cfg: dict, title: str, message: str) -> dict:
    token = cfg.get("bot_token")
    chat_id = cfg.get("chat_id")
    if not token or not chat_id:
        raise NotifyError("Telegram 缺少 bot_token / chat_id")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    return _post_json(url, {"chat_id": chat_id, "text": f"{title}\n{message}"})


def _send_webhook(cfg: dict, title: str, message: str, event: str) -> dict:
    url = cfg.get("url")
    if not url:
        raise NotifyError("Webhook 缺少 url")
    headers = cfg.get("headers") or {}
    return _post_json(url, {"event": event, "title": title, "message": message,
                            "time": db.now_iso()}, headers)


def _send_email(cfg: dict, title: str, message: str) -> dict:
    host = cfg.get("host")
    port = int(cfg.get("port") or 587)
    sender = cfg.get("from") or cfg.get("username")
    to = cfg.get("to")
    if not host or not sender or not to:
        raise NotifyError("邮件配置缺少 host / from / to")
    recipients = [x.strip() for x in str(to).split(",") if x.strip()]
    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(message)
    mode = (cfg.get("tls") or "starttls").lower()
    context = ssl.create_default_context()
    if mode == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=15, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=15)
    try:
        if mode == "starttls":
            server.starttls(context=context)
        if cfg.get("username"):
            server.login(cfg["username"], cfg.get("password") or "")
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return {"status": "sent", "to": recipients}


def send(channel_type: str, config: dict, event: str, title: str, message: str) -> dict:
    if channel_type == "bark":
        return _send_bark(config, title, message)
    if channel_type == "telegram":
        return _send_telegram(config, title, message)
    if channel_type == "webhook":
        return _send_webhook(config, title, message, event)
    if channel_type == "email":
        return _send_email(config, title, message)
    raise NotifyError(f"未知通知类型: {channel_type}")


def log(conn, channel_id, event, title, message, status, error="") -> None:
    conn.execute(
        "INSERT INTO notification_logs(channel_id, event, title, message, status, error, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (channel_id, event, title, message, status, error, db.now_iso()),
    )


def dispatch(conn, event: str, title: str, message: str, account_id: int | None = None,
             owner_id: int | None = None) -> list[dict]:
    """Send to all enabled channels applicable to *account_id*.

    A channel with no account bindings is global.  A channel with bindings only
    fires for the bound accounts.  Operator-owned channels only receive events
    for their own accounts; admin (owner_id=1) channels can receive everything.
    When *owner_id* is given without an account (e.g. scheduled reports), only
    channels owned by that user are used.
    Failures are logged, never raised.
    """
    owner = None
    owner_only = False
    if account_id:
        row = conn.execute("SELECT owner_id FROM accounts WHERE id=?", (account_id,)).fetchone()
        owner = row["owner_id"] if row else None
    elif owner_id:
        owner = owner_id
        owner_only = True
    sql = (
        "SELECT * FROM notification_channels c WHERE c.enabled=1 AND ("
        "  NOT EXISTS(SELECT 1 FROM account_notification_bindings b WHERE b.channel_id=c.id)"
        "  OR EXISTS(SELECT 1 FROM account_notification_bindings b WHERE b.channel_id=c.id AND b.account_id=?)"
        ")"
    )
    args: list = [account_id]
    if owner:
        sql += " AND c.owner_id=?" if owner_only else " AND (c.owner_id=? OR c.owner_id=1)"
        args.append(owner)
    else:
        sql += " AND c.owner_id=1"
    sql += " ORDER BY c.id"
    rows = conn.execute(sql, args).fetchall()
    results = []
    for row in rows:
        channel = dict(row)
        try:
            cfg = json.loads(channel["config_json"] or "{}")
        except json.JSONDecodeError:
            cfg = {}
            log(conn, channel["id"], event, title, message, "failed", "配置不是合法 JSON")
            results.append({"channel_id": channel["id"], "ok": False, "error": "配置不是合法 JSON"})
            continue
        try:
            detail = send(channel["type"], cfg, event, title, message)
            log(conn, channel["id"], event, title, message, "sent", "")
            results.append({"channel_id": channel["id"], "name": channel["name"], "ok": True, "detail": detail})
        except Exception as exc:  # network/SMTP errors must not break business logic
            log(conn, channel["id"], event, title, message, "failed", str(exc))
            results.append({"channel_id": channel["id"], "name": channel["name"], "ok": False, "error": str(exc)})
    conn.commit()
    return results


def notify_async_safe(conn, event, title, message, account_id=None) -> None:
    try:
        dispatch(conn, event, title, message, account_id)
    except Exception:
        pass
