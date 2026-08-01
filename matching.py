"""matching.py — buy-list → comparison table (collector-number first,
token-name fallback), plus autocomplete over the local card index.
"""
from __future__ import annotations

import sqlite3

import db
from config import STORE_ORDER
from filters import _name_matches
from parsers import parse_buy_list_line


def _resolve_name(conn: sqlite3.Connection, name: str) -> list[str]:
    """Name → card_keys. Exact (case-insensitive) first, token fallback."""
    rows = conn.execute(
        "SELECT card_key FROM cards WHERE LOWER(name) = LOWER(?)",
        (name,)).fetchall()
    if rows:
        return [r["card_key"] for r in rows]
    hits = []
    for row in conn.execute("SELECT card_key, name FROM cards WHERE name IS NOT NULL"):
        if _name_matches(name, row["name"]):
            hits.append(row["card_key"])
    return hits


def _best_listings(conn: sqlite3.Connection, card_key: str) -> dict:
    """Per (finish, store): the cheapest in-stock listing (out-of-stock
    shown only when nothing in stock exists)."""
    out: dict[str, dict[str, dict]] = {}
    for row in conn.execute(
            "SELECT * FROM listings WHERE card_key = ?", (card_key,)):
        cell = {
            "price": row["price"],
            "url": row["url"],
            "in_stock": bool(row["in_stock"]),
            "condition": row["condition"],
            "title": row["title_raw"],
        }
        per_store = out.setdefault(row["finish"], {})
        cur = per_store.get(row["store"])
        if cur is None:
            per_store[row["store"]] = cell
            continue
        # In-stock beats out-of-stock; then cheaper wins.
        if (cell["in_stock"], -cell["price"]) > (cur["in_stock"], -cur["price"]):
            per_store[row["store"]] = cell
    return out


def comparison(list_text: str) -> dict:
    """Buy-list text → comparison rows (grouped nonfoil/foil) + unmatched."""
    entries = [e for e in
               (parse_buy_list_line(l) for l in list_text.splitlines()) if e]
    rows, unmatched = [], []
    with db.connect() as conn:
        for entry in entries:
            keys: list[str] = []
            if "card_key" in entry:
                exists = conn.execute(
                    "SELECT 1 FROM cards WHERE card_key = ?",
                    (entry["card_key"],)).fetchone()
                if exists:
                    keys = [entry["card_key"]]
            else:
                keys = _resolve_name(conn, entry["name"])
            if not keys:
                unmatched.append(entry)
                continue
            for key in keys:
                card = conn.execute(
                    "SELECT * FROM cards WHERE card_key = ?",
                    (key,)).fetchone()
                per_finish = _best_listings(conn, key)
                for finish in ("nonfoil", "foil"):
                    stores = per_finish.get(finish)
                    if not stores:
                        continue
                    prices = [c["price"] for c in stores.values()
                              if c["in_stock"]]
                    rows.append({
                        "raw": entry["raw"],
                        "qty": entry["qty"],
                        "card_key": key,
                        "name": card["name"],
                        "set_code": card["set_code"],
                        "number": card["number"],
                        "rarity": card["rarity"],
                        "is_alt_art": bool(card["is_alt_art"]),
                        "finish": finish,
                        "best_price": min(prices) if prices else None,
                        "stores": stores,
                    })
    rows.sort(key=lambda r: (r["raw"].lower(), r["finish"]))
    return {"rows": rows, "unmatched": unmatched,
            "store_order": STORE_ORDER}


def autocomplete(q: str, limit: int = 12) -> list[dict]:
    if not q.strip():
        return []
    like = f"%{q.strip()}%"
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT card_key, name, set_code, number, rarity FROM cards
               WHERE name LIKE ? OR card_key LIKE ?
               ORDER BY (LOWER(name) LIKE LOWER(?)) DESC, name
               LIMIT ?""",
            (like, like, f"{q.strip()}%", limit)).fetchall()
    return [dict(r) for r in rows]
