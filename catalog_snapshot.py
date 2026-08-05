"""Bootstrap a fresh hosted database from a public-only catalogue snapshot."""
from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path

import db
from config import BASE_DIR

SNAPSHOT_PATH = BASE_DIR / "data" / "catalog_snapshot.json.gz"
log = logging.getLogger("riftvor.catalog_snapshot")


def bootstrap_if_empty(path: Path = SNAPSHOT_PATH) -> dict:
    """Load cards and public price listings when a new database is empty."""
    with db.connect() as conn:
        cards_present = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        listings_present = conn.execute(
            "SELECT COUNT(*) FROM listings"
        ).fetchone()[0]
        if cards_present and listings_present:
            return {"loaded": False, "reason": "catalogue already present"}
        if not path.exists():
            raise FileNotFoundError(f"Catalogue snapshot missing: {path}")

        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        cards = payload.get("cards") or []
        listings = payload.get("listings") or []
        external_prices = payload.get("external_prices") or []
        fx_rates = payload.get("fx_rates") or []
        if not cards or not listings:
            raise ValueError("Catalogue snapshot contains no searchable data")

        conn.executemany(
            """INSERT OR REPLACE INTO cards
               (card_key, set_code, number, name, rarity, color, is_alt_art,
                img_url)
               VALUES (:card_key, :set_code, :number, :name, :rarity, :color,
                       :is_alt_art, :img_url)""", cards)
        conn.executemany(
            """INSERT OR REPLACE INTO listings
               (store, card_key, title_raw, url, price, currency, finish,
                condition, in_stock, language, synced_at)
               VALUES (:store, :card_key, :title_raw, :url, :price, :currency,
                       :finish, :condition, :in_stock, :language, :synced_at)""",
            listings)
        conn.executemany(
            """INSERT OR REPLACE INTO external_prices
               (source, card_key, finish, native_price, native_currency,
                sgd_price, delta_1d_sgd, delta_7d_sgd, url, synced_at)
               VALUES (:source, :card_key, :finish, :native_price,
                       :native_currency, :sgd_price, :delta_1d_sgd,
                       :delta_7d_sgd, :url, :synced_at)""", external_prices)
        conn.executemany(
            """INSERT OR REPLACE INTO fx_rates
               (base, quote, rate, as_of, synced_at)
               VALUES (:base, :quote, :rate, :as_of, :synced_at)""", fx_rates)

        generated_at = float(payload.get("generated_at") or 0)
        by_store: dict[str, int] = {}
        for row in listings:
            by_store[row["store"]] = by_store.get(row["store"], 0) + 1
        conn.executemany(
            """INSERT OR REPLACE INTO sync_meta
               (store, synced_at, ok, message, listing_count)
               VALUES (?, ?, 1, ?, ?)""",
            [(store, generated_at, "Hosted review catalogue snapshot", count)
             for store, count in by_store.items()])

    result = {"loaded": True, "cards": len(cards),
              "listings": len(listings)}
    log.info("loaded hosted review snapshot: %s", result)
    return result
