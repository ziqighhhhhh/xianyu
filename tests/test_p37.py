"""Encrypted account export tests."""

from __future__ import annotations

import base64
import json
import unittest

from test_core import BaseCase


class EncryptedExportTests(BaseCase):
    def test_encrypted_roundtrip(self):
        r = self.client.post("/api/accounts/export/encrypted", json={"password": "secret123"})
        self.assertEqual(r.status_code, 200, r.data)
        blob = r.json["blob"]
        self.assertEqual(blob["format"], "fap-accounts-encrypted")
        raw = base64.b64decode(blob["ciphertext"])
        self.assertNotIn(b"demo-cookie", raw)
        self.assertNotIn("演示账号".encode("utf-8"), raw)

        imported = self.client.post("/api/accounts/import", json={
            "blob": blob, "password": "secret123",
        })
        self.assertEqual(imported.status_code, 200, imported.data)
        # every exported account already exists by name, so they are skipped
        self.assertGreaterEqual(imported.json["skipped"], 1)

    def test_wrong_password(self):
        blob = self.client.post("/api/accounts/export/encrypted", json={"password": "secret123"}).json["blob"]
        r = self.client.post("/api/accounts/import", json={"blob": blob, "password": "wrongpass"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("密码错误", r.json["error"])

    def test_password_required_and_min_length(self):
        self.assertEqual(self.client.post("/api/accounts/export/encrypted", json={"password": "123"}).status_code, 400)
        self.assertEqual(self.client.post("/api/accounts/import", json={
            "format": "fap-accounts-encrypted", "salt": "", "nonce": "", "ciphertext": "",
        }).status_code, 400)

    def test_import_new_account_from_encrypted(self):
        # Build a fresh encrypted blob via the module (as an external tool would).
        from fap import account_export
        blob = account_export.encrypt([{"name": "加密导入", "cookie": "demo-enc"}], "secret123")
        r = self.client.post("/api/accounts/import", json={"blob": blob, "password": "secret123"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.json["imported"], 1)
        names = [a["name"] for a in self.client.get("/api/accounts").json["accounts"]]
        self.assertIn("加密导入", names)


if __name__ == "__main__":
    unittest.main()
