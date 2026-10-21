"""Clean-instance smoke test.

Creates a temporary data directory, boots the app, and exercises the core flows
through the Flask test client.  Run with::

    python scripts/smoke.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    data_dir = tempfile.mkdtemp(prefix="fap-smoke-")
    os.environ["FAP_DATA_DIR"] = data_dir
    os.environ["FAP_DISABLE_SCHEDULER"] = "1"
    from fap import VERSION, create_app

    app = create_app({"TESTING": True})
    client = app.test_client()
    checks: list[str] = []

    def check(name: str, response, predicate=None):
        ok = response.status_code == 200
        if predicate is not None:
            ok = ok and predicate(response)
        if not ok:
            raise SystemExit(f"FAIL {name}: HTTP {response.status_code} {response.data[:300]!r}")
        checks.append(name)

    try:
        check("health", client.get("/api/health"), lambda r: r.json["ok"])
        check("setup", client.post("/api/setup", json={
            "username": "admin", "password": "admin123", "seed_demo": True}))
        check("login", client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123"}), lambda r: r.json["ok"])
        check("dashboard", client.get("/api/dashboard"), lambda r: "stats" in r.json)

        account = client.post("/api/accounts", json={
            "name": "冒烟账号", "cookie": "demo-smoke"}).json["id"]
        checks.append("account.create")

        goods = client.post("/api/goods", json={
            "account_id": account, "title": "冒烟商品", "price": 9.9, "stock": 10}).json["id"]
        checks.append("goods.create")

        check("autosell.rule", client.post("/api/autosell/rules", json={
            "name": "冒烟发货", "goods_id": goods, "delivery_type": "fixed", "content": "SMOKE-KEY"}))

        order = client.post("/api/sim/order", json={"goods_id": goods, "quantity": 1}).json["order"]
        checks.append("order.sim")
        if order["status"] != "delivered":
            raise SystemExit(f"FAIL order delivery: {order['status']} {order.get('delivery_error')}")
        check("order.ship", client.post(f"/api/orders/{order['id']}/ship"))

        client.post("/api/sim/message", json={
            "account_id": account, "buyer": "冒烟买家", "text": "多久发货？"})
        convs = client.get("/api/conversations").json["conversations"]
        conv = next(c for c in convs if c["buyer"] == "冒烟买家")
        check("conversation.messages", client.get(f"/api/conversations/{conv['id']}/messages"),
              lambda r: len(r.json["messages"]) >= 1)

        ticket = client.post("/api/movie-tickets", json={
            "movie_name": "冒烟电影", "status": "paid", "amount": 39.9}).json["ticket"]
        check("movie.verify", client.post(f"/api/movie-tickets/{ticket['id']}/verify"))
        check("movie.export", client.get("/api/movie-tickets.xlsx"),
              lambda r: r.data.startswith(b"PK"))

        check("backup", client.post("/api/backups"), lambda r: r.json.get("ok"))
        check("audit", client.get("/api/audit-logs"), lambda r: len(r.json["logs"]) > 0)

        print(f"FishAutoPro Clone {VERSION} clean-instance smoke: {len(checks)} checks passed")
        for name in checks:
            print("  ok", name)
        print("data_dir:", data_dir)
        return 0
    finally:
        import shutil
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
