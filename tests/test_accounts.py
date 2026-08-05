"""Account sessions, freemium gates, and collection ownership."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module  # noqa: E402
import accounts  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "accounts.db")
    db.init_db()
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO cards (card_key, set_code, number, name, rarity)
               VALUES ('OGN-043', 'OGN', '043', 'Charm', 'Common')"""
        )
    app_module.app.config.update(TESTING=True, SECRET_KEY="account-test-secret")
    return app_module.app.test_client()


def signup(client, email="player@example.com", analytics_consent=False):
    return client.post("/api/auth/signup", json={
        "email": email,
        "password": "eightchars",
        "accept_terms": True,
        "analytics_consent": analytics_consent,
    })


def test_signup_session_and_logout(client):
    assert client.get("/api/auth/me").json["authenticated"] is False
    response = signup(client)
    assert response.status_code == 201
    assert response.json["account"]["tier"] == "member"
    assert client.get("/api/auth/me").json["authenticated"] is True
    assert client.get("/api/collection").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/collection").status_code == 401
    assert client.get("/collection").status_code == 302


def test_riot_verification_file_stays_public_behind_review_password(
        client, monkeypatch):
    monkeypatch.setattr(config, "AUTH_PASSWORD_HASH", "")
    monkeypatch.setattr(config, "AUTH_PASSWORD", "review-secret")
    assert client.get("/").status_code == 401
    response = client.get("/riot.txt")
    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    assert response.get_data(as_text=True).strip() == (
        "06e8fc0e-b6a8-4bab-af84-3c4f2c087bcf"
    )


def test_review_gate_accepts_hashed_password(client, monkeypatch):
    from werkzeug.security import generate_password_hash

    monkeypatch.setattr(config, "AUTH_USER", "riotgames")
    monkeypatch.setattr(config, "AUTH_PASSWORD", "ignored-old-password")
    monkeypatch.setattr(
        config, "AUTH_PASSWORD_HASH", generate_password_hash("sorakareview"),
    )
    wrong = client.get("/", headers={
        "Authorization": "Basic cmlvdGdhbWVzOndyb25n",
    })
    assert wrong.status_code == 401
    correct = client.get("/", headers={
        "Authorization": "Basic cmlvdGdhbWVzOnNvcmFrYXJldmlldw==",
    })
    assert correct.status_code == 200


def test_password_and_duplicate_email_validation(client):
    short = client.post("/api/auth/signup", json={
        "email": "player@example.com", "password": "short", "accept_terms": True,
    })
    assert short.status_code == 400
    assert signup(client).status_code == 201
    client.post("/api/auth/logout")
    assert signup(client).status_code == 400


def test_username_account_can_sign_in_for_multicard_search(client, monkeypatch):
    created = signup(client, "riotgames")
    assert created.status_code == 201
    assert created.json["account"]["email"] == "riotgames"
    client.post("/api/auth/logout")
    signed_in = client.post("/api/auth/login", json={
        "email": "riotgames", "password": "eightchars",
    })
    assert signed_in.status_code == 200
    assert signed_in.json["account"]["entitlements"]["multi_card_search"] is True

    monkeypatch.setattr(app_module, "_full_comparison", lambda *args, **kwargs: (
        {"rows": [], "unmatched": [], "store_order": [], "basket": {},
         "carousell": []}, {"synced": []}))
    searched = client.post("/api/search", json={
        "list_text": "OGN-043\nUNL-053",
    })
    assert searched.status_code == 200


def test_internal_review_account_is_provisioned_without_fake_consent(
        client, monkeypatch):
    from werkzeug.security import generate_password_hash

    monkeypatch.setattr(config, "REVIEW_ACCOUNT_USERNAME", "riotgames")
    monkeypatch.setattr(
        config, "REVIEW_ACCOUNT_PASSWORD_HASH",
        generate_password_hash("sorakareview"),
    )
    assert accounts.ensure_review_account() is True
    assert accounts.ensure_review_account() is False

    signed_in = client.post("/api/auth/login", json={
        "email": "riotgames", "password": "sorakareview",
    })
    assert signed_in.status_code == 200
    assert signed_in.json["account"]["entitlements"]["multi_card_search"] is True
    assert signed_in.json["account"]["entitlements"]["portfolio_analytics"] is True
    assert client.get("/portfolio").status_code == 200
    with db.connect() as conn:
        reviewer = conn.execute(
            """SELECT tier, terms_version, analytics_consent FROM users
               WHERE email = 'riotgames'"""
        ).fetchone()
        assert reviewer["tier"] == "founder"
        assert reviewer["terms_version"] is None
        assert reviewer["analytics_consent"] == 0
        consent_rows = conn.execute(
            """SELECT COUNT(*) FROM privacy_consents p JOIN users u
               ON p.user_id = u.id WHERE u.email = 'riotgames'"""
        ).fetchone()[0]
        assert consent_rows == 0


def test_pulse_is_public_and_collection_links_to_it(client):
    pulse = client.get("/pulse")
    assert pulse.status_code == 200
    assert b"Riftbound Pulse" in pulse.data
    assert b"Awaiting approved sources" in pulse.data

    signup(client)
    collection_page = client.get("/collection")
    assert collection_page.status_code == 200
    assert b'href="/pulse"' in collection_page.data


def test_founder_collection_header_links_directly_to_portfolio(client):
    signup(client)
    with db.connect() as conn:
        conn.execute("UPDATE users SET tier = 'founder'")
    collection_page = client.get("/collection")
    assert b'href="/portfolio"' in collection_page.data


def test_signup_requires_terms_and_keeps_analytics_optional(client):
    refused = client.post("/api/auth/signup", json={
        "email": "private@example.com", "password": "eightchars",
        "accept_terms": False,
    })
    assert refused.status_code == 400
    joined = signup(client, "private@example.com")
    assert joined.status_code == 201
    assert joined.json["account"]["privacy"]["analytics_consent"] is False


def test_analytics_consent_records_sparse_events_and_withdrawal_deletes(client):
    signup(client, analytics_consent=True)
    user_id = client.get("/api/auth/me").json["account"]["id"]
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO analytics_events
               (user_id, event_type, card_key, finish, quantity, event_day, created_at)
               VALUES (?, 'search', 'OGN-043', 'nonfoil', 1, '2026-08-05', ?)""",
            (user_id, time.time()),
        )
    response = client.patch("/api/account/privacy", json={
        "analytics_consent": False,
    })
    assert response.status_code == 200
    assert response.json["privacy"]["events_removed"] == 1
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM analytics_events").fetchone()[0] == 0
        latest = conn.execute(
            """SELECT granted FROM privacy_consents
               WHERE user_id = ? AND purpose = 'community_analytics'
               ORDER BY id DESC LIMIT 1""", (user_id,),
        ).fetchone()
        assert latest["granted"] == 0


def test_anonymous_multi_card_search_is_gated_before_sync(client, monkeypatch):
    called = False

    def fake_comparison(*args, **kwargs):
        nonlocal called
        called = True
        return ({"rows": [], "unmatched": [], "store_order": [],
                 "basket": {}, "carousell": []}, {"synced": []})

    monkeypatch.setattr(app_module, "_full_comparison", fake_comparison)
    response = client.post("/api/search", json={
        "list_text": "OGN-043\nUNL-053",
    })
    assert response.status_code == 403
    assert response.json["code"] == "account_required"
    assert called is False


def test_one_card_is_public_and_multi_card_works_after_signup(client, monkeypatch):
    def fake_comparison(*args, **kwargs):
        return ({"rows": [], "unmatched": [], "store_order": [],
                 "basket": {}, "carousell": []}, {"synced": []})

    monkeypatch.setattr(app_module, "_full_comparison", fake_comparison)
    assert client.post("/api/search", json={"list_text": "OGN-043"}).status_code == 200
    signup(client)
    assert client.post("/api/search", json={
        "list_text": "OGN-043\nUNL-053",
    }).status_code == 200


def test_manual_inventory_is_private(client):
    signup(client, "first@example.com")
    added = client.post("/api/collection/manual", json={
        "card_query": "OGN-043",
        "finish": "nonfoil",
        "qty": 3,
        "unit_paid": 0.75,
        "store": "Trade",
        "acquired_at": time.time(),
    })
    assert added.status_code == 200
    first_items = client.get("/api/collection").json["items"]
    assert len(first_items) == 1
    first_id = first_items[0]["id"]

    client.post("/api/auth/logout")
    signup(client, "second@example.com")
    assert client.get("/api/collection").json["items"] == []
    assert client.delete(f"/api/collection/{first_id}").status_code == 200

    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={
        "email": "first@example.com", "password": "eightchars",
    })
    assert len(client.get("/api/collection").json["items"]) == 1


def test_portfolio_is_gated_then_uses_observed_shop_prices(client):
    signup(client)
    assert client.get("/api/portfolio").status_code == 403

    with db.connect() as conn:
        user_id = conn.execute(
            "SELECT id FROM users WHERE email = 'player@example.com'"
        ).fetchone()["id"]
        conn.execute("UPDATE users SET tier = 'founder' WHERE id = ?", (user_id,))
        conn.execute(
            """INSERT INTO collection
               (user_id, card_key, finish, qty, unit_paid, acquired_at)
               VALUES (?, 'OGN-043', 'nonfoil', 2, 10, ?)""",
            (user_id, time.time()),
        )
        now = time.time()
        for store, price in (("hideout", 12), ("goat", 16)):
            conn.execute(
                """INSERT INTO listings
                   (store, card_key, title_raw, url, price, finish, in_stock, synced_at)
                   VALUES (?, 'OGN-043', 'Charm', ?, ?, 'nonfoil', 1, ?)""",
                (store, f"https://example.test/{store}", price, now),
            )
        conn.execute(
            """INSERT INTO price_history
               (store, card_key, finish, price, in_stock, seen_at)
               VALUES ('hideout', 'OGN-043', 'nonfoil', 11, 1, ?)""",
            (now - 7 * 86400,),
        )
        conn.execute(
            """INSERT INTO external_prices
               (source, card_key, finish, native_price, native_currency,
                sgd_price, delta_1d_sgd, delta_7d_sgd, url, synced_at)
               VALUES ('riftbound_gg_tcgplayer', 'OGN-043', 'nonfoil', 10,
                       'USD', 13, 0.1, 0.5, 'https://riftbound.gg/cards/charm/', ?)""",
            (now,),
        )
        conn.execute(
            """INSERT INTO fx_rates (base, quote, rate, as_of, synced_at)
               VALUES ('USD', 'SGD', 1.3, '2026-08-04', ?)""",
            (now,),
        )

    response = client.get("/api/portfolio")
    assert response.status_code == 200
    data = response.json
    assert data["summary"]["paid"] == 20
    assert data["summary"]["value"] == 26
    assert data["summary"]["sg_value"] == 28
    assert data["summary"]["delta"] == 6
    assert data["summary"]["sg_vs_benchmark"] == 2
    assert data["summary"]["coverage_pct"] == 100
    assert data["positions"][0]["shops"] == 2
    assert data["positions"][0]["native_currency"] == "USD"
    assert data["trend_30d"]["status"] == "ready"


def test_existing_first_account_receives_founder_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "migration.db")
    db.init_db()
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO users (email, password_hash, tier, created_at)
               VALUES ('first@example.com', 'hash', 'member', 1)"""
        )
    db.init_db()
    with db.connect() as conn:
        tier = conn.execute("SELECT tier FROM users").fetchone()["tier"]
    assert tier == "founder"
