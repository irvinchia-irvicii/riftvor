"""app.py — Riftvor Flask app (port 5009).

Dashboard skeleton ported from 3vor Fetch: buy-list search → comparison
table, watchlist, history charts, xlsx export, saved buy lists.
/api/status is CORS-open for the dashboard hub card.
"""
from __future__ import annotations

import logging
import time

from flask import Flask, jsonify, render_template, request, send_file

import card_art
import cards_central
import carousell
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
config.load_env()


@app.get("/")
def index():
    return render_template(
        "index.html",
        stores=([{"key": s["key"], "name": s["name"], "base": s["base"]}
                 for s in config.STORES]
                + [{"key": config.CARDS_CENTRAL["key"],
                    "name": config.CARDS_CENTRAL["name"],
                    "base": config.CARDS_CENTRAL["base"],
                    "live": True}]),
        ttl=config.TTL_SECONDS,
    )


@app.get("/api/health")
def api_health():
    return jsonify({"ok": True, "service": "riftvor"})


def _sync_state():
    with db.connect() as conn:
        ages = db.sync_ages(conn)
        notices = [dict(r) for r in conn.execute(
            "SELECT * FROM dormant_notices ORDER BY noticed_at DESC")]
    return {"ages": ages, "ttl": config.TTL_SECONDS,
            "dormant_notices": notices}


@app.post("/api/search")
def api_search():
    payload = request.get_json(force=True) or {}
    text = payload.get("list_text", "")
    force = bool(payload.get("force"))
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
    # Carousell P2P panel — fuzzy name matches, separate from store rows.
    names = list({r["name"] for r in result["rows"] if r["name"]})
    result["carousell"] = carousell.panel_for(names)
    result["sync"] = {**_sync_state(), "summary": summary}
    return jsonify(result)


@app.get("/api/state")
def api_state():
    return jsonify(_sync_state())


@app.post("/api/refresh")
def api_refresh():
    summary = sync.ensure_fresh(force=True)
    return jsonify({**_sync_state(), "summary": summary})


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
    text = payload.get("list_text", "")
    result = matching.comparison(text)
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
    log.info("Riftvor on http://127.0.0.1:%d", config.PORT)
    app.run(host="127.0.0.1", port=config.PORT, debug=False)
