"""cards_central.py — Cards Central integration (§5, scrape path).

Gate result (1 Aug 2026): their /api/lgs/search aggregator feed is
MTG-filtered (Riftbound queries return []), so we scrape the
server-rendered search page instead: /search?brand=riftbound&q=<name>.

Cards Central is per-query by design → called live per buy-list card
(async, parallel, small concurrency), results skip the TTL cache and are
never written to listings; they're attached to the comparison response at
request time. History is not recorded for this store.

Each result anchor in the HTML carries everything we need:
    <a ... title="Yasuo, Windrider" href="/card/yasuo-windrider-ogn-205">
      ... title="OGN-205a/298" ...          ← full collector key
      <span class="truncate">Foil</span> ... S$8.50 ... 1 in stock
"""
from __future__ import annotations

import asyncio
import logging
import re

import httpx

import stores
from config import CARDS_CENTRAL, TIMEOUT_S, USER_AGENT
from stores import breaker_for

log = logging.getLogger("riftvor.cardscentral")

STORE_KEY = CARDS_CENTRAL["key"]
_BASE = CARDS_CENTRAL["base"]

# One <a ...>...</a> per card result.
_ANCHOR_RE = re.compile(
    r'<a[^>]+title="(?P<name>[^"]+)"[^>]+href="(?P<href>/card/[^"]+)".*?</a>',
    re.S)
_KEY_RE = re.compile(r'title="(?P<set>[A-Z]{2,4})-(?P<num>\d{1,3})'
                     r'(?P<letter>[a-z])?/\d+"')
_PRICE_ROW_RE = re.compile(
    r'<span class="truncate">(?P<finish>Normal|Foil)</span>.*?'
    r'S\$(?P<price>[\d,.]+)</span>.*?(?P<stock>\d+)(?:<!-- -->)?\s*in stock',
    re.S)

_CONCURRENCY = 4


def parse_search_html(html: str) -> list[dict]:
    """Search-results HTML → [{name, url, card_key, finishes:{finish: {...}}}]"""
    out = []
    for m in _ANCHOR_RE.finditer(html):
        block = m.group(0)
        km = _KEY_RE.search(block)
        if not km:
            continue
        card_key = (f"{km.group('set').upper()}-"
                    f"{int(km.group('num')):03d}{km.group('letter') or ''}")
        finishes: dict[str, dict] = {}
        for pm in _PRICE_ROW_RE.finditer(block):
            finish = "foil" if pm.group("finish") == "Foil" else "nonfoil"
            price = float(pm.group("price").replace(",", ""))
            stock = int(pm.group("stock"))
            cell = {"price": price, "in_stock": stock > 0,
                    "url": _BASE + m.group("href"),
                    "condition": "Near Mint",
                    "title": m.group("name")}
            cur = finishes.get(finish)
            if cur is None or price < cur["price"]:
                finishes[finish] = cell
        if finishes:
            out.append({"name": m.group("name"), "card_key": card_key,
                        "finishes": finishes})
    return out


async def _search_one(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                      query: str) -> list[dict]:
    async with sem:
        try:
            resp = await client.get(
                f"{_BASE}/search", params={"brand": "riftbound", "q": query})
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            breaker_for(STORE_KEY).record_success()
            return parse_search_html(resp.text)
        except Exception as exc:  # noqa: BLE001 — best-effort store
            breaker_for(STORE_KEY).record_failure()
            log.warning("cards central search %r failed: %s", query, exc)
            return []


async def _lookup_async(cards: list[dict]) -> dict[str, dict]:
    """cards: [{card_key, name}] → {card_key: {finish: cell}}.
    One query per distinct card NAME (a name query returns every printing,
    so alt-arts ride along free), matched back by exact collector key."""
    if not breaker_for(STORE_KEY).allow():
        log.info("cards central breaker open, skipping")
        return {}
    names = sorted({c["name"] for c in cards if c.get("name")})
    if not names:
        return {}
    sem = asyncio.Semaphore(_CONCURRENCY)
    # stores.make_client so the egress proxy applies here too — Cards Central
    # is scraped from the same IP and refused for the same reason.
    async with stores.make_client() as client:
        batches = await asyncio.gather(
            *(_search_one(client, sem, name) for name in names))
    wanted = {c["card_key"] for c in cards}
    out: dict[str, dict] = {}
    for batch in batches:
        for hit in batch:
            if hit["card_key"] not in wanted:
                continue
            slot = out.setdefault(hit["card_key"], {})
            for finish, cell in hit["finishes"].items():
                cur = slot.get(finish)
                if cur is None or cell["price"] < cur["price"]:
                    slot[finish] = cell
    return out


def lookup(cards: list[dict]) -> dict[str, dict]:
    """Blocking wrapper for Flask. cards: [{card_key, name}]."""
    try:
        return asyncio.run(_lookup_async(cards))
    except Exception:  # noqa: BLE001
        log.exception("cards central lookup crashed")
        return {}
