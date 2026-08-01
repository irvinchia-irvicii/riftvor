"""check_watchlist.py — price-watch alerts (semantics ported from 3vor
Fetch). Runs the watchlist against current listings and emails when a
card's best in-stock price dips to/under its target.

Alert hygiene lives in watchlist.check(): one email per dip — a card
sitting at SGD 8 under a SGD 10 target alerts once, then stays quiet
unless it drops further or bounces back above target first (which
re-arms it). If email credentials are missing or sending fails, hits are
still logged and the alert state is NOT updated, so the alert fires again
once email works.

Called from run_nightly.sh (after the heartbeat sync) and after every
live sync via sync-triggered checks. Can also be run standalone:
    venv/bin/python check_watchlist.py
Exit codes: 0 = ran fine (alerts or not), 1 = could not run.
"""
from __future__ import annotations

import logging
import sys

import db
import emailer
import watchlist
from config import STORE_BY_KEY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("check_watchlist")


def run() -> int:
    """Check + email. Returns the number of alerts sent."""
    with db.connect() as conn:
        hits = watchlist.check(conn)
    if not hits:
        log.info("watchlist: no triggers")
        return 0
    sent = 0
    for hit in hits:
        store_name = STORE_BY_KEY.get(hit["store"], {}).get(
            "name", hit["store"])
        subject = (f"Riftvor alert: {hit['card_key']} ({hit['finish']}) "
                   f"S${hit['price']:.2f} ≤ S${hit['target_price']:.2f}")
        body = (f"{hit['card_key']} ({hit['finish']}) is at "
                f"S${hit['price']:.2f} at {store_name} — target was "
                f"S${hit['target_price']:.2f}.\n\n"
                f"http://127.0.0.1:5009/\n")
        log.info("TRIGGER %s", subject)
        if emailer.send(subject, body):
            watchlist.mark_alerted(hit["card_key"], hit["finish"],
                                   hit["price"])
            sent += 1
        else:
            log.warning("email failed — alert state left armed, will "
                        "re-fire next run")
    return sent


if __name__ == "__main__":
    try:
        db.init_db()
        run()
        sys.exit(0)
    except Exception:  # noqa: BLE001
        log.exception("watchlist check could not run")
        sys.exit(1)
