"""Security header and cookie flag tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from test_core import BaseCase


class SecurityHeaderTests(BaseCase):
    def test_headers(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertIn("camera=()", r.headers["Permissions-Policy"])
        csp = r.headers["Content-Security-Policy"]
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("script-src 'self'", csp)

    def test_cookie_flags(self):
        r = self.app.test_client().post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        cookie = r.headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertNotIn("Secure", cookie)

    def test_secure_cookie_toggle(self):
        with patch.dict("os.environ", {"FAP_SECURE_COOKIES": "1"}):
            r = self.app.test_client().post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        self.assertIn("Secure", r.headers.get("Set-Cookie", ""))


if __name__ == "__main__":
    unittest.main()
