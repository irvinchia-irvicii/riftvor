"""Account sessions, freemium gates, and collection ownership."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module  # noqa: E402
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


def signup(client, email="player@example.com"):
    return client.post("/api/auth/signup", json={
        "email": email,
        "password": "eightchars",
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


def test_password_and_duplicate_email_validation(client):
    short = client.post("/api/auth/signup", json={
        "email": "player@example.com", "password": "short",
    })
    assert short.status_code == 400
    assert signup(client).status_code == 201
    client.post("/api/auth/logout")
    assert signup(client).status_code == 400


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
