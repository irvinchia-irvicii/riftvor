"""collection.py — what you bought, at what you paid.

Cost basis is snapshotted at purchase time and never recalculated; market
value is looked up live from current listings. The gap between the two is
the point of the feature — 'further proofing' that a buy was good.

Concept ported from 3vor Fetch's collection.py (items + valuation), but
much smaller: Riftvor already has a canonical card key and a live listings
table, so there's no CSV import or fuzzy matcher to carry over.
"""
from __future__ import annotations

import sqlite3
import time

import db


def add_many(user_id: int, items: list[dict], note: str | None = None) -> int:
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
        try:
            acquired_at = float(item.get("acquired_at") or now)
        except (TypeError, ValueError):
            acquired_at = now
        if acquired_at <= 0:
            acquired_at = now
        try:
            folder_id = int(item["folder_id"]) if item.get("folder_id") else None
        except (TypeError, ValueError):
            folder_id = None
        rows.append((user_id, folder_id, item["card_key"],
                     finish if finish in ("nonfoil", "foil") else "nonfoil",
                     qty, unit, item.get("store"), acquired_at, note))
    if not rows:
        return 0
    with db.connect() as conn:
        valid_folders = {
            row["id"] for row in conn.execute(
                "SELECT id FROM collection_folders WHERE user_id = ?", (user_id,)
            )
        }
        rows = [
            (row[0], row[1] if row[1] in valid_folders else None, *row[2:])
            for row in rows
        ]
        conn.executemany(
            """INSERT INTO collection (user_id, folder_id, card_key, finish,
                                       qty, unit_paid, store, acquired_at, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
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


def list_items(user_id: int) -> dict:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT c.*, k.name, k.set_code, k.number, k.rarity,
                      f.name AS folder_name
               FROM collection c LEFT JOIN cards k USING (card_key)
               LEFT JOIN collection_folders f ON f.id = c.folder_id
               WHERE c.user_id = ?
               ORDER BY c.acquired_at DESC, c.id DESC""",
            (user_id,)).fetchall()
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
            "folder_id": row["folder_id"],
            "folder_name": row["folder_name"],
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


def remove(user_id: int, item_id: int) -> None:
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM collection WHERE id = ? AND user_id = ?",
            (item_id, user_id),
        )


def clear(user_id: int) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM collection WHERE user_id = ?", (user_id,))


def list_folders(user_id: int) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT f.id, f.name, f.created_at, COUNT(c.id) AS item_count,
                      COALESCE(SUM(c.qty), 0) AS card_count
               FROM collection_folders f
               LEFT JOIN collection c
                 ON c.folder_id = f.id AND c.user_id = f.user_id
               WHERE f.user_id = ?
               GROUP BY f.id
               ORDER BY LOWER(f.name)""",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def create_folder(user_id: int, name: str) -> tuple[dict | None, str | None]:
    name = " ".join((name or "").strip().split())
    if not name:
        return None, "Folder name is required."
    if len(name) > 80:
        return None, "Folder name must be 80 characters or fewer."
    try:
        with db.connect() as conn:
            folder_id = conn.execute(
                """INSERT INTO collection_folders (user_id, name, created_at)
                   VALUES (?, ?, ?)""",
                (user_id, name, time.time()),
            ).lastrowid
    except sqlite3.IntegrityError:
        return None, "You already have a folder with that name."
    return {"id": folder_id, "name": name, "item_count": 0,
            "card_count": 0}, None


def rename_folder(user_id: int, folder_id: int,
                  name: str) -> tuple[bool, str | None]:
    name = " ".join((name or "").strip().split())
    if not name or len(name) > 80:
        return False, "Use a folder name between 1 and 80 characters."
    try:
        with db.connect() as conn:
            changed = conn.execute(
                """UPDATE collection_folders SET name = ?
                   WHERE id = ? AND user_id = ?""",
                (name, folder_id, user_id),
            ).rowcount
    except sqlite3.IntegrityError:
        return False, "You already have a folder with that name."
    return bool(changed), None if changed else "Folder not found."


def delete_folder(user_id: int, folder_id: int) -> bool:
    with db.connect() as conn:
        return bool(conn.execute(
            "DELETE FROM collection_folders WHERE id = ? AND user_id = ?",
            (folder_id, user_id),
        ).rowcount)


def set_item_folder(user_id: int, item_id: int,
                    folder_id: int | None) -> tuple[bool, str | None]:
    with db.connect() as conn:
        if folder_id is not None:
            exists = conn.execute(
                """SELECT 1 FROM collection_folders
                   WHERE id = ? AND user_id = ?""",
                (folder_id, user_id),
            ).fetchone()
            if not exists:
                return False, "Folder not found."
        changed = conn.execute(
            """UPDATE collection SET folder_id = ?
               WHERE id = ? AND user_id = ?""",
            (folder_id, item_id, user_id),
        ).rowcount
    return bool(changed), None if changed else "Collection item not found."
