"""Collection tests — cost basis snapshotting and valuation against a
temporary database."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collection  # noqa: E402
import db  # noqa: E402


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    with db.connect() as conn:
        conn.executemany(
            """INSERT INTO cards (card_key, set_code, number, name)
               VALUES (?, ?, ?, ?)""",
            [("OGN-043", "OGN", "043", "Charm"),
             ("UNL-053", "UNL", "053", "Scuttle Crab")])
        conn.executemany(
            """INSERT INTO listings (store, card_key, title_raw, url, price,
                                     finish, condition, in_stock, synced_at)
               VALUES (?, ?, 't', ?, ?, ?, 'Near Mint', ?, ?)""",
            [("goat", "OGN-043", "u1", 2.00, "nonfoil", 1, time.time()),
             ("hideout", "OGN-043", "u2", 1.50, "nonfoil", 1, time.time()),
             # Cheaper but out of stock — must not set market value.
             ("tefuda", "OGN-043", "u3", 0.10, "nonfoil", 0, time.time())])
    return tmp_path


def test_add_and_value_uses_cheapest_in_stock(temp_db):
    assert collection.add_many([
        {"card_key": "OGN-043", "finish": "nonfoil", "qty": 4,
         "unit_paid": 0.80, "store": "goat"}]) == 1
    data = collection.list_items()
    item = data["items"][0]
    assert item["name"] == "Charm"
    assert item["paid"] == 3.20          # 4 x 0.80, snapshotted
    assert item["unit_now"] == 1.50      # cheapest IN-STOCK, not the 0.10
    assert item["value"] == 6.00
    assert item["delta"] == 2.80
    assert data["summary"]["cards"] == 4


def test_cost_basis_is_never_recalculated(temp_db):
    collection.add_many([{"card_key": "OGN-043", "qty": 1, "unit_paid": 0.80}])
    # Market moves; what you paid must not.
    with db.connect() as conn:
        conn.execute("UPDATE listings SET price = 99.00 WHERE card_key = ?",
                     ("OGN-043",))
    item = collection.list_items()["items"][0]
    assert item["unit_paid"] == 0.80
    assert item["unit_now"] == 99.00
    assert item["delta"] == 98.20


def test_item_with_no_in_stock_listing_is_unpriced_not_zero(temp_db):
    collection.add_many([{"card_key": "UNL-053", "qty": 1, "unit_paid": 3.50}])
    data = collection.list_items()
    item = data["items"][0]
    assert item["unit_now"] is None
    assert item["value"] is None
    assert item["delta"] is None
    # Paid still counts; value simply excludes what it cannot price.
    assert data["summary"]["paid"] == 3.50
    assert data["summary"]["value"] == 0.0
    assert data["summary"]["unpriced"] == 1


def test_malformed_items_are_skipped_not_stored(temp_db):
    added = collection.add_many([
        {"card_key": "OGN-043", "qty": 1, "unit_paid": 1.0},   # good
        {"finish": "foil", "qty": 1, "unit_paid": 1.0},        # no card_key
        {"card_key": "OGN-043", "qty": 1},                     # no price
        {"card_key": "OGN-043", "qty": 1, "unit_paid": "abc"},  # not a number
        {"card_key": "OGN-043", "qty": 1, "unit_paid": -5},    # negative
    ])
    assert added == 1
    assert collection.list_items()["summary"]["lines"] == 1


def test_unknown_finish_defaults_to_nonfoil(temp_db):
    collection.add_many([{"card_key": "OGN-043", "finish": "sparkly",
                          "qty": 1, "unit_paid": 1.0}])
    assert collection.list_items()["items"][0]["finish"] == "nonfoil"


def test_remove(temp_db):
    collection.add_many([{"card_key": "OGN-043", "qty": 1, "unit_paid": 1.0}])
    item_id = collection.list_items()["items"][0]["id"]
    collection.remove(item_id)
    assert collection.list_items()["summary"]["lines"] == 0
