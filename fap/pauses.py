"""Auto-reply pause expiry scanning."""

from __future__ import annotations

from . import db


def tick(conn=None) -> int:
    own = conn is None
    conn = conn or db.connect()
    try:
        cur = conn.execute(
            "UPDATE conversations SET autoreply_paused=0, autoreply_paused_until='' "
            "WHERE autoreply_paused=1 AND autoreply_paused_until<>'' AND autoreply_paused_until<=?",
            (db.now_iso(),),
        )
        conn.commit()
        return cur.rowcount or 0
    finally:
        if own:
            conn.close()
