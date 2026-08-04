"""config.py — Riftvor configuration: stores, sets, politeness, paths.

Sibling of 3vor Fetch (gishath-local-v2). File names/interfaces are kept
recognisable so fixes stay diff-portable between the two projects.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = BASE_DIR / "state"
STATE_DIR.mkdir(exist_ok=True)
DB_PATH = STATE_DIR / "riftvor.db"
ART_DIR = STATE_DIR / "art"

# ── Repo-local .env (gitignored) ────────────────────────────────────────────
# Loaded before anything below reads os.environ so the file can configure the
# whole app, not just email. Real environment variables always win, which is
# what makes hosted deployments (Render env vars) authoritative.
ENV_PATH = BASE_DIR / ".env"


def load_env() -> None:
    """Load repo-local .env into os.environ (existing env vars win)."""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


load_env()

PORT = int(os.environ.get("RIFTVOR_PORT", 5009))
# Localhost-only by default. RIFTVOR_HOST is the declared exposure intent:
# anything other than a loopback address means "reachable by other people",
# and app.py refuses to start in that state without RIFTVOR_AUTH_PASSWORD.
# (Under gunicorn the actual bind comes from the start command; this value
# is still read, so the guard holds there too.)
HOST = os.environ.get("RIFTVOR_HOST", "127.0.0.1")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

# Public origin, used in alert email bodies. Locally this is the dev server;
# on Render, set RIFTVOR_BASE_URL to the service URL.
BASE_URL = os.environ.get("RIFTVOR_BASE_URL", f"http://127.0.0.1:{PORT}/")

# ── HTTP basic auth (HOSTING.md Stage 0 prep #3) ────────────────────────────
# Unset password = disabled, which keeps local single-user use exactly as it
# was. Set it and every route except /api/health requires credentials.
AUTH_USER = os.environ.get("RIFTVOR_AUTH_USER", "riftvor")
AUTH_PASSWORD = os.environ.get("RIFTVOR_AUTH_PASSWORD", "")

# Flask account sessions. Hosted deployments should set RIFTVOR_SECRET_KEY
# explicitly so sessions survive deploys. Local development gets a stable,
# randomly-generated key stored under state/ (which is already gitignored).
SESSION_SECRET_PATH = STATE_DIR / ".session_secret"


def _session_secret() -> str:
    configured = os.environ.get("RIFTVOR_SECRET_KEY", "").strip()
    if configured:
        return configured
    if SESSION_SECRET_PATH.exists():
        saved = SESSION_SECRET_PATH.read_text(encoding="utf-8").strip()
        if saved:
            return saved
    generated = secrets.token_urlsafe(48)
    SESSION_SECRET_PATH.write_text(generated, encoding="utf-8")
    return generated


SESSION_SECRET = _session_secret()
SESSION_COOKIE_SECURE = os.environ.get("RIFTVOR_SESSION_COOKIE_SECURE", "0") == "1"


def auth_enabled() -> bool:
    return bool(AUTH_PASSWORD)

# ── Politeness (§10 of the PRD) ─────────────────────────────────────────────
USER_AGENT = "Riftvor/1.0 personal price tracker"
TTL_SECONDS = int(os.environ.get("RIFTVOR_TTL_SECONDS", 300))

# Pacing. The defaults are the residential ones and are deliberately
# unchanged — a datacenter IP's problem is no reason to slow down the Mac.
# render.yaml turns the polite path on; nothing else does.
PAGE_DELAY_S = float(os.environ.get("RIFTVOR_PAGE_DELAY_S", 0.5))
# Jitter on top of every delay. A metronome-exact interval is itself a bot
# signal; 3vor Fetch pairs a 300 ms floor with 0–600 ms of jitter for the
# same reason (its domain_rate_limiter.go).
PAGE_JITTER_S = float(os.environ.get("RIFTVOR_PAGE_JITTER_S", 0.6))
# Stores are synced in parallel by default (fast, and fine spread across five
# different hosts). Sequential mode exists because from Render's IP the stores
# throttle hard — see HOSTING.md "Stage 0 result".
SEQUENTIAL_SYNC = os.environ.get("RIFTVOR_SEQUENTIAL_SYNC", "0") == "1"
STORE_DELAY_S = float(os.environ.get("RIFTVOR_STORE_DELAY_S", 10.0))

# ── Egress proxy (HOSTING.md "Stage 0 result") ──────────────────────────────
# Shopify's edge refuses this app from datacenter IPs — not rate-based, so no
# amount of pacing fixes it. 3vor Fetch hit the identical wall and says so in
# its own source (binderpos/storefront.go: "direct calls (no proxy) fail for
# Shopify/Cloudflare stores ... a residential proxy is required").
#
# Unset = direct, which is what the Mac wants: the residential path has never
# needed this. Accepts a full URL (http://user:pass@host:port) or 3vor Fetch's
# pipe format (host|port|user|pass) so credentials stay portable between the
# two projects.
_PROXY_RAW = os.environ.get("RIFTVOR_PROXY_URL", "").strip()


def _parse_proxy(raw: str) -> str:
    if not raw or "://" in raw:
        return raw
    parts = [p.strip() for p in raw.split("|")]
    host, port = (parts + ["", ""])[:2]
    user, password = (parts[2:] + ["", ""])[:2]
    if not host or not port:
        return ""
    auth = f"{user}:{password}@" if (user or password) else ""
    return f"http://{auth}{host}:{port}"


PROXY_URL = _parse_proxy(_PROXY_RAW)


def proxy_label() -> str:
    """Host:port only — never let credentials reach a log line."""
    if not PROXY_URL:
        return "direct"
    tail = PROXY_URL.split("://", 1)[-1]
    return tail.rsplit("@", 1)[-1] or "direct"
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
        # BinderPOS decklist widget — the only SG store with bulk entry
        # (probed 1 Aug 2026; the other four 404 on this path).
        "multi_search": "https://hideoutcg.com/pages/multi-card-search",
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
# (ENV_PATH / load_env live at the top: they run before anything reads env.)
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_FROM_ENV = "RIFTVOR_EMAIL_FROM"
SMTP_APP_PASSWORD_ENV = "RIFTVOR_SMTP_APP_PASSWORD"
EMAIL_TO_ENV = "RIFTVOR_EMAIL_TO"  # optional; defaults to EMAIL_FROM
