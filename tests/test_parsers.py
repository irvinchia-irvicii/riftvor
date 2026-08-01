"""Parser unit tests using the REAL title examples from the PRD (§5) and
the live catalog probes of 1 Aug 2026."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from filters import is_cn, is_dropped, _name_matches  # noqa: E402
from parsers import (parse_buy_list_line, parse_fourelements, parse_goat,  # noqa: E402
                     parse_hideout, parse_teamcardgame, parse_tefuda)


def test_hideout_basic():
    c = parse_hideout({"title": "Dazzling Aurora [OGN-160/298]", "tags": ["OGN", "Riftbound"]})
    assert c.card_key == "OGN-160"
    assert c.name == "Dazzling Aurora"
    assert not c.is_alt_art


def test_hideout_cn_prefix_still_parses():
    # CN listings are dropped by filters, but the parser must not choke.
    c = parse_hideout({"title": "[Chinese] Seal of Insight [SFD-229/221]",
                       "tags": ["Riftbound", "SFD CN"]})
    assert c.card_key == "SFD-229"
    assert c.name == "Seal of Insight"
    assert c.overnumbered  # 229 > 221


def test_tefuda_basic():
    c = parse_tefuda({"title": "Evelynn - Entrancing [UNL - 141/219] Unleashed",
                      "tags": ["Rare", "Unleashed"]})
    assert c.card_key == "UNL-141"
    assert c.name == "Evelynn - Entrancing"
    assert c.rarity == "Rare"


def test_tefuda_overnumbered_showcase():
    c = parse_tefuda({"title": "Daring Poro (Overnumbered) [UNL - 225/219] Unleashed",
                      "tags": ["English", "Showcase", "Unleashed"]})
    assert c.card_key == "UNL-225"
    assert c.name == "Daring Poro"
    assert c.overnumbered
    assert c.is_alt_art  # showcase tag


def test_fourelements_basic():
    c = parse_fourelements({"title": "Charm [OGN-043/298] [Origins]",
                            "tags": ["Calm", "Common", "Origins", "Riftbound"]})
    assert c.card_key == "OGN-043"
    assert c.name == "Charm"
    assert c.rarity == "Common"
    assert c.color == "Calm"


def test_goat_foil():
    c = parse_goat({"title": "Yasuo - Unforgiven (259/298) - Origins Foil", "tags": []})
    assert c.card_key == "OGN-259"
    assert c.name == "Yasuo - Unforgiven"
    assert c.foil_in_title


def test_goat_alt_art():
    c = parse_goat({"title": "Viktor - Herald of the Arcane (076a/298) - Origins", "tags": []})
    assert c.card_key == "OGN-076a"
    assert c.is_alt_art
    assert not c.foil_in_title


def test_teamcardgame_set_from_tags():
    c = parse_teamcardgame({"title": "Discipline (058/298)",
                            "tags": ["058298", "OGN", "Origins", "Uncommon"]})
    assert c.card_key == "OGN-058"
    assert c.name == "Discipline"
    assert c.rarity == "Uncommon"


def test_fourelements_live_edge_cases():
    """Formats found in the live 1 Aug 2026 catalog, beyond the PRD regexes."""
    # Overnumbered with asterisk marker
    c = parse_fourelements({"title": "Ahri, Inquisitive [SFD-227*/221] [Spiritforged]", "tags": []})
    assert c.card_key == "SFD-227"
    assert c.overnumbered
    # Vendetta special
    c = parse_fourelements({"title": "Ahri, Inquisitive [VEN-SP3/006] [Vendetta]", "tags": []})
    assert c.card_key == "VEN-SP3"
    # Missing opening bracket (store typo) + trailing [Foil]
    c = parse_fourelements({"title": "Allay, Eager Admirer UNL-041/219] [Unleashed] [Foil]", "tags": []})
    assert c.card_key == "UNL-041"
    assert c.foil_in_title
    # Proving Grounds set
    c = parse_fourelements({"title": "Annie, Fiery [OGS-001/024] [Origins Proving Grounds]", "tags": []})
    assert c.card_key == "OGS-001"
    # Token / rune / rune-shorthand numbering (no set size → no padding,
    # so rune 'SFD-02' cannot collide with main-set 'SFD-002')
    c = parse_fourelements({"title": "Baron Pit [UNL-T01] [Unleashed]", "tags": []})
    assert c.card_key == "UNL-T01"
    c = parse_fourelements({"title": "Body Rune [SFD-R04a] [Spiritforged]", "tags": []})
    assert c.card_key == "SFD-R04a"
    c = parse_fourelements({"title": "Calm Rune [SFD-02] [Spiritforged]", "tags": []})
    assert c.card_key == "SFD-02"


def test_dual_faced_tokens_key_on_first_face():
    c = parse_teamcardgame({"title": "Baron Pit // Gold (T01 // T05)",
                            "tags": ["UNL", "Unleashed"]})
    assert c.card_key == "UNL-T01"
    assert c.name == "Baron Pit // Gold"
    c = parse_teamcardgame({"title": "Body Rune (R04a)", "tags": ["SFD"]})
    assert c.card_key == "SFD-R04a"
    c = parse_tefuda({"title": "Baron Pit // Gold [UNL - T01 // T05] Unleashed",
                      "tags": ["Unleashed"]})
    assert c.card_key == "UNL-T01"


def test_buy_list_rune_token_keys():
    assert parse_buy_list_line("UNL-T01")["card_key"] == "UNL-T01"
    assert parse_buy_list_line("2x SFD-R04a")["card_key"] == "SFD-R04a"


def test_no_collector_number_returns_none():
    assert parse_hideout({"title": "Riftbound Playmat", "tags": []}) is None
    assert parse_teamcardgame({"title": "Random Rune Token", "tags": []}) is None


# ── Filters ─────────────────────────────────────────────────────────────────

def test_cn_detection():
    assert is_cn("[Chinese] Time Warp [OGN-122/298]")
    assert is_cn("Seal of Focus", tags=["SFD CN"])
    assert is_cn("Seal of Focus", handle="seal-of-focus-sfd-226-221-cn")
    assert not is_cn("Dazzling Aurora [OGN-160/298]", tags=["OGN", "Riftbound"])


def test_sealed_dropped_showcase_kept():
    assert is_dropped("Riftbound Origins Booster Box", tags=[])
    assert is_dropped("Proving Grounds Box", tags=[])
    assert is_dropped("Champion Deck - Jinx", tags=[])
    # 'Showcase' must NOT trip the \bcase\b sealed filter.
    assert not is_dropped("Daring Poro (Overnumbered) [UNL - 225/219]",
                          tags=["Showcase", "Unleashed"])


def test_runes_tokens_kept_other_games_dropped():
    assert not is_dropped("Fury Rune (T-01)", tags=["Riftbound"])
    assert is_dropped("Charizard ex (199/165)", tags=["Pokemon"])
    assert is_dropped("Riftbound Premium Sleeves 100ct", tags=[])


# ── Buy-list line parsing ───────────────────────────────────────────────────

def test_buy_list_collector_number():
    e = parse_buy_list_line("OGN-043")
    assert e["card_key"] == "OGN-043" and e["qty"] == 1
    e = parse_buy_list_line("2x ogn 43")
    assert e["card_key"] == "OGN-043" and e["qty"] == 2
    e = parse_buy_list_line("3 UNL-225")
    assert e["card_key"] == "UNL-225" and e["qty"] == 3


def test_buy_list_pasted_store_title():
    e = parse_buy_list_line("Charm [OGN-043/298] [Origins]")
    assert e["card_key"] == "OGN-043"


def test_buy_list_name_fallback():
    e = parse_buy_list_line("4x Dazzling Aurora")
    assert e == {"raw": "4x Dazzling Aurora", "qty": 4, "name": "Dazzling Aurora"}


def test_name_matching_ported_semantics():
    assert _name_matches("Yasuo", "Yasuo - Unforgiven")
    assert _name_matches("Dazzling Aurora", "Dazzling Aurora [OGN-160/298]")
    assert not _name_matches("The One", "One to Rule Them All")
