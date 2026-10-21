"""Product materials/publish, auto-relist, quick phrases and PWA tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase


class PublishTests(BaseCase):
    def test_seed_materials(self):
        mats = self.client.get("/api/materials").json["materials"]
        self.assertEqual(len(mats), 3)
        self.assertTrue(all(m["account_id"] for m in mats))

    def test_publish_single_creates_goods_and_log(self):
        mats = self.client.get("/api/materials").json["materials"]
        before = len(self.client.get("/api/goods").json["goods"])
        resp = self.client.post("/api/product-publish/publish", json={"material_ids": [mats[0]["id"]]})
        self.assertEqual(resp.status_code, 200, resp.data)
        result = resp.json["result"]
        self.assertEqual(result["success"], 1)
        self.assertTrue(result["results"][0]["item_id"].startswith("mock-"))
        goods = self.client.get("/api/goods").json["goods"]
        self.assertEqual(len(goods), before + 1)
        self.assertEqual(goods[0]["title"], mats[0]["title"])
        logs = self.client.get("/api/product-publish/logs").json["logs"]
        self.assertEqual(logs[0]["status"], "success")
        self.assertTrue(logs[0]["goods_id"])

    def test_batch_publish(self):
        mats = self.client.get("/api/materials").json["materials"]
        ids = [m["id"] for m in mats[:2]]
        resp = self.client.post("/api/product-publish/publish", json={"material_ids": ids})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json["result"]["success"], 2)

    def test_material_crud(self):
        created = self.client.post("/api/materials", json={
            "name": "测试素材", "title": "测试商品", "price": 12.5, "stock": 5,
        })
        self.assertEqual(created.status_code, 200)
        mid = created.json["id"]
        self.client.patch(f"/api/materials/{mid}", json={"price": 20, "stock": 9})
        mats = self.client.get("/api/materials").json["materials"]
        row = next(m for m in mats if m["id"] == mid)
        self.assertEqual(row["price"], 20)
        self.assertEqual(row["stock"], 9)
        self.client.delete(f"/api/materials/{mid}")
        mats = self.client.get("/api/materials").json["materials"]
        self.assertFalse(any(m["id"] == mid for m in mats))


class RelistTests(BaseCase):
    def test_relist_after_off_shelf(self):
        rules = self.client.get("/api/auto-relist/rules").json["rules"]
        self.assertTrue(rules)
        rule = rules[0]
        goods_id = rule["goods_id"]
        self.client.patch(f"/api/goods/{goods_id}", json={"status": "off_shelf", "stock": 0})
        resp = self.client.post(f"/api/auto-relist/rules/{rule['id']}/run")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.json["result"]["status"], "relisted")
        goods = self.client.get("/api/goods").json["goods"]
        row = next(g for g in goods if g["id"] == goods_id)
        self.assertEqual(row["status"], "on_sale")
        self.assertGreater(row["stock"], 0)
        logs = self.client.get("/api/auto-relist/logs").json["logs"]
        self.assertEqual(logs[0]["status"], "success")

    def test_relist_skips_when_in_stock(self):
        rule = self.client.get("/api/auto-relist/rules").json["rules"][0]
        goods = self.client.get("/api/goods").json["goods"]
        row = next(g for g in goods if g["id"] == rule["goods_id"])
        self.assertEqual(row["status"], "on_sale")
        resp = self.client.post(f"/api/auto-relist/rules/{rule['id']}/run")
        self.assertEqual(resp.json["result"]["status"], "skipped")

    def test_create_relilst_rule(self):
        goods = self.client.get("/api/goods").json["goods"]
        resp = self.client.post("/api/auto-relist/rules", json={
            "goods_id": goods[0]["id"], "interval_seconds": 30,
        })
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(self.client.get("/api/auto-relist/rules").json["rules"])


class QuickPhraseTests(BaseCase):
    def test_crud(self):
        phrases = self.client.get("/api/quick-phrases").json["phrases"]
        self.assertEqual(len(phrases), 3)
        created = self.client.post("/api/quick-phrases", json={"content": "新话术"})
        self.assertEqual(created.status_code, 200)
        pid = created.json["id"]
        self.client.patch(f"/api/quick-phrases/{pid}", json={"content": "更新话术"})
        phrases = self.client.get("/api/quick-phrases").json["phrases"]
        self.assertIn("更新话术", [p["content"] for p in phrases])
        self.client.delete(f"/api/quick-phrases/{pid}")
        phrases = self.client.get("/api/quick-phrases").json["phrases"]
        self.assertNotIn("更新话术", [p["content"] for p in phrases])

    def test_reject_empty(self):
        self.assertEqual(self.client.post("/api/quick-phrases", json={"content": " "}).status_code, 400)


class PWATests(BaseCase):
    def test_manifest_and_worker(self):
        manifest = self.client.get("/manifest.webmanifest")
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json["short_name"], "FAP Clone")
        self.assertIn(manifest.json["theme_color"], ("#0d9488",))
        sw = self.client.get("/sw.js")
        self.assertEqual(sw.status_code, 200)
        self.assertIn(b"fap-shell", sw.data)
        icon = self.client.get("/icons/icon-192.png")
        self.assertEqual(icon.status_code, 200)
        self.assertEqual(icon.data[:8], b"\x89PNG\r\n\x1a\n")
        index = self.client.get("/").data
        self.assertIn(b"manifest.webmanifest", index)


if __name__ == "__main__":
    unittest.main()
