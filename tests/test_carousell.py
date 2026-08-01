"""Carousell parser + noise-filter tests (synthetic blocks matching the
live page structure of 1 Aug 2026)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carousell import _NOISE_RE, parse_listings  # noqa: E402


def _page(cards):
    state = {"SearchListing": {"listingCards": cards}}
    return (f"<script>{json.dumps(state)}</script>"
            "<script>window.initialState = JSON.parse("
            "document.currentScript.previousSibling.textContent);</script>")


def _card(listing_id, title, price_str, cond="Like new"):
    return {
        "listingID": listing_id,
        "belowFold": [
            {"component": "header_1", "stringContent": title},
            {"component": "header_2", "stringContent": price_str},
            {"component": "tag", "stringContent": "EN"},
            {"component": "paragraph", "stringContent": cond},
        ],
    }


def test_parse_listing_cards():
    html = _page([
        _card(111, "Renekton Overnumbered Riftbound Vendetta card", "S$145"),
        _card(222, "Riftbound Vendetta Singles", "S$1,050.50"),
    ])
    out = parse_listings(html)
    assert len(out) == 2
    assert out[0]["title"].startswith("Renekton")
    assert out[0]["price"] == 145.0
    assert out[0]["url"] == "https://www.carousell.sg/p/111"
    assert out[1]["price"] == 1050.50
    assert out[0]["condition"] == "Like new"


def test_noise_filters():
    noisy = [
        "WTB Riftbound Yasuo",
        "Riftbound bulk lot 200 cards",
        "Riftbound Origins Booster Box sealed",
        "WTT Riftbound alt arts for trade",
        "Riftbound champion deck Jinx",
    ]
    clean = [
        "Renekton Overnumbered Riftbound Vendetta card",
        "Riftbound Vendetta Singles",
        "Yasuo Windrider showcase foil",
    ]
    for t in noisy:
        assert _NOISE_RE.search(t), t
    for t in clean:
        assert not _NOISE_RE.search(t), t


def test_structure_change_returns_empty():
    assert parse_listings("<html>no state here</html>") == []
