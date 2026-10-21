"""Login session registry and per-device revocation tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase
from fap import auth


class SessionTests(BaseCase):
    def _login(self, username="admin", password="admin123"):
        client = self.app.test_client()
        r = client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(r.status_code, 200, r.data)
        return client

    def test_list_and_revoke_other_device(self):
        second = self._login()
        sessions = self.client.get("/api/auth/sessions").json["sessions"]
        self.assertEqual(len(sessions), 2)
        current = [s for s in sessions if s["current"]]
        others = [s for s in sessions if not s["current"]]
        self.assertEqual(len(current), 1)
        self.assertEqual(len(others), 1)
        self.assertEqual(second.get("/api/auth/me").status_code, 200)
        r = self.client.delete(f"/api/auth/sessions/{others[0]['id']}")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(second.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        self.assertEqual(len(self.client.get("/api/auth/sessions").json["sessions"]), 1)

    def test_logout_revokes_current_session(self):
        client = self._login()
        self.assertEqual(client.get("/api/auth/me").status_code, 200)
        client.post("/api/auth/logout")
        self.assertEqual(client.get("/api/auth/me").status_code, 401)

    def test_legacy_token_without_jti_rejected(self):
        legacy = self.app.test_client()
        legacy.set_cookie("fap_session", auth.make_session(1, 0))
        self.assertEqual(legacy.get("/api/auth/me").status_code, 401)

    def test_revoke_unknown_session(self):
        self.assertEqual(self.client.delete("/api/auth/sessions/99999").status_code, 404)

    def test_sessions_are_per_user(self):
        self.client.post("/api/users", json={"username": "op9", "password": "op123456", "role": "operator"})
        op = self._login("op9", "op123456")
        self.assertEqual(len(op.get("/api/auth/sessions").json["sessions"]), 1)
        self.assertEqual(len(self.client.get("/api/auth/sessions").json["sessions"]), 1)


if __name__ == "__main__":
    unittest.main()
