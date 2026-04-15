# MTG Card Scanner — Claude Code Context

## Project Overview
A Raspberry Pi-based Magic: The Gathering card scanner that identifies cards using the Claude Vision API, fetches card data from Scryfall, and saves results to a local SQLite inventory database. **Headless for now** (no attached screen): feedback via logs, Flask, or the serial/SSH session — no browser, no desktop assumed on the Pi.

## Hardware
- **Pi:** Raspberry Pi 4 (2GB)
- **Camera:** Raspberry Pi Camera Module 3 (standard, not wide-angle), accessed via Picamera2
- **Input:** Physical momentary buttons wired to GPIO pins (no touchscreen)

**Scan quality (accuracy):** Fill most of the frame with the card, use diffuse light (avoid specular glare on the title), and keep the name line in focus. Optional Picamera2 env vars (see [`camera.py`](camera.py)): **`MTG_STILL_SIZE`** or **`CAMERA_STILL_SIZE`** as `WxH` for still resolution (default `2304x1296`; higher can help text but uses more RAM on a 2GB Pi), **`CAMERA_SETTLE_S`** seconds after start before capture (default `2`), **`CAMERA_AF_RANGE`** `0` Normal / `1` Macro (default, desk distance) / `2` Full if focus hunts at your working distance.

## Project Structure
```
mtg-scanner/
├── app.py           # Flask server — coordinates all modules
├── camera.py        # Picamera2 wrapper — captures JPEG on demand
├── claude_id.py     # Claude Vision API call — returns card name + set
├── scryfall.py      # Scryfall API wrapper — fetches card data and pricing
├── db.py            # SQLite CRUD — inventory read/write
├── gpio.py          # GPIO button input handler
├── inventory.db     # Auto-created SQLite file (gitignore this)
├── .env             # API keys (gitignore this)
└── requirements.txt
```

*(Deferred: optional `display.py` + DSI framebuffer UI — not in scope until re-enabled.)*

## Key APIs

### Claude Vision API
- Model: `claude-sonnet-4-20250514`
- Purpose: Identify card name and set from a JPEG image (reads the **printed title line**; `set_name` only when clearly printed, else `null`). When the **type-line set code** and **collector number** are legible, the model also returns **`set_code`** and **`collector_number`** so Scryfall can use an exact card URL instead of fuzzy name search.
- Implementation uses a short **system** message plus a **user** prompt and image; the model must return **only** a JSON object. See [`claude_id.py`](claude_id.py) for the exact keys and wording.
- API key stored in `.env` as `ANTHROPIC_API_KEY`

### Testing Claude ID

- Activate your project venv first if you use one (see **Python venv** under Development Notes).
- Set `ANTHROPIC_API_KEY` in `.env` (or export it in the shell). Optional: `ANTHROPIC_MODEL` overrides the default Sonnet model id.
- With any JPEG of a card (for example from the Pi: `python3 test_camera.py --save` then copy `/tmp/card_test.jpg`):

  `python3 claude_id.py /path/to/card.jpg`

- Prints JSON with `name` and `set_name` to stdout, or a clear error message on stderr.

### Scryfall API
- Base URL: `https://api.scryfall.com`
- No authentication required
- Fuzzy card lookup: `GET /cards/named?fuzzy={card_name}`
- When [`claude_id.py`](claude_id.py) returns readable **`set_code`** and **`collector_number`** from the type line, [`scryfall.lookup_card_from_vision`](scryfall.py) uses **`GET /cards/{set}/{collector}`** first (exact print), then falls back to fuzzy name if that fails—this greatly reduces wrong reprints.
- Returns: price (USD/foil), image URI, set code, legality, collector number
- Respect Scryfall's request that clients wait 50–100ms between requests

### Testing Scryfall lookup

- Activate your project venv if you use one (see **Python venv** under Development Notes). No API key is required.
- Fuzzy lookup uses only the **card name** for now. `set_name` from [`claude_id.py`](claude_id.py) is not passed to Scryfall until we resolve display set names to set codes (e.g. a separate sets endpoint).
- Optional: `SCRYFALL_MIN_INTERVAL_MS` (default `75`) sets the minimum gap between outbound Scryfall requests in milliseconds.

  `python3 scryfall.py "Lightning Bolt"`

- Prints normalized JSON (`id`, `name`, `set_code`, `collector_number`, `price_usd`, `price_usd_foil`, `image_uri`, `legalities`) or an error on stderr.

## Database Schema
```sql
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
```

### Testing inventory DB

- No API keys required. A venv is optional (stdlib `sqlite3` only).
- Default file is **`inventory.db`** in the process working directory (gitignored). Override with **`INVENTORY_DB`** or **`INVENTORY_DB_PATH`** (same meaning) for a fixed path on the Pi (e.g. under `/var/lib/...`).
- **v1:** each confirm is a new `INSERT`; duplicate `scryfall_id` rows are allowed (no unique constraint). Upsert/increment can be added later.

  `python3 db.py --init` — creates the file and `inventory` table if needed; prints the resolved path.

  `python3 db.py --list` — prints a JSON array of recent rows (newest first, default limit 50).

## User Flow
1. User presses physical **scan button** (GPIO)
2. `camera.py` captures a JPEG
3. `claude_id.py` sends image to Claude API → returns `{"name": ..., "set_name": ...}`
4. `scryfall.py` does a fuzzy lookup → returns price, art URL, legality
5. **Headless:** app surfaces the match (e.g. logging, Flask JSON, or stdout) so the operator can decide
6. User presses **confirm button** → saved to SQLite via `db.py`
7. User presses **rescan button** → discard and restart flow

## GPIO Button Mapping
- Define pin numbers in `.env` or a `config.py` — do not hardcode
- Debounce all button inputs in `gpio.py`
- Use `RPi.GPIO` or `gpiozero` — prefer `gpiozero` for cleaner code

## Development Notes
- **Python venv (required if `pip` says “externally managed”):** macOS Homebrew / Xcode Python and current Raspberry Pi OS use PEP 668, so you must not install into the system interpreter. From the project root:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  ```
  Use `python3` / `pip` only while the venv is activated (or run tools as `.venv/bin/python`). On Windows: `.venv\Scripts\activate`.
- **Dev machine:** All development happens on a separate computer. The Pi is the deploy target only.
- **No desktop on Pi:** Do not assume X11, Wayland, or a browser is available.
- **Testing camera locally:** Mock `camera.py` with a static test JPEG when not on Pi hardware.
- **Deployment:** rsync or `scp` to Pi, run via a systemd service on boot.

### Running the Flask app (headless API)

- **v1 has no authentication**; only run on a network you trust (e.g. home LAN). Listens on `0.0.0.0` so other devices can reach the Pi.
- Activate venv, set **`ANTHROPIC_API_KEY`** (and optional **`MOCK_CAMERA=1`** on a dev machine without a camera). Optional: **`FLASK_PORT`** (default `5000`), **`FLASK_DEBUG=1`** for Flask debug mode (not for production).

  `python3 app.py`

- **Endpoints:** `GET /api/health` — liveness. `POST /api/identify` — capture → Claude only; returns `{ "vision": { "name", "set_name", "set_code", "collector_number" } }` and does **not** call Scryfall or change **pending**. `POST /api/scan` — capture → Claude → Scryfall; returns `{ "vision", "scryfall" }` and stores a single **pending** match for confirm. `POST /api/confirm` — optional JSON body `{"foil": false, "quantity": 1}`; writes one inventory row; clears pending. `POST /api/rescan` — clears pending without saving. `GET /api/inventory?limit=50` — recent rows (limit capped at 200).

- **Example curl** (from another machine, replace host):

  ```bash
  curl -sS http://raspberrypi.local:5000/api/health
  curl -sS -X POST http://raspberrypi.local:5000/api/identify
  curl -sS -X POST http://raspberrypi.local:5000/api/scan
  curl -sS -X POST http://raspberrypi.local:5000/api/confirm -H 'Content-Type: application/json' -d '{"foil":false,"quantity":1}'
  ```

- A stub JPEG from `MOCK_CAMERA=1` is not a real card image; use a Pi capture or a real JPEG to test vision accuracy.

## Environment Variables (.env)
```
ANTHROPIC_API_KEY=your_key_here
SCAN_BUTTON_PIN=17
CONFIRM_BUTTON_PIN=27
RESCAN_BUTTON_PIN=22
```

## Requirements (requirements.txt)
```
flask
picamera2
anthropic
requests
gpiozero
python-dotenv
```

## What To Avoid
- Do not use Chromium, a browser, or any web-based display
- Do not hardcode GPIO pin numbers or API keys
- Do not assume the Pi has internet access during dev/test — mock API calls where needed
