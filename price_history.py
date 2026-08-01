"""price_history.py — per-card, per-store history series for the chart
(3vor Fetch's price_history, now backed by SQLite price_history rows)."""
from __future__ import annotations

import time

import db
from config import STORE_BY_KEY


def history(card_key: str, finish: str | None = None,
            days: int = 90) -> dict:
    since = time.time() - days * 86400
    params: list = [card_key, since]
    finish_sql = ""
    if finish in ("nonfoil", "foil"):
        finish_sql = "AND finish = ?"
        params.append(finish)
    series: dict[str, list[dict]] = {}
    with db.connect() as conn:
        rows = conn.execute(
            f"""SELECT store, finish, price, in_stock, seen_at
                FROM price_history
                WHERE card_key = ? AND seen_at >= ? {finish_sql}
                ORDER BY seen_at""", params).fetchall()
        card = conn.execute("SELECT * FROM cards WHERE card_key = ?",
                            (card_key,)).fetchone()
    for row in rows:
        key = f"{row['store']}:{row['finish']}"
        series.setdefault(key, []).append({
            "t": row["seen_at"],
            "price": row["price"],
            "in_stock": bool(row["in_stock"]),
        })
    # Thin out same-day duplicates (live syncs append per TTL expiry): keep
    # the last point per store per ~hour so the chart stays readable.
    for key, points in series.items():
        thinned, last_bucket = [], None
        for p in points:
            bucket = int(p["t"] // 3600)
            if bucket == last_bucket:
                thinned[-1] = p
            else:
                thinned.append(p)
                last_bucket = bucket
        series[key] = thinned
    return {
        "card_key": card_key,
        "name": card["name"] if card else card_key,
        "series": series,
        "store_names": {k: v["name"] for k, v in STORE_BY_KEY.items()},
    }
