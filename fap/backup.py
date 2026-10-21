"""Backup and restore.

Backups are ZIP files containing a consistent SQLite snapshot (via the sqlite3
online backup API), ``secret.key`` and a small metadata file.  Restore is staged
and applied on the next process start, which avoids replacing an open SQLite
file on Windows.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import time
import zipfile
from pathlib import Path

from . import db

REQUIRED_TABLES = {"users", "accounts", "goods", "orders", "settings", "schema_meta"}
MAX_RESTORE_BYTES = 200 * 1024 * 1024
KEEP_BACKUPS = 20


class BackupError(Exception):
    pass


def backups_dir() -> Path:
    p = db.data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _validate_sqlite_bytes(data: bytes) -> None:
    if not data.startswith(b"SQLite format 3\x00"):
        raise BackupError("不是有效的 SQLite 数据库")
    if len(data) > MAX_RESTORE_BYTES:
        raise BackupError("备份文件过大")
    import tempfile

    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        Path(tmp).write_bytes(data)
        conn = sqlite3.connect(tmp)
        try:
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = REQUIRED_TABLES - names
            if missing:
                raise BackupError("备份缺少必要数据表: " + ", ".join(sorted(missing)))
        finally:
            conn.close()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def create_backup(conn: sqlite3.Connection) -> dict:
    name = f"fap-backup-{_stamp()}.zip"
    target = backups_dir() / name
    tmp_db = backups_dir() / (name + ".db")
    dest = sqlite3.connect(str(tmp_db))
    try:
        conn.backup(dest)
    finally:
        dest.close()
    try:
        secret_path = Path(os.environ.get("FAP_SECRET_FILE", db.data_dir() / "secret.key"))
        meta = {
            "created_at": db.now_iso(),
            "schema_version": db.SCHEMA_VERSION,
            "app": "FishAutoPro Clone",
        }
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp_db, "app.db")
            if secret_path.exists():
                zf.write(secret_path, "secret.key")
            zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
    finally:
        try:
            tmp_db.unlink()
        except OSError:
            pass
    _prune()
    st = target.stat()
    return {"name": name, "size": st.st_size, "created_at": db.now_iso()}


def _prune() -> None:
    files = sorted(backups_dir().glob("fap-backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[KEEP_BACKUPS:]:
        try:
            old.unlink()
        except OSError:
            pass


def list_backups() -> list[dict]:
    out = []
    for p in sorted(backups_dir().glob("fap-backup-*.zip"), key=lambda x: x.stat().st_mtime, reverse=True):
        st = p.stat()
        out.append({
            "name": p.name,
            "size": st.st_size,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime)),
        })
    return out


def backup_path(name: str) -> Path:
    name = Path(name).name
    if not name.startswith("fap-backup-") or not name.endswith(".zip"):
        raise BackupError("备份文件名无效")
    path = backups_dir() / name
    if not path.exists():
        raise BackupError("备份不存在")
    return path


def delete_backup(name: str) -> None:
    path = backup_path(name)
    try:
        path.unlink()
    except PermissionError as exc:
        raise BackupError("备份正在被下载，请稍后重试") from exc


def stage_restore(data: bytes, filename: str = "") -> dict:
    """Validate an uploaded .zip/.db and write it as the pending restore."""
    if len(data) > MAX_RESTORE_BYTES:
        raise BackupError("备份文件过大")
    db_bytes = None
    key_bytes = None
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = set(zf.namelist())
                if "app.db" not in names:
                    raise BackupError("压缩包中缺少 app.db")
                db_bytes = zf.read("app.db")
                if "secret.key" in names:
                    key_bytes = zf.read("secret.key")
        except zipfile.BadZipFile as exc:
            raise BackupError("压缩包损坏") from exc
    else:
        db_bytes = data
    if db_bytes is None:
        raise BackupError("无法识别的备份格式")
    _validate_sqlite_bytes(db_bytes)
    pending = db.data_dir() / "restore-pending.db"
    pending.write_bytes(db_bytes)
    if key_bytes:
        (db.data_dir() / "restore-pending.key").write_bytes(key_bytes)
    else:
        kp = db.data_dir() / "restore-pending.key"
        if kp.exists():
            kp.unlink()
    return {"staged": True, "bytes": len(db_bytes), "filename": filename,
            "note": "重启服务后生效"}


def apply_pending_restore() -> bool:
    """Called before init_db() on startup."""
    pending = db.data_dir() / "restore-pending.db"
    if not pending.exists():
        return False
    target = db.db_path()
    backup = target.with_name(target.name + ".bak-" + _stamp())
    if target.exists():
        shutil.copy2(target, backup)
    for suffix in ("-wal", "-shm"):
        side = Path(str(target) + suffix)
        if side.exists():
            try:
                side.unlink()
            except OSError:
                pass
    os.replace(pending, target)
    pending_key = db.data_dir() / "restore-pending.key"
    if pending_key.exists():
        secret = Path(os.environ.get("FAP_SECRET_FILE", db.data_dir() / "secret.key"))
        if secret.exists():
            shutil.copy2(secret, secret.with_name(secret.name + ".bak-" + _stamp()))
        os.replace(pending_key, secret)
    return True
