"""filters.py — Riftbound singles keep-list + name matching.

Inverse of 3vor Fetch's filters.py drop-list philosophy: we sync whole
"singles" collections, then DROP anything that is sealed product, an
accessory, another game, or a Chinese-language listing (EN-only v1).
Runes/tokens are KEPT — they're playable Riftbound cards (Team Card Game
sells them as singles).

Contents:
    _name_matches(card_name, result_name) -> bool   (ported from 3vor Fetch)
    is_cn(title, handle, tags)            -> bool
    is_dropped(title, handle, tags)       -> bool   (sealed/accessory/other-game)
"""
from __future__ import annotations

import re

# ── Name matching (ported verbatim from 3vor Fetch filters.py) ──────────────


def _name_matches(card_name: str, result_name: str) -> bool:
    """Return True if result_name is a plausible match for card_name.

    Two-stage check:
      1. Fast path: card_name is a literal substring of result_name
         (case-insensitive, whole-word bounded).
      2. Slow path: every word-token in card_name appears as a whole word in
         result_name (word-boundary regex, punctuation stripped from tokens).

    Whole-word matching prevents false positives — the token "the" is not a
    standalone word inside "them", so \\bthe\\b correctly fails to match.
    """
    cn = card_name.lower()
    rn = result_name.lower()

    if re.search(r"\b" + re.escape(cn) + r"\b", rn):
        return True

    tokens = re.findall(r"[a-z0-9']+", cn)
    if not tokens:
        return False
    return all(re.search(r"\b" + re.escape(t) + r"\b", rn) for t in tokens)


# ── Sealed / accessory / other-game drop keywords ───────────────────────────
# Word-boundary regexes: "Showcase" must not trip on "case", card names like
# "Boxcar" must not trip on "box".

_SEALED_PATTERNS = [
    r"\bbooster\b",
    r"\bbox\b",
    r"\bboxes\b",
    r"\bdisplay\b",
    r"\bchampion deck\b",
    r"\bvault\b",
    r"\bbundle\b",
    r"\bcase\b",
    r"\bproving grounds box\b",
    r"\bsealed\b",
    r"\bprerelease\b",
    r"\bstarter\b",
]

# Ported from 3vor Fetch _ACCESSORY_KEYWORDS (substring match is safe — no
# real card name contains these).
_ACCESSORY_KEYWORDS = (
    "sleeve",
    "deck box",
    "deckbox",
    "playmat",
    "play mat",
    "binder",
    "life counter",
    "life pad",
    "dice tower",
    "card storage",
    "toploader",
    "top loader",
    "card holder",
    "portfolio",
    "carrying case",
    "dice set",
    "keychain",
    "plush",
    "pin badge",
    "lanyard",
)

_OTHER_GAME_KEYWORDS = (
    "pokemon",
    "pokémon",
    "mtg",
    "magic: the gathering",
    "magic the gathering",
    "one piece",
    "lorcana",
    "grand archive",
    "yugioh",
    "yu-gi-oh",
    "digimon",
    "flesh and blood",
    "star wars",
    "weiss",
    "vanguard",
    "dragon ball",
    "gundam",
    "union arena",
    "shadowverse",
)

_SEALED_RE = re.compile("|".join(_SEALED_PATTERNS), re.I)


def is_cn(title: str, handle: str = "", tags: list[str] | None = None) -> bool:
    """Chinese-language listing? Stores interleave CN with EN (§2.4)."""
    t = title.lower()
    if "[chinese]" in t or "chinese" in t:
        return True
    if re.search(r"\bcn\b", t):
        return True
    h = (handle or "").lower()
    if "chinese" in h or h.endswith("-cn") or "-cn-" in h:
        return True
    for tag in tags or []:
        tl = tag.lower()
        if tl == "cn" or tl.endswith(" cn") or "chinese" in tl:
            return True
    return False


def is_dropped(title: str, handle: str = "", tags: list[str] | None = None) -> bool:
    """True if this product is NOT an EN Riftbound single we want."""
    blob = " ".join([title] + (tags or [])).lower()
    if _SEALED_RE.search(blob):
        return True
    for kw in _ACCESSORY_KEYWORDS:
        if kw in blob:
            return True
    for kw in _OTHER_GAME_KEYWORDS:
        if kw in blob:
            return True
    if is_cn(title, handle, tags):
        return True
    return False
