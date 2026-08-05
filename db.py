"""db.py — SQLite schema + helpers (§6 of the PRD).

All state lives in repo-local state/ (gitignored). WAL mode so the Flask
app and the nightly heartbeat can overlap safely.
"""
from __future__ import annotations

import sqlite3
import time

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    tier          TEXT NOT NULL DEFAULT 'member',
    created_at    REAL NOT NULL,
    terms_version TEXT,
    terms_accepted_at REAL,
    analytics_consent INTEGER NOT NULL DEFAULT 0,
    analytics_consent_version TEXT,
    analytics_consented_at REAL
);

CREATE TABLE IF NOT EXISTS collection_folders(
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    name       TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE (user_id, name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

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
    user_id    INTEGER,
    name       TEXT NOT NULL,
    content    TEXT NOT NULL,               -- raw textarea text
    created_at REAL NOT NULL,
    PRIMARY KEY (user_id, name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- What you actually bought, at what you actually paid. unit_paid is
-- snapshotted at purchase time and never recalculated — the whole point
-- is comparing cost basis against today's market.
CREATE TABLE IF NOT EXISTS collection(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    folder_id   INTEGER,
    card_key    TEXT NOT NULL,
    finish      TEXT NOT NULL DEFAULT 'nonfoil',
    qty         INTEGER NOT NULL DEFAULT 1,
    unit_paid   REAL NOT NULL,
    store       TEXT,
    acquired_at REAL NOT NULL,
    note        TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (folder_id) REFERENCES collection_folders(id) ON DELETE SET NULL
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

-- External reference prices are kept separate from local shop inventory.
-- They are benchmarks, not listings the user can necessarily buy in SGD.
CREATE TABLE IF NOT EXISTS external_prices(
    source          TEXT NOT NULL,
    card_key        TEXT NOT NULL,
    finish          TEXT NOT NULL,
    native_price    REAL NOT NULL,
    native_currency TEXT NOT NULL,
    sgd_price       REAL NOT NULL,
    delta_1d_sgd    REAL,
    delta_7d_sgd    REAL,
    url             TEXT,
    synced_at       REAL NOT NULL,
    PRIMARY KEY (source, card_key, finish)
);
CREATE INDEX IF NOT EXISTS idx_external_prices_card
    ON external_prices(card_key, finish);

CREATE TABLE IF NOT EXISTS fx_rates(
    base       TEXT NOT NULL,
    quote      TEXT NOT NULL,
    rate       REAL NOT NULL,
    as_of      TEXT,
    synced_at  REAL NOT NULL,
    PRIMARY KEY (base, quote)
);

CREATE TABLE IF NOT EXISTS privacy_consents(
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    purpose    TEXT NOT NULL,
    granted    INTEGER NOT NULL,
    version    TEXT NOT NULL,
    recorded_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_privacy_consents_user
    ON privacy_consents(user_id, recorded_at);

-- Deliberately sparse: no email, folder name, search text, shop, price, IP,
-- or exact timestamp is placed in the research dataset.
CREATE TABLE IF NOT EXISTS analytics_events(
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    card_key   TEXT NOT NULL,
    finish     TEXT NOT NULL,
    quantity   INTEGER NOT NULL DEFAULT 1,
    event_day  TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_analytics_events_rollup
    ON analytics_events(event_day, event_type, card_key, finish);

CREATE TABLE IF NOT EXISTS retailer_subscriptions(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT NOT NULL COLLATE NOCASE UNIQUE,
    shop_name   TEXT NOT NULL,
    plan        TEXT NOT NULL DEFAULT 'preview',
    status      TEXT NOT NULL DEFAULT 'approval_waitlist',
    consent_version TEXT NOT NULL,
    consented_at REAL NOT NULL,
    created_at  REAL NOT NULL,
    unsubscribe_token TEXT UNIQUE
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
        _migrate_account_ownership(conn)
        _migrate_privacy(conn)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate_account_ownership(conn: sqlite3.Connection) -> None:
    """Add account ownership without discarding pre-account local data.

    Legacy rows remain unowned until the first account is created, when
    claim_legacy_data() attaches them to that local owner.
    """
    if "user_id" not in _columns(conn, "collection"):
        conn.execute(
            "ALTER TABLE collection ADD COLUMN user_id INTEGER REFERENCES users(id)"
        )

    if "folder_id" not in _columns(conn, "collection"):
        conn.execute(
            """ALTER TABLE collection ADD COLUMN folder_id INTEGER
               REFERENCES collection_folders(id) ON DELETE SET NULL"""
        )

    collection_fks = conn.execute("PRAGMA foreign_key_list(collection)").fetchall()
    user_delete_cascades = any(
        row["table"] == "users" and row["from"] == "user_id"
        and row["on_delete"].upper() == "CASCADE"
        for row in collection_fks
    )
    if not user_delete_cascades:
        conn.executescript(
            """
            ALTER TABLE collection RENAME TO collection_legacy;
            CREATE TABLE collection(
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                folder_id   INTEGER,
                card_key    TEXT NOT NULL,
                finish      TEXT NOT NULL DEFAULT 'nonfoil',
                qty         INTEGER NOT NULL DEFAULT 1,
                unit_paid   REAL NOT NULL,
                store       TEXT,
                acquired_at REAL NOT NULL,
                note        TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (folder_id) REFERENCES collection_folders(id)
                    ON DELETE SET NULL
            );
            INSERT INTO collection
                (id, user_id, folder_id, card_key, finish, qty, unit_paid, store,
                 acquired_at, note)
                SELECT id, user_id, folder_id, card_key, finish, qty, unit_paid, store,
                       acquired_at, note
                FROM collection_legacy;
            DROP TABLE collection_legacy;
            """
        )

    if "user_id" not in _columns(conn, "buy_lists"):
        conn.executescript(
            """
            ALTER TABLE buy_lists RENAME TO buy_lists_legacy;
            CREATE TABLE buy_lists(
                user_id    INTEGER,
                name       TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (user_id, name),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            INSERT INTO buy_lists (user_id, name, content, created_at)
                SELECT NULL, name, content, created_at FROM buy_lists_legacy;
            DROP TABLE buy_lists_legacy;
            """
        )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_collection_card "
        "ON collection(card_key, finish)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_collection_user "
        "ON collection(user_id, acquired_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_collection_folder "
        "ON collection(user_id, folder_id)"
    )

    # This is a local founder preview: the first account on an existing
    # installation gets portfolio access. New sign-ups remain free members.
    # We deliberately choose by id and never inspect or hard-code private email.
    has_preview = conn.execute(
        "SELECT 1 FROM users WHERE tier IN ('founder', 'pro') LIMIT 1"
    ).fetchone()
    if not has_preview:
        first = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        if first:
            conn.execute(
                "UPDATE users SET tier = 'founder' WHERE id = ?", (first["id"],)
            )


def _migrate_privacy(conn: sqlite3.Connection) -> None:
    """Existing accounts stay private: analytics consent defaults to off."""
    columns = _columns(conn, "users")
    additions = {
        "terms_version": "TEXT",
        "terms_accepted_at": "REAL",
        "analytics_consent": "INTEGER NOT NULL DEFAULT 0",
        "analytics_consent_version": "TEXT",
        "analytics_consented_at": "REAL",
    }
    for name, declaration in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} {declaration}")
    retailer_columns = _columns(conn, "retailer_subscriptions")
    if "unsubscribe_token" not in retailer_columns:
        conn.execute(
            "ALTER TABLE retailer_subscriptions ADD COLUMN unsubscribe_token TEXT"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_retailer_unsubscribe "
            "ON retailer_subscriptions(unsubscribe_token)"
        )


def claim_legacy_data(user_id: int) -> None:
    """Give pre-account local data to the first account, once."""
    with connect() as conn:
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if user_count != 1:
            return
        conn.execute(
            "UPDATE collection SET user_id = ? WHERE user_id IS NULL", (user_id,)
        )
        conn.execute(
            "UPDATE buy_lists SET user_id = ? WHERE user_id IS NULL", (user_id,)
        )


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
