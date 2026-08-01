"""parsers.py — per-store title parsers → canonical card identity.

Card identity = collector number `SET-NNN[a]` (e.g. OGN-043, OGN-076a
alt-art, UNL-225 overnumbered where 225 > set size 219).

Each parser takes a Shopify product dict (title/tags/handle) and returns a
ParsedCard or None when the title carries no recognisable collector number
(the listing is still kept, unmatched, with card_key NULL).

Title formats (live-probed 1 Aug 2026):
    Hideout        'Dazzling Aurora [OGN-160/298]'; CN prefixed '[Chinese]'
    Tefuda         'Evelynn - Entrancing [UNL - 141/219] Unleashed'
                   'Daring Poro (Overnumbered) [UNL - 225/219] Unleashed'
    4 Elements     'Charm [OGN-043/298] [Origins]'
    GOAT TCG       'Yasuo - Unforgiven (259/298) - Origins Foil'; alt '(076a/298)'
    Team Card Game 'Discipline (058/298)' + set code in tags ('OGN')
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from config import SETS, SET_NAME_TO_CODE

_SET_CODES = "|".join(SETS)

# Bracketed collector numbers, live formats (1 Aug 2026 probe):
#   '[OGN-160/298]' · '[UNL - 141/219]' · '[SFD-227*/221]' (4E overnumbered)
#   '[UNL-T01]' tokens · '[SFD-R04a]' runes · '[SFD-02]' rune shorthand
#   '[VEN-SP3/006]' specials · 'UNL-041/219]' (4E missing-open-bracket typo)
# Groups: 1=set 2=prefix(R/T/SP) 3=digits 4=letter 5=set-size (may be None)
# Dual-faced tokens print both faces — 'Baron Pit // Gold [UNL - T01 // T05]',
# '(T01 // T05)' — identity keys on the first face.
_DUAL_TAIL = r"(?:\s*//\s*(?:R|T|SP)?\d{1,3}[a-z]?)?"
BRACKET_RE = re.compile(
    rf"\[?\s*({_SET_CODES})\s*-\s*(R|T|SP)?(\d{{1,3}})([a-z])?\*?{_DUAL_TAIL}"
    rf"\s*(?:/\s*(\d+)\s*)?\]", re.I
)
# '(259/298)' · '(076a/298)' · '(058/298)'
PAREN_RE = re.compile(r"\(\s*(\d{1,3})([a-z])?\s*/\s*\d+\s*\)")
# Team Card Game runes/tokens: bare '(R04a)' · '(T01)' · '(T01 // T05)'
BARE_PREFIX_RE = re.compile(
    rf"\(\s*(R|T|SP)(\d{{1,3}})([a-z])?{_DUAL_TAIL}\s*\)", re.I)


@dataclass
class ParsedCard:
    set_code: str
    number: str                 # zero-padded, optional letter: '043', '076a'
    name: str
    is_alt_art: bool = False
    overnumbered: bool = False
    foil_in_title: bool = False  # GOAT encodes foil in the title, not variants
    rarity: str | None = None
    color: str | None = None
    tags: list[str] = field(default_factory=list)

    @property
    def card_key(self) -> str:
        return f"{self.set_code}-{self.number}"


_RARITIES = {"common", "uncommon", "rare", "epic", "legendary", "overload",
             "showcase", "secret", "promo"}
_COLORS = {"calm", "chaos", "fury", "mind", "order", "body", "colorless"}


def _norm_number(digits: str, letter: str | None, prefix: str | None = None,
                 has_size: bool = True) -> str:
    """Canonical number. Main-set numbers (no prefix, printed with a set
    size) are zero-padded to 3 digits so every store agrees on 'OGN-043'.
    Prefixed (R/T/SP runes/tokens/specials) and size-less shorthand numbers
    keep their printed digits — 'SFD-02' (rune) must NOT collide with the
    main-set card 'SFD-002'."""
    if prefix:
        return f"{prefix.upper()}{digits}{(letter or '').lower()}"
    if not has_size:
        return f"{digits}{(letter or '').lower()}"
    return f"{int(digits):03d}{(letter or '').lower()}"


def _rarity_color_from_tags(tags: list[str]) -> tuple[str | None, str | None]:
    rarity = color = None
    for tag in tags:
        tl = tag.strip().lower()
        if tl in _RARITIES and rarity is None:
            rarity = tag.strip()
        elif tl in _COLORS and color is None:
            color = tag.strip()
    return rarity, color


def _is_overnumbered(set_code: str, number: str) -> bool:
    if not number or not number[0].isdigit():
        return False  # rune/token/special numbering has no overflow notion
    size = SETS.get(set_code, (None, None))[1]
    digits = int(re.sub(r"[a-z]", "", number))
    return bool(size) and digits > size


def _finish_card(set_code: str, digits: str, letter: str | None, name: str,
                 tags: list[str], foil_in_title: bool = False,
                 prefix: str | None = None, has_size: bool = True) -> ParsedCard:
    number = _norm_number(digits, letter, prefix, has_size)
    rarity, color = _rarity_color_from_tags(tags)
    name = re.sub(r"\s+", " ", name).strip(" -–—·|").strip()
    return ParsedCard(
        set_code=set_code.upper(),
        number=number,
        name=name,
        is_alt_art=bool(letter),
        overnumbered=_is_overnumbered(set_code.upper(), number),
        foil_in_title=foil_in_title,
        rarity=rarity,
        color=color,
        tags=tags,
    )


# ── Per-store parsers ───────────────────────────────────────────────────────


def parse_hideout(product: dict) -> ParsedCard | None:
    """'Dazzling Aurora [OGN-160/298]' — CN handled upstream by filters."""
    title = product.get("title", "")
    m = BRACKET_RE.search(title)
    if not m:
        return None
    name = title[: m.start()]
    name = re.sub(r"^\[chinese\]\s*", "", name, flags=re.I)
    return _finish_card(m.group(1), m.group(3), m.group(4), name,
                        product.get("tags", []), prefix=m.group(2),
                        has_size=bool(m.group(5)))


def parse_tefuda(product: dict) -> ParsedCard | None:
    """'Daring Poro (Overnumbered) [UNL - 225/219] Unleashed'."""
    title = product.get("title", "")
    m = BRACKET_RE.search(title)
    if not m:
        return None
    name = title[: m.start()]
    name = re.sub(r"\(overnumbered\)", "", name, flags=re.I)
    name = re.sub(r"\(showcase\)", "", name, flags=re.I)
    card = _finish_card(m.group(1), m.group(3), m.group(4), name,
                        product.get("tags", []), prefix=m.group(2),
                        has_size=bool(m.group(5)))
    if "showcase" in [t.lower() for t in product.get("tags", [])]:
        card.is_alt_art = True
    return card


def parse_fourelements(product: dict) -> ParsedCard | None:
    """'Charm [OGN-043/298] [Origins]'."""
    title = product.get("title", "")
    m = BRACKET_RE.search(title)
    if not m:
        return None
    # 4E marks foil in a trailing '[Foil]' bracket.
    foil = bool(re.search(r"\[\s*foil\s*\]", title, re.I))
    return _finish_card(m.group(1), m.group(3), m.group(4), title[: m.start()],
                        product.get("tags", []), foil_in_title=foil,
                        prefix=m.group(2), has_size=bool(m.group(5)))


def _set_from_text(text: str) -> str | None:
    tl = text.lower()
    # Longest names first so 'proving grounds' wins over any shorter overlap.
    for set_name in sorted(SET_NAME_TO_CODE, key=len, reverse=True):
        if set_name in tl:
            return SET_NAME_TO_CODE[set_name]
    return None


def parse_goat(product: dict) -> ParsedCard | None:
    """'Yasuo - Unforgiven (259/298) - Origins Foil' — set + foil in title."""
    title = product.get("title", "")
    m = PAREN_RE.search(title)
    if not m:
        return None
    tail = title[m.end():]
    set_code = _set_from_text(tail) or _set_from_text(title)
    if not set_code:
        return None
    foil = bool(re.search(r"\bfoil\b", tail, re.I))
    return _finish_card(set_code, m.group(1), m.group(2), title[: m.start()],
                        product.get("tags", []), foil_in_title=foil)


def parse_teamcardgame(product: dict) -> ParsedCard | None:
    """'Discipline (058/298)' — set code lives in tags ('OGN')."""
    title = product.get("title", "")
    tags = product.get("tags", [])
    set_code = None
    for tag in tags:
        if tag.strip().upper() in SETS:
            set_code = tag.strip().upper()
            break
    if set_code is None:
        set_code = _set_from_text(" ".join(tags)) or _set_from_text(title)
    foil = bool(re.search(r"\bfoil\b", title, re.I))
    m = PAREN_RE.search(title)
    if m:
        if not set_code:
            return None
        return _finish_card(set_code, m.group(1), m.group(2), title[: m.start()],
                            tags, foil_in_title=foil)
    # Runes/tokens: 'Body Rune (R04a)' · 'Mech // Buff (T01)'
    bm = BARE_PREFIX_RE.search(title)
    if bm and set_code:
        return _finish_card(set_code, bm.group(2), bm.group(3),
                            title[: bm.start()], tags, foil_in_title=foil,
                            prefix=bm.group(1), has_size=False)
    return None


PARSERS = {
    "hideout": parse_hideout,
    "tefuda": parse_tefuda,
    "fourelements": parse_fourelements,
    "goat": parse_goat,
    "teamcardgame": parse_teamcardgame,
}


def parse_product(parser_key: str, product: dict) -> ParsedCard | None:
    return PARSERS[parser_key](product)


# ── Buy-list line parsing (matching.py uses this) ───────────────────────────

# 'OGN-043' · 'ogn 043' · 'OGN-076a' · 'UNL-T01' · 'SFD-R04a'
BUYLIST_KEY_RE = re.compile(
    rf"^\s*({_SET_CODES})[\s-]+(R|T|SP)?(\d{{1,3}})([a-z])?\s*$", re.I)


def parse_buy_list_line(line: str) -> dict | None:
    """One buy-list line → {'raw', 'qty', 'card_key' | 'name'} or None.

    Returns None for structural lines so a pasted deck list works as-is:
    section headers ('Legend:', 'MainDeck:', 'Rune Pool:', 'Sideboard:')
    and comments. No Riftbound card name ends in a colon, so trailing-colon
    is a safe header test.
    """
    raw = line.strip()
    if not raw:
        return None
    if raw.startswith(("//", "#")):
        return None
    if raw.endswith(":"):
        return None
    qty = 1
    m = re.match(r"^(\d+)\s*[xX]?\s+(.*)$", raw)
    if m:
        qty, rest = int(m.group(1)), m.group(2)
    else:
        rest = raw
    key_match = BUYLIST_KEY_RE.match(rest)
    if key_match:
        card_key = (f"{key_match.group(1).upper()}-"
                    f"{_norm_number(key_match.group(3), key_match.group(4), key_match.group(2))}")
        return {"raw": raw, "qty": qty, "card_key": card_key}
    # A pasted store title? Extract its collector number.
    bm = BRACKET_RE.search(rest)
    if bm:
        card_key = (f"{bm.group(1).upper()}-"
                    f"{_norm_number(bm.group(3), bm.group(4), bm.group(2), bool(bm.group(5)))}")
        return {"raw": raw, "qty": qty, "card_key": card_key}
    return {"raw": raw, "qty": qty, "name": rest.strip()}
