"""FishAutoPro-compatible self-hosted clone."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory

from . import backup, db

log = logging.getLogger("fap")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
VERSION = "1.0.0"
_scheduler_started = False


def _scheduler_loop(stop: threading.Event) -> None:
    from . import jobs, pauses, publish
    from .engines import monitor

    while not stop.is_set():
        try:
            monitor.tick()
            publish.relist_tick()
            pauses.tick()
            jobs.tick()
        except Exception:  # keep the scheduler alive
            log.exception("scheduler tick failed")
        stop.wait(5)


def create_app(config: dict | None = None) -> Flask:
    global _scheduler_started
    app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")
    app.config.update(
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
        JSON_AS_ASCII=False,
        VERSION=VERSION,
    )
    if config:
        app.config.update(config)

    if backup.apply_pending_restore():
        log.info("applied staged database restore")
    db.init_db()

    from .api import api

    app.register_blueprint(api)

    @app.before_request
    def _guard():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("Origin")
            if origin:
                from urllib.parse import urlparse

                if urlparse(origin).netloc != request.host:
                    return jsonify({"ok": False, "error": "跨站请求被拒绝"}), 403

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; worker-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        return resp

    @app.teardown_appcontext
    def _close(_exc):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "name": "FishAutoPro Clone", "version": app.config.get("VERSION", "1.0.0")})

    @app.get("/media/<path:filename>")
    def media(filename):
        return send_from_directory(db.data_dir() / "media", filename, max_age=86400)

    @app.errorhandler(404)
    def _404(err):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "接口不存在"}), 404
        if request.path.startswith("/media/"):
            return jsonify({"ok": False, "error": "文件不存在"}), 404
        return send_from_directory(WEB_DIR, "index.html")

    @app.errorhandler(413)
    def _413(err):
        return jsonify({"ok": False, "error": "请求体过大"}), 413

    @app.errorhandler(500)
    def _500(err):
        log.exception("internal error")
        return jsonify({"ok": False, "error": "服务器内部错误"}), 500

    if not app.config.get("TESTING") and os.environ.get("FAP_DISABLE_SCHEDULER") != "1":
        if not _scheduler_started:
            stop = threading.Event()
            t = threading.Thread(target=_scheduler_loop, args=(stop,), daemon=True, name="fap-scheduler")
            t.start()
            _scheduler_started = True

    return app


__all__ = ["create_app"]




































































