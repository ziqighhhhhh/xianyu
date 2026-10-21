"""Legacy audit entity backfill tests."""

from __future__ import annotations

import unittest

from test_core import BaseCase
from fap import db


class AuditBackfillTests(BaseCase):
    def test_backfill_legacy_rows(self):
        account = self.client.get("/api/accounts").json["accounts"][0]
        self.client.post("/api/orders/sync", json={"account_id": account["id"], "order_id": "MOCK-SOLD-1"})
        order = self.client.get("/api/orders").json["orders"][0]
        conn = db.connect()
        try:
            conn.execute(
                "INSERT INTO audit_logs(user_id, action, detail, entity_type, entity_id, created_at) "
                "VALUES(1,'order.note',?, '',0,?)",
                (f"order={order['id']}", db.now_iso()),
            )
            conn.commit()
            self.assertEqual(db.backfill_order_audit(conn), 1)
            row = conn.execute(
                "SELECT entity_type, entity_id FROM audit_logs WHERE detail=?",
                (f"order={order['id']}",),
            ).fetchone()
            self.assertEqual(row["entity_type"], "order")
            self.assertEqual(row["entity_id"], order["id"])
            self.assertEqual(db.backfill_order_audit(conn), 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
