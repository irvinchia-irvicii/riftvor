"""dormant_poll.py — weekly poll of dormant SG stores (§5).

1Collectibles, Cardboard Collectible and Sentinel Games are Shopify shops
with no Riftbound singles online today (sealed only, or nothing). Weekly,
hit their /search/suggest.json for 'riftbound' products; if a result with a
singles-like handle appears (not sealed/accessory), record a
"new store selling singles?" notice that the UI surfaces as a banner.

Runs from run_nightly.sh once per ISO week (state/dormant_last_poll).
"""
from __future__ import annotations

import json
import logging
import time

import httpx

import db
from config import DORMANT_STORES, STATE_DIR, TIMEOUT_S, USER_AGENT
from filters import is_dropped
from parsers import BRACKET_RE, PAREN_RE


def _singles_like(title: str, handle: str) -> bool:
    """A single carries a collector number in its title, or says 'single'.
    'Riftbound Set 3 Booster Box' / 'Showdown Deck' must NOT trip this."""
    if is_dropped(title, handle, []):
        return False
    if BRACKET_RE.search(title) or PAREN_RE.search(title):
        return True
    return "single" in (title + " " + handle).lower()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dormant_poll")

_STAMP = STATE_DIR / "dormant_last_poll"


def due(now: float | None = None) -> bool:
    now = now or time.time()
    try:
        last = float(_STAMP.read_text().strip())
    except (FileNotFoundError, ValueError):
        return True
    return (now - last) >= 6.5 * 86400


def poll() -> list[dict]:
    notices = []
    with httpx.Client(headers={"User-Agent": USER_AGENT},
                      timeout=TIMEOUT_S, follow_redirects=True) as client:
        for store in DORMANT_STORES:
            url = (f"{store['base']}/search/suggest.json"
                   f"?q=riftbound&resources[type]=product")
            try:
                resp = client.get(url)
                resp.raise_for_status()
                products = (resp.json().get("resources", {})
                            .get("results", {}).get("products", []))
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                log.warning("%s: poll failed: %s", store["name"], exc)
                continue
            singles = [
                p for p in products
                if "riftbound" in (p.get("title", "") + p.get("handle", "")).lower()
                and _singles_like(p.get("title", ""), p.get("handle", ""))
            ]
            if singles:
                titles = "; ".join(p["title"] for p in singles[:3])
                log.info("%s: singles-like products found: %s",
                         store["name"], titles)
                notices.append({"store": store["name"], "detail": titles})
            else:
                log.info("%s: nothing singles-like (%d products)",
                         store["name"], len(products))
    with db.connect() as conn:
        conn.execute("DELETE FROM dormant_notices")
        conn.executemany(
            """INSERT INTO dormant_notices (store, detail, noticed_at)
               VALUES (?, ?, ?)""",
            [(n["store"], n["detail"], time.time()) for n in notices])
    _STAMP.write_text(str(time.time()))
    return notices


if __name__ == "__main__":
    db.init_db()
    if due():
        poll()
    else:
        log.info("polled within the last week — skipping (delete "
                 "state/dormant_last_poll to force)")
