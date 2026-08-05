import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import catalog_snapshot  # noqa: E402
import db  # noqa: E402


def test_bootstrap_loads_only_public_catalogue_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "snapshot.db")
    db.init_db()
    snapshot = tmp_path / "catalog.json.gz"
    payload = {
        "generated_at": 123.0,
        "cards": [{"card_key": "OGN-043", "set_code": "OGN",
                   "number": "043", "name": "Charm", "rarity": "Common",
                   "color": None, "is_alt_art": 0, "img_url": None}],
        "listings": [{"store": "hideout", "card_key": "OGN-043",
                      "title_raw": "Charm [OGN-043]", "url": "https://shop/card",
                      "price": 1.5, "currency": "SGD", "finish": "nonfoil",
                      "condition": "Near Mint", "in_stock": 1,
                      "language": "EN", "synced_at": 122.0}],
        "external_prices": [], "fx_rates": [],
    }
    with gzip.open(snapshot, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)
    result = catalog_snapshot.bootstrap_if_empty(snapshot)
    assert result == {"loaded": True, "cards": 1, "listings": 1}
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM collection").fetchone()[0] == 0
        meta = conn.execute(
            "SELECT message, listing_count FROM sync_meta WHERE store='hideout'"
        ).fetchone()
        assert meta["message"] == "Hosted review catalogue snapshot"
        assert meta["listing_count"] == 1


def test_bootstrap_does_not_overwrite_existing_catalogue(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "existing.db")
    db.init_db()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO cards (card_key, set_code, number) VALUES ('X-1','X','1')"
        )
        conn.execute(
            """INSERT INTO listings
               (store, card_key, title_raw, url, price, finish, in_stock,
                synced_at) VALUES ('shop', 'X-1', 'Existing',
                'https://shop/existing', 1, 'nonfoil', 1, 1)"""
        )
    result = catalog_snapshot.bootstrap_if_empty(tmp_path / "missing.json.gz")
    assert result["loaded"] is False
