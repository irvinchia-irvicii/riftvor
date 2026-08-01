# Riftvor — Build PRD (v4, final)

**Project:** Riftvor — Riftbound (League of Legends TCG) singles price scraper for the Singapore market
**Owner:** Trevor (aerialist88) · **Repo:** github.com/aerialist88/riftvor (rename from `Riftbound-Fetch`)
**Sibling project:** 3vor Fetch (`gishath-local-v2`) — MTG. Riftvor is standalone; the MTG repo is never modified.
**Date:** 1 Aug 2026 · All store endpoints below were live-probed on this date.

---

## 1. Problem

Riftbound singles are sold across a scattered set of SG stores with no price-comparison layer. Trevor wants the 3vor Fetch experience for Riftbound: paste a buy list → one SGD price-comparison table across every SG store selling singles, with watchlist alerts, price history, and xlsx export. Riftbound moves fast (Vendetta released 31 Jul 2026, Radiance due 23 Oct 2026), so data must be live at query time, not batch-stale.

## 2. Decisions already made (do not relitigate)

1. **Standalone repo**, Python only. No Go engine. Port code from 3vor Fetch where useful, keeping file names/interfaces recognisable so fixes stay diff-portable between siblings.
2. **Live-sync-on-search architecture** (§4) — NOT nightly-batch-only, NOT per-card live scraping.
3. **Full feature parity**: watchlist + email alerts, price history, saved buy lists, xlsx export.
4. **EN-only v1**; CN listings must be *detected and excluded* from day one (stores interleave them).
5. Scope order: 6 core stores → dormant store polling → Carousell best-effort → (v1.1+) Kyo Cards.
6. Machine: M5 MacBook Air 32 GB. Stack: Python 3.12+, Flask, httpx, SQLite, openpyxl. **No Playwright in v1** (reserve only — see §5 Carousell).

## 3. Success criteria

- Buy list in → comparison table across all active stores in ≤ ~5 s (fresh sync) or instantly (within TTL), SGD, with stock, foil/finish, direct product links, card art.
- Data freshness: never older than the user's search click + TTL (default 5 min, configurable). Force-refresh button bypasses TTL.
- Watchlist (card + target price) checked on every sync + nightly; email alert on trigger (port 3vor Fetch's watchlist/email code).
- Price history chart per card per store; nightly heartbeat sync guarantees ≥1 datapoint/day for every card at every store.
- xlsx export of any comparison table.
- Polite scraping: per-domain rate limiting, honest User-Agent, TTL cache, circuit breaker on repeated failures (port breaker pattern from `playwright_scraper.py`).

## 4. Architecture

```
buy list ──> search handler ──> sync orchestrator (async httpx, parallel)
                                    │  per store: TTL fresh? serve cache : pull full catalog
                                    ▼
                            normaliser (per-store title parsers → canonical listing)
                                    ▼
                     SQLite: listings (current) + price_history (append-only)
                                    ▼
                match buy list rows (collector-number first, name fallback)
                                    ▼
              Flask UI: comparison table · watchlist · history charts · xlsx
```

**Live-sync-on-search:** a search triggers a parallel pull of every active store's *entire* Riftbound singles catalog (1–4 paginated requests each, ~20 requests total — cheaper AND fresher than per-card searching for lists ≥ ~4 cards). Results answer the query and are snapshotted into history.
**TTL cache:** default 300 s per store; searches within TTL reuse the cached catalog. Force-refresh bypasses.
**Nightly heartbeat:** cron/launchd script runs one sync purely for history continuity + watchlist check (port `run_nightly.sh` pattern).
**Cards Central exception:** their API is per-query by design → called live per buy-list card (async, parallel), not catalog-synced. Its results skip the TTL cache.

## 5. Store integrations (probed 1 Aug 2026)

### Active — Shopify catalog sync (5 stores)

All use `GET {base}/collections/{handle}/products.json?limit=250&page=N` (loop until empty page). Prices SGD. Parse per-store title formats below; every store embeds the collector number — the canonical key.

| Store | Base | Collection handle(s) | Title format example | Variant/foil signals |
|---|---|---|---|---|
| **Hideout** | hideoutcg.com | `riftbound-singles` | `Dazzling Aurora [OGN-160/298]`; CN prefixed `[Chinese]` | variants `Near Mint` / `Near Mint Foil`; tags incl. `OGN`, `SFD CN` |
| **Tefuda** | tefudagames.com | `riftbound-spiritforged-singles`, `riftbound-unleashed-singles` (enumerate more via `/collections.json`, filter `riftbound.*singles`) | `Evelynn - Entrancing [UNL - 141/219] Unleashed` | single default variant; tags: rarity, `Showcase`, `English`; `(Overnumbered)` in title for overnumbered showcases |
| **4 Elements** | 4elements.sg | `riftbound-singles` | `Charm [OGN-043/298] [Origins]` | variant title = condition (`Near Mint`); tags: rarity + color |
| **GOAT TCG** | goattcg.com | EN + CN collections per set — enumerate via `/collections.json`, keep EN only | `Yasuo - Unforgiven (259/298) - Origins Foil`; alt art `(076a/298)` | `Foil` in title; separate CN collections (exclude) |
| **Team Card Game** | teamcardgame.com | `riftbound-origin-singles-ogn`, `riftbound-spiritforged-singles-sfd`, `riftbound-unleashed-singles`, `riftbound-runes-tokens` | `Discipline (058/298)` | NM pricing; foil variants |

Implementation notes: one generic `ShopifyCatalogStore` class + per-store config (base URL, handles or handle-discovery regex, title parser). Collection handles WILL change as sets release — discover handles via `/collections.json` filtered by regex at sync time rather than hardcoding, falling back to configured list. If a store's `products.json` starts getting challenged (Hideout sits behind BinderPOS/Cloudflare; JSON endpoint was open when probed), retry via `curl_cffi` Chrome impersonation (dependency already familiar from 3vor Fetch) before declaring the store down.

### Active — API (1 store, pending one manual check)

**Cards Central** — custom platform, purpose-built aggregator API: `GET https://cardscentral.com/api/lgs/search?q=<card name>` → JSON array (name, set, price, cheapest-first; see 3vor Fetch `engine-src/api/gateway/cardscentral/search.go` for the MTG response shape). **GATE:** the feed was documented MTG-filtered; whether it returns Riftbound is unverified (robots-blocked to remote fetchers). First build step: run `curl "https://cardscentral.com/api/lgs/search?q=Yasuo"` locally. If Riftbound absent → fall back to scraping `cardscentral.com/shop/riftbound` per-set index pages (server-rendered; URL pattern `/card/<name-code-num>`).

### Dormant (auto-enable watchers — Shopify, sealed-only or no stock today)

**1Collectibles** (1collectibles.com), **Cardboard Collectible** (cardboardcollectible.com), **Sentinel Games** (sentinelgamessg.com): weekly poll of `/search/suggest.json?q=riftbound&resources[type]=product`; if a result with a singles-like handle appears (not `sealed-*`), surface a "new store selling singles?" notice in the UI. Also on the watch-later list (no Riftbound singles online as of probe): Flagship, Grey Ogre, OneMtg, Dueller's Point, Games Haven, Card Connect, Hideyoshi, Card Arena, Gamersaurus Rex (robots-blocked).

### Best-effort (build last within v1; cut to v1.1 if it drags)

**Carousell** — `carousell.sg/hobbies-toys/toys-games/riftbound/q-12/` is server-rendered and was accessible to a plain fetch; ~60% singles, freeform titles. Fuzzy name matching only (no collector numbers), aggressive noise filters (drop: lots/bundles/"WTB"/sealed keywords), show as a separate "P2P listings" panel — never merged into the store comparison rows. If blocked at build time, this is the ONLY component allowed to bring in Playwright.

### Deferred v1.1

**Kyo Cards** (kyocards.com) — Next.js marketplace, SGD; sealed-only today, Riftbound productLine code not exposed. Revisit when their singles market exists.

## 6. Canonical data model

Card identity = **collector number**: `SET-NNN[a]` (e.g. `OGN-043`, `OGN-076a` alt-art, `UNL-225` overnumbered where 225 > set size 219). Sets: OGN (298), SFD (221), UNL (219), VEN, PG/promos, RAD (Oct 2026).

```sql
cards(card_key TEXT PK,          -- 'OGN-043'
      set_code TEXT, number TEXT, name TEXT, rarity TEXT, color TEXT,
      is_alt_art BOOL, img_url TEXT)

listings(store TEXT, card_key TEXT NULL,   -- NULL for unmatched/Carousell
         title_raw TEXT, url TEXT, price REAL, currency TEXT DEFAULT 'SGD',
         finish TEXT,                       -- 'nonfoil' | 'foil'
         condition TEXT DEFAULT 'Near Mint',
         in_stock BOOL, language TEXT DEFAULT 'EN',
         synced_at TIMESTAMP,
         PRIMARY KEY (store, url, finish, condition))

price_history(store, card_key, finish, price, in_stock, seen_at)  -- append per sync
watchlist(card_key, finish, target_price, email_sent_at)
buy_lists(name, created_at) / buy_list_items(list_name, card_key NULL, raw_query)
```

Title parsers (one per store, unit-tested against the real examples in §5):
- Extract `SET`, `NNN[a]`, name, `Foil`, `(Alternate Art)`, `(Overnumbered)`, `[Chinese]`/CN markers.
- Regexes to start from: `\[(OGN|SFD|UNL|VEN|PG|RAD)\s*-\s*(\d{3}[a-z]?)/\d+\]` (Hideout/Tefuda/4E) and `\((\d{3}[a-z]?)/(\d+)\)` + set-name→code map (GOAT/TCG).

Filters (Riftbound keep-list, inverse of 3vor Fetch's `filters.py` drop-list): drop sealed (`booster`, `box`, `display`, `champion deck`, `vault`, `bundle`, `case`, `proving grounds box`), accessories (port `_ACCESSORY_KEYWORDS`), other games (`pokemon`, `mtg`, `magic`, `one piece`, `lorcana`, `grand archive`, …), CN (`[chinese]`, ` cn`, `chinese` in title/tags/handle). Keep runes/tokens (Team Card Game sells them as singles — they're playable Riftbound cards).

## 7. Card index & art

Seed `cards` from the **union of store catalogs** keyed by collector number (name/rarity/color backfilled from store tags) — zero third-party dependency. Art: RiftMana's predictable URLs — `https://riftmana.com/wp-content/uploads/Cards/<SET-NNN>.webp` (`-p` suffix variants for alt versions); cache images locally on first use; fall back to the store's own product image (present in every Shopify `products.json`) if RiftMana 404s. Cross-check source if needed: riftbound.one (`/cards/<SET-NUM>-160w.webp`, daily-synced, card pages `/card/<SET-NUM>-<name>`). Neither site has an API — do not scrape them beyond image GETs.

## 8. App surface (Flask, port the 3vor Fetch dashboard skeleton)

- `POST /api/search` — buy list (textarea: names and/or collector numbers) → triggers sync (TTL-aware) → comparison table JSON. Autocomplete from `cards` (port `card_index.py` pattern, local SQLite instead of Scryfall).
- Comparison table: rows = buy-list cards (grouped nonfoil/foil), columns = stores, cell = cheapest in-stock listing + link; unmatched rows flagged. Carousell panel below, separate.
- `POST /api/refresh` — force sync (bypass TTL). Show per-store sync age in the header.
- Watchlist CRUD + email (port `watchlist.py`, `check_watchlist.py` SMTP setup).
- Price history endpoint + chart per card (port `price_history.py`, now backed by SQLite).
- xlsx export (openpyxl, port export shape).
- `run_nightly.sh` equivalent: heartbeat sync + watchlist check via launchd/cron.

## 9. Build order (each phase ends runnable + committed)

1. **Scaffold + gate check**: repo `riftvor`, venv, config; run the Cards Central curl and record the answer in README. Generic `ShopifyCatalogStore` + Hideout config; print a raw catalog to prove the pipe.
2. **Normalisation**: 5 title parsers + filters + SQLite schema; unit tests using §5's real title examples; full 5-store sync writing `listings` + `price_history`.
3. **Search + UI**: buy-list matching (collector-number first, token-name fallback), TTL cache, Flask comparison table, force-refresh, autocomplete.
4. **Cards Central integration** (API or scrape path per gate result).
5. **Parity features**: watchlist + email, history charts, xlsx, nightly heartbeat, dormant-store weekly poller.
6. **Carousell best-effort panel** (time-boxed; cut to v1.1 without guilt).

## 10. Constraints & politeness

Parallel across stores, sequential-with-delay (≥500 ms) between pages within a store; timeout 15 s; 2 retries; per-store circuit breaker (3 consecutive failures → 10 min cooldown — port the breaker semantics). Honest UA string (`Riftvor/1.0 personal price tracker`). Respect TTL religiously — no sync storms. All state in repo-local `state/` (gitignored), code in git from commit one.

## 11. Open items

1. Cards Central Riftbound support — the curl gate (Phase 1).
2. Hideout `products.json` from a residential IP — confirmed open to a remote fetcher; verify locally in Phase 1, `curl_cffi` fallback ready.
3. VEN singles are just landing; RAD (Oct) will need: new set code in regexes (make the set list config, not code), new collection handles (mitigated by handle discovery), card index refresh (automatic via catalog-union design).
4. Locator blind spot: the official UVS locator misses 4 of 6 active stores — periodic manual re-research of the SG market (quarterly) is worth a calendar note.
