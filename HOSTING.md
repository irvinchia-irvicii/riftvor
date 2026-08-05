# Riftvor — Hosting & Productization Plan

**Date:** 1 Aug 2026 · **Platform decision: Render** (confirmed by Trevor)
**Goal:** host Riftvor publicly as a freemium paid SaaS — free price comparison;
paid watchlist / price history / xlsx export. Open signup, unknown ceiling.
**Status:** Stage 0 **run — the gate FAILED** (1 Aug 2026, riftvor.onrender.com,
free instance, singapore). Zero of five stores synced from Render's IP. See
"Stage 0 result" below. The fork is live: Stage A as written is blocked.

Companion to `riftvor-prd.md` (the v4 build PRD). That document covers the
local single-user build; this one covers what changes to host it.

---

## Why staged

The app works today because it runs on one Mac, on a residential IP, for one
user. Public paid hosting breaks all three assumptions at once. The plan
breaks them one at a time, cheapest and most reversible first, so every risk
is tested at the moment it costs the least to discover.

The single biggest unknown is not hosting — it is whether the five SG stores
and Cards Central respond to a scraper calling from a **datacenter IP**.
Every gate check ever run (README, 1 Aug 2026) was from a residential IP.
Cloud ASNs are exactly what Cloudflare/Shopify bot-protection profiles.
That question gates everything, so it is Stage 0.

---

## Stage 0 — egress gate test ($0, ~1 hour)

Deploy the repo as-is to a **free Render instance, Singapore region**. Run
one forced sync (`POST /api/refresh`). Read the per-store results in
`sync_meta`.

Expected outcomes, ranked:

- **5 Shopify stores** — likely OK: `products.json` is a public feed, and
  `stores.py` already falls back to `curl_cffi` Chrome impersonation on
  403/429/503.
- **Cards Central** — coin flip (server-rendered scrape path).
- **Carousell** — most likely casualty: it already 403s a plain fetch from a
  residential IP and only passes via Chrome impersonation. Acceptable — it is
  a best-effort panel and degrades to empty gracefully.

**Decision fork:** pass → Stage A. Fail (stores challenge/block) → split
architecture: scraper stays on a residential-flavored origin (the Mac via the
existing nightly pattern, or a residential proxy on the `curl_cffi` client),
web/auth/billing tier lives on Render, the two share Postgres. Render stays
the home of the web tier either way, so no work is wasted.

**Prep commit — done (1 Aug 2026):**

1. ✅ `gunicorn` + `flask-httpauth` in requirements; start command is
   `gunicorn --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:$PORT app:app`
   (`--timeout 120` added: a cold forced sync of five catalogs outruns the
   30 s default and gunicorn would kill the worker mid-sync)
2. ✅ `render.yaml` — free plan, singapore region, `healthCheckPath /api/health`
3. ✅ Basic auth (`app.py`, `before_request` gate over every route except
   `/api/health`, which Render probes unauthenticated). Off when
   `RIFTVOR_AUTH_PASSWORD` is unset, so local use is unchanged — and
   `RIFTVOR_HOST=0.0.0.0` **without** a password now refuses to boot rather
   than serving an open instance (gotcha #4 is a live abuse surface).
4. ✅ `RIFTVOR_BASE_URL` — gotcha #5 fixed
5. ✅ `POST /api/nightly` — sync + watchlist + dormant poll in-process

Verified locally under the real start command: unauthed `/` → 401, authed →
200, `/api/health` → 200 unauthed, boot guard fires, 39 tests still pass.

**To run the gate test** (needs a Render account — not doable from here):

1. Push `main` to `github.com/aerialist88/riftvor`
2. Render → New → Blueprint → pick the repo (it reads `render.yaml`)
3. Confirm the review username/password hash variables and set
   `RIFTVOR_BASE_URL` to the assigned service URL
4. `curl -u riotgames:<pw> -X POST https://<service>.onrender.com/api/refresh`
5. Read the verdict — per-store `ok` / `message`:
   `curl -su riotgames:<pw> https://<service>.onrender.com/api/state`

First request cold-starts a free instance (~1 min); the sync itself runs
30–90 s. A store that answers reports `ok: true` with a listing count; a
blocked one reports `fetch failed/breaker open`.

Note: Singapore *region* does not dodge bot detection (Cloudflare classifies
by ASN, not geography) — but it gives the lowest latency to the SG stores and
SG users, so it is the right region regardless.

## Stage 0 result (1 Aug 2026, ~14:44 SGT)

`POST /api/refresh` against riftvor.onrender.com, free instance, singapore
region. **Zero of five stores produced a usable catalog.**

| Store | Status | What answered |
|---|---|---|
| hideout | `partial` | page 1 only (250 products); page 2 unanswered |
| teamcardgame | `partial` | 1 of 4 handles (203 products); discovery unanswered |
| tefuda | `failed` | nothing — discovery + both handles unanswered |
| 4elements | `failed` | nothing |
| goat | `failed` | `/collections.json` answered; all 3 `/products.json` did not |

Both partials were discarded rather than written. Under the pre-fix code this
same run would have reported hideout and teamcardgame as `ok` and replaced
their complete local catalogs with 250 and 203 products.

**This is throttling, not an ASN block.** Hideout served page 1 and refused
page 2; GOAT served collections.json and refused every products.json. A
blanket ASN block refuses the first request too. The `curl_cffi` Chrome
impersonation fallback is wired in and did not rescue it.

**Control:** the same commit, from Trevor's residential IP, ~20 minutes
earlier: all five stores `ok`, 8,450 listings, same `PAGE_DELAY_S`, same
cross-store parallelism. Same code, same hour, same targets — only the
egress IP differs.

**Caveat, unresolved:** three forced syncs ran from that Render IP within
~40 minutes. Some of the escalation may be self-inflicted rather than
standing policy. The cheap disambiguation before committing to the split
architecture, in order:

1. Leave the Render instance idle ≥1 hour.
2. ✅ **Built.** Polite pacing, enabled only in `render.yaml`:
   `RIFTVOR_SEQUENTIAL_SYNC=1` (one store at a time, not five at once),
   `RIFTVOR_PAGE_DELAY_S=3` (was 0.5), `RIFTVOR_STORE_DELAY_S=10`. The Mac
   keeps the fast parallel defaults — a datacenter IP's problem is no reason
   to slow the residential path, and a test guards that promise.
   A full crawl at these settings runs several minutes, so `/api/refresh`
   returns `202` immediately and the sync continues detached; poll
   `GET /api/state` until `syncing` is false, then read `ages`.
3. One single forced sync. If it still returns nothing, the IP is the cause
   and the split architecture is justified. If it succeeds, this was pacing,
   and hosted scraping stays viable at a slower cadence — which is enough,
   because catalog data is global and cached, so store load is independent of
   user count. One good sync per interval is all the product needs.

Note for Stage A: `/api/nightly` is still synchronous, so under sequential
pacing a Render Cron Job curling it will outrun the request timeout. Point it
at the detached path or give it the background treatment before Stage A.

**Pacing re-test (1 Aug 2026, +98 min idle, sequential, 3 s pages): no
change.** Still zero usable catalogs; GOAT moved `failed` → `partial`, which
is noise. Decisive detail: `/collections.json` was refused for *every* store
in the same 90 seconds. Five unrelated merchants on five domains do not
coordinate a rate limit — what they share is Shopify. This is the platform
edge making a reputation call on the IP, which is why no pacing setting
touches it. **Pacing hypothesis closed.**

### Confirmed by 3vor Fetch

The sibling project reached the same conclusion and wrote it in its source.
`api/gateway/binderpos/storefront.go:12`:

> "direct calls (no proxy) fail for Shopify/Cloudflare stores … a residential
> proxy via DYNAMIC_PROXY env var is required"

Its AWS Lambda runs outside a VPC, so it egresses from `ap-southeast-1`
datacenter IPs and hits exactly this wall; its whole proxy tier
(`DEDICATED_PROXY_1..7`, `DYNAMIC_PROXY`, `RESIDENTIAL_PROXY_1`) exists to
work around it. Its strategy ladder puts the proxied attempt *first*, and
`searchByStorefrontAPI` refuses to run without one. That is working
precedent, not speculation.

### Proxy support — built (1 Aug 2026)

`RIFTVOR_PROXY_URL`, set only in the Render dashboard (it carries
credentials). Accepts `http://user:pass@host:port` or 3vor Fetch's
`host|port|user|pass`, so credentials stay portable between the projects.
Unset = direct, which is what the Mac wants.

All five egress paths honour it — `stores.py` (httpx + the `curl_cffi`
fallback), `cards_central.py`, `carousell.py`, `dormant_poll.py. One missed
client would leak the real IP and re-trip the block the proxy exists to
avoid, so `stores.make_client()` is the single place outbound traffic is
configured and a test pins that. Credentials never reach a log line.

Pacing also gained jitter (`PAGE_JITTER_S`, 0–0.6 s on top of every delay) —
a metronome-exact interval is itself a bot signal, which is why 3vor Fetch
pairs its 300 ms floor with 0–600 ms of jitter.

**Still needed: a proxy provider account.** Costs should be far lower here
than for 3vor Fetch, which caches nothing and scrapes live on every user
query. Riftvor's catalog is global and TTL-cached, so proxy traffic is one
sync per interval *regardless of user count* — roughly 5–10 MB per full
five-store sync. At typical residential rates that is low single-digit
dollars a month, provided sync frequency stays controlled.

## Stage A — private hosted single-user (~$7.25/mo)

### Private review deployment (current)

The Render blueprint sets `RIFTVOR_CATALOG_MODE=snapshot`. A new Render
database is bootstrapped from `data/catalog_snapshot.json.gz`, which contains
only public card, shop-listing, external-price, and FX rows. It contains no
accounts, passwords, collections, saved lists, consent records, analytics
events, or retailer sign-ups.

This makes search reliable for Riot/private review even though Render's
datacenter IP cannot refresh the Shopify catalogues. The UI labels these
prices as a review snapshot, live Cards Central/Carousell requests are skipped,
and `/api/refresh` is disabled. Run `scripts/build_catalog_snapshot.py` locally
and deploy its output when a newer approved review snapshot is needed. This is
a review bridge, not the production live-data architecture.

Starter instance ($7/mo) + 1 GB persistent disk ($0.25/GB/mo) mounted at
`state/`. Keep SQLite. Basic auth, single user: Trevor.

Purpose beyond convenience: this is a **weeks-long soak test** of scraping
stability from Render's IP — data to have *before* charging anyone. Free
instances are disqualified for real use (15-min idle spin-down, ~1-min cold
start).

Nightly heartbeat on Render: a Cron Job whose only body is
`curl -X POST` against the authenticated `/api/nightly` endpoint
(runs sync + watchlist + dormant poll in-process, where the DB is).

## Stage B — public freemium SaaS

Enter only after Stage A runs clean for a few weeks. Its own PRD before any
code — this is a real build, not a deploy:

- **SQLite → Postgres** (Render managed, from ~$6/mo; the free Postgres tier
  expires after 30 days — do not build on it).
- **Tenancy:** add `user_id` to `watchlist`, `buy_lists`, `collection` only.
  Catalog data (`cards`, `listings`, `price_history`) stays global/shared —
  the expensive scraping happens once regardless of user count. The global
  TTL cache already makes Shopify-store load independent of traffic.
- **Auth:** Clerk or Supabase Auth — not hand-rolled.
- **Billing:** Stripe Checkout + Billing for the paid tier.
- **Rate limiting** on all endpoints; `force`/`/api/refresh`/`/api/export`
  become paid-tier-gated or heavily limited.
- **Cards Central cache** (60–120 s per card) — mandatory before public
  traffic; see gotcha #6.

---

## Render-specific gotchas (found by reading the code — do not re-derive)

1. **Single process only.** Module-level state everywhere: `_SYNC_LOCK`
   (sync.py), `_BREAKERS` (stores.py), Carousell `_cache`. Multi-worker
   gunicorn silently breaks sync-storm protection and breaker semantics →
   `--workers 1 --threads 8`, no more. Also `sync.ensure_fresh()` calls
   `asyncio.run()` inside Flask request threads — fine threaded, breaks
   under ASGI/uvicorn.
2. **Render Cron Jobs are separate services with separate filesystems** —
   they cannot mount the web service's persistent disk. `nightly.py` as a
   Render cron would write history into a database nobody reads. Hence the
   curl-an-endpoint pattern. This constraint disappears at Postgres.
3. **Persistent disk trade-off:** pins the service to a single instance and
   disables zero-downtime deploys. Acceptable for Stage A; gone at Stage B.
4. **Abuse surfaces:** `/api/refresh`, `force` on `/api/search`, and
   `/api/export` are unauthenticated TTL-bypass / free CPU. Anyone with the
   URL can make *this server* hammer five SG stores on demand. Basic auth at
   Stage A; tier-gate + rate-limit before public.
5. **Bug:** hardcoded `http://127.0.0.1:5009/` in `check_watchlist.py`
   alert emails.
6. **Cards Central bypasses ALL caching by design** (`app.py`, comparison
   assembly): live scrape per search × per user × per distinct card name.
   The one component whose load scales with traffic. Short per-card cache
   is the Stage B gate.

## Costs

| Stage | Monthly | One-off |
|---|---|---|
| 0 | $0 (free instance) | ~1 hr + prep commit |
| A | ~$7.25 (Starter + 1 GB disk) | gaps 1–5 fixed |
| B | ~$13+ (Starter + Postgres) + Stripe fees (~2.9% + 30¢/txn); Clerk free until real user volume | tenancy migration, auth, billing |

## Open item (Trevor's call, unresolved)

Legal/ToS exposure: scraping five competing stores' full catalogs plus Cards
Central's shop pages to power a **commercial** product is a different risk
posture than a personal tracker. Flagged; not a technical question.

## Alternatives considered

Fly.io — matches Render on Singapore, slightly cheaper compute, more ops
attention; runner-up. Hetzner/DO VPS — only relevant as the scraper half of
the split architecture if Stage 0 fails. Serverless (Vercel/Lambda) — poor
fit: the app depends on background threads and a persistent module-level
sync lock. Everything through Stage A is portable to any host in an
afternoon; nothing is one-way.
