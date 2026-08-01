"""basket.py — purchase plans over a comparison result.

The comparison table answers "what does each card cost where". This
answers the question you actually act on: "so what do I buy, and what
does it come to?"

Three plans, because the cheapest basket is rarely the practical one —
cherry-picking the floor price usually means ordering from every store,
and each extra store is another postage fee and another parcel to chase:

    cheapest        cheapest in-stock listing per line, wherever it is
    fewest_stores   greedy set cover — fewest stores that still cover
                    everything obtainable, priced within that set
    single_store    per-store coverage + cost, ranked by how much of the
                    list each store can fill on its own

Plans are computed per buy-list LINE (the raw text the user typed), not
per card_key: a line like '6 Calm Rune' legitimately matches several
printings, and for the buyer those are interchangeable. Lines matching
more than one distinct card are flagged `ambiguous` so a wrong guess is
visible rather than silent.

Stock DEPTH is unknown — Shopify's products.json exposes an availability
boolean, not a count — so a line's cost is qty x unit price and assumes
the store can actually supply that many. `assumes_stock_depth` carries
that caveat to the UI.
"""
from __future__ import annotations

from config import CARDS_CENTRAL, STORE_BY_KEY


def store_names() -> dict[str, str]:
    names = {k: v["name"] for k, v in STORE_BY_KEY.items()}
    names[CARDS_CENTRAL["key"]] = CARDS_CENTRAL["name"]
    return names


def _group_lines(rows: list[dict]) -> list[dict]:
    """Comparison rows → one entry per buy-list line, with every in-stock
    listing that could satisfy it."""
    groups: dict[str, dict] = {}
    for row in rows:
        group = groups.setdefault(row["raw"], {
            "raw": row["raw"],
            "qty": row["qty"],
            "options": [],
            "card_keys": set(),
        })
        group["card_keys"].add(row["card_key"])
        for store, cell in (row.get("stores") or {}).items():
            if not cell.get("in_stock"):
                continue
            group["options"].append({
                "store": store,
                "price": cell["price"],
                "url": cell["url"],
                "card_key": row["card_key"],
                "finish": row["finish"],
                "name": row["name"],
            })
    out = []
    for group in groups.values():
        group["ambiguous"] = len(group["card_keys"]) > 1
        group["match_count"] = len(group["card_keys"])
        del group["card_keys"]
        out.append(group)
    return out


def _pick(option: dict, group: dict) -> dict:
    return {
        "raw": group["raw"],
        "qty": group["qty"],
        "name": option["name"],
        "card_key": option["card_key"],
        "finish": option["finish"],
        "store": option["store"],
        "unit_price": option["price"],
        "line_cost": round(option["price"] * group["qty"], 2),
        "url": option["url"],
        "ambiguous": group["ambiguous"],
    }


def _summarise(picks: list[dict], missing: list[str], groups: list[dict],
               label: str, note: str = "") -> dict:
    by_store: dict[str, dict] = {}
    for pick in picks:
        slot = by_store.setdefault(pick["store"], {"store": pick["store"],
                                                  "lines": [], "subtotal": 0.0})
        slot["lines"].append(pick)
        slot["subtotal"] = round(slot["subtotal"] + pick["line_cost"], 2)
    return {
        "label": label,
        "note": note,
        "total": round(sum(p["line_cost"] for p in picks), 2),
        "store_count": len(by_store),
        "lines_filled": len(picks),
        "lines_total": len(groups),
        "cards_total": sum(p["qty"] for p in picks),
        "missing": missing,
        "by_store": sorted(by_store.values(),
                           key=lambda s: -s["subtotal"]),
    }


def _cheapest(groups: list[dict]) -> dict:
    picks, missing = [], []
    for group in groups:
        if not group["options"]:
            missing.append(group["raw"])
            continue
        picks.append(_pick(min(group["options"], key=lambda o: o["price"]),
                           group))
    return _summarise(picks, missing, groups, "Cheapest",
                      "Absolute floor price — but you order from every "
                      "store it names.")


def _single_store(groups: list[dict], store_order: list[str]) -> list[dict]:
    ranked = []
    for store in store_order:
        picks, missing = [], []
        for group in groups:
            options = [o for o in group["options"] if o["store"] == store]
            if not options:
                missing.append(group["raw"])
                continue
            picks.append(_pick(min(options, key=lambda o: o["price"]), group))
        if not picks:
            continue
        summary = _summarise(picks, missing, groups,
                             store_names().get(store, store),
                             "One order, one postage.")
        summary["store"] = store
        ranked.append(summary)
    # Most of the list filled wins; cost breaks ties.
    ranked.sort(key=lambda s: (-s["lines_filled"], s["total"]))
    return ranked


def _fewest_stores(groups: list[dict]) -> dict:
    """Greedy set cover: repeatedly take the store that fills the most
    still-unfilled lines (cheapest total breaks ties)."""
    fillable = [g for g in groups if g["options"]]
    missing = [g["raw"] for g in groups if not g["options"]]
    remaining, chosen = list(fillable), []
    while remaining:
        coverage: dict[str, list[dict]] = {}
        for group in remaining:
            for store in {o["store"] for o in group["options"]}:
                coverage.setdefault(store, []).append(group)
        if not coverage:
            break

        def score(store: str) -> tuple[int, float]:
            covered = coverage[store]
            cost = sum(
                min(o["price"] for o in g["options"] if o["store"] == store)
                * g["qty"] for g in covered)
            return (len(covered), -cost)

        best = max(coverage, key=score)
        chosen.append(best)
        remaining = [g for g in remaining if g not in coverage[best]]

    picks = []
    for group in fillable:
        options = [o for o in group["options"] if o["store"] in chosen]
        if not options:
            missing.append(group["raw"])
            continue
        picks.append(_pick(min(options, key=lambda o: o["price"]), group))
    plural = "s" if len(chosen) != 1 else ""
    return _summarise(picks, missing, groups, "Fewest stores",
                      f"Everything obtainable from {len(chosen)} store{plural}.")


def plans(rows: list[dict], store_order: list[str]) -> dict:
    """Comparison rows → the three purchase plans + store display names."""
    groups = _group_lines(rows)
    if not groups:
        return {"plans": [], "single_store": [], "store_names": store_names()}

    cheapest = _cheapest(groups)
    fewest = _fewest_stores(groups)
    singles = _single_store(groups, store_order)

    # Show what the convenience of fewer parcels actually costs.
    for plan in [fewest] + singles:
        if plan["lines_filled"] == cheapest["lines_filled"]:
            plan["premium"] = round(plan["total"] - cheapest["total"], 2)
        else:
            plan["premium"] = None

    return {
        "plans": [cheapest, fewest],
        "single_store": singles,
        "store_names": store_names(),
        "assumes_stock_depth": any(g["qty"] > 1 for g in groups),
        "ambiguous_lines": [g["raw"] for g in groups if g["ambiguous"]],
    }
