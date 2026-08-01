"""sync.py — live-sync-on-search orchestrator with TTL cache (§4).

A search triggers a parallel pull of every active store's ENTIRE Riftbound
singles catalog (1–4 paginated requests each) — cheaper AND fresher than
per-card searching for lists ≥ ~4 cards. Results are written to SQLite
(listings replaced, price_history appended) and answer the query from
there.

TTL: searches within TTL_SECONDS reuse the cached catalog; force-refresh
bypasses. A module-level lock prevents sync storms when two searches land
at once.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time

import httpx

import db
from config import RIFTMANA_ART_URL, STORES, TTL_SECONDS
from filters import is_dropped
from parsers import parse_product
from stores import ShopifyCatalogStore, make_client

log = logging.getLogger("riftvor.sync")

_SYNC_LOCK = threading.Lock()


def _listing_rows(cfg: dict, products: list[dict]) -> tuple[list[dict], list[dict]]:
    """Parse + filter one store's raw products → (listing rows, card rows)."""
    rows: list[dict] = []
    cards: dict[str, dict] = {}
    base = cfg["base"].rstrip("/")
    for product in products:
        title = product.get("title", "")
        handle = product.get("handle", "")
        tags = product.get("tags", [])
        if is_dropped(title, handle, tags):
            continue
        parsed = parse_product(cfg["parser"], product)
        url = f"{base}/products/{handle}"
        images = product.get("images") or []
        img_url = images[0].get("src") if images else None
        for variant in product.get("variants", []):
            try:
                price = float(variant.get("price") or 0)
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            vtitle = (variant.get("title") or "").strip()
            foil = ("foil" in vtitle.lower()
                    or (parsed.foil_in_title if parsed else False))
            condition = "Near Mint"
            if vtitle and vtitle.lower() not in ("default title",):
                # Variant titles look like 'Near Mint' / 'Near Mint - Foil' /
                # 'Lightly Played'; strip the foil marker to get condition.
                cond = vtitle
                cond = cond.replace("- Foil", "").replace("Foil", "").strip(" -")
                if cond:
                    condition = cond
            rows.append({
                "card_key": parsed.card_key if parsed else None,
                "title_raw": title,
                "url": url,
                "price": price,
                "currency": "SGD",
                "finish": "foil" if foil else "nonfoil",
                "condition": condition,
                "in_stock": int(bool(variant.get("available"))),
                "language": "EN",
            })
        if parsed:
            cards.setdefault(parsed.card_key, {
                "card_key": parsed.card_key,
                "set_code": parsed.set_code,
                "number": parsed.number,
                "name": parsed.name,
                "rarity": parsed.rarity,
                "color": parsed.color,
                "is_alt_art": int(parsed.is_alt_art),
                # RiftMana's predictable URL first; store image is the
                # fallback card_art.py uses if RiftMana 404s.
                "img_url": img_url,
            })
    # The (store, url, finish, condition) PK can collide when a product page
    # lists duplicate variants — keep the cheapest.
    dedup: dict[tuple, dict] = {}
    for r in rows:
        k = (r["url"], r["finish"], r["condition"])
        if k not in dedup or r["price"] < dedup[k]["price"]:
            dedup[k] = r
    return list(dedup.values()), list(cards.values())


async def _sync_store(cfg: dict, client: httpx.AsyncClient) -> dict:
    store = ShopifyCatalogStore(cfg)
    started = time.time()
    try:
        products = await store.fetch_catalog(client)
    except Exception as exc:  # noqa: BLE001 — one store must not kill the sync
        log.exception("%s: sync crashed", cfg["key"])
        products = None
        message = f"crash: {exc}"
    else:
        message = "ok" if products is not None else "fetch failed/breaker open"
    if products is None:
        return {"store": cfg["key"], "ok": False, "message": message,
                "listings": 0, "took_s": round(time.time() - started, 1)}
    rows, cards = _listing_rows(cfg, products)
    with db.connect() as conn:
        db.replace_store_listings(conn, cfg["key"], rows)
        db.upsert_cards(conn, cards)
        db.record_sync(conn, cfg["key"], True, "ok", len(rows))
    return {"store": cfg["key"], "ok": True, "message": "ok",
            "listings": len(rows), "took_s": round(time.time() - started, 1)}


async def _sync_stores(cfgs: list[dict]) -> list[dict]:
    async with make_client() as client:
        return list(await asyncio.gather(
            *(_sync_store(cfg, client) for cfg in cfgs)))


def stale_stores(force: bool = False) -> list[dict]:
    if force:
        return list(STORES)
    with db.connect() as conn:
        ages = db.sync_ages(conn)
    out = []
    for cfg in STORES:
        meta = ages.get(cfg["key"])
        if (meta is None or meta["age_s"] is None
                or meta["age_s"] > TTL_SECONDS or not meta["ok"]):
            out.append(cfg)
    return out


def ensure_fresh(force: bool = False) -> dict:
    """Sync whatever is stale (or everything, if force). Blocking; safe to
    call from a Flask request. Returns a per-store summary."""
    with _SYNC_LOCK:
        cfgs = stale_stores(force)   # re-check inside the lock: the search
        if not cfgs:                 # that queued behind a sync is now fresh
            return {"synced": [], "fresh": True}
        results = asyncio.run(_sync_stores(cfgs))
        for r in results:
            if not r["ok"]:
                with db.connect() as conn:
                    db.record_sync(conn, r["store"], False, r["message"], 0)
        return {"synced": results, "fresh": False}
