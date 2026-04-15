"""Flask orchestrator: scan (camera → Claude → Scryfall), confirm → DB, rescan."""

from __future__ import annotations

import os
import threading
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from camera import CardCamera
from claude_id import CardIdentificationError, identify_card_from_jpeg
from db import InventoryDBError, add_inventory_item, init_db, list_inventory_items
from scryfall import ScryfallLookupError, lookup_card_from_vision

init_db()

app = Flask(__name__)

_lock = threading.Lock()
_pending: dict[str, Any] | None = None


def _run_scan_pipeline() -> tuple[dict[str, Any], dict[str, Any]]:
    cam = CardCamera()
    try:
        cam.start()
        jpeg = cam.capture_jpeg()
    finally:
        cam.stop()
    vision = identify_card_from_jpeg(jpeg)
    sf = lookup_card_from_vision(vision)
    return vision, sf


@app.get("/api/health")
def api_health() -> Any:
    return jsonify(ok=True)


@app.post("/api/scan")
def api_scan() -> Any:
    """Clear stale pending, capture, identify, Scryfall; store pending on success."""
    global _pending
    with _lock:
        _pending = None
    try:
        vision, sf = _run_scan_pipeline()
    except CardIdentificationError as e:
        return jsonify(error=str(e)), 502
    except ScryfallLookupError as e:
        msg = str(e)
        status = 404 if "No card matched" in msg else 502
        return jsonify(error=msg), status
    except Exception as e:
        return jsonify(error=str(e)), 500

    with _lock:
        _pending = {"vision": vision, "scryfall": sf}
    return jsonify(vision=vision, scryfall=sf)


@app.post("/api/confirm")
def api_confirm() -> Any:
    global _pending
    body = request.get_json(silent=True) or {}
    foil = bool(body.get("foil", False))
    raw_qty = body.get("quantity", 1)
    try:
        qty = int(raw_qty)
    except (TypeError, ValueError):
        return jsonify(error="quantity must be an integer"), 400
    if qty < 1:
        qty = 1

    with _lock:
        if _pending is None:
            return jsonify(error="No pending scan; POST /api/scan first"), 400
        sf = _pending["scryfall"]

    price = sf.get("price_usd_foil") if foil else sf.get("price_usd")
    sid = sf.get("id")
    if sid is not None:
        sid = str(sid)
    name = sf.get("name") or ""
    set_code = sf.get("set_code")

    try:
        rid = add_inventory_item(
            name=name,
            scryfall_id=sid,
            set_code=set_code,
            quantity=qty,
            foil=foil,
            price_usd=price,
        )
    except InventoryDBError as e:
        return jsonify(error=str(e)), 502

    with _lock:
        _pending = None

    row: dict[str, Any] | None = None
    for r in list_inventory_items(limit=200):
        if r.get("id") == rid:
            row = r
            break
    if row is None:
        row = {
            "id": rid,
            "scryfall_id": sid,
            "name": name,
            "set_code": set_code,
            "quantity": qty,
            "foil": foil,
            "price_usd": price,
            "added_at": None,
        }

    return jsonify(inventory_id=rid, row=row)


@app.post("/api/rescan")
def api_rescan() -> Any:
    global _pending
    with _lock:
        _pending = None
    return jsonify(ok=True)


@app.get("/api/inventory")
def api_inventory() -> Any:
    raw = request.args.get("limit", default=50, type=int)
    limit = 50 if raw is None else raw
    limit = max(1, min(limit, 200))
    try:
        items = list_inventory_items(limit=limit)
    except InventoryDBError as e:
        return jsonify(error=str(e)), 500
    return jsonify(items)


if __name__ == "__main__":
    port = int(os.environ.get("FLASK_PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
