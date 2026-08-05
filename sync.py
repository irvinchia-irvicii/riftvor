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
from config import (RIFTMANA_ART_URL, SEQUENTIAL_SYNC, SNAPSHOT_MODE,
                    STORE_DELAY_S, STORES, TTL_SECONDS)
from filters import is_dropped
from parsers import parse_product
from stores import CatalogResult, ShopifyCatalogStore, make_client

log = logging.getLogger("riftvor.sync")

_SYNC_LOCK = threading.Lock()
_SYNC_RUNNING = threading.Event()


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
        result = await store.fetch_catalog(client)
    except Exception as exc:  # noqa: BLE001 — one store must not kill the sync
        log.exception("%s: sync crashed", cfg["key"])
        result = CatalogResult(None, [f"crash: {exc}"])
    took = round(time.time() - started, 1)

    if result.status != "ok":
        # A partial catalog is discarded, not written. replace_store_listings
        # deletes the store's rows before inserting, so a truncated fetch
        # would erase every card it failed to see — they would read as
        # stocked nowhere, and price_history would record that fiction
        # permanently (it is append-only). Last complete snapshot, clearly
        # marked stale, beats a fresh and wrong one.
        detail = result.detail or "fetch failed"
        if result.status == "partial":
            detail = (f"partial: {len(result.products)} products fetched but "
                      f"discarded — {detail}")
        with db.connect() as conn:
            db.record_sync(conn, cfg["key"], False, detail, 0)
        return {"store": cfg["key"], "ok": False, "status": result.status,
                "message": detail, "listings": 0, "took_s": took}

    rows, cards = _listing_rows(cfg, result.products)
    with db.connect() as conn:
        db.replace_store_listings(conn, cfg["key"], rows)
        db.upsert_cards(conn, cards)
        db.record_sync(conn, cfg["key"], True, "ok", len(rows))
    return {"store": cfg["key"], "ok": True, "status": "ok", "message": "ok",
            "listings": len(rows), "took_s": took}


async def _sync_stores(cfgs: list[dict]) -> list[dict]:
    async with make_client() as client:
        if not SEQUENTIAL_SYNC:
            return list(await asyncio.gather(
                *(_sync_store(cfg, client) for cfg in cfgs)))
        # One store at a time, with a pause between. Parallel is harmless
        # residentially — five different hosts, one request each in flight —
        # but from a datacenter IP it reads as a burst and gets throttled.
        results = []
        for i, cfg in enumerate(cfgs):
            if i:
                await asyncio.sleep(STORE_DELAY_S)
            results.append(await _sync_store(cfg, client))
        return results


def stale_stores(force: bool = False) -> list[dict]:
    if SNAPSHOT_MODE:
        return []
    if force:
        return list(STORES)
    with db.connect() as conn:
        ages = db.sync_ages(conn)
    out = []
    for cfg in STORES:
        meta = ages.get(cfg["key"])
        # TTL applies to failures too. Retrying a failed store on every
        # search — which is what excluding it from the TTL used to do —
        # means the stores most likely to be throttling us are the ones we
        # hit hardest. The breaker still backs off on top of this.
        if (meta is None or meta["age_s"] is None
                or meta["age_s"] > TTL_SECONDS):
            out.append(cfg)
    return out


def running() -> bool:
    return _SYNC_RUNNING.is_set()


def start_background(force: bool = False) -> bool:
    """Run a sync in a daemon thread. False if one is already in flight.

    A polite sequential sync takes minutes, which outruns both gunicorn's
    worker timeout and any proxy in front of it — a synchronous /api/refresh
    would be killed mid-crawl and report a store failure that never happened.
    """
    if running():
        return False

    def _run():
        try:
            ensure_fresh(force=force)
        except Exception:  # noqa: BLE001 — nothing upstream to catch this
            log.exception("background sync failed")

    threading.Thread(target=_run, daemon=True).start()
    return True


def ensure_fresh(force: bool = False) -> dict:
    """Sync whatever is stale (or everything, if force). Blocking; safe to
    call from a Flask request. Returns a per-store summary."""
    if SNAPSHOT_MODE:
        return {"synced": [], "fresh": True, "mode": "snapshot"}
    with _SYNC_LOCK:
        cfgs = stale_stores(force)   # re-check inside the lock: the search
        if not cfgs:                 # that queued behind a sync is now fresh
            return {"synced": [], "fresh": True}
        _SYNC_RUNNING.set()
        try:
            results = asyncio.run(_sync_stores(cfgs))
        finally:
            _SYNC_RUNNING.clear()
        # (_sync_store records every outcome itself, successes and failures
        # alike, so the failure path no longer needs recording again here.)
        if any(r["ok"] for r in results):
            _spawn_watchlist_check()
        return {"synced": results, "fresh": False}


def _spawn_watchlist_check() -> None:
    """PRD §3: watchlist checked on every sync (email fires in background,
    never blocking a search response)."""
    def _run():
        import check_watchlist  # local import — avoids cycle at module load
        try:
            check_watchlist.run()
        except Exception:  # noqa: BLE001
            log.exception("post-sync watchlist check failed")
    threading.Thread(target=_run, daemon=True).start()
