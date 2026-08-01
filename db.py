"""db.py — SQLite schema + helpers (§6 of the PRD).

All state lives in repo-local state/ (gitignored). WAL mode so the Flask
app and the nightly heartbeat can overlap safely.
"""
from __future__ import annotations

import sqlite3
import time

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards(
    card_key   TEXT PRIMARY KEY,            -- 'OGN-043'
    set_code   TEXT NOT NULL,
    number     TEXT NOT NULL,
    name       TEXT,
    rarity     TEXT,
    color      TEXT,
    is_alt_art INTEGER DEFAULT 0,
    img_url    TEXT
);

CREATE TABLE IF NOT EXISTS listings(
    store      TEXT NOT NULL,
    card_key   TEXT,                        -- NULL for unmatched/Carousell
    title_raw  TEXT NOT NULL,
    url        TEXT NOT NULL,
    price      REAL NOT NULL,
    currency   TEXT DEFAULT 'SGD',
    finish     TEXT NOT NULL,               -- 'nonfoil' | 'foil'
    condition  TEXT DEFAULT 'Near Mint',
    in_stock   INTEGER NOT NULL,
    language   TEXT DEFAULT 'EN',
    synced_at  REAL NOT NULL,
    PRIMARY KEY (store, url, finish, condition)
);
CREATE INDEX IF NOT EXISTS idx_listings_card ON listings(card_key);

CREATE TABLE IF NOT EXISTS price_history(
    store    TEXT NOT NULL,
    card_key TEXT NOT NULL,
    finish   TEXT NOT NULL,
    price    REAL NOT NULL,
    in_stock INTEGER NOT NULL,
    seen_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_card ON price_history(card_key, store, finish);

CREATE TABLE IF NOT EXISTS watchlist(
    card_key      TEXT NOT NULL,
    finish        TEXT NOT NULL DEFAULT 'nonfoil',
    target_price  REAL NOT NULL,
    created_at    REAL NOT NULL,
    email_sent_at REAL,
    -- alert hygiene (ported semantics from 3vor Fetch watchlist.py):
    -- one email per dip; re-armed when price bounces back above target
    -- or drops further below the last alerted price.
    last_alert_price REAL,
    armed         INTEGER DEFAULT 1,
    PRIMARY KEY (card_key, finish)
);

CREATE TABLE IF NOT EXISTS buy_lists(
    name       TEXT PRIMARY KEY,
    content    TEXT NOT NULL,               -- raw textarea text
    created_at REAL NOT NULL
);

-- What you actually bought, at what you actually paid. unit_paid is
-- snapshotted at purchase time and never recalculated — the whole point
-- is comparing cost basis against today's market.
CREATE TABLE IF NOT EXISTS collection(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    card_key    TEXT NOT NULL,
    finish      TEXT NOT NULL DEFAULT 'nonfoil',
    qty         INTEGER NOT NULL DEFAULT 1,
    unit_paid   REAL NOT NULL,
    store       TEXT,
    acquired_at REAL NOT NULL,
    note        TEXT
);
CREATE INDEX IF NOT EXISTS idx_collection_card ON collection(card_key, finish);

CREATE TABLE IF NOT EXISTS sync_meta(
    store         TEXT PRIMARY KEY,
    synced_at     REAL,
    ok            INTEGER,
    message       TEXT,
    listing_count INTEGER
);

CREATE TABLE IF NOT EXISTS dormant_notices(
    store      TEXT PRIMARY KEY,
    detail     TEXT,
    noticed_at REAL
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def replace_store_listings(conn: sqlite3.Connection, store: str,
                           rows: list[dict]) -> None:
    """Swap a store's current listings and append the history snapshot."""
    now = time.time()
    conn.execute("DELETE FROM listings WHERE store = ?", (store,))
    conn.executemany(
        """INSERT OR REPLACE INTO listings
           (store, card_key, title_raw, url, price, currency, finish,
            condition, in_stock, language, synced_at)
           VALUES (:store, :card_key, :title_raw, :url, :price, :currency,
                   :finish, :condition, :in_stock, :language, :synced_at)""",
        [{**r, "store": store, "synced_at": now} for r in rows],
    )
    # One history point per (card, finish): stores like GOAT list every
    # condition (NM → Damaged) as variants — the chart series tracks the
    # cheapest in-stock listing, Near Mint preferred, so a $21 Damaged copy
    # never masquerades as the market price.
    snapshot: dict[tuple, dict] = {}
    for r in rows:
        if not r["card_key"]:
            continue
        key = (r["card_key"], r["finish"])
        cur = snapshot.get(key)
        rank = (r["in_stock"], r["condition"] == "Near Mint", -r["price"])
        if cur is None or rank > cur["_rank"]:
            snapshot[key] = {**r, "_rank": rank}
    conn.executemany(
        """INSERT INTO price_history (store, card_key, finish, price,
                                      in_stock, seen_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [(store, r["card_key"], r["finish"], r["price"], r["in_stock"], now)
         for r in snapshot.values()],
    )


def record_sync(conn: sqlite3.Connection, store: str, ok: bool,
                message: str, listing_count: int) -> None:
    conn.execute(
        """INSERT INTO sync_meta (store, synced_at, ok, message, listing_count)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(store) DO UPDATE SET
             synced_at = excluded.synced_at, ok = excluded.ok,
             message = excluded.message,
             listing_count = excluded.listing_count""",
        (store, time.time(), int(ok), message, listing_count),
    )


def upsert_cards(conn: sqlite3.Connection, cards: list[dict]) -> None:
    """Seed/refresh the card index from the union of store catalogs (§7)."""
    conn.executemany(
        """INSERT INTO cards (card_key, set_code, number, name, rarity, color,
                              is_alt_art, img_url)
           VALUES (:card_key, :set_code, :number, :name, :rarity, :color,
                   :is_alt_art, :img_url)
           ON CONFLICT(card_key) DO UPDATE SET
             name       = COALESCE(cards.name, excluded.name),
             rarity     = COALESCE(cards.rarity, excluded.rarity),
             color      = COALESCE(cards.color, excluded.color),
             is_alt_art = MAX(cards.is_alt_art, excluded.is_alt_art),
             img_url    = COALESCE(cards.img_url, excluded.img_url)""",
        cards,
    )


def sync_ages(conn: sqlite3.Connection) -> dict[str, dict]:
    now = time.time()
    out = {}
    for row in conn.execute("SELECT * FROM sync_meta"):
        out[row["store"]] = {
            "synced_at": row["synced_at"],
            "age_s": (now - row["synced_at"]) if row["synced_at"] else None,
            "ok": bool(row["ok"]),
            "message": row["message"],
            "listing_count": row["listing_count"],
        }
    return out
