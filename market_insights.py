"""Consent-gated, privacy-preserving community market signals."""
from __future__ import annotations

import time
import secrets
from datetime import datetime, timedelta, timezone

import config
import db

ALLOWED_EVENTS = {"search", "collection_add"}


def record(user_id: int | None, event_type: str, items: list[dict]) -> int:
    """Keep only coarse card activity needed for aggregate market research."""
    if not user_id or event_type not in ALLOWED_EVENTS:
        return 0
    now = time.time()
    event_date = datetime.fromtimestamp(now, timezone.utc).date()
    day = event_date.isoformat()
    # Coarsen the stored timestamp to midnight UTC; exact activity time is
    # intentionally not retained in the research dataset.
    coarse_time = datetime.combine(
        event_date, datetime.min.time(), tzinfo=timezone.utc
    ).timestamp()
    rows = []
    for item in items:
        key = str(item.get("card_key") or "").strip().upper()
        if not key:
            continue
        finish = item.get("finish") if item.get("finish") in ("foil", "nonfoil") else "nonfoil"
        try:
            quantity = min(max(int(item.get("qty", 1)), 1), 100)
        except (TypeError, ValueError):
            quantity = 1
        rows.append((user_id, event_type, key, finish, quantity, day, coarse_time))
    if not rows:
        return 0
    with db.connect() as conn:
        consent = conn.execute(
            "SELECT analytics_consent FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not consent or not consent["analytics_consent"]:
            return 0
        conn.executemany(
            """INSERT INTO analytics_events
               (user_id, event_type, card_key, finish, quantity, event_day, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""", rows,
        )
    return len(rows)


def weekly_pulse(days: int = 7, min_contributors: int | None = None) -> dict:
    """Return only aggregates meeting a distinct-contributor privacy floor."""
    floor = max(2, min_contributors or config.ANALYTICS_MIN_CONTRIBUTORS)
    since = (datetime.now(timezone.utc).date() - timedelta(days=days - 1)).isoformat()
    with db.connect() as conn:
        contributors = conn.execute(
            """SELECT COUNT(DISTINCT user_id) FROM analytics_events
               WHERE event_day >= ?""", (since,)
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT e.event_type, e.card_key, e.finish,
                      COALESCE(c.name, e.card_key) AS name,
                      COUNT(DISTINCT e.user_id) AS contributors,
                      COUNT(*) AS actions, SUM(e.quantity) AS quantity
               FROM analytics_events e LEFT JOIN cards c USING (card_key)
               WHERE e.event_day >= ?
               GROUP BY e.event_type, e.card_key, e.finish
               HAVING COUNT(DISTINCT e.user_id) >= ?
               ORDER BY contributors DESC, actions DESC, e.card_key
               LIMIT 20""", (since, floor)
        ).fetchall()
    return {
        "period_days": days,
        "minimum_contributors": floor,
        "contributing_users": contributors,
        "status": "ready" if rows else "sample_too_small",
        "signals": [dict(row) for row in rows],
        "methodology": (
            "Only opted-in activity is counted. Results require the displayed "
            "number of distinct contributors; suppressed rows are never returned. "
            "Collection additions and searches are interest signals, not verified sales."
        ),
    }


def subscribe_retailer(email: str, shop_name: str, accepted: bool) -> tuple[dict | None, str | None]:
    import accounts  # avoids duplicating the email validator

    email = (email or "").strip().lower()
    shop_name = " ".join((shop_name or "").strip().split())
    if not accounts.EMAIL_RE.match(email) or len(email) > 254:
        return None, "Enter a valid business email address."
    if len(shop_name) < 2 or len(shop_name) > 100:
        return None, "Enter a shop name between 2 and 100 characters."
    if accepted is not True:
        return None, "Please agree to receive the retailer preview newsletter."
    now = time.time()
    token = secrets.token_urlsafe(32)
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO retailer_subscriptions
               (email, shop_name, plan, status, consent_version, consented_at,
                created_at, unsubscribe_token)
               VALUES (?, ?, 'preview', 'approval_waitlist', ?, ?, ?, ?)
               ON CONFLICT(email) DO UPDATE SET
                 shop_name=excluded.shop_name, status='approval_waitlist',
                 consent_version=excluded.consent_version,
                 consented_at=excluded.consented_at,
                 unsubscribe_token=COALESCE(
                   retailer_subscriptions.unsubscribe_token,
                   excluded.unsubscribe_token)""",
            (email, shop_name, config.CONSENT_VERSION, now, now, token),
        )
    return {"email": email, "shop_name": shop_name,
            "status": "approval_waitlist"}, None


def retailer_for_token(token: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute(
            """SELECT email, shop_name, status FROM retailer_subscriptions
               WHERE unsubscribe_token = ?""", (token,),
        ).fetchone()
    return dict(row) if row else None


def unsubscribe_retailer(token: str) -> bool:
    with db.connect() as conn:
        changed = conn.execute(
            """UPDATE retailer_subscriptions SET status = 'unsubscribed'
               WHERE unsubscribe_token = ?""", (token,),
        ).rowcount
    return bool(changed)
