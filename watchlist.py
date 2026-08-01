"""watchlist.py — card + target-price watchlist, alert hygiene ported from
3vor Fetch: one email per dip — a card sitting under target alerts once,
then stays quiet unless it drops further or bounces back above target
first (which re-arms it).
"""
from __future__ import annotations

import sqlite3
import time

import db


def get_all() -> list[dict]:
    """Watchlist joined with card names and the current best in-stock price."""
    out = []
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT w.*, c.name, c.set_code, c.number
               FROM watchlist w LEFT JOIN cards c USING (card_key)
               ORDER BY c.name""").fetchall()
        for row in rows:
            best = conn.execute(
                """SELECT store, MIN(price) AS price FROM listings
                   WHERE card_key = ? AND finish = ? AND in_stock = 1""",
                (row["card_key"], row["finish"])).fetchone()
            out.append({
                "card_key": row["card_key"],
                "finish": row["finish"],
                "target_price": row["target_price"],
                "name": row["name"],
                "set_code": row["set_code"],
                "number": row["number"],
                "best_price": best["price"] if best else None,
                "best_store": best["store"] if best and best["price"] is not None else None,
                "triggered": (best["price"] is not None
                              and best["price"] <= row["target_price"])
                             if best else False,
                "email_sent_at": row["email_sent_at"],
            })
    return out


def add(card_key: str, finish: str, target_price: float) -> None:
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO watchlist (card_key, finish, target_price,
                                      created_at, armed)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT(card_key, finish) DO UPDATE SET
                 target_price = excluded.target_price, armed = 1""",
            (card_key, finish, target_price, time.time()))


def remove(card_key: str, finish: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM watchlist WHERE card_key = ? AND finish = ?",
                     (card_key, finish))


def check(conn: sqlite3.Connection) -> list[dict]:
    """Run after a sync: returns the entries that should alert NOW, and
    updates arming state. Caller is responsible for actually emailing and
    then calling mark_alerted() — if email fails, alert state is untouched
    so it fires again once email works (3vor Fetch semantics)."""
    hits = []
    for row in conn.execute("SELECT * FROM watchlist").fetchall():
        best = conn.execute(
            """SELECT store, MIN(price) AS price FROM listings
               WHERE card_key = ? AND finish = ? AND in_stock = 1""",
            (row["card_key"], row["finish"])).fetchone()
        price = best["price"] if best else None
        if price is None:
            continue
        if price > row["target_price"]:
            # Bounced above target → re-arm.
            if not row["armed"]:
                conn.execute(
                    """UPDATE watchlist SET armed = 1
                       WHERE card_key = ? AND finish = ?""",
                    (row["card_key"], row["finish"]))
            continue
        dipped_further = (row["last_alert_price"] is not None
                          and price < row["last_alert_price"])
        if row["armed"] or dipped_further:
            hits.append({
                "card_key": row["card_key"],
                "finish": row["finish"],
                "target_price": row["target_price"],
                "price": price,
                "store": best["store"],
            })
    return hits


def mark_alerted(card_key: str, finish: str, price: float) -> None:
    with db.connect() as conn:
        conn.execute(
            """UPDATE watchlist SET email_sent_at = ?, last_alert_price = ?,
                                    armed = 0
               WHERE card_key = ? AND finish = ?""",
            (time.time(), price, card_key, finish))
