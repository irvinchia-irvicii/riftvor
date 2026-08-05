"""Privacy thresholds and retailer approval waitlist."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402
import market_insights  # noqa: E402


def _user(conn, number, consent=True):
    return conn.execute(
        """INSERT INTO users
           (email, password_hash, tier, created_at, analytics_consent)
           VALUES (?, 'hash', 'member', ?, ?)""",
        (f"user{number}@example.com", time.time(), int(consent)),
    ).lastrowid


def test_weekly_pulse_suppresses_small_groups(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "insights.db")
    db.init_db()
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO cards (card_key, set_code, number, name)
               VALUES ('OGN-043', 'OGN', '043', 'Charm')"""
        )
        users = [_user(conn, i) for i in range(3)]
    for user_id in users:
        assert market_insights.record(user_id, "search", [{
            "card_key": "OGN-043", "finish": "nonfoil", "qty": 1,
        }]) == 1
    with db.connect() as conn:
        assert conn.execute(
            "SELECT created_at FROM analytics_events LIMIT 1"
        ).fetchone()["created_at"] % 86400 == 0

    hidden = market_insights.weekly_pulse(min_contributors=4)
    assert hidden["status"] == "sample_too_small"
    assert hidden["signals"] == []
    visible = market_insights.weekly_pulse(min_contributors=3)
    assert visible["status"] == "ready"
    assert visible["signals"][0]["name"] == "Charm"
    assert visible["signals"][0]["contributors"] == 3


def test_retailer_signup_is_waitlist_not_billing(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "retailers.db")
    db.init_db()
    subscriber, error = market_insights.subscribe_retailer(
        "shop@example.com", "Example Cards", True
    )
    assert error is None
    assert subscriber["status"] == "approval_waitlist"
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM retailer_subscriptions").fetchone()
    assert row["plan"] == "preview"
    assert row["status"] == "approval_waitlist"
    assert row["unsubscribe_token"]
    assert market_insights.unsubscribe_retailer(row["unsubscribe_token"]) is True
    assert market_insights.retailer_for_token(row["unsubscribe_token"])["status"] == "unsubscribed"
