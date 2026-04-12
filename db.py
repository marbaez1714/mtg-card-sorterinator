"""SQLite inventory — schema and CRUD for confirmed card rows."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from typing import Any

_DEFAULT_DB = "inventory.db"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS inventory (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scryfall_id TEXT,
  name TEXT NOT NULL,
  set_code TEXT,
  quantity INTEGER DEFAULT 1,
  foil BOOLEAN DEFAULT 0,
  price_usd REAL,
  added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class InventoryDBError(Exception):
    """Invalid arguments or SQLite failure."""


def get_db_path() -> str:
    for key in ("INVENTORY_DB", "INVENTORY_DB_PATH"):
        v = os.environ.get(key)
        if v and str(v).strip():
            return os.path.abspath(str(v).strip())
    return os.path.abspath(_DEFAULT_DB)


def init_db(path: str | None = None) -> str:
    """Create the inventory table if needed. Returns the resolved database path."""
    p = path or get_db_path()
    parent = os.path.dirname(p)
    if parent and not os.path.isdir(parent):
        raise InventoryDBError(f"Database directory does not exist: {parent!r}")
    try:
        conn = sqlite3.connect(p)
        try:
            conn.executescript(_CREATE_SQL)
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as e:
        raise InventoryDBError(f"Could not initialize database: {e}") from e
    return p


def add_inventory_item(
    *,
    name: str,
    scryfall_id: str | None = None,
    set_code: str | None = None,
    quantity: int = 1,
    foil: bool = False,
    price_usd: float | None = None,
    path: str | None = None,
) -> int:
    """
    Insert one inventory row (one physical confirm). Returns new row id.

    Caller chooses price_usd (e.g. Scryfall usd vs usd_foil). v1: duplicates allowed.
    """
    n = (name or "").strip()
    if not n:
        raise InventoryDBError("name must be non-empty")

    try:
        q = int(quantity)
    except (TypeError, ValueError) as e:
        raise InventoryDBError("quantity must be an integer") from e
    if q < 1:
        q = 1

    foil_i = 1 if foil else 0
    p = path or get_db_path()

    try:
        conn = sqlite3.connect(p)
        try:
            cur = conn.execute(
                """
                INSERT INTO inventory (scryfall_id, name, set_code, quantity, foil, price_usd)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (scryfall_id, n, set_code, q, foil_i, price_usd),
            )
            conn.commit()
            rid = cur.lastrowid
        finally:
            conn.close()
    except sqlite3.Error as e:
        raise InventoryDBError(f"Insert failed: {e}") from e

    if rid is None:
        raise InventoryDBError("Insert did not return row id")
    return int(rid)


def list_inventory_items(*, limit: int = 50, path: str | None = None) -> list[dict[str, Any]]:
    """Newest rows first. Each dict includes foil as bool."""
    if limit < 1:
        limit = 1
    p = path or get_db_path()
    try:
        conn = sqlite3.connect(p)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                """
                SELECT id, scryfall_id, name, set_code, quantity, foil, price_usd, added_at
                FROM inventory
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = []
            for r in cur.fetchall():
                d = dict(r)
                d["foil"] = bool(d.get("foil"))
                rows.append(d)
            return rows
        finally:
            conn.close()
    except sqlite3.Error as e:
        raise InventoryDBError(f"Query failed: {e}") from e


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("--init", "--list"):
        print("Usage: python3 db.py --init | python3 db.py --list", file=sys.stderr)
        sys.exit(2)
    try:
        if sys.argv[1] == "--init":
            out = init_db()
            print(out)
        else:
            init_db()
            items = list_inventory_items()
            print(json.dumps(items, indent=2, default=str))
    except InventoryDBError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
