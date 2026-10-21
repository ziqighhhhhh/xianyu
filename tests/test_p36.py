"""Account JSON export/import tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class AccountTransferTests(BaseCase):
    def test_export_and_import(self):
        data = self.client.get("/api/accounts/export").json
        self.assertEqual(data["version"], 1)
        names = [a["name"] for a in data["accounts"]]
        self.assertIn("演示账号", names)
        self.assertIn("cookie", data["accounts"][0])

        r = self.client.post("/api/accounts/import", json={"accounts": [
            {"name": "导入账号A", "cookie": "demo-import", "proxy": "", "note": "导入"},
            {"name": "导入账号A", "cookie": "demo-import"},
            {"name": "", "cookie": "x"},
        ]})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.json["imported"], 1)
        self.assertEqual(r.json["skipped"], 2)
        names = [a["name"] for a in self.client.get("/api/accounts").json["accounts"]]
        self.assertEqual(names.count("导入账号A"), 1)

    def test_invalid_payload(self):
        self.assertEqual(self.client.post("/api/accounts/import", json={"accounts": []}).status_code, 400)
        self.assertEqual(self.client.post("/api/accounts/import", json={"accounts": "nope"}).status_code, 400)

    def test_operator_scope(self):
        self.client.post("/api/users", json={"username": "op22", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op22", "password": "op123456"})
        data = op.get("/api/accounts/export").json
        self.assertEqual(data["accounts"], [])
        op.post("/api/accounts/import", json={"accounts": [{"name": "运营导入", "cookie": "demo-op"}]})
        self.assertEqual([a["name"] for a in op.get("/api/accounts").json["accounts"]], ["运营导入"])


if __name__ == "__main__":
    unittest.main()
