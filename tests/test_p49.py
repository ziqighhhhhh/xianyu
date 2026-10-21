"""Movie ticket export tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class MovieExportTests(BaseCase):
    def test_export(self):
        self.client.post("/api/movie-tickets", json={"movie_name": "导出影片", "status": "paid"})
        r = self.client.get("/api/movie-tickets.xlsx")
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r.headers["Content-Type"])
        self.assertTrue(r.data.startswith(b"PK"))
        r.close()

    def test_operator_export_scope(self):
        self.client.post("/api/users", json={"username": "op31", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op31", "password": "op123456"})
        r = op.get("/api/movie-tickets.xlsx")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data.startswith(b"PK"))
        r.close()


if __name__ == "__main__":
    unittest.main()
