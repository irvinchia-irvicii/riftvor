# Soraka's Wish

*Make a wish list. Let the market answer.*

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

## Purchase plans

The comparison table says what each card costs where; the plan panel says
what to actually buy. Three plans, because the cheapest basket is rarely
the practical one — cherry-picking the floor price usually means ordering
from every store, and each extra store is another postage fee:

- **Cheapest** — cheapest in-stock listing per line, wherever it lives.
- **Fewest stores** — greedy set cover: the fewest stores that still cover
  everything obtainable, with the convenience premium shown against the
  cheapest plan.
- **Best single store** — per-store coverage and cost, ranked by how much
  of the list each store can fill alone.

Plans work per buy-list *line*, not per card: `6 Calm Rune` legitimately
matches several printings and for a buyer those are interchangeable. Lines
matching more than one card are flagged rather than silently guessed.
Stock *depth* is unknown (Shopify publishes an availability boolean, not a
count), so multi-copy lines assume the store can supply the quantity — the
UI and the xlsx both say so.

Pasted deck lists work as-is: section headers (`Legend:`, `MainDeck:`,
`Rune Pool:`, `Sideboard:`) and `//` or `#` comments are skipped.

Each store block in a plan has a **Copy list** button that puts that
shop's cards on the clipboard as `qty Name` per line — the format
BinderPOS-style bulk search boxes expect. Only **Hideout** actually has
one (`/pages/multi-card-search`); the other four Shopify stores and Cards
Central 404 on every bulk-entry path probed on 1 Aug 2026, so only Hideout
shows a **Paste →** link. For the rest the clipboard is still useful for
pasting into a note or a message to the shop.

## Accounts and access tiers

- **Free, no account:** one card line per search.
- **Free account:** multi-card/deck-list search, saved lists, and a private
  collection with cost basis and manual inventory entry.
- **Founder preview:** the first account on an existing local installation gets
  Portfolio Analytics while the feature is being developed. New accounts stay
  on the free-account tier.
- **Portfolio Analytics:** TCGplayer market prices supplied by Riftbound.gg are
  the main benchmark, converted from USD to SGD with the latest daily
  Frankfurter exchange rate and cached for six hours. The dashboard compares
  that benchmark with the median price at connected Singapore shops, then
  shows gains/losses, coverage, allocations, concentration, and a 30-day local
  shop pulse once enough history has accumulated. Bilgewater Market remains
  labelled as unconnected because its feed requires protected credentials; the
  app never invents missing prices.

Riftbound.gg data is displayed with source attribution and links back to its
card pages. Its TCGplayer figures are reference values rather than buyable shop
listings, and portfolio values are estimates rather than guaranteed sale
proceeds.

Local development uses email/password accounts with securely hashed passwords
and per-user SQLite ownership. Google sign-in and email verification are a
hosting-stage addition because they require OAuth credentials and a public
callback URL.

## Consent and community market analytics

Account creation requires acceptance of the development Terms and Privacy
Notice. Community analytics is a separate optional checkbox that defaults off;
existing accounts also remain opted out. A consenting user's research events
contain only the card key, finish, capped quantity, event type, and calendar
day. Search text, email, folder names, notes, prices paid, shop, location, IP,
and exact event time are not copied into the analytics dataset.

Users can withdraw from the Account panel. Withdrawal stops collection and
deletes that account's prior analytics events while leaving its private
collection intact. Retailer aggregates suppress every card row until at least
20 distinct consenting users contribute during the reporting window.

`/retailers` is an approval-stage retailer newsletter waitlist. Billing is
deliberately disabled until Riot Games and relevant data providers approve the
intended use. `/privacy` and `/terms` are development drafts and must receive a
professional review before a public launch. Configure the public privacy/DPO
contact with `RIFTVOR_PRIVACY_CONTACT_EMAIL` when hosting.

## Collection

**+ Add all to collection** on a plan (or **+ Collection** on a single
shop) records what you bought with the price snapshotted at purchase
time. `/collection` shows cost basis against today's cheapest in-stock
price, per line and in total. Cost basis is never recalculated — the gap
is the point. Lines with nothing in stock anywhere are counted as
unpriced and excluded from market value rather than guessed at zero.

Signed-in users can create named collection folders for decks, sideboards,
trades, or individual purchases. Items can be assigned while adding them,
moved between folders later, and filtered by folder. Deleting a folder never
deletes its cards; they return to **Unfiled**.

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
  queries** (`Yasuo`) → the feed is MTG-filtered as documented. Soraka's Wish uses
  the fallback: scraping `cardscentral.com/shop/riftbound` (server-rendered,
  HTTP 200, ~296 KB). Re-check the API each set release.
- **Hideout `products.json`**: open from a residential IP (no Cloudflare
  challenge); `curl_cffi` Chrome-impersonation fallback is wired in anyway.

## Setup

### Windows + Visual Studio Code

1. Install [Python 3](https://www.python.org/downloads/windows/) and select
   **Add python.exe to PATH** in the installer.
2. Open this `riftvor` folder in VS Code. If prompted, install the recommended
   Python extension.
3. Open **Terminal → New Terminal** and run:

```powershell
py -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe app.py
```

4. Open <http://127.0.0.1:5009> in a browser. Keep the terminal open while
   using Soraka's Wish. Press `Ctrl+C` in that terminal to stop it.

After the one-time setup, press `F5` in VS Code and choose **Run Soraka's Wish** to
start it. Run the tests from the terminal with:

```powershell
.\venv\Scripts\python.exe -m pytest tests
```

If `py` is not recognised after installing Python, close and reopen VS Code.

## Working-title and fan-project notice

“Soraka's Wish” is an existing Riot card/ability name, so this is a local
working title—not a trademark clearance. Before a public or paid launch, get
legal advice and Riot approval or choose a fully original product name. The
logo and background in this repository are original generated artwork and do
not depict Soraka or copy Riot artwork.

Soraka's Wish isn't endorsed by Riot Games and doesn't reflect the views or
opinions of Riot Games or anyone officially involved in producing or managing
Riot Games properties. Riot Games and all associated properties are trademarks
or registered trademarks of Riot Games, Inc.

### macOS / Linux

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

## Hosting

`HOSTING.md` is the staged plan for taking this online (Render). The repo
carries the Stage 0 prep: `render.yaml`, a gunicorn start command, and HTTP
basic auth. Optional env vars, all read from the environment or `.env`:

| Var | Default | Effect |
|---|---|---|
| `RIFTVOR_AUTH_USER` | `riftvor` | Basic-auth username |
| `RIFTVOR_AUTH_PASSWORD` | *(unset)* | Set it to require auth on every route except `/api/health`. Unset = off (local single-user default) |
| `RIFTVOR_AUTH_PASSWORD_HASH` | *(unset)* | Preferred hosted alternative: a Werkzeug password hash. When set, it takes precedence over the plaintext password variable. |
| `RIFTVOR_HOST` | `127.0.0.1` | Anything non-loopback declares the app publicly reachable; the app then **refuses to start** without `RIFTVOR_AUTH_PASSWORD` |
| `RIFTVOR_BASE_URL` | `http://127.0.0.1:5009/` | Link written into watchlist alert emails |
| `RIFTVOR_SECRET_KEY` | auto-generated locally | Flask session signing key; set explicitly when hosted |
| `RIFTVOR_SESSION_COOKIE_SECURE` | `0` | Set to `1` behind hosted HTTPS |

`POST /api/nightly` runs the heartbeat (sync + watchlist + dormant poll) in
the web process — Render Cron Jobs get their own filesystem and cannot reach
the web service's disk, so a cron there must curl this rather than run
`nightly.py`.

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
