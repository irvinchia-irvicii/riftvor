"""config.py — Riftvor configuration: stores, sets, politeness, paths.

Sibling of 3vor Fetch (gishath-local-v2). File names/interfaces are kept
recognisable so fixes stay diff-portable between the two projects.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = BASE_DIR / "state"
STATE_DIR.mkdir(exist_ok=True)
DB_PATH = STATE_DIR / "riftvor.db"
ART_DIR = STATE_DIR / "art"

PORT = int(os.environ.get("RIFTVOR_PORT", 5009))

# ── Politeness (§10 of the PRD) ─────────────────────────────────────────────
USER_AGENT = "Riftvor/1.0 personal price tracker"
TTL_SECONDS = int(os.environ.get("RIFTVOR_TTL_SECONDS", 300))
PAGE_DELAY_S = 0.5          # sequential delay between pages within one store
TIMEOUT_S = 15.0
RETRIES = 2
BREAKER_THRESHOLD = 3       # consecutive failures before a store is benched
BREAKER_COOLDOWN_S = 600

# ── Sets (config, not code — add new codes here as sets release) ────────────
# code -> (display name, printed set size or None if not yet known)
SETS: dict[str, tuple[str, int | None]] = {
    "OGN": ("Origins", 298),
    "SFD": ("Spiritforged", 221),
    "UNL": ("Unleashed", 219),
    "VEN": ("Vendetta", None),
    "OGS": ("Origins Proving Grounds", 24),   # 4E: [OGS-001/024]
    "PG": ("Proving Grounds", None),
    "RAD": ("Radiance", None),
}

# Store titles spell sets out by name (GOAT, Tefuda suffixes) — map back to codes.
SET_NAME_TO_CODE: dict[str, str] = {
    "origins": "OGN",
    "origin": "OGN",
    "spiritforged": "SFD",
    "spirit forged": "SFD",
    "unleashed": "UNL",
    "vendetta": "VEN",
    "origins proving grounds": "OGS",
    "proving grounds": "OGS",
    "radiance": "RAD",
}

# ── Active Shopify catalog-sync stores (§5, probed 1 Aug 2026) ──────────────
# Collection handles WILL change as sets release: handles are discovered at
# sync time via /collections.json filtered by `discover`, with `handles` as
# the fallback when discovery fails.
STORES: list[dict] = [
    {
        "key": "hideout",
        "name": "Hideout",
        "base": "https://hideoutcg.com",
        "handles": ["riftbound-singles"],
        "discover": {"regex": r"riftbound.*singles"},
        "parser": "hideout",
    },
    {
        "key": "tefuda",
        "name": "Tefuda",
        "base": "https://tefudagames.com",
        "handles": [
            "riftbound-spiritforged-singles",
            "riftbound-unleashed-singles",
        ],
        # `-copy` collections duplicate products; `chinese-*` are CN sealed.
        "discover": {"regex": r"riftbound.*singles", "exclude_regex": r"chinese|-copy$"},
        "parser": "tefuda",
    },
    {
        "key": "4elements",
        "name": "4 Elements",
        "base": "https://4elements.sg",
        "handles": ["riftbound-singles"],
        "discover": {"regex": r"riftbound.*singles", "exclude_regex": r"chinese"},
        "parser": "fourelements",
    },
    {
        "key": "goat",
        "name": "GOAT TCG",
        "base": "https://goattcg.com",
        "handles": [
            "riftbound-origins-en",
            "riftbound-spiritforged-en",
            "riftbound-unleashed-en",
        ],
        # GOAT keeps EN + CN collections per set; EN ones end in `-en`
        # (titles carry "(EN)"). Keep EN only.
        "discover": {"regex": r"riftbound.*-en$"},
        "parser": "goat",
    },
    {
        "key": "teamcardgame",
        "name": "Team Card Game",
        "base": "https://teamcardgame.com",
        "handles": [
            "riftbound-origin-singles-ogn",
            "riftbound-spiritforged-singles-sfd",
            "riftbound-unleashed-singles",
            "riftbound-runes-tokens",
        ],
        "discover": {
            "regex": r"riftbound.*(singles|runes|tokens)",
            "exclude_regex": r"chinese|\bcn\b",
        },
        "parser": "teamcardgame",
    },
]

STORE_BY_KEY = {s["key"]: s for s in STORES}
STORE_ORDER = [s["key"] for s in STORES]

# ── Cards Central (§5) — per-query aggregator, scrape path (gate: API is
# MTG-only as of 1 Aug 2026; /api/lgs/search?q=Yasuo returns []) ────────────
CARDS_CENTRAL = {
    "key": "cardscentral",
    "name": "Cards Central",
    "base": "https://cardscentral.com",
    "api_search": "https://cardscentral.com/api/lgs/search",  # re-check per release
    "shop_riftbound": "https://cardscentral.com/shop/riftbound",
}

# ── Dormant stores (§5) — weekly poll; surface a notice if singles appear ───
DORMANT_STORES: list[dict] = [
    {"name": "1Collectibles", "base": "https://1collectibles.com"},
    {"name": "Cardboard Collectible", "base": "https://cardboardcollectible.com"},
    {"name": "Sentinel Games", "base": "https://sentinelgamessg.com"},
]

# ── Carousell best-effort P2P panel (§5) ────────────────────────────────────
CAROUSELL_URL = "https://www.carousell.sg/hobbies-toys/toys-games/riftbound/q-12/"

# ── Card art (§7) ───────────────────────────────────────────────────────────
RIFTMANA_ART_URL = "https://riftmana.com/wp-content/uploads/Cards/{card_key}.webp"

# ── Email (watchlist alerts) — creds live in repo-local .env (gitignored) ───
ENV_PATH = BASE_DIR / ".env"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_FROM_ENV = "RIFTVOR_EMAIL_FROM"
SMTP_APP_PASSWORD_ENV = "RIFTVOR_SMTP_APP_PASSWORD"
EMAIL_TO_ENV = "RIFTVOR_EMAIL_TO"  # optional; defaults to EMAIL_FROM


def load_env() -> None:
    """Load repo-local .env into os.environ (existing env vars win)."""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())
