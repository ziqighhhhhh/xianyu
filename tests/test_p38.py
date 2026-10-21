"""Movie ticket module tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class MovieTicketTests(BaseCase):
    def test_seed_and_create(self):
        tickets = self.client.get("/api/movie-tickets").json["tickets"]
        self.assertTrue(any(t["order_no"] == "MT-DEMO-1" for t in tickets))
        r = self.client.post("/api/movie-tickets", json={
            "movie_name": "测试影片", "cinema": "测试影院", "show_time": "2026-12-01 20:00",
            "seats": "1排1座", "quantity": 1, "amount": 39.9, "buyer": "票务买家", "phone": "13900000000",
        })
        self.assertEqual(r.status_code, 200, r.data)
        t = r.json["ticket"]
        self.assertEqual(t["status"], "pending")
        self.assertTrue(t["code"])
        self.assertTrue(t["order_no"].startswith("MT"))

    def test_update_status_and_filter(self):
        t = self.client.post("/api/movie-tickets", json={"movie_name": "状态影片"}).json["ticket"]
        r = self.client.patch(f"/api/movie-tickets/{t['id']}", json={"status": "paid"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.json["ticket"]["status"], "paid")
        paid = self.client.get("/api/movie-tickets", query_string={"status": "paid"}).json["tickets"]
        self.assertIn(t["id"], [x["id"] for x in paid])
        self.assertEqual(self.client.patch(f"/api/movie-tickets/{t['id']}", json={"status": "bad"}).status_code, 400)

    def test_qr_and_delete(self):
        t = self.client.post("/api/movie-tickets", json={"movie_name": "票码影片"}).json["ticket"]
        r = self.client.get(f"/api/movie-tickets/{t['id']}/qr")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.json["data_url"].startswith("data:image/png;base64,"))
        self.assertEqual(self.client.delete(f"/api/movie-tickets/{t['id']}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/movie-tickets/{t['id']}/qr").status_code, 404)

    def test_operator_isolation(self):
        self.client.post("/api/users", json={"username": "op23", "password": "op123456", "role": "operator"})
        op = self.app.test_client()
        op.post("/api/auth/login", json={"username": "op23", "password": "op123456"})
        self.assertEqual(op.get("/api/movie-tickets").json["tickets"], [])
        demo = self.client.get("/api/movie-tickets").json["tickets"][0]
        self.assertEqual(op.patch(f"/api/movie-tickets/{demo['id']}", json={"status": "used"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
