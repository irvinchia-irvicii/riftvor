"""Partial-catalog semantics.

Regression tests for the Stage 0 finding (HOSTING.md): a store that answered
page 1 and throttled page 2 used to report `ok` with a quarter of its stock,
and that truncated catalog then replaced the complete one in the DB. These
pin down that an incomplete fetch is called incomplete and is never written.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import stores  # noqa: E402
import sync  # noqa: E402
from stores import CatalogResult, ShopifyCatalogStore  # noqa: E402

CFG = {"key": "teststore", "name": "Test", "base": "https://example.test",
       "handles": ["riftbound-singles"], "parser": "hideout"}
CFG_DISCOVER = {**CFG, "discover": {"regex": r"riftbound.*singles"}}


def _product(pid):
    return {"id": pid, "title": f"Yasuo [OGN-{pid:03d}]", "handle": f"p{pid}",
            "tags": [], "images": [], "variants": [
                {"title": "Near Mint", "price": "1.00", "available": True}]}


class FakeClient:
    """Answers whatever `pages` maps, None meaning 'stays unanswered'."""

    def __init__(self, pages):
        self.pages = pages
        self.asked = []

    async def get(self, url):  # pragma: no cover - not used directly
        raise AssertionError("_get_json is patched; .get should not be called")


def _run(cfg, pages):
    """Drive fetch_catalog with _get_json stubbed to `pages` (url -> data)."""
    store = ShopifyCatalogStore(cfg)
    store.breaker.benched_until = 0.0

    async def fake_get_json(client, url):
        for fragment, data in pages.items():
            if fragment in url:
                return data
        return None

    # Instance attribute shadows the method, so it is called unbound:
    # self._get_json(client, url) passes exactly two arguments.
    store._get_json = fake_get_json
    return asyncio.run(store.fetch_catalog(FakeClient(pages)))


def test_every_page_answered_is_ok():
    res = _run(CFG, {"page=1": {"products": [_product(1), _product(2)]}})
    assert res.status == "ok"
    assert res.problems == []
    assert len(res.products) == 2


def test_unanswered_second_page_is_partial_not_ok():
    # 250 products on page 1 means pagination continues; page 2 never answers.
    res = _run(CFG, {"page=1": {"products": [_product(i) for i in range(250)]},
                     "page=2": None})
    assert res.status == "partial"
    assert len(res.products) == 250          # data did arrive...
    assert "page 2 unanswered" in res.detail  # ...but is flagged incomplete


def test_nothing_answered_is_failed():
    res = _run(CFG, {})
    assert res.status == "failed"
    assert res.products is None


def test_discovery_falling_back_is_partial():
    # collections.json unanswered → configured handles are a stale subset.
    res = _run(CFG_DISCOVER, {"page=1": {"products": [_product(1)]}})
    assert res.status == "partial"
    assert "discovery unanswered" in res.detail


def test_partial_counts_against_the_breaker():
    store = ShopifyCatalogStore(CFG)
    before = store.breaker.failures
    _run(CFG, {"page=1": {"products": [_product(i) for i in range(250)]},
               "page=2": None})
    assert stores.breaker_for("teststore").failures > before


def _sync_once(cfg, result, monkeypatch):
    """Run _sync_store against a canned CatalogResult, recording DB writes."""
    writes = {"replaced": [], "recorded": []}

    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(sync.db, "connect", lambda: FakeConn())
    monkeypatch.setattr(sync.db, "replace_store_listings",
                        lambda c, s, rows: writes["replaced"].append((s, len(rows))))
    monkeypatch.setattr(sync.db, "upsert_cards", lambda c, cards: None)
    monkeypatch.setattr(sync.db, "record_sync",
                        lambda c, s, ok, msg, n: writes["recorded"].append((s, ok, msg)))

    async def fake_fetch(self, client):
        return result

    monkeypatch.setattr(ShopifyCatalogStore, "fetch_catalog", fake_fetch)
    out = asyncio.run(sync._sync_store(cfg, None))
    return out, writes


def test_partial_catalog_is_never_written(monkeypatch):
    partial = CatalogResult([_product(1)], ["riftbound-singles page 2 unanswered"])
    out, writes = _sync_once(CFG, partial, monkeypatch)
    assert out["ok"] is False and out["status"] == "partial"
    assert writes["replaced"] == []          # the whole point: no overwrite
    assert writes["recorded"][0][1] is False
    assert "partial" in writes["recorded"][0][2]


def test_complete_catalog_is_written(monkeypatch):
    out, writes = _sync_once(CFG, CatalogResult([_product(1)], []), monkeypatch)
    assert out["ok"] is True and out["status"] == "ok"
    assert writes["replaced"] == [("teststore", 1)]
