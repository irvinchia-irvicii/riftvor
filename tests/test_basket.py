"""Purchase-plan tests — synthetic comparison rows with known answers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import basket  # noqa: E402
from parsers import parse_buy_list_line  # noqa: E402

ORDER = ["hideout", "tefuda", "4elements", "goat", "teamcardgame"]


def _row(raw, card_key, prices, qty=1, finish="nonfoil", name=None):
    """prices: {store: (price, in_stock)}"""
    return {
        "raw": raw, "qty": qty, "card_key": card_key,
        "name": name or card_key, "finish": finish,
        "stores": {
            store: {"price": p, "url": f"https://{store}/x", "in_stock": ok,
                    "condition": "Near Mint", "title": card_key}
            for store, (p, ok) in prices.items()
        },
    }


def test_cheapest_picks_floor_price_and_multiplies_qty():
    rows = [
        _row("2 Charm", "OGN-043", {"hideout": (1.00, True),
                                    "goat": (0.80, True)}, qty=2),
        _row("1 Eclipse", "OGN-063", {"hideout": (0.30, True),
                                      "goat": (0.50, True)}),
    ]
    plan = basket.plans(rows, ORDER)["plans"][0]
    assert plan["label"] == "Cheapest"
    # 2 x 0.80 (goat) + 1 x 0.30 (hideout)
    assert plan["total"] == 1.90
    assert plan["store_count"] == 2
    assert plan["cards_total"] == 3
    assert plan["lines_filled"] == 2


def test_out_of_stock_never_enters_a_plan():
    rows = [_row("1 Charm", "OGN-043", {"hideout": (0.10, False),
                                        "goat": (5.00, True)})]
    plan = basket.plans(rows, ORDER)["plans"][0]
    assert plan["total"] == 5.00
    assert plan["by_store"][0]["store"] == "goat"


def test_line_with_nothing_in_stock_is_reported_missing():
    rows = [
        _row("1 Charm", "OGN-043", {"goat": (1.00, True)}),
        _row("1 Ghost", "OGN-999", {"goat": (2.00, False)}),
    ]
    result = basket.plans(rows, ORDER)
    plan = result["plans"][0]
    assert plan["missing"] == ["1 Ghost"]
    assert plan["lines_filled"] == 1
    assert plan["lines_total"] == 2
    assert plan["total"] == 1.00


def test_fewest_stores_trades_a_premium_for_one_parcel():
    # goat alone covers both lines; cheapest would split across two stores.
    rows = [
        _row("1 A", "OGN-001", {"hideout": (1.00, True), "goat": (1.50, True)}),
        _row("1 B", "OGN-002", {"tefuda": (1.00, True), "goat": (1.20, True)}),
    ]
    result = basket.plans(rows, ORDER)
    cheapest, fewest = result["plans"]
    assert cheapest["total"] == 2.00 and cheapest["store_count"] == 2
    assert fewest["total"] == 2.70 and fewest["store_count"] == 1
    # The convenience premium is surfaced, not hidden.
    assert fewest["premium"] == 0.70


def test_single_store_ranked_by_coverage_then_cost():
    rows = [
        _row("1 A", "OGN-001", {"hideout": (9.00, True), "goat": (1.00, True)}),
        _row("1 B", "OGN-002", {"hideout": (9.00, True)}),
    ]
    singles = basket.plans(rows, ORDER)["single_store"]
    # hideout fills 2/2 despite being pricier; goat only manages 1/2.
    assert singles[0]["store"] == "hideout"
    assert singles[0]["lines_filled"] == 2
    assert singles[1]["store"] == "goat"
    assert singles[1]["lines_filled"] == 1
    # Coverage differs, so no premium comparison is claimed.
    assert singles[1]["premium"] is None


def test_finishes_of_one_line_compete_rather_than_double_count():
    """'1 Retreat' yields a nonfoil and a foil row — the buyer wants one."""
    rows = [
        _row("1 Retreat", "OGN-104", {"goat": (1.24, True)}, finish="nonfoil"),
        _row("1 Retreat", "OGN-104", {"goat": (0.90, True)}, finish="foil"),
    ]
    plan = basket.plans(rows, ORDER)["plans"][0]
    assert plan["lines_total"] == 1
    assert plan["total"] == 0.90
    assert plan["by_store"][0]["lines"][0]["finish"] == "foil"


def test_multiple_printings_flagged_ambiguous():
    rows = [
        _row("6 Calm Rune", "SFD-R02", {"goat": (0.50, True)}, qty=6),
        _row("6 Calm Rune", "UNL-R02", {"goat": (0.30, True)}, qty=6),
    ]
    result = basket.plans(rows, ORDER)
    assert result["ambiguous_lines"] == ["6 Calm Rune"]
    assert result["assumes_stock_depth"] is True
    assert result["plans"][0]["total"] == 1.80  # 6 x cheapest printing


def test_empty_rows_produce_no_plans():
    assert basket.plans([], ORDER)["plans"] == []


# ── Deck-list section headers (the bug the screenshot surfaced) ─────────────

def test_deck_list_section_headers_are_skipped():
    for header in ("Legend:", "MainDeck:", "Battlefield:", "Rune Pool:",
                   "Sideboard:"):
        assert parse_buy_list_line(header) is None, header
    for comment in ("// my deck", "# notes"):
        assert parse_buy_list_line(comment) is None, comment


def test_real_card_lines_still_parse_around_headers():
    deck = "Legend:\n1 Yasuo\n\nRune Pool:\n6 Calm Rune\n// end"
    parsed = [e for e in
              (parse_buy_list_line(l) for l in deck.splitlines()) if e]
    assert [e["raw"] for e in parsed] == ["1 Yasuo", "6 Calm Rune"]
    assert parsed[1]["qty"] == 6
