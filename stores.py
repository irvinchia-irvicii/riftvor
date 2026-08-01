"""stores.py — Shopify catalog fetchers with politeness + circuit breaker.

One generic ShopifyCatalogStore + per-store config (config.STORES).
Politeness (§10): parallel ACROSS stores, sequential-with-delay (≥500 ms)
between pages WITHIN a store; timeout 15 s; 2 retries; per-store breaker
(3 consecutive failures → 10 min cooldown — semantics ported from 3vor
Fetch's playwright_scraper.py).

If a store's products.json starts getting challenged (Hideout sits behind
BinderPOS/Cloudflare), we retry via curl_cffi Chrome impersonation before
declaring the store down.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time

import httpx

from config import (BREAKER_COOLDOWN_S, BREAKER_THRESHOLD, PAGE_DELAY_S,
                    RETRIES, TIMEOUT_S, USER_AGENT)

log = logging.getLogger("riftvor.stores")


class CircuitBreaker:
    """3 consecutive failures → bench the store for 10 minutes."""

    def __init__(self, name: str):
        self.name = name
        self.failures = 0
        self.benched_until = 0.0

    def allow(self) -> bool:
        return time.time() >= self.benched_until

    def record_success(self) -> None:
        self.failures = 0

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= BREAKER_THRESHOLD:
            self.benched_until = time.time() + BREAKER_COOLDOWN_S
            self.failures = 0
            log.warning("breaker OPEN for %s — cooling down %ds",
                        self.name, BREAKER_COOLDOWN_S)


_BREAKERS: dict[str, CircuitBreaker] = {}


def breaker_for(key: str) -> CircuitBreaker:
    if key not in _BREAKERS:
        _BREAKERS[key] = CircuitBreaker(key)
    return _BREAKERS[key]


def _curl_cffi_get_json(url: str) -> dict | None:
    """Blocking Chrome-impersonated fallback for challenged endpoints."""
    try:
        from curl_cffi import requests as cffi_requests
        resp = cffi_requests.get(url, impersonate="chrome",
                                 timeout=TIMEOUT_S)
        if resp.status_code == 200:
            return resp.json()
        log.warning("curl_cffi fallback for %s → HTTP %s", url,
                    resp.status_code)
    except Exception as exc:  # noqa: BLE001 — fallback of a fallback
        log.warning("curl_cffi fallback for %s failed: %s", url, exc)
    return None


class ShopifyCatalogStore:
    """Pull a store's full Riftbound singles catalog via products.json."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.key = cfg["key"]
        self.base = cfg["base"].rstrip("/")
        self.breaker = breaker_for(self.key)

    async def _get_json(self, client: httpx.AsyncClient, url: str) -> dict | None:
        last_exc: Exception | None = None
        for attempt in range(RETRIES + 1):
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code in (403, 429, 503):
                    # Challenged — try Chrome impersonation before giving up.
                    log.info("%s → HTTP %s, trying curl_cffi", url,
                             resp.status_code)
                    data = await asyncio.to_thread(_curl_cffi_get_json, url)
                    if data is not None:
                        return data
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                last_exc = exc
            if attempt < RETRIES:
                await asyncio.sleep(1.0 + attempt)
        log.warning("%s: giving up on %s (%s)", self.key, url, last_exc)
        return None

    async def discover_handles(self, client: httpx.AsyncClient) -> list[str]:
        """Find singles collections via /collections.json (handles WILL
        change as sets release); fall back to the configured list."""
        disc = self.cfg.get("discover")
        fallback = list(self.cfg.get("handles", []))
        if not disc:
            return fallback
        data = await self._get_json(
            client, f"{self.base}/collections.json?limit=250")
        if not data or "collections" not in data:
            log.info("%s: handle discovery failed, using configured handles",
                     self.key)
            return fallback
        include = re.compile(disc["regex"], re.I)
        exclude = re.compile(disc["exclude_regex"], re.I) if disc.get(
            "exclude_regex") else None
        must = disc.get("title_must_contain")
        handles = []
        for coll in data["collections"]:
            handle, title = coll.get("handle", ""), coll.get("title", "")
            if not include.search(handle):
                continue
            if exclude and (exclude.search(handle) or exclude.search(title.lower())):
                continue
            if must and must not in title:
                continue
            handles.append(handle)
        return handles or fallback

    async def fetch_catalog(self, client: httpx.AsyncClient) -> list[dict] | None:
        """Full catalog: every product across the store's singles
        collections, deduped by product id (Tefuda's `-copy` collections
        repeat products). Returns None on hard failure (breaker counts it)."""
        if not self.breaker.allow():
            log.info("%s: breaker open, skipping sync", self.key)
            return None
        handles = await self.discover_handles(client)
        products: dict[int, dict] = {}
        got_any_page = False
        for handle in handles:
            page = 1
            while True:
                url = (f"{self.base}/collections/{handle}/products.json"
                       f"?limit=250&page={page}")
                data = await self._get_json(client, url)
                if data is None:
                    break
                got_any_page = True
                batch = data.get("products", [])
                if not batch:
                    break
                for p in batch:
                    p["_handle"] = handle
                    products[p["id"]] = p
                if len(batch) < 250:
                    break
                page += 1
                await asyncio.sleep(PAGE_DELAY_S)
            await asyncio.sleep(PAGE_DELAY_S)
        if not got_any_page:
            self.breaker.record_failure()
            return None
        self.breaker.record_success()
        return list(products.values())


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_S,
        follow_redirects=True,
    )
