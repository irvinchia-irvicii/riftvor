"""Cards Central HTML parser test against a real captured search page
(/search?brand=riftbound&q=yasuo, 1 Aug 2026)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cards_central import parse_search_html  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "cc_search_yasuo.html"


def test_parse_live_fixture():
    hits = parse_search_html(FIXTURE.read_text())
    assert hits, "no results parsed from fixture"
    by_key = {}
    for h in hits:
        by_key.setdefault(h["card_key"], h)
    # Alt-art showcase Yasuo seen in the fixture at S$10 foil, 1 in stock.
    assert "OGN-076a" in by_key
    foil = by_key["OGN-076a"]["finishes"]["foil"]
    assert foil["price"] == 10.0
    assert foil["in_stock"]
    assert foil["url"].startswith("https://cardscentral.com/card/")
    # Windrider alt-art at S$8.50 foil.
    assert by_key["OGN-205a"]["finishes"]["foil"]["price"] == 8.5
    # Every parsed hit has a plausible key and at least one priced finish.
    for h in hits:
        assert h["finishes"]
        for cell in h["finishes"].values():
            assert cell["price"] > 0
