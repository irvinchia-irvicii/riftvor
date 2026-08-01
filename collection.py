"""collection.py — what you bought, at what you paid.

Cost basis is snapshotted at purchase time and never recalculated; market
value is looked up live from current listings. The gap between the two is
the point of the feature — 'further proofing' that a buy was good.

Concept ported from 3vor Fetch's collection.py (items + valuation), but
much smaller: Riftvor already has a canonical card key and a live listings
table, so there's no CSV import or fuzzy matcher to carry over.
"""
from __future__ import annotations

import time

import db


def add_many(items: list[dict], note: str | None = None) -> int:
    """items: [{card_key, finish, qty, unit_paid, store}] → rows inserted."""
    rows = []
    now = time.time()
    for item in items:
        try:
            qty = max(1, int(item.get("qty", 1)))
            unit = float(item["unit_paid"])
        except (KeyError, TypeError, ValueError):
            continue
        if not item.get("card_key") or unit < 0:
            continue
        finish = item.get("finish")
        rows.append((item["card_key"],
                     finish if finish in ("nonfoil", "foil") else "nonfoil",
                     qty, unit, item.get("store"), now, note))
    if not rows:
        return 0
    with db.connect() as conn:
        conn.executemany(
            """INSERT INTO collection (card_key, finish, qty, unit_paid,
                                       store, acquired_at, note)
               VALUES (?, ?, ?, ?, ?, ?, ?)""", rows)
    return len(rows)


def _market_prices(conn) -> dict[tuple, float]:
    """(card_key, finish) → cheapest in-stock price across stores today."""
    out: dict[tuple, float] = {}
    for row in conn.execute(
            """SELECT card_key, finish, MIN(price) AS price
               FROM listings
               WHERE in_stock = 1 AND card_key IS NOT NULL
               GROUP BY card_key, finish"""):
        out[(row["card_key"], row["finish"])] = row["price"]
    return out


def list_items() -> dict:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT c.*, k.name, k.set_code, k.number, k.rarity
               FROM collection c LEFT JOIN cards k USING (card_key)
               ORDER BY c.acquired_at DESC, c.id DESC""").fetchall()
        market = _market_prices(conn)
    items, paid_total, value_total = [], 0.0, 0.0
    for row in rows:
        paid = row["unit_paid"] * row["qty"]
        unit_now = market.get((row["card_key"], row["finish"]))
        value = unit_now * row["qty"] if unit_now is not None else None
        paid_total += paid
        if value is not None:
            value_total += value
        items.append({
            "id": row["id"],
            "card_key": row["card_key"],
            "name": row["name"] or row["card_key"],
            "set_code": row["set_code"],
            "number": row["number"],
            "finish": row["finish"],
            "qty": row["qty"],
            "unit_paid": round(row["unit_paid"], 2),
            "paid": round(paid, 2),
            "unit_now": round(unit_now, 2) if unit_now is not None else None,
            "value": round(value, 2) if value is not None else None,
            "delta": round(value - paid, 2) if value is not None else None,
            "store": row["store"],
            "acquired_at": row["acquired_at"],
        })
    return {
        "items": items,
        "summary": {
            "lines": len(items),
            "cards": sum(i["qty"] for i in items),
            "paid": round(paid_total, 2),
            "value": round(value_total, 2),
            "delta": round(value_total - paid_total, 2),
            # Items with nothing in stock anywhere have no market price
            # today, so the value total understates rather than guesses.
            "unpriced": sum(1 for i in items if i["value"] is None),
        },
    }


def remove(item_id: int) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM collection WHERE id = ?", (item_id,))


def clear() -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM collection")
