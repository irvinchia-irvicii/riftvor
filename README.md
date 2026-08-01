# Riftvor

Riftbound (League of Legends TCG) singles price scraper for the Singapore
market. Paste a buy list → one SGD price-comparison table across every SG
store selling singles, with watchlist email alerts, price history, and xlsx
export.

Sibling of [3vor Fetch](https://github.com/aerialist88/gishath-local-v2)
(MTG) — same architecture ideas, standalone codebase, file names kept
recognisable so fixes stay diff-portable.

## Architecture

**Live-sync-on-search:** a search pulls every active store's entire
Riftbound singles catalog in parallel (Shopify `products.json`, 1–4 pages
each), normalises titles to canonical collector numbers (`OGN-043`),
snapshots prices into SQLite, and answers the query from there. TTL cache
(default 300 s) means repeat searches are instant; force-refresh bypasses.
A nightly heartbeat guarantees ≥1 history datapoint/day and runs the
watchlist check.

## Stores (probed 1 Aug 2026)

| Store | Method |
|---|---|
| Hideout, Tefuda, 4 Elements, GOAT TCG (EN), Team Card Game | Shopify catalog sync, handles auto-discovered via `/collections.json` |
| Cards Central | per-card scrape of the server-rendered shop pages (see gate below) |
| Carousell | best-effort P2P panel, fuzzy name match, never merged into store rows |
| 1Collectibles, Cardboard Collectible, Sentinel Games | dormant — weekly poll, UI notice if singles appear |

### Gate check results (1 Aug 2026, residential IP)

- **Cards Central API** (`/api/lgs/search?q=...`): live and working for MTG
  (`Lightning Bolt` returns results) but **returns `[]` for Riftbound
  queries** (`Yasuo`) → the feed is MTG-filtered as documented. Riftvor uses
  the fallback: scraping `cardscentral.com/shop/riftbound` (server-rendered,
  HTTP 200, ~296 KB). Re-check the API each set release.
- **Hideout `products.json`**: open from a residential IP (no Cloudflare
  challenge); `curl_cffi` Chrome-impersonation fallback is wired in anyway.

## Setup

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python app.py            # http://localhost:5009
```

Watchlist email alerts need a repo-local `.env` (gitignored):

```
RIFTVOR_EMAIL_FROM=you@gmail.com
RIFTVOR_SMTP_APP_PASSWORD=<gmail app password>
```

Nightly heartbeat: `./run_nightly.sh` via cron/launchd (see
`install_nightly.command`).

## Tests

```bash
venv/bin/python -m pytest tests/
```

Parser unit tests run against real title examples captured from the live
catalogs — including 4 Elements' `*` overnumbered markers, rune/token
numbering (`UNL-T01`, `SFD-R04a`), dual-faced tokens (`T01 // T05`), and
the Vendetta specials (`VEN-SP3/006`).

## Data model

Card identity = collector number `SET-NNN[a]` (e.g. `OGN-043`, `OGN-076a`
alt-art, `UNL-225` overnumbered). SQLite in `state/riftvor.db` (gitignored):
`cards` (index seeded from the union of store catalogs — no third-party
dependency), `listings` (current), `price_history` (append-only),
`watchlist`, `buy_lists`, `sync_meta`. Card art via RiftMana's predictable
URLs, cached locally, store product image as fallback.

## Politeness

Parallel across stores, ≥500 ms between pages within a store, 15 s timeout,
2 retries, per-store circuit breaker (3 consecutive failures → 10 min
cooldown), honest UA (`Riftvor/1.0 personal price tracker`), TTL respected
religiously.
