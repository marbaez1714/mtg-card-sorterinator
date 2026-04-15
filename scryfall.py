"""Scryfall API: fuzzy card lookup by name."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any
from urllib.parse import quote

import requests

_BASE = "https://api.scryfall.com"
_USER_AGENT = "mtg-card-sorter/0.1 (personal MTG inventory scanner)"
_TIMEOUT = 10.0

_lock = threading.Lock()
_last_request_end = 0.0


def _min_interval_s() -> float:
    ms = os.environ.get("SCRYFALL_MIN_INTERVAL_MS", "75").strip()
    try:
        v = float(ms) / 1000.0
    except ValueError:
        v = 0.075
    return max(0.05, v)


def _throttle() -> None:
    global _last_request_end
    with _lock:
        gap = time.monotonic() - _last_request_end
        need = _min_interval_s() - gap
        if need > 0:
            time.sleep(need)


def _mark_request_done() -> None:
    global _last_request_end
    with _lock:
        _last_request_end = time.monotonic()


class ScryfallLookupError(Exception):
    """Scryfall HTTP error, not found, or bad response."""


def _parse_price(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _image_uri(card: dict[str, Any]) -> str | None:
    iu = card.get("image_uris")
    if isinstance(iu, dict):
        u = iu.get("normal") or iu.get("large")
        if isinstance(u, str):
            return u
    faces = card.get("card_faces")
    if isinstance(faces, list) and faces:
        fiu = faces[0].get("image_uris") if isinstance(faces[0], dict) else None
        if isinstance(fiu, dict):
            u = fiu.get("normal") or fiu.get("large")
            if isinstance(u, str):
                return u
    return None


def _normalize_card(card: dict[str, Any]) -> dict[str, Any]:
    prices = card.get("prices") if isinstance(card.get("prices"), dict) else {}
    legalities = card.get("legalities")
    if not isinstance(legalities, dict):
        legalities = {}

    name = card.get("name")
    if not isinstance(name, str):
        name = ""

    return {
        "id": card.get("id"),
        "name": name,
        "set_code": card.get("set"),
        "collector_number": card.get("collector_number"),
        "price_usd": _parse_price(prices.get("usd")),
        "price_usd_foil": _parse_price(prices.get("usd_foil")),
        "image_uri": _image_uri(card),
        "legalities": legalities,
    }


def _request_scryfall_card(
    path: str,
    params: dict[str, str] | None = None,
    *,
    not_found_message: str,
) -> dict[str, Any]:
    _throttle()
    url = f"{_BASE}{path}"
    try:
        r = requests.get(
            url,
            params=params or {},
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        _mark_request_done()
        raise ScryfallLookupError(f"Request failed: {e}") from e

    _mark_request_done()

    if r.status_code == 404:
        raise ScryfallLookupError(not_found_message)
    if r.status_code == 429:
        raise ScryfallLookupError("Rate limited by Scryfall (429)")
    if not r.ok:
        raise ScryfallLookupError(f"Scryfall HTTP {r.status_code}: {r.text[:200]!r}")

    try:
        card = r.json()
    except json.JSONDecodeError as e:
        raise ScryfallLookupError("Invalid JSON from Scryfall") from e
    if not isinstance(card, dict):
        raise ScryfallLookupError("Unexpected response shape")

    return _normalize_card(card)


def lookup_card_by_fuzzy_name(name: str) -> dict[str, Any]:
    """
    GET /cards/named?fuzzy=... — returns a normalized dict for inventory / JSON APIs.

    Throttles consecutive calls (SCRYFALL_MIN_INTERVAL_MS, default 75).
    """
    q = (name or "").strip()
    if not q:
        raise ScryfallLookupError("Empty card name")

    return _request_scryfall_card(
        "/cards/named",
        {"fuzzy": q},
        not_found_message="No card matched fuzzy name",
    )


def lookup_card_by_set_and_collector(set_code: str, collector_number: str) -> dict[str, Any]:
    """
    GET /cards/{set}/{collector_number} — exact print when set and collector are known.

    Throttles like other Scryfall calls.
    """
    sc = (set_code or "").strip().lower()
    cn = (collector_number or "").strip()
    if not sc or not cn:
        raise ScryfallLookupError("set_code and collector_number are required")
    path = f"/cards/{quote(sc, safe='')}/{quote(cn, safe='')}"
    return _request_scryfall_card(
        path,
        None,
        not_found_message="No card matched set and collector",
    )


def lookup_card_from_vision(vision: dict[str, Any]) -> dict[str, Any]:
    """
    Prefer exact ``/cards/{set}/{collector}`` when vision includes both; else fuzzy name.
    """
    name = vision.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ScryfallLookupError("vision result missing name")

    sc = vision.get("set_code")
    cn = vision.get("collector_number")
    if isinstance(sc, str) and isinstance(cn, str) and sc.strip() and cn.strip():
        try:
            return lookup_card_by_set_and_collector(sc, cn)
        except ScryfallLookupError:
            pass
    return lookup_card_by_fuzzy_name(name.strip())


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python3 scryfall.py "Card Name"', file=sys.stderr)
        sys.exit(2)
    name = " ".join(sys.argv[1:]).strip()
    try:
        result = lookup_card_by_fuzzy_name(name)
    except ScryfallLookupError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
