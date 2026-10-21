"""Password change and session-version invalidation tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class PasswordTests(BaseCase):
    def test_change_password_invalidates_old_session(self):
        old_token = self.client.get_cookie("fap_session").value
        r = self.client.post("/api/auth/password", json={
            "old_password": "admin123", "new_password": "newpass123",
        })
        self.assertEqual(r.status_code, 200, r.data)
        # current client received the rotated cookie and stays logged in
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)

        stale = self.app.test_client()
        stale.set_cookie("fap_session", old_token)
        self.assertEqual(stale.get("/api/auth/me").status_code, 401)

        fresh = self.app.test_client()
        self.assertEqual(fresh.post("/api/auth/login", json={
            "username": "admin", "password": "admin123",
        }).status_code, 401)
        self.assertEqual(fresh.post("/api/auth/login", json={
            "username": "admin", "password": "newpass123",
        }).status_code, 200)

    def test_wrong_or_short_password(self):
        self.assertEqual(self.client.post("/api/auth/password", json={
            "old_password": "bad", "new_password": "newpass123",
        }).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/password", json={
            "old_password": "admin123", "new_password": "123",
        }).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/password", json={
            "old_password": "admin123", "new_password": "admin123",
        }).status_code, 400)

    def test_admin_reset_invalidates_target_session(self):
        self.client.post("/api/users", json={"username": "op8", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        self.assertEqual(op.post("/api/auth/login", json={
            "username": "op8", "password": "op123456",
        }).status_code, 200)
        users = self.client.get("/api/users").json["users"]
        uid = next(u["id"] for u in users if u["username"] == "op8")
        self.client.patch(f"/api/users/{uid}", json={"password": "reset123"})
        self.assertEqual(op.get("/api/auth/me").status_code, 401)
        self.assertEqual(op.post("/api/auth/login", json={
            "username": "op8", "password": "op123456",
        }).status_code, 401)
        self.assertEqual(op.post("/api/auth/login", json={
            "username": "op8", "password": "reset123",
        }).status_code, 200)


if __name__ == "__main__":
    unittest.main()
