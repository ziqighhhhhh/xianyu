"""End-to-end tests for the clone (stdlib unittest; no extra dependencies)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

os.environ.setdefault("FAP_DISABLE_SCHEDULER", "1")


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fap-test-")
        os.environ["FAP_DATA_DIR"] = self.tmp
        from fap import create_app

        self.app = create_app({"TESTING": True})
        self.client = self.app.test_client()
        resp = self.client.post("/api/setup", json={
            "username": "admin", "password": "admin123", "seed_demo": True,
        })
        self.assertEqual(resp.status_code, 200, resp.data)

    def tearDown(self):
        pass


class AuthTests(BaseCase):
    def test_login_required(self):
        self.client.post("/api/auth/logout")
        resp = self.client.get("/api/accounts")
        self.assertEqual(resp.status_code, 401)

    def test_setup_only_once(self):
        resp = self.client.post("/api/setup", json={"username": "x", "password": "123456"})
        self.assertEqual(resp.status_code, 409)

    def test_login(self):
        self.client.post("/api/auth/logout")
        resp = self.client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        self.assertEqual(resp.status_code, 401)
        resp = self.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json["ok"])


class ReplyTests(BaseCase):
    def test_keyword_rule(self):
        resp = self.client.post("/api/autoreply/test", json={"text": "能便宜一点吗"})
        data = resp.json
        self.assertTrue(data["matched"])
        self.assertIn("活动价", data["reply"]["content"])

    def test_no_match(self):
        resp = self.client.post("/api/autoreply/test", json={"text": "今天天气不错"})
        self.assertFalse(resp.json["matched"])

    def test_simulated_message_creates_conversation_and_reply(self):
        resp = self.client.post("/api/sim/message", json={"text": "多久发货？", "buyer": "buyer1"})
        data = resp.json
        self.assertTrue(data["replied"])
        self.assertIn("自动发货", data["reply"]["content"])
        convs = self.client.get("/api/conversations").json["conversations"]
        self.assertTrue(any(c["buyer"] == "buyer1" for c in convs))


class DeliveryTests(BaseCase):
    def test_fixed_delivery(self):
        goods = self.client.get("/api/goods").json["goods"]
        fixed = next(g for g in goods if "自动发货测试" in g["title"])
        resp = self.client.post("/api/sim/order", json={"goods_id": fixed["id"], "quantity": 1})
        data = resp.json
        self.assertEqual(data["order"]["status"], "delivered")
        self.assertIn("DEMO-", data["order"]["delivery_content"])

    def test_stock_multi_quantity(self):
        goods = self.client.get("/api/goods").json["goods"]
        stock = next(g for g in goods if "库存卡密" in g["title"])
        resp = self.client.post("/api/sim/order", json={"goods_id": stock["id"], "quantity": 3})
        content = resp.json["order"]["delivery_content"]
        self.assertEqual(len(content.splitlines()), 3)
        # stock count decreased by 3
        rules = self.client.get("/api/autosell/rules").json["rules"]
        rule = next(r for r in rules if r["goods_id"] == stock["id"])
        self.assertEqual(rule["stock_available"], 17)

    def test_insufficient_stock_fails(self):
        goods = self.client.get("/api/goods").json["goods"]
        stock = next(g for g in goods if "库存卡密" in g["title"])
        resp = self.client.post("/api/sim/order", json={"goods_id": stock["id"], "quantity": 999})
        self.assertEqual(resp.json["order"]["status"], "failed")
        self.assertIn("库存不足", resp.json["order"]["delivery_error"])


class WorkflowTests(BaseCase):
    def test_condition_branch(self):
        nodes = [
            {"id": "s", "type": "trigger"},
            {"id": "c", "type": "condition", "left": "{{quantity}}", "op": ">", "right": "1"},
            {"id": "a", "type": "deliver", "content": "many"},
            {"id": "b", "type": "deliver", "content": "one"},
        ]
        edges = [
            {"from": "s", "to": "c"},
            {"from": "c", "to": "a", "when": "true"},
            {"from": "c", "to": "b", "when": "false"},
        ]
        created = self.client.post("/api/workflows", json={"name": "t", "nodes": nodes, "edges": edges})
        self.assertEqual(created.status_code, 200, created.data)
        wf_id = created.json["id"]
        r1 = self.client.post(f"/api/workflows/{wf_id}/run", json={"context": {"quantity": 2}})
        self.assertEqual(r1.json["result"]["context"]["delivery"], "many")
        r2 = self.client.post(f"/api/workflows/{wf_id}/run", json={"context": {"quantity": 1}})
        self.assertEqual(r2.json["result"]["context"]["delivery"], "one")

    def test_invalid_workflow_rejected(self):
        resp = self.client.post("/api/workflows", json={"nodes": [{"id": "x", "type": "nope"}], "edges": []})
        self.assertEqual(resp.status_code, 400)


class MonitorTests(BaseCase):
    def test_run_task_records_item(self):
        tasks = self.client.get("/api/monitor/tasks").json["tasks"]
        task = tasks[0]
        resp = self.client.post(f"/api/monitor/tasks/{task['id']}/run")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json["result"]["new"], 1)
        items = self.client.get("/api/monitor/items").json["items"]
        self.assertTrue(any(i["task_id"] == task["id"] for i in items))


class SecurityTests(BaseCase):
    def test_cross_origin_write_rejected(self):
        resp = self.client.post("/api/goods", json={"title": "x"}, headers={"Origin": "http://evil.example"})
        self.assertEqual(resp.status_code, 403)

    def test_password_is_hashed(self):
        import sqlite3

        conn = sqlite3.connect(os.path.join(self.tmp, "app.db"))
        row = conn.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()
        conn.close()
        self.assertTrue(row[0].startswith("pbkdf2$"))
        self.assertNotIn("admin123", row[0])


if __name__ == "__main__":
    unittest.main()

class RuleCrudTests(BaseCase):
    def test_create_exact_rule_and_match(self):
        resp = self.client.post("/api/autoreply/rules", json={
            "name": "在吗", "match_type": "exact", "pattern": "在吗",
            "reply_type": "text", "content": "在的，亲", "priority": 99,
        })
        self.assertEqual(resp.status_code, 200, resp.data)
        rule_id = resp.json["id"]
        test = self.client.post("/api/autoreply/test", json={"text": "在吗"})
        self.assertTrue(test.json["matched"])
        self.assertEqual(test.json["reply"]["content"], "在的，亲")
        # disable -> no longer matches
        self.client.patch(f"/api/autoreply/rules/{rule_id}", json={"enabled": False})
        test = self.client.post("/api/autoreply/test", json={"text": "在吗"})
        self.assertFalse(test.json["matched"])

    def test_create_stock_rule_and_preview(self):
        goods = self.client.get("/api/goods").json["goods"]
        target = goods[1]
        resp = self.client.post("/api/autosell/rules", json={
            "name": "自定义卡密", "goods_id": target["id"], "delivery_type": "stock",
            "multi_quantity": True,
        })
        self.assertEqual(resp.status_code, 200, resp.data)
        rule_id = resp.json["id"]
        add = self.client.post(f"/api/autosell/rules/{rule_id}/stock", json={"items": "A-1\nA-2\nA-3"})
        self.assertEqual(add.json["added"], 3)
        preview = self.client.post(f"/api/autosell/rules/{rule_id}/preview", json={"quantity": 2})
        self.assertEqual(len(preview.json["preview"].splitlines()), 2)
        order = self.client.post("/api/sim/order", json={"goods_id": target["id"], "quantity": 3})
        self.assertEqual(order.json["order"]["status"], "delivered")
        self.assertEqual(order.json["order"]["delivery_content"], "A-1\nA-2\nA-3")


class SettingsTests(BaseCase):
    def test_ai_key_is_masked(self):
        resp = self.client.put("/api/settings", json={
            "ai_enabled": True, "ai_base_url": "https://api.example.com/v1",
            "ai_model": "demo-model", "ai_api_key": "sk-secret",
        })
        self.assertEqual(resp.status_code, 200, resp.data)
        data = self.client.get("/api/settings").json
        self.assertTrue(data["ai"]["enabled"])
        self.assertTrue(data["ai"]["has_key"])
        self.assertNotIn("sk-secret", json.dumps(data))


class PageTests(BaseCase):
    def test_index_served(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"FishAutoPro", resp.data)

    def test_health(self):
        self.assertEqual(self.client.get("/api/health").json["ok"], True)
