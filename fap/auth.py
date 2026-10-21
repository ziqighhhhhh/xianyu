"""Authentication primitives.

Passwords use PBKDF2-HMAC-SHA256.  Sessions are stateless signed cookies
(HMAC-SHA256) whose key is generated on first run and stored under
``data/secret.key``; unlike the original product we never ship a default
secret.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from functools import wraps
from pathlib import Path

from flask import g, jsonify, request

from . import db

COOKIE_NAME = "fap_session"


def cookie_secure() -> bool:
    import os
    return os.environ.get("FAP_SECURE_COOKIES", "").lower() in ("1", "true", "yes")
SESSION_TTL = 7 * 24 * 3600
PBKDF2_ROUNDS = 210_000


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def get_secret() -> bytes:
    path = Path(os.environ.get("FAP_SECRET_FILE", db.data_dir() / "secret.key"))
    if path.exists():
        return path.read_bytes().strip()
    secret = secrets.token_hex(32).encode("ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(secret)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return secret


def make_session(user_id: int, sv: int = 0, jti: str = "", ttl: int = SESSION_TTL) -> str:
    payload = {"uid": int(user_id), "sv": int(sv), "jti": jti, "exp": int(time.time()) + int(ttl)}
    body = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = _b64e(hmac.new(get_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def issue_session(user_id: int, sv: int, user_agent: str = "", ip: str = "", ttl: int = SESSION_TTL) -> str:
    jti = secrets.token_urlsafe(24)
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO user_sessions(user_id, jti, user_agent, ip, created_at, last_seen_at) "
            "VALUES(?,?,?,?,?,?)",
            (int(user_id), jti, (user_agent or "")[:300], (ip or "")[:64], db.now_iso(), db.now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    return make_session(user_id, sv, jti, ttl)


def revoke_session(jti: str) -> None:
    if not jti:
        return
    conn = db.connect()
    try:
        conn.execute("UPDATE user_sessions SET revoked_at=? WHERE jti=? AND revoked_at=''",
                     (db.now_iso(), jti))
        conn.commit()
    finally:
        conn.close()


def revoke_user_sessions(user_id: int) -> None:
    conn = db.connect()
    try:
        conn.execute("UPDATE user_sessions SET revoked_at=? WHERE user_id=? AND revoked_at=''",
                     (db.now_iso(), user_id))
        conn.commit()
    finally:
        conn.close()


def parse_session(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expected = _b64e(hmac.new(get_secret(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64d(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < time.time():
        return None
    return payload


def current_user() -> dict | None:
    if "user" in g:
        return g.user
    payload = parse_session(request.cookies.get(COOKIE_NAME))
    user = None
    if payload:
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT id, username, role, is_active, session_version, created_at FROM users WHERE id=?",
                (payload["uid"],),
            ).fetchone()
            jti = payload.get("jti") or ""
            session = conn.execute(
                "SELECT * FROM user_sessions WHERE jti=? AND user_id=?", (jti, payload.get("uid"))
            ).fetchone() if jti else None
            if (row and row["is_active"] and session and not session["revoked_at"]
                    and int(payload.get("sv", 0)) == int(row["session_version"])):
                user = {"id": row["id"], "username": row["username"], "role": row["role"],
                        "is_active": row["is_active"], "created_at": row["created_at"]}
                cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 300))
                if not session["last_seen_at"] or session["last_seen_at"] < cutoff:
                    conn.execute("UPDATE user_sessions SET last_seen_at=? WHERE jti=?", (db.now_iso(), jti))
                    conn.commit()
        finally:
            conn.close()
    g.user = user
    return user


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录或会话已过期"}), 401
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


def setup_required() -> bool:
    conn = db.connect()
    try:
        return conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 0
    finally:
        conn.close()


def create_user(username: str, password: str, role: str = "admin") -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO users(username, password_hash, role, created_at) VALUES(?,?,?,?)",
            (username, hash_password(password), role, db.now_iso()),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def authenticate(username: str, password: str) -> dict | None:
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not row or not row["is_active"] or not verify_password(password, row["password_hash"]):
            return None
        return {"id": row["id"], "username": row["username"], "role": row["role"],
                "is_active": row["is_active"], "session_version": row["session_version"],
                "created_at": row["created_at"]}
    finally:
        conn.close()
