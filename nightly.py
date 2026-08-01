"""nightly.py — heartbeat (equivalent of 3vor Fetch's run_nightly.sh body).

One forced sync purely for history continuity (≥1 datapoint/day for every
card at every store) + watchlist check + weekly dormant-store poll.
Invoked by run_nightly.sh via launchd/cron; safe to run by hand.
"""
from __future__ import annotations

import logging

import check_watchlist
import db
import dormant_poll
import sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s: %(message)s",
)
log = logging.getLogger("riftvor.nightly")


def main() -> None:
    db.init_db()
    result = sync.ensure_fresh(force=True)
    for r in result.get("synced", []):
        log.info("sync %s: ok=%s listings=%s (%ss)",
                 r["store"], r["ok"], r["listings"], r["took_s"])
    sent = check_watchlist.run()
    log.info("watchlist: %d alert(s) emailed", sent)
    if dormant_poll.due():
        notices = dormant_poll.poll()
        log.info("dormant poll: %d notice(s)", len(notices))
    else:
        log.info("dormant poll: not due this week")


if __name__ == "__main__":
    main()
