"""carousell.py — best-effort P2P panel (§5).

carousell.sg's Riftbound category page is server-rendered with the search
state embedded as JSON (a script node consumed by
`JSON.parse(document.currentScript.previousSibling.textContent)`).
A plain fetch is 403'd (checked 1 Aug 2026) but curl_cffi Chrome
impersonation gets through — Playwright stays unused.

Freeform titles, no collector numbers → fuzzy name matching only,
aggressive noise filters (lots/bundles/WTB/sealed), rendered as a separate
"P2P listings" panel — never merged into the store comparison rows.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time

from config import CAROUSELL_URL, TTL_SECONDS
from filters import _name_matches

log = logging.getLogger("riftvor.carousell")

_LISTING_URL = "https://www.carousell.sg/p/{id}"

# WTB/trades, lots/bundles, and sealed product never belong in the panel.
_NOISE_RE = re.compile(
    r"\bwtb\b|\bwant to buy\b|\bbuying\b|\bwtt\b|\btrade\b|"
    r"\blot\b|\blots\b|\bbulk\b|\bbundle\b|\bplayset\b|\bcollection\b|"
    r"\bbooster\b|\bbox\b|\bdisplay\b|\bsealed\b|\bpack\b|\bcase\b|"
    r"\bchampion deck\b|\bstarter\b|\bprerelease\b",
    re.I)

_cache: dict = {"at": 0.0, "listings": []}
_lock = threading.Lock()


def _fetch_html() -> str | None:
    try:
        from curl_cffi import requests as cffi_requests
        resp = cffi_requests.get(CAROUSELL_URL, impersonate="chrome",
                                 timeout=20)
        if resp.status_code == 200:
            return resp.text
        log.warning("carousell → HTTP %s", resp.status_code)
    except Exception as exc:  # noqa: BLE001 — best-effort panel
        log.warning("carousell fetch failed: %s", exc)
    return None


def parse_listings(html: str) -> list[dict]:
    i = html.find("window.initialState")
    if i == -1:
        return []
    prev_end = html.rfind("</script>", 0, i)
    prev_start = html.rfind(">", 0, prev_end) + 1
    try:
        data = json.loads(html[prev_start:prev_end])
        cards = data["SearchListing"]["listingCards"]
    except (json.JSONDecodeError, KeyError, TypeError):
        log.warning("carousell page structure changed — no listingCards")
        return []
    out = []
    for card in cards:
        title = price = condition = None
        for comp in card.get("belowFold", []):
            if comp.get("component") == "header_1":
                title = comp.get("stringContent")
            elif comp.get("component") == "header_2":
                m = re.search(r"S\$\s*([\d,.]+)", comp.get("stringContent", ""))
                price = float(m.group(1).replace(",", "")) if m else None
            elif comp.get("component") == "paragraph" and not condition:
                condition = comp.get("stringContent") or None
        if not title or price is None:
            continue
        out.append({
            "title": title.strip(),
            "price": price,
            "url": _LISTING_URL.format(id=card.get("listingID", "")),
            "condition": condition,
        })
    return out


def all_listings(max_age_s: int = TTL_SECONDS) -> list[dict]:
    """Category page pull, module-cached for the TTL window."""
    with _lock:
        if time.time() - _cache["at"] < max_age_s and _cache["listings"]:
            return _cache["listings"]
        html = _fetch_html()
        if html:
            listings = [l for l in parse_listings(html)
                        if not _NOISE_RE.search(l["title"])]
            _cache.update(at=time.time(), listings=listings)
        return _cache["listings"]


def _match_terms(name: str) -> list[str]:
    """Card names are 'Renekton, Crocodile of the Sands' / 'Yasuo -
    Unforgiven'; P2P titles usually just say 'Renekton'. Try the full name
    first, then the part before the comma/dash (champion name) when it's
    distinctive enough."""
    terms = [name]
    head = re.split(r"\s*[,–—-]\s+", name)[0].strip()
    if len(head) >= 4 and head.lower() != name.lower():
        terms.append(head)
    return terms


def panel_for(names: list[str]) -> list[dict]:
    """Fuzzy-match P2P listings against the buy-list card names."""
    names = [n for n in names if n]
    if not names:
        return []
    hits = []
    for listing in all_listings():
        for name in names:
            if any(_name_matches(t, listing["title"])
                   for t in _match_terms(name)):
                hits.append({**listing, "matched": name})
                break
    hits.sort(key=lambda h: h["price"])
    return hits
