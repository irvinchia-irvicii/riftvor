"""Portfolio analytics built only from prices the app has actually observed.

The dashboard uses median in-stock asking prices across connected Singapore
shops as its reference value. It does not guess a value for unpriced cards and
does not present marketplace asking prices as guaranteed sale proceeds.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
import time

import config
import db


def _money(value: float) -> float:
    return round(value + 1e-9, 2)


def _pct(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator * 100, 1) if denominator else None


def _label_set(code: str | None) -> str:
    if not code:
        return "Unknown set"
    known = config.SETS.get(code)
    return known[0] if known else code


def build(user_id: int) -> dict:
    cutoff = time.time() - 30 * 86400
    with db.connect() as conn:
        holdings = conn.execute(
            """SELECT c.card_key, c.finish, SUM(c.qty) AS qty,
                      SUM(c.qty * c.unit_paid) AS paid,
                      MAX(COALESCE(k.name, c.card_key)) AS name,
                      MAX(k.set_code) AS set_code
               FROM collection c LEFT JOIN cards k USING (card_key)
               WHERE c.user_id = ?
               GROUP BY c.card_key, c.finish
               ORDER BY paid DESC""",
            (user_id,),
        ).fetchall()
        folder_rows = conn.execute(
            """SELECT c.card_key, c.finish, c.qty, c.unit_paid,
                      COALESCE(f.name, 'Unfiled') AS folder_name
               FROM collection c
               LEFT JOIN collection_folders f ON f.id = c.folder_id
               WHERE c.user_id = ?""",
            (user_id,),
        ).fetchall()
        listing_rows = conn.execute(
            """SELECT card_key, finish, store, MIN(price) AS price,
                      MAX(synced_at) AS synced_at
               FROM listings
               WHERE in_stock = 1 AND card_key IS NOT NULL
               GROUP BY card_key, finish, store"""
        ).fetchall()
        history_rows = conn.execute(
            """SELECT card_key, finish, store, price, seen_at
               FROM price_history
               WHERE in_stock = 1 AND seen_at >= ?""",
            (cutoff,),
        ).fetchall()

    store_names = {s["key"]: s["name"] for s in config.STORES}
    prices: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    newest_sync = None
    for row in listing_rows:
        prices[(row["card_key"], row["finish"])][row["store"]] = row["price"]
        newest_sync = max(newest_sync or 0, row["synced_at"] or 0)

    positions = []
    set_totals: dict[str, dict[str, float]] = defaultdict(
        lambda: {"paid": 0.0, "value": 0.0, "cards": 0, "priced_cards": 0}
    )
    price_for: dict[tuple[str, str], float] = {}
    total_paid = total_value = 0.0
    total_cards = priced_cards = 0
    store_coverage: dict[str, dict[str, float]] = defaultdict(
        lambda: {"value": 0.0, "cards": 0, "lines": 0}
    )

    for row in holdings:
        key = (row["card_key"], row["finish"])
        observed = prices.get(key, {})
        unit_value = median(observed.values()) if observed else None
        if unit_value is not None:
            price_for[key] = unit_value
        paid = float(row["paid"])
        value = unit_value * row["qty"] if unit_value is not None else None
        delta = value - paid if value is not None else None
        total_paid += paid
        total_cards += row["qty"]
        if value is not None:
            total_value += value
            priced_cards += row["qty"]
        set_name = _label_set(row["set_code"])
        bucket = set_totals[set_name]
        bucket["paid"] += paid
        bucket["cards"] += row["qty"]
        if value is not None:
            bucket["value"] += value
            bucket["priced_cards"] += row["qty"]
        for store, unit in observed.items():
            store_coverage[store]["value"] += unit * row["qty"]
            store_coverage[store]["cards"] += row["qty"]
            store_coverage[store]["lines"] += 1
        positions.append({
            "card_key": row["card_key"],
            "name": row["name"],
            "set": set_name,
            "finish": row["finish"],
            "qty": row["qty"],
            "paid": _money(paid),
            "unit_value": _money(unit_value) if unit_value is not None else None,
            "value": _money(value) if value is not None else None,
            "delta": _money(delta) if delta is not None else None,
            "return_pct": _pct(delta, paid) if delta is not None else None,
            "shops": len(observed),
        })

    positions.sort(key=lambda p: p["value"] if p["value"] is not None else -1,
                   reverse=True)
    valued = [p for p in positions if p["value"] is not None]
    top_value = valued[0]["value"] if valued else 0

    folder_totals: dict[str, dict[str, float]] = defaultdict(
        lambda: {"paid": 0.0, "value": 0.0, "cards": 0, "priced_cards": 0}
    )
    for row in folder_rows:
        bucket = folder_totals[row["folder_name"]]
        paid = row["qty"] * row["unit_paid"]
        ref = price_for.get((row["card_key"], row["finish"]))
        bucket["paid"] += paid
        bucket["cards"] += row["qty"]
        if ref is not None:
            bucket["value"] += ref * row["qty"]
            bucket["priced_cards"] += row["qty"]

    def allocations(source: dict[str, dict[str, float]]) -> list[dict]:
        result = []
        for name, values in source.items():
            result.append({
                "name": name,
                "cards": int(values["cards"]),
                "priced_cards": int(values["priced_cards"]),
                "paid": _money(values["paid"]),
                "value": _money(values["value"]),
                "share_pct": _pct(values["value"], total_value) or 0,
            })
        return sorted(result, key=lambda item: item["value"], reverse=True)

    # Compare today's reference value with the oldest available daily median
    # in the last 30 days, using only positions that have both endpoints.
    daily: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in history_rows:
        day = datetime.fromtimestamp(row["seen_at"], timezone.utc).date().isoformat()
        daily[(row["card_key"], row["finish"], day)].append(row["price"])
    start_value = end_value = 0.0
    trend_cards = 0
    by_key: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for (card_key, finish, day), values in daily.items():
        by_key[(card_key, finish)].append((day, median(values)))
    qty_by_key = {(r["card_key"], r["finish"]): r["qty"] for r in holdings}
    for key, points in by_key.items():
        if key not in price_for:
            continue
        points.sort()
        qty = qty_by_key.get(key, 0)
        if not qty:
            continue
        start_value += points[0][1] * qty
        end_value += price_for[key] * qty
        trend_cards += qty

    source_rows = []
    for store, values in sorted(store_coverage.items(),
                                key=lambda item: item[1]["value"], reverse=True):
        source_rows.append({
            "name": store_names.get(store, store.replace("_", " ").title()),
            "status": "connected",
            "detail": f"{int(values['cards'])} cards covered · current in-stock asks",
            "value": _money(values["value"]),
            "coverage_pct": _pct(values["cards"], total_cards) or 0,
        })
    source_rows.extend([
        {"name": "Cards Central", "status": "search_only",
         "detail": "Live search source; portfolio snapshots are not stored yet.",
         "url": "https://cardscentral.com/shop/riftbound"},
        {"name": "Bilgewater Market", "status": "not_connected",
         "detail": "Reference marketplace found; an authorised data feed is still needed.",
         "url": "https://bilgewatermarket.com/cards"},
        {"name": "TCGplayer", "status": "not_connected",
         "detail": "Riftbound is listed, but this app needs an approved feed/API before importing prices.",
         "url": "https://www.tcgplayer.com/search/riftbound-tcg/product"},
        {"name": "Card Kingdom", "status": "unavailable",
         "detail": "No verified Riftbound singles catalogue was found, so it is excluded."},
    ])

    return {
        "summary": {
            "cards": total_cards,
            "positions": len(positions),
            "paid": _money(total_paid),
            "value": _money(total_value),
            "delta": _money(total_value - total_paid),
            "return_pct": _pct(total_value - total_paid, total_paid),
            "priced_cards": priced_cards,
            "coverage_pct": _pct(priced_cards, total_cards) or 0,
            "top_holding_pct": _pct(top_value, total_value) or 0,
            "as_of": newest_sync,
        },
        "positions": positions,
        "top_gainers": sorted(
            valued, key=lambda p: p["delta"], reverse=True
        )[:5],
        "top_decliners": sorted(
            valued, key=lambda p: p["delta"]
        )[:5],
        "sets": allocations(set_totals),
        "folders": allocations(folder_totals),
        "trend_30d": {
            "status": "ready" if trend_cards else "collecting_history",
            "cards": trend_cards,
            "start_value": _money(start_value) if trend_cards else None,
            "end_value": _money(end_value) if trend_cards else None,
            "delta": _money(end_value - start_value) if trend_cards else None,
            "change_pct": _pct(end_value - start_value, start_value)
            if trend_cards else None,
        },
        "sources": source_rows,
        "methodology": (
            "Reference value is the median of each card's cheapest current "
            "in-stock asking price at connected Singapore shops. Missing prices "
            "are not estimated. Values are in SGD and are not sale proceeds or "
            "financial advice."
        ),
    }
