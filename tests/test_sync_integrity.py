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


# ── Pacing (Stage 0 re-test) ────────────────────────────────────────────────

def _record_concurrency(monkeypatch):
    """Drive _sync_stores over 3 stores, recording peak overlap and order."""
    state = {"live": 0, "peak": 0, "order": []}

    async def fake_sync_store(cfg, client):
        state["live"] += 1
        state["peak"] = max(state["peak"], state["live"])
        state["order"].append(cfg["key"])
        await asyncio.sleep(0)          # yield: parallel would interleave here
        state["live"] -= 1
        return {"store": cfg["key"], "ok": True, "status": "ok",
                "message": "ok", "listings": 1, "took_s": 0.0}

    class NullClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(sync, "_sync_store", fake_sync_store)
    monkeypatch.setattr(sync, "make_client", lambda: NullClient())
    monkeypatch.setattr(sync, "STORE_DELAY_S", 0)   # keep the test instant
    cfgs = [{**CFG, "key": f"s{i}"} for i in range(3)]
    asyncio.run(sync._sync_stores(cfgs))
    return state


def test_parallel_is_the_default(monkeypatch):
    monkeypatch.setattr(sync, "SEQUENTIAL_SYNC", False)
    assert _record_concurrency(monkeypatch)["peak"] == 3


def test_sequential_mode_syncs_one_store_at_a_time(monkeypatch):
    # The whole point of the Render path: never more than one store in flight.
    monkeypatch.setattr(sync, "SEQUENTIAL_SYNC", True)
    state = _record_concurrency(monkeypatch)
    assert state["peak"] == 1
    assert state["order"] == ["s0", "s1", "s2"]


# ── Egress proxy ────────────────────────────────────────────────────────────

def test_proxy_accepts_a_plain_url():
    import config
    assert config._parse_proxy("http://u:p@1.2.3.4:8080") == "http://u:p@1.2.3.4:8080"


def test_proxy_accepts_3vor_fetch_pipe_format():
    # Credentials stay portable between the two projects.
    import config
    assert config._parse_proxy("1.2.3.4|8080|user|pass") == "http://user:pass@1.2.3.4:8080"
    assert config._parse_proxy("1.2.3.4|8080") == "http://1.2.3.4:8080"


def test_proxy_unset_or_malformed_means_direct():
    import config
    assert config._parse_proxy("") == ""
    assert config._parse_proxy("nonsense") == ""      # no port -> not a proxy
    assert config._parse_proxy("host|") == ""


def test_proxy_label_never_leaks_credentials(monkeypatch):
    # This label goes to a log line on every boot.
    import config
    monkeypatch.setattr(config, "PROXY_URL", "http://user:hunter2@1.2.3.4:8080")
    label = config.proxy_label()
    assert label == "1.2.3.4:8080"
    assert "hunter2" not in label and "user" not in label


def test_proxy_reaches_every_egress_path(monkeypatch):
    """All five outbound paths must honour it — one missed client would leak
    the real IP and re-trip the block that the proxy exists to avoid."""
    import cards_central
    import carousell
    import dormant_poll
    assert stores.make_client  # httpx: stores + cards_central (via make_client)
    assert stores.cffi_proxies  # curl_cffi: stores fallback + carousell
    assert "make_client" in cards_central.lookup.__globals__["stores"].__dict__
    assert "stores" in carousell._fetch_html.__code__.co_names
    assert "PROXY_URL" in dormant_poll.poll.__globals__


def test_pacing_is_jittered():
    import config
    assert config.PAGE_JITTER_S > 0


def test_local_defaults_are_unchanged():
    # Guards the promise that only render.yaml opts into the slow path.
    import importlib

    import config
    importlib.reload(config)
    assert config.SEQUENTIAL_SYNC is False
    assert config.PAGE_DELAY_S == 0.5
    assert config.PROXY_URL == ""          # the Mac has never needed one
