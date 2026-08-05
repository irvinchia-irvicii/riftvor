"""Export only public catalogue data from the local SQLite database."""
from __future__ import annotations

import gzip
import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "state" / "riftvor.db"
TARGET = ROOT / "data" / "catalog_snapshot.json.gz"
PUBLIC_TABLES = ("cards", "listings", "external_prices", "fx_rates")


def rows(conn: sqlite3.Connection, table: str) -> list[dict]:
    return [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Local catalogue database not found: {SOURCE}")
    conn = sqlite3.connect(SOURCE)
    conn.row_factory = sqlite3.Row
    payload = {"format_version": 1, "generated_at": time.time()}
    payload.update({table: rows(conn, table) for table in PUBLIC_TABLES})
    if not payload["cards"] or not payload["listings"]:
        raise SystemExit("Refusing to create an empty catalogue snapshot")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(TARGET, "wt", encoding="utf-8", compresslevel=9) as handle:
        json.dump(payload, handle, separators=(",", ":"), ensure_ascii=False)
    print(f"Wrote {TARGET} with {len(payload['cards'])} cards and "
          f"{len(payload['listings'])} listings")


if __name__ == "__main__":
    main()
