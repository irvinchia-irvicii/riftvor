"""card_art.py — card images (§7).

RiftMana's predictable URLs first (cached locally on first use), the
store's own product image (from Shopify products.json, held in cards.img_url)
as fallback if RiftMana 404s. No scraping beyond image GETs.
"""
from __future__ import annotations

import logging
import re

import httpx
from flask import abort, redirect, send_file

import db
from config import ART_DIR, RIFTMANA_ART_URL, USER_AGENT

log = logging.getLogger("riftvor.art")

_KEY_RE = re.compile(r"^[A-Z]{2,3}-[A-Za-z0-9]{1,6}$")


def serve(card_key: str):
    """Flask handler body for /api/card_img/<card_key>."""
    if not _KEY_RE.fullmatch(card_key):
        abort(404)
    ART_DIR.mkdir(exist_ok=True)
    path = ART_DIR / f"{card_key}.webp"
    if path.exists():
        return send_file(path, mimetype="image/webp",
                         max_age=7 * 24 * 3600)
    url = RIFTMANA_ART_URL.format(card_key=card_key)
    try:
        resp = httpx.get(url, headers={"User-Agent": USER_AGENT},
                         timeout=10, follow_redirects=True)
        if (resp.status_code == 200
                and resp.headers.get("content-type", "").startswith("image")):
            path.write_bytes(resp.content)
            return send_file(path, mimetype="image/webp",
                             max_age=7 * 24 * 3600)
    except httpx.HTTPError as exc:
        log.info("riftmana fetch failed for %s: %s", card_key, exc)
    with db.connect() as conn:
        row = conn.execute("SELECT img_url FROM cards WHERE card_key = ?",
                           (card_key,)).fetchone()
    if row and row["img_url"]:
        return redirect(row["img_url"])
    abort(404)
