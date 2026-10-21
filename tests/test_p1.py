"""P1 feature tests: notifications, backup/restore, media, rate limiting."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from test_core import BaseCase


def _png_bytes(color=(0, 128, 255)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (12, 12), color).save(buf, "PNG")
    return buf.getvalue()


class _WebhookHandler(BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        try:
            _WebhookHandler.received.append(json.loads(body))
        except ValueError:
            _WebhookHandler.received.append({"raw": body.decode("utf-8", "replace")})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args):
        pass


class NotificationTests(BaseCase):
    def setUp(self):
        super().setUp()
        _WebhookHandler.received = []
        os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _WebhookHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/hook"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_channel_crud_and_test(self):
        resp = self.client.post("/api/notifications/channels", json={
            "name": "hook", "type": "webhook", "config": {"url": self.url},
        })
        self.assertEqual(resp.status_code, 200, resp.data)
        ch_id = resp.json["id"]
        test = self.client.post(f"/api/notifications/channels/{ch_id}/test")
        self.assertEqual(test.status_code, 200, test.data)
        self.assertTrue(_WebhookHandler.received)
        channels = self.client.get("/api/notifications/channels").json["channels"]
        self.assertEqual(channels[0]["type"], "webhook")
        logs = self.client.get("/api/notifications/logs").json["logs"]
        self.assertTrue(any(l["event"] == "test" and l["status"] == "sent" for l in logs))

    def test_order_delivery_triggers_notification(self):
        self.client.post("/api/notifications/channels", json={
            "name": "hook", "type": "webhook", "config": {"url": self.url},
        })
        goods = self.client.get("/api/goods").json["goods"]
        fixed = next(g for g in goods if "自动发货测试" in g["title"])
        resp = self.client.post("/api/sim/order", json={"goods_id": fixed["id"], "quantity": 1})
        self.assertEqual(resp.json["order"]["status"], "delivered")
        events = [item.get("event") for item in _WebhookHandler.received]
        self.assertIn("order.delivered", events)
        logs = self.client.get("/api/notifications/logs").json["logs"]
        self.assertTrue(any(l["event"] == "order.delivered" and l["status"] == "sent" for l in logs))


class BackupTests(BaseCase):
    def test_backup_create_download_delete(self):
        create = self.client.post("/api/backups")
        self.assertEqual(create.status_code, 200, create.data)
        name = create.json["backup"]["name"]
        self.assertTrue(name.endswith(".zip"))
        listed = self.client.get("/api/backups").json["backups"]
        self.assertEqual(listed[0]["name"], name)
        download = self.client.get(f"/api/backups/{name}/download")
        self.assertEqual(download.status_code, 200)
        self.assertTrue(download.data.startswith(b"PK\x03\x04"))
        download.close()
        self.assertEqual(self.client.delete(f"/api/backups/{name}").status_code, 200)
        self.assertFalse(self.client.get("/api/backups").json["backups"])

    def test_restore_is_staged_and_applied(self):
        original = self.client.get("/api/settings").json["ai"]["model"]
        create = self.client.post("/api/backups")
        name = create.json["backup"]["name"]
        download = self.client.get(f"/api/backups/{name}/download")
        blob = download.data
        download.close()

        self.client.put("/api/settings", json={"ai_model": "changed-model"})
        self.assertEqual(self.client.get("/api/settings").json["ai"]["model"], "changed-model")

        restore = self.client.post("/api/backups/restore", data={"file": (io.BytesIO(blob), name)},
                                   content_type="multipart/form-data")
        self.assertEqual(restore.status_code, 200, restore.data)
        self.assertTrue(self.client.get("/api/backups").json["pending_restore"])

        # Simulate the restart that applies the staged restore.
        from fap import backup

        self.assertTrue(backup.apply_pending_restore())
        self.assertEqual(self.client.get("/api/settings").json["ai"]["model"], original)

    def test_restore_rejects_non_sqlite(self):
        resp = self.client.post("/api/backups/restore", data={"file": (io.BytesIO(b"not a db"), "x.db")},
                                content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)


class MediaTests(BaseCase):
    def test_upload_serve_delete(self):
        resp = self.client.post("/api/media/upload",
                                data={"file": (io.BytesIO(_png_bytes()), "test.png")},
                                content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 200, resp.data)
        url = resp.json["url"]
        self.assertTrue(url.startswith("/media/"))
        served = self.client.get(url)
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.data[:8], b"\x89PNG\r\n\x1a\n")
        served.close()
        media = self.client.get("/api/media").json["media"]
        self.assertEqual(len(media), 1)
        self.client.delete(f"/api/media/{media[0]['id']}")
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_upload_rejects_non_image(self):
        resp = self.client.post("/api/media/upload",
                                data={"file": (io.BytesIO(b"hello"), "x.txt")},
                                content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)


class RateLimitTests(BaseCase):
    def test_login_lockout(self):
        codes = []
        for _ in range(6):
            resp = self.client.post("/api/auth/login", json={"username": "ratelimit_user", "password": "bad"})
            codes.append(resp.status_code)
        self.assertEqual(codes[:5], [401] * 5)
        self.assertEqual(codes[5], 429)
        locked = self.client.post("/api/auth/login", json={"username": "ratelimit_user", "password": "bad"})
        self.assertEqual(locked.status_code, 429)
        self.assertIn("Retry-After", locked.headers)
        logs = self.client.get("/api/audit-logs").json["logs"]
        self.assertTrue(any(l["action"] == "login.failed" for l in logs))


if __name__ == "__main__":
    unittest.main()
