"""Movie ticket verification tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class MovieVerifyTests(BaseCase):
    def _ticket(self, status="paid"):
        return self.client.post("/api/movie-tickets", json={
            "movie_name": "核销影片", "status": status,
        }).json["ticket"]

    def test_verify_by_id(self):
        t = self._ticket()
        r = self.client.post(f"/api/movie-tickets/{t['id']}/verify")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.json["already"])
        self.assertEqual(r.json["ticket"]["status"], "used")
        self.assertTrue(r.json["ticket"]["used_at"])
        self.assertEqual(r.json["ticket"]["verified_by"], "admin")
        again = self.client.post(f"/api/movie-tickets/{t['id']}/verify")
        self.assertTrue(again.json["already"])

    def test_verify_by_code(self):
        t = self._ticket()
        r = self.client.post("/api/movie-tickets/verify", json={"code": t["code"].lower()})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.json["ticket"]["id"], t["id"])

    def test_pending_cannot_verify(self):
        t = self._ticket("pending")
        self.assertEqual(self.client.post(f"/api/movie-tickets/{t['id']}/verify").status_code, 400)
        self.assertEqual(self.client.post("/api/movie-tickets/verify", json={"code": "NOPE"}).status_code, 404)

    def test_operator_cannot_verify_admin_ticket(self):
        t = self._ticket()
        self.client.post("/api/users", json={"username": "op24", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op24", "password": "op123456"})
        self.assertEqual(op.post(f"/api/movie-tickets/{t['id']}/verify").status_code, 404)
        self.assertEqual(op.post("/api/movie-tickets/verify", json={"code": t["code"]}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
