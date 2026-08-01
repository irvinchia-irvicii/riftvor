"""app.py — Riftvor Flask app (port 5009).

Dashboard skeleton ported from 3vor Fetch: buy-list search → comparison
table, watchlist, history charts, xlsx export, saved buy lists.
/api/status is CORS-open for the dashboard hub card.
"""
from __future__ import annotations

import hmac
import logging
import time

from flask import Flask, jsonify, render_template, request, send_file
from flask_httpauth import HTTPBasicAuth

import basket
import card_art
import cards_central
import carousell
import collection
import config
import db
import export
import matching
import price_history
import sync
import watchlist

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("riftvor")

app = Flask(__name__)
db.init_db()

# ── Auth (HOSTING.md Stage 0 prep #3) ───────────────────────────────────────
# Every route except /api/health sits behind basic auth once a password is
# set. It is off by default so nothing changes for local single-user use —
# but declaring the app reachable (RIFTVOR_HOST=0.0.0.0, as render.yaml does)
# without setting a password is refused rather than quietly served open.
# /api/health stays public because Render's health check probes it unauthed.
auth = HTTPBasicAuth()
PUBLIC_PATHS = {"/api/health"}

if not config.auth_enabled() and config.HOST not in config.LOCAL_HOSTS:
    raise RuntimeError(
        f"RIFTVOR_HOST={config.HOST} exposes Riftvor beyond this machine but "
        f"RIFTVOR_AUTH_PASSWORD is unset. Set it (see HOSTING.md) — an open "
        f"instance lets anyone make this server hammer the SG stores.")

if config.auth_enabled():
    log.info("basic auth ON (user %r)", config.AUTH_USER)
else:
    log.info("basic auth OFF — localhost only")


@auth.verify_password
def _verify(username: str, password: str) -> str | None:
    ok = (hmac.compare_digest(username or "", config.AUTH_USER)
          & hmac.compare_digest(password or "", config.AUTH_PASSWORD))
    return config.AUTH_USER if ok else None


@app.before_request
def _require_auth():
    """Gate everything at the door rather than decorating 20 routes — a new
    endpoint is then protected by default instead of by remembering to."""
    if not config.auth_enabled() or request.path in PUBLIC_PATHS:
        return None
    # login_required returns the 401 challenge on failure, else the wrapped
    # callable's return — None here, which lets the request through.
    return auth.login_required(lambda: None)()


@app.get("/")
def index():
    return render_template(
        "index.html",
        stores=([{"key": s["key"], "name": s["name"], "base": s["base"],
                  "multi_search": s.get("multi_search")}
                 for s in config.STORES]
                + [{"key": config.CARDS_CENTRAL["key"],
                    "name": config.CARDS_CENTRAL["name"],
                    "base": config.CARDS_CENTRAL["base"],
                    "live": True}]),
        ttl=config.TTL_SECONDS,
    )


@app.get("/api/health")
def api_health():
    """Render's health check target — unauthenticated, so it reports
    liveness only, no catalog or sync detail."""
    try:
        with db.connect() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception as exc:  # noqa: BLE001
        log.exception("health check: database unreachable")
        return jsonify({"ok": False, "service": "riftvor",
                        "error": str(exc)}), 503
    return jsonify({"ok": True, "service": "riftvor"})


def _sync_state():
    with db.connect() as conn:
        ages = db.sync_ages(conn)
        notices = [dict(r) for r in conn.execute(
            "SELECT * FROM dormant_notices ORDER BY noticed_at DESC")]
    return {"ages": ages, "ttl": config.TTL_SECONDS,
            "dormant_notices": notices, "syncing": sync.running()}


def _full_comparison(text: str, force: bool = False,
                     with_carousell: bool = True) -> tuple[dict, dict]:
    """Buy list → the complete comparison the UI and the export both use.
    Shared so an xlsx can never drift from what was on screen."""
    summary = sync.ensure_fresh(force=force)
    result = matching.comparison(text)
    # Cards Central is per-query by design: live per buy-list card, skips
    # the TTL cache, attached at request time (never written to listings).
    wanted = [{"card_key": r["card_key"], "name": r["name"]}
              for r in result["rows"]]
    cc = cards_central.lookup(wanted) if wanted else {}
    for row in result["rows"]:
        cell = cc.get(row["card_key"], {}).get(row["finish"])
        if cell:
            row["stores"][cards_central.STORE_KEY] = cell
            if cell["in_stock"] and (row["best_price"] is None
                                     or cell["price"] < row["best_price"]):
                row["best_price"] = cell["price"]
    result["store_order"] = (result["store_order"]
                             + [cards_central.STORE_KEY])
    if with_carousell:
        # Fuzzy name matches, kept separate from the store rows.
        names = list({r["name"] for r in result["rows"] if r["name"]})
        result["carousell"] = carousell.panel_for(names)
    # Purchase plans — computed after Cards Central merges in, so its
    # prices count toward the basket.
    result["basket"] = basket.plans(result["rows"], result["store_order"])
    return result, summary


@app.post("/api/search")
def api_search():
    payload = request.get_json(force=True) or {}
    result, summary = _full_comparison(payload.get("list_text", ""),
                                       force=bool(payload.get("force")))
    result["sync"] = {**_sync_state(), "summary": summary}
    return jsonify(result)


@app.get("/api/state")
def api_state():
    return jsonify(_sync_state())


def _wants_background() -> bool:
    """Detached sync is the default exactly where it has to be — a polite
    sequential crawl takes minutes and no HTTP client should hold that open.
    Override either way with ?background=1 / ?background=0."""
    raw = request.args.get("background")
    if raw is None:
        return config.SEQUENTIAL_SYNC
    return raw.lower() not in ("0", "false", "no")


@app.post("/api/refresh")
def api_refresh():
    if _wants_background():
        started = sync.start_background(force=True)
        return jsonify({
            **_sync_state(),
            "started": started,
            "poll": "GET /api/state — 'syncing' goes false when it is done, "
                    "then read per-store ok/message under 'ages'",
        }), 202
    summary = sync.ensure_fresh(force=True)
    return jsonify({**_sync_state(), "summary": summary})


@app.post("/api/nightly")
def api_nightly():
    """The nightly heartbeat, in-process (HOSTING.md Stage 0 prep #5).

    Render Cron Jobs are separate services with separate filesystems, so
    running nightly.py as a cron there would write history into a database
    nobody reads (gotcha #2). A Cron Job that only curls this endpoint puts
    the work back where the DB lives. Same body as nightly.py; behind the
    same basic auth as everything else.
    """
    # Local imports: both modules call logging.basicConfig at import time,
    # which would otherwise pre-empt this app's log format.
    import check_watchlist
    import dormant_poll

    result = sync.ensure_fresh(force=True)
    sent = check_watchlist.run()
    notices = len(dormant_poll.poll()) if dormant_poll.due() else None
    log.info("nightly: %d alert(s), dormant notices=%s", sent, notices)
    return jsonify({"sync": result, "alerts_sent": sent,
                    "dormant_notices": notices})


@app.get("/api/autocomplete")
def api_autocomplete():
    return jsonify(matching.autocomplete(request.args.get("q", "")))


@app.get("/api/card_img/<card_key>")
def api_card_img(card_key: str):
    return card_art.serve(card_key)


@app.get("/api/history/<card_key>")
def api_history(card_key: str):
    finish = request.args.get("finish")
    days = min(int(request.args.get("days", 90)), 365)
    return jsonify(price_history.history(card_key, finish, days))


# ── Watchlist CRUD ──────────────────────────────────────────────────────────

@app.get("/api/watchlist")
def api_watchlist():
    return jsonify(watchlist.get_all())


@app.post("/api/watchlist")
def api_watchlist_add():
    payload = request.get_json(force=True) or {}
    card_key = payload.get("card_key", "")
    finish = payload.get("finish", "nonfoil")
    try:
        target = float(payload.get("target_price"))
    except (TypeError, ValueError):
        return jsonify({"error": "target_price must be a number"}), 400
    if finish not in ("nonfoil", "foil") or not card_key:
        return jsonify({"error": "bad card_key/finish"}), 400
    watchlist.add(card_key, finish, target)
    return jsonify({"ok": True})


@app.delete("/api/watchlist/<card_key>/<finish>")
def api_watchlist_remove(card_key: str, finish: str):
    watchlist.remove(card_key, finish)
    return jsonify({"ok": True})


# ── Collection (cost basis vs today's market) ───────────────────────────────

@app.get("/collection")
def collection_page():
    return render_template("collection.html")


@app.get("/api/collection")
def api_collection():
    return jsonify(collection.list_items())


@app.post("/api/collection")
def api_collection_add():
    payload = request.get_json(force=True) or {}
    items = payload.get("items") or []
    if not isinstance(items, list):
        return jsonify({"error": "items must be a list"}), 400
    added = collection.add_many(items, note=payload.get("note"))
    return jsonify({"ok": True, "added": added})


@app.delete("/api/collection/<int:item_id>")
def api_collection_remove(item_id: int):
    collection.remove(item_id)
    return jsonify({"ok": True})


# ── Saved buy lists ─────────────────────────────────────────────────────────

@app.get("/api/buylists")
def api_buylists():
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT name, content, created_at FROM buy_lists ORDER BY name"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/buylists")
def api_buylists_save():
    payload = request.get_json(force=True) or {}
    name = (payload.get("name") or "").strip()
    content = payload.get("content") or ""
    if not name:
        return jsonify({"error": "name required"}), 400
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO buy_lists (name, content, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET content = excluded.content""",
            (name, content, time.time()))
    return jsonify({"ok": True})


@app.delete("/api/buylists/<name>")
def api_buylists_delete(name: str):
    with db.connect() as conn:
        conn.execute("DELETE FROM buy_lists WHERE name = ?", (name,))
    return jsonify({"ok": True})


# ── xlsx export ─────────────────────────────────────────────────────────────

@app.post("/api/export")
def api_export():
    payload = request.get_json(force=True) or {}
    # Carousell is a browse-and-judge panel, not a spreadsheet column.
    result, _ = _full_comparison(payload.get("list_text", ""),
                                 with_carousell=False)
    buf = export.comparison_xlsx(result)
    return send_file(
        buf,
        as_attachment=True,
        download_name=export.filename(),
        mimetype=("application/vnd.openxmlformats-officedocument"
                  ".spreadsheetml.sheet"),
    )


# ── Hub status (CORS-open, like the other dashboard services) ───────────────

@app.get("/api/status")
def api_status():
    with db.connect() as conn:
        ages = db.sync_ages(conn)
        counts = conn.execute(
            """SELECT COUNT(*) AS listings,
                      SUM(in_stock) AS in_stock,
                      COUNT(DISTINCT card_key) AS cards
               FROM listings""").fetchone()
        watch = conn.execute(
            "SELECT COUNT(*) AS n FROM watchlist").fetchone()
        triggered = sum(1 for w in watchlist.get_all() if w["triggered"])
    newest = max((a["synced_at"] or 0 for a in ages.values()), default=0)
    resp = jsonify({
        "service": "riftvor",
        "stores": len(config.STORES),
        "stores_ok": sum(1 for a in ages.values() if a["ok"]),
        "listings": counts["listings"],
        "in_stock": counts["in_stock"],
        "cards": counts["cards"],
        "watchlist": watch["n"],
        "watchlist_triggered": triggered,
        "last_sync": newest or None,
        "last_sync_age_s": (time.time() - newest) if newest else None,
    })
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


if __name__ == "__main__":
    log.info("Riftvor on http://%s:%d", config.HOST, config.PORT)
    app.run(host=config.HOST, port=config.PORT, debug=False)
