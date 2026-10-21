"""HTTP smoke test: boots waitress on a random local port and uses httpx."""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    data_dir = tempfile.mkdtemp(prefix="fap-http-smoke-")
    os.environ["FAP_DATA_DIR"] = data_dir
    os.environ["FAP_DISABLE_SCHEDULER"] = "1"
    from fap import VERSION, create_app
    from waitress import create_server

    port = free_port()
    app = create_app({"TESTING": False})
    server = create_server(app, host="127.0.0.1", port=port, threads=4)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    import httpx
    base = f"http://127.0.0.1:{port}"
    checks: list[str] = []
    try:
        for _ in range(50):
            try:
                if httpx.get(base + "/api/health", timeout=1).status_code == 200:
                    break
            except Exception:
                time.sleep(0.1)
        with httpx.Client(base_url=base, timeout=10) as c:
            def check(name, r, predicate=None):
                ok = r.status_code == 200 and (predicate(r) if predicate else True)
                if not ok:
                    raise SystemExit(f"FAIL {name}: {r.status_code} {r.text[:300]}")
                checks.append(name)

            check("health", c.get("/api/health"), lambda r: r.json()["version"] == VERSION)
            headers = c.get("/api/health").headers
            if "frame-ancestors 'none'" not in headers.get("Content-Security-Policy", ""):
                raise SystemExit("FAIL csp header")
            checks.append("security.headers")

            check("setup", c.post("/api/setup", json={
                "username": "admin", "password": "admin123", "seed_demo": True}))
            login = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
            check("login", login, lambda r: "fap_session" in c.cookies)
            check("dashboard", c.get("/api/dashboard"), lambda r: "stats" in r.json())

            account = c.post("/api/accounts", json={"name": "HTTP账号", "cookie": "demo-http"}).json()["id"]
            goods = c.post("/api/goods", json={
                "account_id": account, "title": "HTTP商品", "price": 5, "stock": 3}).json()["id"]
            checks += ["account.create", "goods.create"]
            check("autosell.rule", c.post("/api/autosell/rules", json={
                "name": "HTTP发货", "goods_id": goods, "delivery_type": "fixed", "content": "HTTP-KEY"}))
            order = c.post("/api/sim/order", json={"goods_id": goods, "quantity": 1}).json()["order"]
            checks.append("order.sim")
            check("order.ship", c.post(f"/api/orders/{order['id']}/ship"))
            check("movie.export", c.get("/api/movie-tickets.xlsx"), lambda r: r.content.startswith(b"PK"))
            check("backup", c.post("/api/backups"), lambda r: r.json().get("ok"))

        print(f"FishAutoPro Clone {VERSION} HTTP smoke on {base}: {len(checks)} checks passed")
        for name in checks:
            print("  ok", name)
        return 0
    finally:
        server.close()
        thread.join(timeout=5)
        import shutil
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

