"""Cached TCGplayer reference prices supplied by Riftbound.gg / DotGG.

Riftbound.gg's public prices page reads the same unauthenticated DotGG endpoint.
The feed labels `price`/`foilPrice` as TCGplayer USD. We request it at most once
per six hours, convert with a daily Frankfurter USD→SGD rate, and attribute
every reference back to Riftbound.gg.
"""
from __future__ import annotations

import logging
import time

import httpx

import config
import db

SOURCE = "riftbound_gg_tcgplayer"
FEED_URL = "https://api.dotgg.gg/cgfw/getcards?game=riftbound&mode=indexed"
FX_URL = "https://api.frankfurter.app/latest?from=USD&to=SGD"
MIN_EXPECTED_CARDS = 500

log = logging.getLogger("riftvor.riftbound_gg")


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def cached_state() -> dict:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT synced_at, ok, message, listing_count FROM sync_meta WHERE store = ?",
            (SOURCE,),
        ).fetchone()
        fx = conn.execute(
            "SELECT rate, as_of, synced_at FROM fx_rates WHERE base='USD' AND quote='SGD'"
        ).fetchone()
    return {
        "synced_at": row["synced_at"] if row else None,
        "ok": bool(row["ok"]) if row else False,
        "message": row["message"] if row else "Not synced yet.",
        "price_count": row["listing_count"] if row else 0,
        "fx_rate": fx["rate"] if fx else None,
        "fx_as_of": fx["as_of"] if fx else None,
        "fx_synced_at": fx["synced_at"] if fx else None,
    }


def _fresh(state: dict) -> bool:
    synced = state.get("synced_at") or 0
    return bool(state.get("ok") and synced
                and time.time() - synced < config.EXTERNAL_PRICE_TTL_SECONDS)


def _fetch() -> tuple[list[dict], float, str | None]:
    headers = {"User-Agent": config.USER_AGENT}
    with httpx.Client(headers=headers, timeout=config.TIMEOUT_S,
                      follow_redirects=True) as client:
        feed_response = client.get(FEED_URL)
        feed_response.raise_for_status()
        payload = feed_response.json()
        fx_response = client.get(FX_URL)
        fx_response.raise_for_status()
        fx_payload = fx_response.json()

    names = payload.get("names") if isinstance(payload, dict) else None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(names, list) or not isinstance(data, list):
        raise ValueError("DotGG returned an unexpected card feed shape.")
    if len(data) < MIN_EXPECTED_CARDS:
        raise ValueError(f"DotGG returned only {len(data)} cards; cache preserved.")
    rate = _number((fx_payload.get("rates") or {}).get("SGD"))
    if rate is None:
        raise ValueError("USD→SGD rate was missing.")

    index = {name: position for position, name in enumerate(names)}
    required = {"id", "slug", "price", "foilPrice", "deltaPrice",
                "deltaFoilPrice", "delta7dPrice", "delta7dPriceFoil"}
    if not required.issubset(index):
        raise ValueError("DotGG price fields changed; cache preserved.")

    rows = []
    for card in data:
        if not isinstance(card, list):
            continue
        def field(name):
            pos = index[name]
            return card[pos] if pos < len(card) else None

        card_key = str(field("id") or "").strip().upper()
        slug = str(field("slug") or "").strip()
        if not card_key or not slug:
            continue
        url = f"https://riftbound.gg/cards/{slug}/"
        for finish, price_field, d1_field, d7_field in (
            ("nonfoil", "price", "deltaPrice", "delta7dPrice"),
            ("foil", "foilPrice", "deltaFoilPrice", "delta7dPriceFoil"),
        ):
            native = _number(field(price_field))
            if native is None:
                continue
            delta_1d = float(field(d1_field) or 0) * rate
            delta_7d = float(field(d7_field) or 0) * rate
            rows.append({
                "source": SOURCE,
                "card_key": card_key,
                "finish": finish,
                "native_price": native,
                "native_currency": "USD",
                "sgd_price": native * rate,
                "delta_1d_sgd": delta_1d,
                "delta_7d_sgd": delta_7d,
                "url": url,
            })
    if not rows:
        raise ValueError("DotGG returned no usable TCGplayer prices.")
    return rows, rate, fx_payload.get("date")


def ensure_fresh(force: bool = False) -> dict:
    state = cached_state()
    if not force and _fresh(state):
        return {**state, "cached": True}

    now = time.time()
    try:
        rows, rate, fx_date = _fetch()
        with db.connect() as conn:
            conn.execute("DELETE FROM external_prices WHERE source = ?", (SOURCE,))
            conn.executemany(
                """INSERT INTO external_prices
                   (source, card_key, finish, native_price, native_currency,
                    sgd_price, delta_1d_sgd, delta_7d_sgd, url, synced_at)
                   VALUES (:source, :card_key, :finish, :native_price,
                           :native_currency, :sgd_price, :delta_1d_sgd,
                           :delta_7d_sgd, :url, :synced_at)""",
                [{**row, "synced_at": now} for row in rows],
            )
            conn.execute(
                """INSERT INTO fx_rates (base, quote, rate, as_of, synced_at)
                   VALUES ('USD', 'SGD', ?, ?, ?)
                   ON CONFLICT(base, quote) DO UPDATE SET
                     rate=excluded.rate, as_of=excluded.as_of,
                     synced_at=excluded.synced_at""",
                (rate, fx_date, now),
            )
            db.record_sync(conn, SOURCE, True,
                           f"TCGplayer USD via Riftbound.gg · USD/SGD {rate:.4f}",
                           len(rows))
        return {**cached_state(), "cached": False}
    except Exception as exc:  # noqa: BLE001 — stale cache is intentional fallback
        log.warning("Riftbound.gg reference sync failed: %s", exc)
        with db.connect() as conn:
            existing = conn.execute(
                "SELECT COUNT(*) FROM external_prices WHERE source = ?", (SOURCE,)
            ).fetchone()[0]
            db.record_sync(conn, SOURCE, False, str(exc), existing)
        return {**cached_state(), "cached": bool(state.get("price_count")),
                "using_stale": bool(state.get("price_count"))}
