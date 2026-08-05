"""Riftbound.gg public TCGplayer reference feed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402
import riftbound_gg  # noqa: E402


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get(self, url):
        FakeClient.calls += 1
        if "frankfurter" in url:
            return FakeResponse({"date": "2026-08-04", "rates": {"SGD": 1.28}})
        names = ["id", "slug", "price", "foilPrice", "deltaPrice",
                 "deltaFoilPrice", "delta7dPrice", "delta7dPriceFoil"]
        rows = [[f"TST-{i:03d}", f"test-{i}", "2.00", "3.00", "0.10",
                 "0.20", "0.30", "0.40"] for i in range(500)]
        return FakeResponse({"names": names, "data": rows})


def test_public_feed_is_converted_cached_and_attributed(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "external.db")
    monkeypatch.setattr(riftbound_gg.httpx, "Client", FakeClient)
    db.init_db()

    result = riftbound_gg.ensure_fresh(force=True)
    assert result["ok"] is True
    assert result["fx_rate"] == 1.28
    assert FakeClient.calls == 2
    with db.connect() as conn:
        normal = conn.execute(
            """SELECT * FROM external_prices
               WHERE card_key='TST-001' AND finish='nonfoil'"""
        ).fetchone()
        assert normal["sgd_price"] == 2.56
        assert normal["native_currency"] == "USD"
        assert normal["url"] == "https://riftbound.gg/cards/test-1/"
        assert conn.execute("SELECT COUNT(*) FROM external_prices").fetchone()[0] == 1000

    riftbound_gg.ensure_fresh()
    assert FakeClient.calls == 2
